"""
OutMass — Billing Router (Stripe)
POST /billing/create-checkout   → Create Stripe Checkout session
POST /billing/webhook           → Stripe webhook handler
GET  /billing/portal            → Stripe Customer Portal
GET  /billing/status            → Current plan + usage
GET  /billing/success           → Post-payment success page
GET  /billing/cancel            → Payment cancelled page
"""

import logging
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from pydantic import BaseModel

from config import (
    BACKEND_URL,
    STRIPE_PORTAL_CONFIG_ID,
    STRIPE_STARTER_PRICE_ID,
    STRIPE_PRO_PRICE_ID,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    FREE_PLAN_MONTHLY_LIMIT,
    STARTER_PLAN_MONTHLY_LIMIT,
    PRO_PLAN_MONTHLY_LIMIT,
)
from database import get_db
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

stripe.api_key = STRIPE_SECRET_KEY

# ── Plan limits ──────────────────────────────────────────────────────────────
PLAN_LIMITS = {
    "free": FREE_PLAN_MONTHLY_LIMIT,
    "starter": STARTER_PLAN_MONTHLY_LIMIT,
    "pro": PRO_PLAN_MONTHLY_LIMIT,
}


class CheckoutRequest(BaseModel):
    plan: str = "pro"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_user_from_db(user_id: str) -> dict | None:
    """Fetch fresh user data from DB."""
    db = get_db()
    result = db.table("users").select("*").eq("id", user_id).execute()
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


# ─── 1. Create Checkout / Upgrade ──────────────────────────────────────────

@router.post("/create-checkout")
async def create_checkout(body: CheckoutRequest, user: dict = Depends(get_current_user)):
    """
    For Free users: create a new Stripe Checkout Session.
    For users with an active subscription: modify the existing subscription
    to the new plan with proration (charge only the difference).
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    if body.plan == "starter":
        price_id = STRIPE_STARTER_PRICE_ID
    else:
        price_id = STRIPE_PRO_PRICE_ID

    if not price_id:
        raise HTTPException(status_code=503, detail="Stripe price ID not configured")

    current_plan = user.get("plan", "free")
    if current_plan == body.plan:
        raise HTTPException(status_code=400, detail=f"Already on {body.plan} plan")
    if current_plan == "pro":
        raise HTTPException(status_code=400, detail="Already on Pro plan")

    # ── Existing subscriber: modify the subscription with proration ──
    existing_sub_id = user.get("stripe_subscription_id")
    if existing_sub_id:
        try:
            sub = stripe.Subscription.retrieve(existing_sub_id)
        except stripe.StripeError as e:
            logger.error("Could not retrieve subscription %s: %s", existing_sub_id, e)
            sub = None

        # Only modify if the subscription is still active (not canceled/expired)
        if sub and sub.get("status") in ("active", "trialing", "past_due"):
            try:
                # Get the current item to replace its price
                items = sub.get("items", {}).get("data", [])
                if not items:
                    raise HTTPException(
                        status_code=502, detail="Subscription has no items"
                    )
                item_id = items[0]["id"]

                stripe.Subscription.modify(
                    existing_sub_id,
                    items=[{"id": item_id, "price": price_id}],
                    proration_behavior="create_prorations",
                    payment_behavior="pending_if_incomplete",
                )
            except stripe.StripeError as e:
                logger.error("Stripe modify error: %s", e)
                raise HTTPException(
                    status_code=502, detail=f"Upgrade error: {str(e)}"
                )

            # Update plan in DB immediately (webhook will also fire and confirm)
            from database import get_db
            from datetime import datetime, timezone

            get_db().table("users").update({
                "plan": body.plan,
                "plan_updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", user["id"]).execute()

            return {
                "modified": True,
                "plan": body.plan,
                "message": f"Upgraded to {body.plan}. Stripe will charge the prorated difference.",
            }

    # ── New subscriber: create a Checkout Session ──
    try:
        session = stripe.checkout.Session.create(
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=f"{BACKEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BACKEND_URL}/billing/cancel",
            customer_email=user.get("email"),
            metadata={"user_id": user["id"]},
        )
    except stripe.StripeError as e:
        logger.error("Stripe checkout error: %s", e)
        raise HTTPException(status_code=502, detail=f"Checkout error: {str(e)}")

    return {"checkout_url": session.url}


# ─── 2. Webhook ─────────────────────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Verify and handle incoming Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe webhooks not configured")

    # Verify signature
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data_object = event["data"]["object"]
    db = get_db()

    # ── checkout.session.completed ──
    if event_type == "checkout.session.completed":
        user_id = data_object.get("metadata", {}).get("user_id")
        if not user_id:
            logger.warning("checkout.session.completed without user_id in metadata")
            return {"received": True}

        customer_id = data_object.get("customer")
        subscription_id = data_object.get("subscription")

        # Determine plan from the price ID in the subscription
        plan = "pro"
        if subscription_id:
            try:
                sub = stripe.Subscription.retrieve(subscription_id)
                sub_price_id = sub["items"]["data"][0]["price"]["id"] if sub["items"]["data"] else ""
                if sub_price_id == STRIPE_STARTER_PRICE_ID:
                    plan = "starter"
            except Exception:
                pass

        db.table("users").update({
            "plan": plan,
            "stripe_customer_id": customer_id,
            "stripe_subscription_id": subscription_id,
            "plan_updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", user_id).execute()

        logger.info("User %s upgraded to %s", user_id, plan)

    # ── customer.subscription.deleted ──
    elif event_type == "customer.subscription.deleted":
        customer_id = data_object.get("customer")
        if customer_id:
            db.table("users").update({
                "plan": "free",
                "stripe_subscription_id": None,
                "plan_updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("stripe_customer_id", customer_id).execute()

            logger.info("Subscription deleted for customer %s", customer_id)

    # ── customer.subscription.updated ──
    elif event_type == "customer.subscription.updated":
        customer_id = data_object.get("customer")
        status = data_object.get("status")

        if customer_id and status:
            update_data = {
                "plan_updated_at": datetime.now(timezone.utc).isoformat(),
            }

            if status in ("active", "trialing"):
                # Determine plan from subscription price
                try:
                    sub_price_id = data_object["items"]["data"][0]["price"]["id"] if data_object.get("items", {}).get("data") else ""
                    if sub_price_id == STRIPE_STARTER_PRICE_ID:
                        update_data["plan"] = "starter"
                    else:
                        update_data["plan"] = "pro"
                except (KeyError, IndexError):
                    update_data["plan"] = "pro"
            elif status in ("canceled", "unpaid", "past_due"):
                update_data["plan"] = "free"

            db.table("users").update(update_data).eq(
                "stripe_customer_id", customer_id
            ).execute()

            logger.info(
                "Subscription updated for customer %s — status: %s",
                customer_id,
                status,
            )

    # ── invoice.payment_failed ──
    elif event_type == "invoice.payment_failed":
        customer_id = data_object.get("customer")
        if customer_id:
            # Don't immediately downgrade — mark as past_due
            db.table("users").update({
                "plan_updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("stripe_customer_id", customer_id).execute()

            logger.warning("Payment failed for customer %s", customer_id)

    # ── charge.dispute.created (chargeback filed) ──
    #
    # A chargeback is the customer's bank side-stepping us entirely to
    # reverse the charge. By the time we see this event, the money is
    # already clawed back (or will be). Our response needs to be:
    #
    #   1. Cancel the subscription immediately so we don't keep billing
    #      a customer who's telling their bank "I don't want this".
    #   2. Mark the user row as free plan, clear stripe_subscription_id.
    #   3. Audit log: durable record with the dispute reason + amount.
    #   4. Telegram alert for the operator — disputes are urgent and
    #      worth a human look (evidence submission window is 7-10 days).
    #
    # We do NOT auto-delete the user's account. The chargeback might be
    # about one disputed charge, not a request to wipe everything. The
    # operator decides on a case-by-case basis whether deletion is the
    # right outcome after reviewing the dispute.
    elif event_type == "charge.dispute.created":
        _handle_dispute_created(db, data_object)

    # ── charge.dispute.closed ──
    elif event_type == "charge.dispute.closed":
        _handle_dispute_closed(db, data_object)

    return {"received": True}


def _handle_dispute_created(db, dispute: dict) -> None:
    """Cancel subscription + audit + alert. Called from webhook handler."""
    from models import audit

    charge_id = dispute.get("charge")
    amount = dispute.get("amount")
    reason = dispute.get("reason") or "unknown"
    dispute_id = dispute.get("id")

    # Look up the user via Stripe charge → customer.
    user_row = None
    customer_id = None
    try:
        if charge_id:
            charge = stripe.Charge.retrieve(charge_id)
            customer_id = charge.get("customer")
        if customer_id:
            r = (
                db.table("users")
                .select("id, email, stripe_subscription_id, plan")
                .eq("stripe_customer_id", customer_id)
                .execute()
            )
            if r.data:
                user_row = r.data[0]
    except Exception:  # noqa: BLE001
        logger.exception("Failed to resolve dispute %s to a user", dispute_id)

    # Cancel the subscription in Stripe. Idempotent — if it's already
    # gone, Stripe returns 404 which we swallow.
    sub_id = user_row.get("stripe_subscription_id") if user_row else None
    if sub_id:
        try:
            stripe.Subscription.delete(sub_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("Dispute cancel of sub %s failed: %s", sub_id, e)

    # Update our DB — drop plan to free regardless of Stripe cancel
    # success, because the user is disputing the relationship.
    if user_row:
        db.table("users").update({
            "plan": "free",
            "stripe_subscription_id": None,
            "plan_updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", user_row["id"]).execute()

        audit.emit(
            "subscription_canceled",
            user_id=user_row["id"],
            email=user_row.get("email"),
            metadata={
                "reason": "chargeback",
                "dispute_id": dispute_id,
                "dispute_reason": reason,
                "amount": amount,
                "charge_id": charge_id,
            },
        )

    # Operator alert. Keep the message actionable — disputes have
    # short evidence windows.
    _telegram_alert(
        "\U0001F6A8 OutMass CHARGEBACK filed\n\n"
        f"Dispute: {dispute_id}\n"
        f"Reason: {reason}\n"
        f"Amount: ${(amount or 0) / 100:.2f}\n"
        f"Customer: {customer_id or 'unresolved'}\n"
        f"User: {user_row['email'] if user_row else 'unresolved'}\n"
        f"Subscription canceled: {'yes' if sub_id else 'already gone'}\n\n"
        "Submit evidence in Stripe dashboard within the response window."
    )


def _handle_dispute_closed(db, dispute: dict) -> None:
    """Log the outcome. We don't unwind anything on a won dispute —
    if the customer still wants service, they can re-subscribe."""
    from models import audit

    status = dispute.get("status")  # won, lost, warning_closed, etc.
    charge_id = dispute.get("charge")
    dispute_id = dispute.get("id")

    customer_id = None
    user_id = None
    user_email = None
    try:
        if charge_id:
            charge = stripe.Charge.retrieve(charge_id)
            customer_id = charge.get("customer")
        if customer_id:
            r = (
                db.table("users")
                .select("id, email")
                .eq("stripe_customer_id", customer_id)
                .execute()
            )
            if r.data:
                user_id = r.data[0]["id"]
                user_email = r.data[0].get("email")
    except Exception:  # noqa: BLE001
        logger.exception("Dispute close: couldn't resolve %s to a user", dispute_id)

    audit.emit(
        "dispute_closed",
        user_id=user_id,
        email=user_email,
        metadata={
            "dispute_id": dispute_id,
            "status": status,
            "charge_id": charge_id,
        },
    )

    _telegram_alert(
        "\u2139\ufe0f OutMass dispute closed\n\n"
        f"Dispute: {dispute_id}\n"
        f"Status: {status}\n"
        f"User: {user_email or 'unresolved'}"
    )


def _telegram_alert(text: str) -> None:
    """Best-effort operator ping. Imports lazily to keep the module
    loadable without Telegram env vars."""
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    import httpx

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": "true",
            },
            timeout=5.0,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Dispute Telegram alert failed: %s", e)


# ─── 3. Customer Portal ─────────────────────────────────────────────────────

@router.get("/portal")
async def billing_portal(user: dict = Depends(get_current_user)):
    """Create a Stripe Billing Portal session so the user can manage their subscription.

    Errors are returned with structured codes in detail.error so the
    extension can surface localized messages instead of raw English
    strings. Each error still carries a human-readable `message` for
    legacy clients (pre-v0.1.4 store build).
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "stripe_not_configured",
                "message": "Stripe not configured",
            },
        )

    # Fetch stripe_customer_id from DB
    db = get_db()
    result = (
        db.table("users")
        .select("stripe_customer_id")
        .eq("id", user["id"])
        .execute()
    )
    customer_id = None
    if result.data and len(result.data) > 0:
        customer_id = result.data[0].get("stripe_customer_id")

    if not customer_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "no_stripe_customer",
                "message": "No Stripe customer found. Please subscribe first.",
            },
        )

    try:
        portal_kwargs = {
            "customer": customer_id,
            "return_url": f"{BACKEND_URL}/billing/status",
        }
        if STRIPE_PORTAL_CONFIG_ID:
            portal_kwargs["configuration"] = STRIPE_PORTAL_CONFIG_ID
        session = stripe.billing_portal.Session.create(**portal_kwargs)
    except stripe.StripeError as e:
        logger.error("Stripe portal error: %s (customer=%s)", e, customer_id)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "portal_error",
                "message": f"Portal error: {str(e)}",
            },
        )

    return {"portal_url": session.url}


# ─── 4. Billing Status ──────────────────────────────────────────────────────

@router.get("/status")
async def billing_status(user: dict = Depends(get_current_user)):
    """Return the user's current plan and monthly usage."""
    fresh_user = _get_user_from_db(user["id"]) or user
    plan = fresh_user.get("plan", "free")
    sent = fresh_user.get("emails_sent_this_month", 0)
    limit = PLAN_LIMITS.get(plan, FREE_PLAN_MONTHLY_LIMIT)

    return {
        "plan": plan,
        "emails_sent_this_month": sent,
        "limit": limit,
    }


# ─── 5. Success Page ────────────────────────────────────────────────────────

@router.get("/success", response_class=HTMLResponse)
async def billing_success():
    """Simple HTML page shown after successful payment."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Successful — OutMass</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               display: flex; justify-content: center; align-items: center;
               min-height: 100vh; margin: 0; background: #f0fdf4; color: #166534; }
        .card { text-align: center; padding: 3rem; background: #fff;
                border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); }
        h1 { margin: 0 0 .5rem; font-size: 1.5rem; }
        p  { margin: 0; color: #4b5563; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Payment successful!</h1>
        <p>Your plan upgrade is now active. You can close this tab.</p>
    </div>
</body>
</html>"""
    return Response(content=html, media_type="text/html")


# ─── 6. Cancel Page ─────────────────────────────────────────────────────────

@router.get("/cancel", response_class=HTMLResponse)
async def billing_cancel():
    """Simple HTML page shown when the user cancels payment."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Cancelled — OutMass</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               display: flex; justify-content: center; align-items: center;
               min-height: 100vh; margin: 0; background: #fef2f2; color: #991b1b; }
        .card { text-align: center; padding: 3rem; background: #fff;
                border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); }
        h1 { margin: 0 0 .5rem; font-size: 1.5rem; }
        p  { margin: 0; color: #4b5563; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Payment cancelled</h1>
        <p>No charges were made. You can try again anytime.</p>
    </div>
</body>
</html>"""
    return Response(content=html, media_type="text/html")
