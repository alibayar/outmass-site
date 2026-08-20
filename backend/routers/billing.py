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
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import HTMLResponse, Response

from pydantic import BaseModel

from config import (
    BACKEND_URL,
    POSTHOG_API_KEY,
    STRIPE_PORTAL_CONFIG_ID,
    STRIPE_STARTER_PRICE_ID,
    STRIPE_PRO_PRICE_ID,
    STRIPE_TEAM_PRICE_ID,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    FREE_PLAN_MONTHLY_LIMIT,
    STARTER_PLAN_MONTHLY_LIMIT,
    PRO_PLAN_MONTHLY_LIMIT,
    PLAN_DROP_NOTICE_DAYS,
)
from database import get_db
from models import user as user_model
from utils import welcome_email
from routers.auth import get_current_user, _request_host

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


def _user_for_customer(db, customer_id: str) -> dict | None:
    """The user row behind a Stripe customer, or None.

    Its own helper rather than reusing _promo_shield's query: that one
    deliberately returns None for anyone NOT inside a promo, which is exactly
    the population that needs to be told their plan dropped.
    """
    if not customer_id:
        return None
    try:
        res = (
            db.table("users")
            .select("id, email, name")
            .eq("stripe_customer_id", customer_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception:  # noqa: BLE001
        logger.exception("could not read the user behind customer %s", customer_id)
        return None


def _event_subscription_is_current(
    db, customer_id: str, event_sub_id, event_type: str
) -> bool:
    """A subscription event may only act on the account whose CURRENT
    subscription it describes.

    Both downgrade branches match users on stripe_customer_id, but a Stripe
    customer can carry more than one subscription over time. The pre-fix
    dual-checkout bug created orphans, and the ordinary cancel-then-
    resubscribe flow does it legitimately: the old subscription dies at
    period end AFTER the new one was created, and its deleted event would
    downgrade the freshly re-paying customer.

    The rules, in order:
    - the event carries no subscription id → act (nothing to compare);
    - no user row for the customer → act (the update is a no-op anyway);
    - stored stripe_subscription_id is NULL → act on the customer match
      (legacy rows, a lost checkout webhook — refusing here would mean
      nothing ever downgrades those accounts);
    - stored id matches the event's → act;
    - stored id set and DIFFERENT → skip, loudly. The event is about a
      subscription this account does not run on.

    Fails toward the old behaviour on any read error: a wrongly-processed
    event is bounded and visible, a silently immortal plan is neither.
    """
    if not event_sub_id:
        return True
    try:
        res = (
            db.table("users")
            .select("id, email, stripe_subscription_id")
            .eq("stripe_customer_id", customer_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return True
        stored = rows[0].get("stripe_subscription_id")
        if not stored or stored == event_sub_id:
            return True
        logger.warning(
            "%s for customer %s describes subscription %s, but the account "
            "runs on %s — leaving the account untouched",
            event_type,
            customer_id,
            event_sub_id,
            stored,
        )
        _telegram_alert(
            "⚠️ OutMass: subscription event ignored\n\n"
            f"Event: {event_type}\n"
            f"Customer: {customer_id} ({rows[0].get('email') or 'no email'})\n"
            f"Event subscription: {event_sub_id}\n"
            f"Account runs on: {stored}\n\n"
            "Two subscriptions have existed for this customer. The account "
            "was left untouched. Check the customer's page in Stripe for an "
            "orphan subscription — cancelling the orphan will NOT downgrade "
            "the account now."
        )
        return False
    except Exception:  # noqa: BLE001
        logger.exception(
            "could not compare subscription ids for customer %s", customer_id
        )
        return True


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


def _capture_billing_event(distinct_id: str, event: str, properties: dict,
                           request_host: str) -> None:
    """Best-effort PostHog capture for checkout-funnel telemetry.

    Closes the gap between upgrade_button_clicked (extension) and the
    Stripe outcome: before this, an abandoned checkout was invisible in
    PostHog and only discoverable by digging through Stripe's API logs.
    Must never raise — billing flows don't depend on analytics.

    Host-guarded since 2026-08-11, for the reason auth.py already was: on
    08-06 a script driving TestClient outside pytest inherited a real
    POSTHOG_API_KEY and wrote 19 fabricated failures into the live funnel.
    The billing webhook is driven by tests the same way, and a fabricated
    PAYMENT in the funnel would be worse than a fabricated failure.
    """
    from routers.auth import _is_reportable_host

    if not POSTHOG_API_KEY or not distinct_id:
        return
    if not _is_reportable_host(request_host):
        return
    try:
        posthog.capture(distinct_id=distinct_id, event=event, properties=properties)
    except Exception:  # noqa: BLE001
        logger.warning("Billing PostHog capture failed (%s)", event, exc_info=True)


# ─── 1. Create Checkout / Upgrade ──────────────────────────────────────────

@router.post("/create-checkout")
async def create_checkout(
    body: CheckoutRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
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
            # 502, not a fallthrough. This used to set sub = None, which the
            # status check below then read as "no live subscription" and
            # dropped into the new-Checkout-Session branch — so a transient
            # Stripe error during an UPGRADE handed an existing subscriber a
            # brand-new full-price subscription alongside the one they were
            # already paying. Cancelling the orphan later then downgraded a
            # customer who had never stopped paying.
            #
            # A failed read is not evidence of absence, and the two are only
            # indistinguishable if you throw the error away.
            logger.error("Could not retrieve subscription %s: %s", existing_sub_id, e)
            raise HTTPException(
                status_code=502,
                detail="Could not check your current subscription. Please try "
                       "again in a moment.",
            )

        # Only modify if the subscription is still active (not canceled/expired)
        if sub and sub.get("status") in _LIVE_SUBSCRIPTION_STATUSES:
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
        _request_host(request),
    )

    return {"checkout_url": session.url}


# ─── 2. Webhook ─────────────────────────────────────────────────────────────


# Checkout session payment_status values that mean the money is actually
# ours. Anything else (notably "unpaid") means a delayed payment method is
# still clearing and the plan must NOT be granted yet.
_SETTLED_PAYMENT_STATUSES = ("paid", "no_payment_required")


# Subscription statuses that mean Stripe is still charging this person. Named
# once because three places ask the question and a fourth is about to: an
# upgrade deciding whether to modify in place, the guard against a second
# subscription, and the webhook that must not treat a live subscriber as
# lapsed. 'incomplete' is deliberately absent — it has never collected money
# and Stripe expires it by itself within a day.
_LIVE_SUBSCRIPTION_STATUSES = ("active", "trialing", "past_due")


def _subscription_still_live(subscription_id: str) -> bool:
    """Is Stripe still billing this subscription?

    Answers True when it cannot tell. Every caller uses this to decide
    whether overwriting a stored subscription is safe, and the two ways to be
    wrong are not symmetric: refusing to overwrite a subscription that was
    actually dead delays a plan grant until someone looks, while overwriting
    one that was actually live drops a paying customer's subscription out of
    our records and re-zeroes their quota. Delay is recoverable by hand; the
    other is a support ticket the customer opens.
    """
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        return sub.get("status") in _LIVE_SUBSCRIPTION_STATUSES
    except Exception:  # noqa: BLE001
        logger.warning(
            "Could not read subscription %s to check whether it is still live; "
            "assuming it is",
            subscription_id,
            exc_info=True,
        )
        return True


# What a subscription resolves to when we cannot read which price it bought.
#
# Both plan lookups used to default to "pro". That is the most expensive
# possible guess: any price id that was not byte-identical to
# STRIPE_STARTER_PRICE_ID — a second currency, an annual tier, a NEW starter
# price minted by a price change (Stripe prices are immutable, so a raise
# means a new id) — delivered 10,000 emails a month for Starter money.
# Silently, and in the customer's favour, so nobody would ever report it.
#
# The lowest paid tier is the right default instead. Under-delivering to
# someone who paid is a support ticket they will open within a day;
# over-delivering is revenue we never see and never hear about. Between two
# failures, prefer the one the customer will tell you about.
_UNKNOWN_PRICE_PLAN = "starter"


def _price_to_plan() -> dict:
    """Stripe price id -> plan name.

    Built per call rather than at import so tests (and a future env reload)
    see current values.

    Empty ids are dropped deliberately: an unset env var must never become a
    key, or a subscription whose price we failed to read — which arrives here
    as "" — would resolve to whatever that blank happened to map to.
    """
    pairs = (
        (STRIPE_STARTER_PRICE_ID, "starter"),
        (STRIPE_PRO_PRICE_ID, "pro"),
        # There is no "team" tier in monthly_limit_for_plan, so a Team
        # subscription can only be delivered as Pro. create_checkout never
        # sells it — this matters solely if one is created by hand in Stripe,
        # and mapping it explicitly beats alerting on something deliberate.
        (STRIPE_TEAM_PRICE_ID, "pro"),
    )
    return {pid: plan for pid, plan in pairs if pid}


def _plan_for_price(price_id: str, context: str) -> str:
    """The plan a Stripe price sells; alerts and falls back when unknown.

    An unrecognised price is not a code bug, it is a DASHBOARD action: adding
    a price in Stripe needs no deploy, so this path can open without anything
    passing through review. It has to be loud.
    """
    plan = _price_to_plan().get(price_id or "")
    if plan:
        return plan

    logger.error(
        "Unrecognised Stripe price %r (%s) — defaulting to %s",
        price_id,
        context,
        _UNKNOWN_PRICE_PLAN,
    )
    _telegram_alert(
        "🔴 OutMass: unknown Stripe price\n\n"
        f"Price: {price_id or '(none read)'}\n"
        f"Where: {context}\n\n"
        f"Granted {_UNKNOWN_PRICE_PLAN} as the safe default. If this price is "
        "real (a new currency, an annual tier, a price change), add it to "
        "_price_to_plan in billing.py and fix this customer's plan by hand."
    )
    return _UNKNOWN_PRICE_PLAN


def _activate_from_checkout_session(db, session: dict, background_tasks,
                                    request_host: str = "") -> None:
    """Grant the plan bought in a completed, PAID checkout session.

    Called from two events, because a card and a bank debit finish at
    different moments:

      * checkout.session.completed — cards. The session completing IS the
        payment, so payment_status is already "paid".
      * checkout.session.async_payment_succeeded — ACH Direct Debit and any
        other delayed notification method. There, session.completed only
        means the customer authorised the debit; the money lands days later
        and can still fail.

    Safe to run from both: the plan write is idempotent and the quota
    re-anchor is behind the same replay guard that protects against Stripe's
    at-least-once delivery.
    """
    user_id = (session.get("metadata") or {}).get("user_id")
    if not user_id:
        logger.warning("checkout session without user_id in metadata")
        return

    customer_id = session.get("customer")
    subscription_id = session.get("subscription")

    # A completed event whose SESSION is weeks old cannot be an organic
    # delivery: Stripe's redelivery horizon is days, delayed bank debits
    # settle within about a week, and checkout sessions themselves expire
    # after 24 hours. What does arrive that old is an operator clicking
    # "Resend" in the dashboard — and replaying an activation from another
    # billing era can resurrect a plan a later cancellation took away,
    # because the replay guard below compares subscription ids and every
    # cancellation NULLs the stored one. Found by the 2026-08-15 review.
    created = session.get("created")
    if created:
        try:
            age_days = (
                datetime.now(timezone.utc)
                - datetime.fromtimestamp(int(created), timezone.utc)
            ).days
        except (TypeError, ValueError, OSError, OverflowError):
            age_days = None
        if age_days is not None and age_days > 14:
            logger.warning(
                "checkout.session.completed for a session %s days old "
                "(session %s, user %s) — refusing to act on history",
                age_days, session.get("id"), user_id,
            )
            _telegram_alert(
                "⚠️ OutMass: historical checkout event ignored\n\n"
                f"Session: {session.get('id')} ({age_days} days old)\n"
                f"User: {user_id}\n\n"
                "Nothing was changed. If this was a deliberate dashboard "
                "Resend, whatever it was meant to fix needs doing by hand — "
                "replaying an old activation could re-grant a plan a later "
                "cancellation removed."
            )
            return

    # Replay guard: Stripe delivers webhooks at-least-once (retries on
    # timeout/non-2xx for days, plus manual dashboard "Resend"). The plan
    # write is idempotent, but the quota re-anchor below is NOT — a replay
    # must never re-zero the counter (bonus quota) or shift the anchor to
    # the redelivery date. If we already stored this subscription id, this
    # event was processed.
    #
    # This also covers the delayed-payment ordering: completed (unpaid, no
    # grant) then async_payment_succeeded (grant) is a single activation,
    # and a redelivery of either is a no-op.
    already_processed = False
    stored_sub_id = None
    if subscription_id:
        existing = (
            db.table("users")
            .select("stripe_subscription_id")
            .eq("id", user_id)
            .execute()
        )
        stored_sub_id = (
            existing.data[0].get("stripe_subscription_id") if existing.data else None
        )
        already_processed = stored_sub_id == subscription_id

    # A DIFFERENT subscription arriving while a live one is stored is not a
    # replay, and the single-slot guard above cannot see it: it only asks
    # "is this the id I already have", so a second subscription reads as a
    # first-time activation.
    #
    # That is reachable. A delayed bank debit is withheld at
    # checkout.session.completed (payment_status 'unpaid', nothing written),
    # so the row still says no subscription; if the customer then pays again
    # by card, the card subscription activates correctly — and days later the
    # bank debit settles and arrives here as an unrecognised id. Overwriting
    # would drop the live, actively-billing card subscription out of our own
    # database and re-zero the customer's quota mid-period as a parting gift.
    #
    # So: keep what we have and tell a human. Both subscriptions are billing
    # a real person; which one to cancel and refund is not a decision this
    # function can make. Doing nothing leaves the customer on the plan they
    # already had, with the counters they already had, which is the only
    # outcome here that is wrong in no direction.
    if subscription_id and stored_sub_id and not already_processed:
        if _subscription_still_live(stored_sub_id):
            logger.error(
                "user %s has live subscription %s and a second one settled (%s)",
                user_id, stored_sub_id, subscription_id,
            )
            _telegram_alert(
                "🔴 OutMass: one customer, two live subscriptions\n\n"
                f"User: {user_id}\n"
                f"Already had: {stored_sub_id}\n"
                f"Just settled: {subscription_id}\n"
                f"Session: {session.get('id')}\n\n"
                "Nothing was changed — their plan and quota are untouched and "
                "the first subscription is still the one we know about. Both "
                "are charging them. Cancel and refund whichever is the "
                "duplicate in Stripe, then update the row by hand if you kept "
                "the second one."
            )
            return

    # Determine plan from the price ID in the subscription
    plan = _UNKNOWN_PRICE_PLAN
    paid_epoch = None
    if subscription_id:
        try:
            sub = stripe.Subscription.retrieve(subscription_id)
            items = (sub.get("items") or {}).get("data") or []
            sub_price_id = items[0]["price"]["id"] if items else ""
            plan = _plan_for_price(
                sub_price_id, f"checkout session {session.get('id')}"
            )
            # Stripe's clock, not ours. The anchor below used to be the day
            # WE processed the webhook; a delivery crossing UTC midnight (a
            # near-midnight checkout, or a retry after a deploy 502) shifted
            # the whole quota cycle a day off the billing cycle, forever.
            # The subscription is already in hand for the price lookup, so
            # take the period start it actually bills from.
            paid_epoch = sub.get("current_period_start")
        except Exception:
            # The retrieve failed, so we know they paid but not for what.
            # This used to `pass` onto a "pro" default — a Stripe outage
            # handed out the top tier.
            logger.exception(
                "Could not read subscription %s to determine plan", subscription_id
            )
            _telegram_alert(
                "🔴 OutMass: could not read a new subscription\n\n"
                f"Subscription: {subscription_id}\n"
                f"Session: {session.get('id')}\n\n"
                f"They paid, but Stripe did not tell us for what. Granted "
                f"{_UNKNOWN_PRICE_PLAN}; check the subscription and fix the "
                "plan by hand if it was the higher tier."
            )
    else:
        # create_checkout only ever opens subscription-mode sessions, so a
        # completed one without a subscription id is anomalous — and it is
        # the same situation as a failed retrieve: money arrived, the plan
        # is unknowable. It used to resolve silently to "pro".
        logger.error(
            "checkout.session.completed with no subscription id (session %s)",
            session.get("id"),
        )
        _telegram_alert(
            "🔴 OutMass: checkout completed with no subscription\n\n"
            f"Session: {session.get('id')}\n"
            f"User: {user_id}\n\n"
            f"Granted {_UNKNOWN_PRICE_PLAN}. Check what they actually bought."
        )

    update_payload = {
        "plan": plan,
        "stripe_customer_id": customer_id,
        "plan_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # A session with no subscription id (the anomalous branch above) must
    # not NULL a stored one: NULL is exactly the state the subscription-
    # identity guards read as "no comparison possible — act", so writing it
    # would disarm them for this customer while the alert about the anomaly
    # is still in flight.
    if subscription_id:
        update_payload["stripe_subscription_id"] = subscription_id
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
        paid_day = (
            datetime.fromtimestamp(int(paid_epoch), timezone.utc).date()
            if paid_epoch
            else datetime.now(timezone.utc).date()
        )
        update_payload.update({
            "emails_sent_this_month": 0,
            "ai_generations_this_month": 0,
            "month_reset_date": paid_day.isoformat(),
            # Re-anchoring means BOTH halves move. This site used to move the
            # date alone, so a customer who paid on a different day than they
            # signed up kept the stale signup anchor — and _anchor_day()
            # prefers the stored day, so their next quota "month" was however
            # long the gap between the two days happened to be (signup on the
            # 5th, pay Aug 31 → next due Sep 5).
            "month_reset_anchor_day": paid_day.day,
        })

    # Grab email/name before the plan write (which doesn't touch them)
    # for the one-time thank-you below.
    upgraded = _get_user_from_db(user_id) if not already_processed else None

    db.table("users").update(update_payload).eq("id", user_id).execute()

    # One-time upgrade thank-you email — rides the same replay guard as
    # the quota re-anchor, so Stripe redeliveries can't send it twice.
    # The user's only confirmation used to be Stripe's bare receipt.
    if upgraded and upgraded.get("email") and background_tasks is not None:
        background_tasks.add_task(
            welcome_email.send_upgrade_email,
            upgraded["email"],
            upgraded.get("name"),
            plan,
            upgraded.get("preferred_language"),
        )

    # The one funnel rung that was missing. Everything up to the click is
    # reported — installed, panel opened, signed in, upgrade clicked,
    # checkout session created — and then the ladder stopped, so "did they
    # actually pay?" could only be answered in Stripe. On 2026-08-11 that
    # cost a database query to notice a customer sitting on 'free'.
    #
    # Rides the same replay guard as the thank-you email and the quota
    # re-anchor: `upgraded` is populated only on a first activation, so a
    # Stripe redelivery cannot inflate the conversion count.
    if upgraded:
        _capture_billing_event(
            upgraded.get("email") or user_id,
            "checkout_completed",
            {
                "plan": plan,
                # Cards settle at checkout.session.completed; ACH and other
                # delayed methods land days later on
                # async_payment_succeeded. Telling them apart is the
                # difference between "converted in 30 seconds" and "in three
                # days".
                "payment_status": session.get("payment_status"),
                "session_id": session.get("id"),
                "$set": {"plan": plan},
            },
            request_host,
        )
        # Operator ping on every first activation. Rides the same replay
        # guard as the thank-you email, so a Stripe redelivery cannot ping
        # twice (Ali, 2026-08-19: every payment reaches the phone live).
        _telegram_alert(
            f"💰 New subscription: {upgraded.get('email') or user_id} → {plan}"
        )

    logger.info(
        "User %s upgraded to %s (%s)",
        user_id,
        plan,
        "replay — anchor kept" if already_processed else "quota period re-anchored",
    )


@router.post("/webhook")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    """Verify and handle incoming Stripe webhook events."""
    # Which public hostname served this. Passed to every telemetry call so a
    # test driving this endpoint cannot write into the production funnel.
    _webhook_host = _request_host(request)
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
    #
    # For a card, this event IS the payment. For a delayed notification
    # method — ACH Direct Debit, enabled 2026-08-08 — it only means the
    # customer authorised the debit; the money arrives days later and can
    # still fail. Stripe says so on the ACH enablement dialog: do not
    # fulfil before the payment clears.
    #
    # Granting here regardless would hand out a full Starter month (2,500
    # sends, counters re-zeroed) against a bank debit that may never
    # settle. The financial loss would be small — sends leave through the
    # customer's own Microsoft mailbox — but a mass-email tool that opens
    # 2,500 sends on an unverified bank instruction is an abuse target, and
    # a plan we grant is a plan we report as revenue.
    if event_type == "checkout.session.completed":
        payment_status = data_object.get("payment_status")
        if payment_status in _SETTLED_PAYMENT_STATUSES:
            _activate_from_checkout_session(
                db, data_object, background_tasks, _webhook_host
            )
        else:
            # Nothing to do but wait for async_payment_succeeded. Logged
            # rather than silent so an ACH sign-up that never settles is
            # findable afterwards.
            logger.info(
                "Checkout session %s completed but payment_status=%s — "
                "delayed payment method, plan withheld until it settles",
                data_object.get("id"),
                payment_status,
            )

    # ── checkout.session.async_payment_succeeded ──
    # The delayed debit cleared. This is the real moment of purchase for
    # ACH, and it runs the identical activation path as a card.
    elif event_type == "checkout.session.async_payment_succeeded":
        logger.info(
            "Delayed payment settled for checkout session %s",
            data_object.get("id"),
        )
        _activate_from_checkout_session(
                db, data_object, background_tasks, _webhook_host
            )

    # ── checkout.session.async_payment_failed ──
    # The debit bounced days after the customer thought they had bought.
    # No plan was granted (the completed branch withheld it), so there is
    # nothing to revoke — but the customer is sitting on the free tier
    # believing otherwise, and only an operator can tell them.
    elif event_type == "checkout.session.async_payment_failed":
        meta = data_object.get("metadata") or {}
        email = data_object.get("customer_email")
        if not email and meta.get("user_id"):
            row = _get_user_from_db(meta["user_id"])
            email = (row or {}).get("email")

        logger.warning(
            "Delayed payment FAILED for checkout session %s (user=%s)",
            data_object.get("id"),
            email or meta.get("user_id"),
        )
        _capture_billing_event(
            email or meta.get("user_id") or "unknown",
            "checkout_async_payment_failed",
            {
                "plan": meta.get("plan"),
                "session_id": data_object.get("id"),
                "amount_total": data_object.get("amount_total"),
                "currency": data_object.get("currency"),
            },
            _webhook_host,
        )
        _telegram_alert(
            "🔴 OutMass delayed payment FAILED (bank debit bounced)\n\n"
            f"User: {email or meta.get('user_id') or 'unknown'}\n"
            f"Plan: {meta.get('plan') or 'unknown'}\n"
            f"Session: {data_object.get('id')}\n\n"
            "No plan was granted, so nothing to revoke — but the customer "
            "went through checkout days ago and believes they subscribed. "
            "They will not find out on their own. Reach out."
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
            _webhook_host,
        )
        logger.info(
            "Checkout abandoned: %s (plan=%s, already_subscribed=%s)",
            email or user_id,
            meta.get("plan"),
            already_subscribed,
        )

        # Somebody reached the payment page and left. Until 2026-08-13 that
        # produced a PostHog event and this log line and nothing else — no
        # email to them, no alert here — so four of the warmest leads we have
        # ever had went unanswered: Kevin.McCann twice, Morgan Everhart,
        # anbu.atomix and flaviorfdc0406. Two of them never even entered a
        # card, which is a question worth asking rather than a decision worth
        # respecting in silence.
        #
        # Not sent when they subscribed via a newer session — that is a stale
        # session ageing out behind a completed purchase, not a lost sale.
        if not already_subscribed:
            _telegram_alert(
                "🛒 OutMass checkout abandoned\n\n"
                f"User: {email or user_id or 'unknown'}\n"
                f"Wanted: {meta.get('plan') or 'unknown'}\n"
                f"Currently on: {current_plan or 'unknown'}\n"
                f"Session: {data_object.get('id')}\n\n"
                "Stripe's Payments list says whether a card was tried:\n"
                "· a decline is the customer's bank, and another method may "
                "work\n"
                "· no attempt at all means they left before paying, which is "
                "worth asking about\n\n"
                "The session is single-use; clicking Upgrade again makes a "
                "new one."
            )

    # ── customer.subscription.deleted ──
    elif event_type == "customer.subscription.deleted":
        customer_id = data_object.get("customer")
        if customer_id and _event_subscription_is_current(
            db, customer_id, data_object.get("id"), "subscription.deleted"
        ):
            update_data = {
                "stripe_subscription_id": None,
                "plan_updated_at": datetime.now(timezone.utc).isoformat(),
                # The cancellation it warned about has happened, so the flag
                # has done its job. Leaving it set would make
                # check_monthly_reset hold their FREE quota rollover one day
                # a month, every month, for a subscription that ended long
                # ago — a stuck counter with no visible cause, which is the
                # shape of defect this whole day has been about.
                "cancel_at_period_end": False,
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

            # Read before the write, mirroring the thank-you email in
            # _activate_from_checkout_session: the update does not touch
            # email or name, but reading first keeps the notification
            # independent of what the write leaves behind.
            dropped = None if shielded else _user_for_customer(db, customer_id)

            db.table("users").update(update_data).eq(
                "stripe_customer_id", customer_id
            ).execute()

            # Tell them their plan changed — but only when they did not ask
            # for it. Stripe distinguishes the two in cancellation_details:
            # 'cancellation_requested' is the customer or us pressing cancel,
            # and a "your plan has gone back to Free" message minutes after
            # their own confirmation is noise, not service. Mary Bass would
            # have received exactly that on 2026-08-12.
            #
            # Anything else — payment_failed, payment_disputed, or a reason
            # Stripe did not give — is a plan the user lost without choosing
            # to, which until now they discovered by hitting the free cap.
            # One guard, not two: `dropped` above is already None for a
            # shielded user, and a second `if not shielded` here would be a
            # redundancy no mutation could distinguish — which is how a
            # guard stops being load-bearing without anyone noticing.
            if dropped:
                reason = (
                    (data_object.get("cancellation_details") or {}).get("reason")
                    or ""
                )
                # `is not None`, not truthiness: BackgroundTasks is a
                # list-like whose empty instance is falsy, so the obvious
                # spelling silently skips the first task of every request.
                if (reason != "cancellation_requested"
                        and dropped.get("email")
                        and background_tasks is not None):
                        background_tasks.add_task(
                            welcome_email.send_plan_dropped_email,
                            dropped["email"],
                            dropped.get("name"),
                            "payment_failed",
                            dropped.get("preferred_language"),
                        )

            if not shielded:
                logger.info("Subscription deleted for customer %s", customer_id)

    # ── customer.subscription.updated ──
    elif event_type == "customer.subscription.updated":
        customer_id = data_object.get("customer")
        status = data_object.get("status")

        if customer_id and status and _event_subscription_is_current(
            db, customer_id, data_object.get("id"), "subscription.updated"
        ):
            update_data = {
                "plan_updated_at": datetime.now(timezone.utc).isoformat(),
                # Recorded on every subscription.updated, whatever the status.
                # Stripe sends this event for the portal toggle that sets a
                # cancellation and for the one that undoes it, so writing it
                # unconditionally is what keeps the flag honest in both
                # directions — and it touches no quota field, which is the
                # rule this handler already documents below.
                #
                # check_monthly_reset reads it so a customer whose
                # subscription ends later today does not roll over into one
                # last free quota month at 00:00 UTC first.
                "cancel_at_period_end": bool(
                    data_object.get("cancel_at_period_end")
                ),
            }

            if status in ("active", "trialing"):
                # Determine plan from subscription price
                try:
                    items = (data_object.get("items") or {}).get("data") or []
                    sub_price_id = items[0]["price"]["id"] if items else ""
                    update_data["plan"] = _plan_for_price(
                        sub_price_id, f"subscription.updated for {customer_id}"
                    )
                except (KeyError, IndexError, TypeError):
                    # Malformed event. Same reasoning as the checkout path:
                    # the old code defaulted to "pro" here too.
                    logger.exception(
                        "Malformed subscription.updated payload for %s", customer_id
                    )
                    update_data["plan"] = _UNKNOWN_PRICE_PLAN
            elif status == "past_due":
                # NOT a downgrade. past_due means Stripe is still collecting:
                # Smart Retries run for about two weeks (Faisal's ran 10
                # attempts from 07-25 to 08-08) and the customer's card may
                # yet succeed. Taking the plan away on the first failed
                # renewal punishes someone Stripe still counts as a paying
                # subscriber, and it did: solutionsweekly dropped to free on
                # 08-10 with an invoice due 09-08, and Faisal spent his last
                # fourteen days as a customer capped at the free tier while
                # we kept trying to charge him.
                #
                # Only plan_updated_at moves, which is the marker an operator
                # reads to tell "handler ran" from "event never arrived".
                #
                # Safe because retry exhaustion ENDS the subscription:
                # Stripe's failed-payment setting cancels it, which arrives
                # as customer.subscription.deleted and downgrades above. If
                # that setting is ever changed to "leave the subscription
                # as-is", nothing would ever downgrade and this branch needs
                # a time limit.
                logger.info(
                    "Subscription past_due for customer %s — plan held while "
                    "Stripe retries",
                    customer_id,
                )
            elif status in ("canceled", "unpaid"):
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
        # A renewal is a fact Stripe reports, not a moment we predict.
        #
        # The quota month used to roll over on a DATE match from the beat,
        # minutes after 00:00 UTC. Stripe charges at the subscription's
        # creation TIME — 20:20 UTC for the customer that surfaced this on
        # 2026-08-14 — so every subscriber got the new month's quota about
        # twenty hours before paying for it, every month.
        #
        # billing_reason tells the three invoice kinds apart, and only one of
        # them is a new month:
        #   subscription_create — the first invoice. _activate_from_checkout
        #     _session already anchors the quota; rolling here would zero a
        #     counter that was just set.
        #   subscription_update — a mid-cycle plan change. The period did not
        #     restart, so neither should the quota.
        #   subscription_cycle  — the renewal. This one.
        if data_object.get("billing_reason") == "subscription_cycle":
            # Both payload shapes, deliberately. Webhook payloads take the
            # shape of the ENDPOINT's pinned API version, not this library's:
            # before 2025-03-31.basil the invoice carries a top-level
            # `subscription`; from basil on it lives at
            # parent.subscription_details.subscription. Reading only one
            # shape would leave the orphan-invoice guard silently inert on
            # the other — and a guard that cannot see its input must say so,
            # hence the warning.
            invoice_sub_id = data_object.get("subscription") or (
                ((data_object.get("parent") or {}).get("subscription_details")
                 or {}).get("subscription")
            )
            if not invoice_sub_id:
                logger.warning(
                    "renewal invoice %s carries no subscription id in either "
                    "the pre-basil or basil shape — the orphan-invoice guard "
                    "cannot run for this event",
                    data_object.get("id"),
                )
            _roll_quota_on_renewal(
                db,
                data_object.get("customer") or "",
                invoice_sub_id=invoice_sub_id,
            )

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
        dispute_update = {
            "stripe_subscription_id": None,
            "plan_updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # A manual promo outranks a chargeback on the SUBSCRIPTION, because
        # they are about different money. The gift was granted by us, for
        # free, usually as an apology; disputing a card charge says nothing
        # about it. The other two downgrade paths — subscription.deleted and
        # subscription.updated — were shielded on 2026-08-08 and this one was
        # missed, which would have made a chargeback the one remaining way to
        # silently revoke a promise we made in writing.
        #
        # The subscription id is still cleared and the Stripe cancel still
        # runs: what the customer paid for genuinely ends. Only the gift
        # survives, and only until its own expiry.
        # customer_id from the charge, not user_row — the lookup above does
        # not select stripe_customer_id, so reading it off the row would
        # always be None and the shield would never fire.
        shielded = _promo_shield(db, customer_id or "")
        if shielded and shielded.get("id") == user_row["id"]:
            _retarget_grant_to_free(db, user_row["id"])
            logger.info(
                "Dispute for user %s — plan held by manual promo until %s",
                user_row["id"],
                shielded.get("manual_promo_until"),
            )
        else:
            dispute_update["plan"] = "free"

        db.table("users").update(dispute_update).eq("id", user_row["id"]).execute()

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


def _roll_quota_on_renewal(
    db, customer_id: str, *, invoice_sub_id: str | None = None
) -> None:
    """Start the paid month at the moment it was paid for.

    Delegates to the same check_monthly_reset the beat uses, with the one
    flag that lifts its hold — so there is exactly one rollover rule and two
    ways to reach it, rather than two rules that can disagree.

    Idempotent by construction: check_monthly_reset does nothing unless the
    stored anchor is genuinely a period behind. A Stripe redelivery, or a
    renewal arriving after the backstop already rolled it, both land on a
    no-op. That is why this is a delegation and not an UPDATE.

    Never raises. This runs inside the webhook handler, and a failure here
    must not make us return non-2xx to Stripe — which would have it retry the
    whole event, including the parts that already succeeded.
    """
    if not customer_id:
        return
    try:
        res = (
            db.table("users")
            .select(
                "id, email, month_reset_date, month_reset_anchor_day, "
                "emails_sent_this_month, ai_generations_this_month, "
                "cancel_at_period_end, stripe_subscription_id"
            )
            .eq("stripe_customer_id", customer_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            logger.warning(
                "renewal invoice for customer %s matches no user row",
                customer_id,
            )
            return
        user = rows[0]

        # The invoice must belong to the subscription this account runs on.
        # A customer can carry an orphan subscription (the pre-fix dual-
        # checkout bug, or cancel-then-resubscribe), and the orphan's cycle
        # differs from the real one — rolling on both would hand out two
        # resets a month. No last_cycle_invoice_at stamp either: stamping on
        # an orphan's invoice would tell the green report the real renewal
        # arrived when it did not.
        stored = user.get("stripe_subscription_id")
        if invoice_sub_id and stored and stored != invoice_sub_id:
            logger.warning(
                "renewal invoice for customer %s is for subscription %s, but "
                "the account runs on %s — not rolling the quota month",
                customer_id,
                invoice_sub_id,
                stored,
            )
            return

        before = user.get("month_reset_date")
        user_model.check_monthly_reset(user, paid_cycle_confirmed=True)
        rolled = user.get("month_reset_date") != before

        # Stamped whether or not it rolled: the question this answers is "is
        # the event path alive", and a redelivery that correctly no-ops is
        # still evidence that it is. Separate update so a missing column
        # (migration 031 unrun) cannot take the rollover down with it.
        try:
            db.table("users").update(
                {"last_cycle_invoice_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", user["id"]).execute()
        except Exception:  # noqa: BLE001
            logger.warning(
                "could not stamp last_cycle_invoice_at for %s "
                "(is migration 031 run?)",
                user["id"],
                exc_info=True,
            )

        logger.info(
            "renewal for %s: quota %s (anchor %s -> %s)",
            user.get("email"),
            "rolled over" if rolled else "already current, no-op",
            before,
            user.get("month_reset_date"),
        )
        # Operator ping on every paid renewal. Deliberately NOT gated on
        # `rolled`: an invoice arriving after the backstop already rolled
        # the month is still real money. Redeliveries are rare (this
        # handler never returns non-2xx), so the duplicate risk is near
        # zero while a missed payment ping would defeat the point.
        _telegram_alert(
            f"🔄 Renewal paid: {user.get('email') or customer_id}"
            + ("" if rolled else " (quota already current)")
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "could not roll the quota month for customer %s", customer_id
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
        # raise_for_status, because a 401 from a revoked token, a 400 from a
        # wrong chat id and a 429 from rate limiting all return normally and
        # would otherwise be indistinguishable from delivery. Every guard in
        # this codebase that pings an operator depends on this call actually
        # arriving; a silently dropped alert is the failure they exist to
        # prevent, reproduced one layer down.
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": "true",
            },
            timeout=5.0,
        ).raise_for_status()
    except Exception as e:  # noqa: BLE001
        # Named for disputes when this helper only sent those; it now carries
        # every operator alert, so the undelivered text goes to the log too.
        logger.warning("Operator alert not delivered (%s). Text:\n%s", e, text)


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

# ── Purchasable plans, each number read from its own source ──
#
# The panel used to show a bare "Upgrade Plan" button that opened Stripe
# Checkout for a hardcoded 'starter'. A user who clicked it to find out the
# price landed on a payment form, and Pro could not be bought from the panel
# at all. Two people reached Checkout in the first half of August and left
# without entering a card, which is the expected outcome of a button that
# reads "show me the plans" and behaves like "pay now".
#
# Prices come from Stripe and limits from config.py, deliberately: writing
# either of them a second time is how docs/terms.html spent months promising
# a 50-email free tier. Nothing here holds a number of its own.
_PLAN_CACHE: dict = {"at": None, "plans": None}
_PLAN_CACHE_TTL_SECONDS = 3600

# One alert per process, not one per request. The cache above stores only
# successes, so a Stripe outage re-enters the failure branch on every panel
# open; an alert that fires hundreds of times gets muted, and a muted channel
# is how the next real one is missed.
_CATALOGUE_ALERTED = False


def _alert_catalogue_unavailable() -> None:
    """Say out loud that the panel has lost its plan picker.

    The startup guard in utils/config_guard.py covers an unset price id. This
    covers everything else that empties the catalogue — Stripe unreachable, a
    price archived, a tiered price with no unit_amount — because they all land
    in the same place: the panel falls back to its old single button and
    nothing says so.
    """
    global _CATALOGUE_ALERTED
    if _CATALOGUE_ALERTED:
        return
    _CATALOGUE_ALERTED = True
    try:
        _telegram_alert(
            "🚨 OutMass PLAN CATALOGUE UNAVAILABLE\n\n"
            "Stripe prices could not be read, so /billing/status is carrying "
            "no plans. The panel is showing its old single Upgrade button, "
            "nobody can see a price before the payment form, and every "
            "checkout is a hardcoded Starter.\n\n"
            "Alerting once per process; check the logs for the cause."
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not deliver the plan-catalogue alert")


def _purchasable_plans() -> list[dict]:
    """Starter and Pro with live prices, or the last good answer.

    On a Stripe failure this serves the cached catalogue rather than a
    partial one: a pricing list missing a product is its own kind of wrong,
    and a WRONG price is worse than no price at all — the caller falls back
    to the old single button when this is empty.
    """
    now = datetime.now(timezone.utc)
    cached = _PLAN_CACHE.get("plans")
    at = _PLAN_CACHE.get("at")
    if cached is not None and at is not None:
        if (now - at).total_seconds() < _PLAN_CACHE_TTL_SECONDS:
            return cached

    wanted = (
        ("starter", STRIPE_STARTER_PRICE_ID, STARTER_PLAN_MONTHLY_LIMIT),
        ("pro", STRIPE_PRO_PRICE_ID, PRO_PLAN_MONTHLY_LIMIT),
    )
    plans = []
    try:
        for key, price_id, limit in wanted:
            if not price_id:
                raise RuntimeError(f"{key} price id is not configured")
            price = stripe.Price.retrieve(price_id)
            amount = price.get("unit_amount")
            if amount is None:
                raise RuntimeError(f"{key} price has no unit_amount")
            plans.append({
                "key": key,
                "amount": amount,
                "currency": price.get("currency") or "usd",
                "interval": (price.get("recurring") or {}).get("interval", "month"),
                "limit": limit,
            })
    except Exception:  # noqa: BLE001
        logger.warning("Could not build the plan catalogue", exc_info=True)
        if not cached and (STRIPE_SECRET_KEY or "").strip():
            # Two conditions, both narrowing toward "a real operator would
            # want to know". Only when the panel is actually left without
            # prices — a stale but good catalogue is still a working picker,
            # and alerting on that is the false alarm that teaches us to
            # ignore the channel. And only where Stripe is configured at all,
            # the same exemption missing_plan_price_ids() makes: a service
            # that does no billing is not misconfigured.
            _alert_catalogue_unavailable()
        return cached or []

    _PLAN_CACHE["plans"] = plans
    _PLAN_CACHE["at"] = now
    return plans


def _plan_ended_recently(user: dict) -> bool:
    """Is this a Free account that was paying until recently?

    stripe_customer_id is written only on a completed checkout, so it set
    while plan is 'free' means exactly "paid at some point, not paying now" —
    no migration needed to ask the question.

    Bounded by PLAN_DROP_NOTICE_DAYS because the condition itself never
    stops being true. A user who paid once in June and has been happily on
    Free since does not need a banner about it in December.

    Never raises: a malformed timestamp must not take out the panel's whole
    status call, and the cost of answering False is a missing explanation
    rather than a wrong one.
    """
    try:
        if (user.get("plan") or "free") != "free":
            return False
        if not user.get("stripe_customer_id"):
            return False
        changed = user.get("plan_updated_at")
        if not changed:
            return False
        when = datetime.fromisoformat(str(changed).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - when).days
        return 0 <= age <= PLAN_DROP_NOTICE_DAYS
    except Exception:  # noqa: BLE001
        logger.warning("plan_ended_recently check failed", exc_info=True)
        return False


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
        # Whether the panel should explain why this account is capped.
        # Computed here, not in the extension: the window is one rule and it
        # belongs in one place.
        "plan_ended_recently": _plan_ended_recently(fresh_user),
        # Additive: older clients ignore the key and keep their single
        # Upgrade button. Empty when Stripe could not be read, which is the
        # signal for the panel to fall back rather than show a guess.
        "plans": _purchasable_plans(),
    }


# ─── 5. Success Page ────────────────────────────────────────────────────────

def _success_page(title: str, headline: str, body: str, tint: str) -> Response:
    """The shared shell for the post-checkout page."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — OutMass</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               display: flex; justify-content: center; align-items: center;
               min-height: 100vh; margin: 0; background: {tint}; color: #166534; }}
        .card {{ text-align: center; padding: 3rem; background: #fff; max-width: 30rem;
                border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
        h1 {{ margin: 0 0 .5rem; font-size: 1.5rem; }}
        p  {{ margin: 0; color: #4b5563; line-height: 1.5; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>{headline}</h1>
        <p>{body}</p>
    </div>
</body>
</html>"""
    return Response(content=html, media_type="text/html")


# The one sentence this page exists to say. A bank debit clears days after
# checkout, and until it does the account is still Free with no subscription
# id — exactly what someone who was told "your upgrade is now active" sees
# when they open the panel, and exactly what makes them pay a second time by
# card. Two subscriptions is then our problem to unpick, and the replay guard
# re-zeroes their quota mid-period on the way.
_DONT_PAY_AGAIN = "You don't need to pay again."


@router.get("/success", response_class=HTMLResponse)
async def billing_success(session_id: str = Query(None)):
    """What actually happened, rather than what we hope happened.

    The page ignored its own session_id until 2026-08-14 and told everyone
    their upgrade was active. For a card that is true within a second. For a
    bank debit — live since 2026-08-08 — it is false for several days, and the
    person reading it is looking at a Free account.

    Unauthenticated by nature: Stripe redirects the browser here, so the
    session id is the only thing we have. It is a long random string and the
    page reveals nothing but the state of that one checkout.
    """
    settled = None  # None = we could not tell
    if session_id and STRIPE_SECRET_KEY:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            settled = session.get("payment_status") in _SETTLED_PAYMENT_STATUSES
        except Exception:  # noqa: BLE001
            # A Stripe blip must not turn the page into an error. Falling
            # through to the neutral wording below is safe in both directions.
            logger.warning(
                "Could not read checkout session on the success page",
                exc_info=True,
            )

    if settled is True:
        return _success_page(
            "Payment Successful",
            "Payment successful!",
            "Your plan upgrade is now active. You can close this tab.",
            "#f0fdf4",
        )

    if settled is False:
        return _success_page(
            "Payment Received",
            "Payment on its way",
            "Your bank has the instruction and is sending the money — that "
            "usually takes a few business days. Your plan switches on by "
            f"itself the moment it lands, and we'll email you then. {_DONT_PAY_AGAIN}",
            "#f0f9ff",
        )

    # Neither confirmed nor denied: no session id (an old link, a bookmark) or
    # Stripe unreadable. Deliberately worded to be true whichever it was, and
    # to carry the sentence that matters in both.
    return _success_page(
        "Thank You",
        "Thanks — we're finishing up",
        "Your plan switches on as soon as the payment clears: instantly for a "
        "card, a few business days for a bank transfer. We'll email you when "
        f"it does. {_DONT_PAY_AGAIN}",
        "#f0f9ff",
    )


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
