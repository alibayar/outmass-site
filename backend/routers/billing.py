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

import posthog
import stripe
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from pydantic import BaseModel

from config import (
    BACKEND_URL,
    POSTHOG_API_KEY,
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
from models import user as user_model
from utils import welcome_email
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


def _promo_shield(db, customer_id: str) -> dict | None:
    """The user behind this Stripe customer IF they are inside a manual promo.

    A manual promo (migration 026) is a plan we granted and put in writing —
    "two months of Starter, already active". Two webhook branches downgrade
    to 'free' on a dead subscription, and they match on stripe_customer_id,
    which a promo does NOT clear. So without this, a stale cancellation for
    the subscription that died BEFORE the promo would silently revoke a gift
    we had just promised, and the user would find out by hitting the old
    limit again — the exact failure the promo was apologising for.

    Returns None on any error: a downgrade that should happen is a smaller
    problem than a downgrade that is skipped by accident, so the caller
    falls through to normal behaviour when we cannot tell.
    """
    if not customer_id:
        return None
    try:
        res = (
            db.table("users")
            .select("id, email, plan, manual_promo_until, stripe_subscription_id")
            .eq("stripe_customer_id", customer_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None

        # A grant CLEARS stripe_subscription_id, and grant_manual_promo
        # refuses to run while a live one is present. So a value here was
        # written AFTER the grant — the user went and subscribed for real
        # during their promo. From that moment Stripe owns their plan, and
        # this event is about that new subscription, not the dead one the
        # promo was granted over.
        #
        # Without this check the shield cannot tell the two apart: it would
        # read "promo still running" and refuse to downgrade someone whose
        # real, paid subscription had just failed — leaving them on a paid
        # tier for free, attached to a subscription id that daily_report
        # counts as revenue. That is the exact bug this whole mechanism was
        # built to remove, reintroduced through the front door.
        if rows[0].get("stripe_subscription_id"):
            return None

        until = rows[0].get("manual_promo_until")
        if not until:
            return None
        until_dt = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
        if until_dt.tzinfo is None:
            until_dt = until_dt.replace(tzinfo=timezone.utc)
        return rows[0] if until_dt > datetime.now(timezone.utc) else None
    except Exception:  # noqa: BLE001
        logger.exception("promo shield check failed for customer %s", customer_id)
        return None


def _retarget_grant_to_free(db, user_id: str) -> None:
    """Point the active grant's restore target at 'free'.

    Called when a shielded user's subscription dies mid-promo. They keep the
    granted plan until the promo ends — but what they go back to afterwards
    is no longer whatever they were paying for when we granted it. Without
    this, expiry would faithfully restore a paid plan nobody is paying for.
    """
    try:
        (
            db.table("manual_promo_grants")
            .update({"previous_plan": "free"})
            .eq("user_id", user_id)
            .eq("status", "active")
            .execute()
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to retarget promo grant for user %s", user_id)


def _capture_billing_event(distinct_id: str, event: str, properties: dict) -> None:
    """Best-effort PostHog capture for checkout-funnel telemetry.

    Closes the gap between upgrade_button_clicked (extension) and the
    Stripe outcome: before this, an abandoned checkout was invisible in
    PostHog and only discoverable by digging through Stripe's API logs.
    Must never raise — billing flows don't depend on analytics.
    """
    if not POSTHOG_API_KEY or not distinct_id:
        return
    try:
        posthog.capture(distinct_id=distinct_id, event=event, properties=properties)
    except Exception:  # noqa: BLE001
        logger.warning("Billing PostHog capture failed (%s)", event, exc_info=True)


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
            # `plan` rides along so checkout.session.expired can report
            # which plan the user walked away from.
            metadata={"user_id": user["id"], "plan": body.plan},
        )
    except stripe.StripeError as e:
        logger.error("Stripe checkout error: %s", e)
        raise HTTPException(status_code=502, detail=f"Checkout error: {str(e)}")

    # Funnel: upgrade_button_clicked → checkout_session_created →
    # checkout.session.completed | checkout_abandoned (webhook).
    _capture_billing_event(
        user.get("email") or user["id"],
        "checkout_session_created",
        {"plan": body.plan, "session_id": session.id},
    )

    return {"checkout_url": session.url}


# ─── 2. Webhook ─────────────────────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
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

        # Replay guard: Stripe delivers webhooks at-least-once (retries on
        # timeout/non-2xx for days, plus manual dashboard "Resend"). The plan
        # write is idempotent, but the quota re-anchor below is NOT — a replay
        # must never re-zero the counter (bonus quota) or shift the anchor to
        # the redelivery date. If we already stored this subscription id, this
        # event was processed.
        already_processed = False
        if subscription_id:
            existing = (
                db.table("users")
                .select("stripe_subscription_id")
                .eq("id", user_id)
                .execute()
            )
            already_processed = bool(
                existing.data
                and existing.data[0].get("stripe_subscription_id") == subscription_id
            )

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

        update_payload = {
            "plan": plan,
            "stripe_customer_id": customer_id,
            "stripe_subscription_id": subscription_id,
            "plan_updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if not already_processed:
            # The paid quota period starts the day they pay: fresh counters +
            # anchor = today, so the rolling monthly reset (check_monthly_reset)
            # keeps quota month == billed month from here on. ALL period-scoped
            # counters reset together (AI too — a new paid period must not
            # inherit the old period's AI usage). Deliberately NOT done in
            # customer.subscription.updated — that event also fires on portal
            # edits (e.g. cancel/uncancel toggles), which must never refill
            # quota. Renewals need no webhook: the rolling reset is time-based
            # off this anchor.
            update_payload.update({
                "emails_sent_this_month": 0,
                "ai_generations_this_month": 0,
                "month_reset_date": datetime.now(timezone.utc).date().isoformat(),
            })

        # Grab email/name before the plan write (which doesn't touch them)
        # for the one-time thank-you below.
        upgraded = _get_user_from_db(user_id) if not already_processed else None

        db.table("users").update(update_payload).eq("id", user_id).execute()

        # One-time upgrade thank-you email — rides the same replay guard as
        # the quota re-anchor, so Stripe redeliveries can't send it twice.
        # The user's only confirmation used to be Stripe's bare receipt.
        if upgraded and upgraded.get("email"):
            background_tasks.add_task(
                welcome_email.send_upgrade_email,
                upgraded["email"],
                upgraded.get("name"),
                plan,
            )

        logger.info(
            "User %s upgraded to %s (%s)",
            user_id,
            plan,
            "replay — anchor kept" if already_processed else "quota period re-anchored",
        )

    # ── checkout.session.expired ──
    # Fires ~24h after an uncompleted Checkout Session was created — i.e.
    # the user clicked Upgrade, the checkout page opened, and they never
    # paid. Surfaced as PostHog `checkout_abandoned` (and via the daily
    # report's info list) so abandonment is visible without digging
    # through Stripe API logs. Telemetry only — no state changes.
    elif event_type == "checkout.session.expired":
        meta = data_object.get("metadata") or {}
        user_id = meta.get("user_id")
        email = data_object.get("customer_email")
        current_plan = None
        already_subscribed = False
        if user_id:
            row = _get_user_from_db(user_id)
            if row:
                email = email or row.get("email")
                current_plan = row.get("plan")
                # They may have paid via a NEWER session while this one
                # aged out — don't report that as a real abandonment.
                already_subscribed = bool(row.get("stripe_subscription_id"))

        _capture_billing_event(
            email or user_id or "unknown",
            "checkout_abandoned",
            {
                "plan": meta.get("plan"),
                "current_plan": current_plan,
                "already_subscribed": already_subscribed,
                "amount_total": data_object.get("amount_total"),
                "currency": data_object.get("currency"),
                "session_id": data_object.get("id"),
            },
        )
        logger.info(
            "Checkout abandoned: %s (plan=%s, already_subscribed=%s)",
            email or user_id,
            meta.get("plan"),
            already_subscribed,
        )

    # ── customer.subscription.deleted ──
    elif event_type == "customer.subscription.deleted":
        customer_id = data_object.get("customer")
        if customer_id:
            update_data = {
                "stripe_subscription_id": None,
                "plan_updated_at": datetime.now(timezone.utc).isoformat(),
            }

            shielded = _promo_shield(db, customer_id)
            if shielded:
                # Inside a manual promo: they keep the granted plan for the
                # rest of it. Only the restore target moves.
                _retarget_grant_to_free(db, shielded["id"])
                logger.info(
                    "Subscription deleted for customer %s — plan held by "
                    "manual promo until %s",
                    customer_id,
                    shielded.get("manual_promo_until"),
                )
            else:
                update_data["plan"] = "free"

            db.table("users").update(update_data).eq(
                "stripe_customer_id", customer_id
            ).execute()

            if not shielded:
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
                # A manual promo outranks a dead subscription. The gift was
                # promised in writing for a fixed window; a cancellation for
                # the subscription that died BEFORE it must not revoke it.
                # Note the shield deliberately does NOT cover the 'active'
                # branch above — a real new subscription always wins, and
                # promo expiry then leaves that user alone.
                shielded = _promo_shield(db, customer_id)
                if shielded:
                    _retarget_grant_to_free(db, shielded["id"])
                    logger.info(
                        "Subscription %s for customer %s — plan held by "
                        "manual promo until %s",
                        status,
                        customer_id,
                        shielded.get("manual_promo_until"),
                    )
                else:
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
        logger.warning("Payment failed for customer %s", customer_id)

        # The bookkeeping write must not be able to swallow the alert.
        # It used to sit unguarded ahead of it, so a Supabase hiccup would
        # raise, return 500, and lose the notification — the one thing in
        # this branch that a human depends on. It is also the marker an
        # operator reads to tell "handler ran" from "event never arrived"
        # (that check is what proved, on 07-31, that Stripe was not
        # delivering invoice.payment_failed at all: three events fired and
        # plan_updated_at never moved off 07-25).
        if customer_id:
            try:
                db.table("users").update({
                    # Don't immediately downgrade — mark as past_due
                    "plan_updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("stripe_customer_id", customer_id).execute()
            except Exception:  # noqa: BLE001
                logger.exception("plan_updated_at write failed for %s", customer_id)

        # Operator alert. Runs even when the invoice carries no customer id:
        # a payment failure nobody hears about is the failure mode we are
        # fixing, so nothing above may gate it.
        #
        # A FIRST payment and a RENEWAL need opposite responses, and saying
        # "Stripe will retry" for both cost us a sale on 07-29: a new
        # customer entered three different cards in 90 seconds, every one
        # refused by the issuer, and the alert said to sit back and wait.
        # Stripe does not Smart-Retry an initial subscription payment — the
        # invoice is voided and the subscription expires ~24h later (07-30
        # 15:47, exactly that). A first-payment failure is a same-day
        # outreach window, not something that heals itself.
        billing_reason = data_object.get("billing_reason") or ""
        is_first_payment = billing_reason == "subscription_create"

        user_email, _plan = _resolve_invoice_user(db, data_object, customer_id or "")

        amount = data_object.get("amount_due")
        attempts = data_object.get("attempt_count")
        next_attempt = data_object.get("next_payment_attempt")

        if is_first_payment:
            headline = "🔴 OutMass FIRST payment FAILED (new customer)"
            guidance = (
                "No auto-retry: Stripe voids the invoice and the "
                "subscription expires ~24h after the attempt. If this "
                "is worth recovering, reach out TODAY."
            )
        else:
            headline = "⚠️ OutMass renewal payment FAILED"
            guidance = (
                "Stripe will auto-retry (Smart Retries) and the plan "
                "restores via customer.subscription.updated — but only "
                "if the card CAN succeed. A hard decline (wrong number, "
                "expired, blocked) never recovers on its own; the "
                "customer has to update the card."
                if next_attempt
                else "No further retry is scheduled — this is the last "
                "attempt. The customer must update the card or the "
                "subscription ends."
            )

        _telegram_alert(
            f"{headline}\n\n"
            f"User: {user_email}\n"
            f"Amount: ${(amount or 0) / 100:.2f}\n"
            f"Customer: {customer_id}\n"
            f"Attempt: {attempts if attempts is not None else '?'}"
            f" · reason: {billing_reason or 'unknown'}\n\n"
            f"{guidance}"
        )

    # ── invoice.payment_action_required (3-D Secure / SCA) ──
    #
    # The bank wants the cardholder to authenticate. This is NOT a decline:
    # the card is fine, the charge simply waits until the customer taps the
    # link Stripe emails them. It matters because it looks like a failure in
    # the dashboard and would otherwise be chased as one — and because the
    # customer, not us, has to act. If nobody acts, the subscription drifts
    # to past_due on its own and the existing path downgrades it.
    elif event_type == "invoice.payment_action_required":
        customer_id = data_object.get("customer")
        user_email, plan = _resolve_invoice_user(db, data_object, customer_id or "")
        _telegram_alert(
            "🔐 OutMass payment needs the customer to authenticate (3-D Secure)\n\n"
            f"User: {user_email}\n"
            f"Plan: {plan}\n"
            f"Amount: ${(data_object.get('amount_due') or 0) / 100:.2f}\n"
            f"Customer: {customer_id}\n\n"
            "Not a decline — the card is fine. Stripe emails them a link to "
            "confirm. Nothing to do unless it is still unpaid in a few days."
        )
        logger.info("Payment action required for customer %s", customer_id)

    # ── invoice.payment_succeeded ──
    #
    # Deliberately quiet for ordinary renewals: one alert per customer per
    # month is noise that trains you to ignore the channel. The case worth
    # hearing about is the CLOSE of a failure we already alerted on —
    # attempt_count > 1 means an earlier attempt failed and this one didn't,
    # so the money we were chasing has landed.
    elif event_type == "invoice.payment_succeeded":
        attempts = data_object.get("attempt_count") or 0
        if attempts > 1:
            customer_id = data_object.get("customer")
            user_email, plan = _resolve_invoice_user(db, data_object, customer_id or "")
            _telegram_alert(
                "✅ OutMass payment RECOVERED\n\n"
                f"User: {user_email}\n"
                f"Amount: ${(data_object.get('amount_paid') or data_object.get('amount_due') or 0) / 100:.2f}\n"
                f"Succeeded on attempt {attempts}\n\n"
                "The plan restores automatically via "
                "customer.subscription.updated — no action needed."
            )
        logger.info(
            "Invoice paid for customer %s (attempt %s)",
            data_object.get("customer"),
            attempts,
        )

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


def _resolve_invoice_user(db, invoice: dict, customer_id: str) -> tuple[str, str]:
    """Best identity we can get for an invoice event: (email, plan).

    The DB lookup is by stripe_customer_id, which we only learn at
    checkout.session.completed — a first-time buyer whose payment fails has
    no such row yet, and this used to report "User: unresolved", leaving the
    operator to dig through Stripe to find out who to contact. The invoice
    itself carries the address, so start there and let our own row win when
    it exists.
    """
    email = (
        invoice.get("customer_email") or invoice.get("customer_name") or "unresolved"
    )
    plan = "unknown"
    try:
        r = (
            db.table("users")
            .select("email, plan")
            .eq("stripe_customer_id", customer_id)
            .execute()
        )
        if r.data:
            email = r.data[0].get("email") or email
            plan = r.data[0].get("plan") or plan
    except Exception:  # noqa: BLE001
        pass
    return email, plan


def _telegram_alert(text: str) -> None:
    """Best-effort operator ping. Imports lazily to keep the module
    loadable without Telegram env vars.

    A missing token used to `return` in silence. That is how three real
    payment-failure alerts (07-29 ×2, 07-30 ×1) vanished while the daily
    reports kept arriving: the reports are sent by the WORKER service and
    these alerts by the WEB service, and on Railway the two do not share
    environment variables. Nothing anywhere said an alert had been dropped.
    Now the alert text goes to the error log, so it is at least recoverable
    from Railway and the misconfiguration is visible.
    """
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    import httpx

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error(
            "OPERATOR ALERT DROPPED — TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
            "missing on this service. Undelivered alert:\n%s",
            text,
        )
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
    # Same rollover check as /settings: this endpoint feeds quota displays,
    # so it must never serve last period's counter after the anniversary.
    user_model.check_monthly_reset(fresh_user)
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
