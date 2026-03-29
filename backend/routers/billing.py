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

from config import (
    BACKEND_URL,
    STRIPE_PRO_PRICE_ID,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    FREE_PLAN_MONTHLY_LIMIT,
)
from database import get_db
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

stripe.api_key = STRIPE_SECRET_KEY

# ── Plan limits ──────────────────────────────────────────────────────────────
PLAN_LIMITS = {
    "free": FREE_PLAN_MONTHLY_LIMIT,
    "pro": 999_999,
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_user_from_db(user_id: str) -> dict | None:
    """Fetch fresh user data from DB."""
    db = get_db()
    result = db.table("users").select("*").eq("id", user_id).execute()
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


# ─── 1. Create Checkout ─────────────────────────────────────────────────────

@router.post("/create-checkout")
async def create_checkout(user: dict = Depends(get_current_user)):
    """Create a Stripe Checkout Session for a Pro subscription."""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    if not STRIPE_PRO_PRICE_ID:
        raise HTTPException(status_code=503, detail="Stripe price ID not configured")

    if user.get("plan") == "pro":
        raise HTTPException(status_code=400, detail="Already on Pro plan")

    try:
        session = stripe.checkout.Session.create(
            line_items=[{"price": STRIPE_PRO_PRICE_ID, "quantity": 1}],
            mode="subscription",
            success_url=f"{BACKEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BACKEND_URL}/billing/cancel",
            customer_email=user.get("email"),
            metadata={"user_id": user["id"]},
        )
    except stripe.StripeError as e:
        logger.error("Stripe checkout error: %s", e)
        raise HTTPException(status_code=502, detail="Failed to create checkout session")

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

        db.table("users").update({
            "plan": "pro",
            "stripe_customer_id": customer_id,
            "stripe_subscription_id": subscription_id,
            "plan_updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", user_id).execute()

        logger.info("User %s upgraded to pro", user_id)

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

    return {"received": True}


# ─── 3. Customer Portal ─────────────────────────────────────────────────────

@router.get("/portal")
async def billing_portal(user: dict = Depends(get_current_user)):
    """Create a Stripe Billing Portal session so the user can manage their subscription."""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe not configured")

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
            detail="No Stripe customer found. Please subscribe first.",
        )

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{BACKEND_URL}/billing/status",
        )
    except stripe.StripeError as e:
        logger.error("Stripe portal error: %s", e)
        raise HTTPException(status_code=502, detail="Failed to create portal session")

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
        <p>Your Pro plan is now active. You can close this tab.</p>
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
