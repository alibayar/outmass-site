"""Checkout-funnel telemetry tests.

Before this feature, an abandoned Stripe Checkout was invisible: the
extension tracked upgrade_button_clicked, then nothing — completed
checkouts showed up via the webhook, abandoned ones only existed in
Stripe's API request logs (found manually during the 2026-07-17
ekaynimos investigation). Now:

  - create-checkout emits `checkout_session_created` (PostHog)
  - checkout.session.expired webhook emits `checkout_abandoned`
  - `checkout_abandoned` rides the daily report's INFO list

The webhook handler is telemetry-only: it must never change user state.
"""
from unittest.mock import MagicMock, patch

from tests.conftest import FAKE_USER, FakeQueryBuilder


def _post_expired(client, session_obj, posthog_key="phc_test"):
    event = {
        "type": "checkout.session.expired",
        "data": {"object": session_obj},
    }
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing.POSTHOG_API_KEY", posthog_key), \
         patch("routers.billing.posthog.capture") as capture:
        resp = client.post(
            "/billing/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
    return resp, capture


def test_expired_session_emits_checkout_abandoned(client, fake_db):
    fake_db.set_table(
        "users",
        FakeQueryBuilder(data=[{
            "id": "u-42",
            "email": "walker@x.com",
            "plan": "free",
            "stripe_subscription_id": None,
        }]),
    )

    resp, capture = _post_expired(client, {
        "id": "cs_expired_1",
        "metadata": {"user_id": "u-42", "plan": "starter"},
        "customer_email": "walker@x.com",
        "amount_total": 900,
        "currency": "usd",
    })

    assert resp.status_code == 200
    capture.assert_called_once()
    kwargs = capture.call_args.kwargs
    assert kwargs["distinct_id"] == "walker@x.com"
    assert kwargs["event"] == "checkout_abandoned"
    props = kwargs["properties"]
    assert props["plan"] == "starter"
    assert props["already_subscribed"] is False
    assert props["amount_total"] == 900


def test_expired_session_flags_user_who_paid_via_newer_session(client, fake_db):
    """User created session A, abandoned it, paid via session B. When A
    expires it must not read as a real abandonment."""
    fake_db.set_table(
        "users",
        FakeQueryBuilder(data=[{
            "id": "u-42",
            "email": "payer@x.com",
            "plan": "starter",
            "stripe_subscription_id": "sub_live",
        }]),
    )

    resp, capture = _post_expired(client, {
        "id": "cs_expired_old",
        "metadata": {"user_id": "u-42", "plan": "starter"},
        "customer_email": "payer@x.com",
    })

    assert resp.status_code == 200
    assert capture.call_args.kwargs["properties"]["already_subscribed"] is True


def test_expired_session_never_mutates_user_state(client, fake_db):
    """Telemetry only — the handler must not write to the users table."""

    class _RecordingUsers(FakeQueryBuilder):
        def __init__(self, rows):
            super().__init__(data=rows)
            self.update_calls = []

        def update(self, vals):
            self.update_calls.append(vals)
            return super().update(vals)

    users = _RecordingUsers(rows=[{
        "id": "u-42",
        "email": "walker@x.com",
        "plan": "free",
        "stripe_subscription_id": None,
    }])
    fake_db.set_table("users", users)

    resp, _ = _post_expired(client, {
        "id": "cs_x",
        "metadata": {"user_id": "u-42", "plan": "pro"},
        "customer_email": "walker@x.com",
    })

    assert resp.status_code == 200
    assert users.update_calls == []


def test_expired_session_without_posthog_key_still_returns_200(client, fake_db):
    resp, capture = _post_expired(
        client,
        {"id": "cs_x", "metadata": {}, "customer_email": "a@b.c"},
        posthog_key="",
    )
    assert resp.status_code == 200
    capture.assert_not_called()


def test_payment_failed_fires_telegram_alert(client, fake_db):
    """A failed renewal must ping the operator (it used to be a silent
    log line — Faisal's 07-25 soft-decline went unnoticed for a day)."""
    from unittest.mock import patch as _patch

    class _StableUsers(FakeQueryBuilder):
        """update() must not clobber the stored row — the handler runs a
        plan_updated_at update BEFORE the email lookup."""

        def update(self, vals):
            return self

    fake_db.set_table(
        "users",
        _StableUsers(data=[{
            "id": "u-f", "email": "payer@x.com", "plan": "starter",
            "stripe_customer_id": "cus_f",
        }]),
    )
    event = {
        "type": "invoice.payment_failed",
        "data": {"object": {"customer": "cus_f", "amount_due": 900}},
    }
    with _patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         _patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         _patch("routers.billing._telegram_alert") as alert:
        resp = client.post(
            "/billing/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200
    alert.assert_called_once()
    msg = alert.call_args.args[0]
    assert "payment FAILED" in msg
    assert "payer@x.com" in msg
    assert "$9.00" in msg


def _fire_payment_failed(client, invoice_obj, users_table=None):
    from unittest.mock import patch as _patch

    with _patch("routers.billing.stripe.Webhook.construct_event", return_value={
        "type": "invoice.payment_failed",
        "data": {"object": invoice_obj},
    }), \
         _patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         _patch("routers.billing._telegram_alert") as alert:
        resp = client.post(
            "/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"}
        )
    assert resp.status_code == 200
    return alert.call_args.args[0]


def test_first_payment_failure_is_flagged_as_urgent_not_self_healing(client, fake_db):
    """A new customer's FIRST payment gets no Smart Retries.

    Stripe voids the invoice and expires the subscription ~24h later, so the
    operator has a same-day window. On 2026-07-29 a new customer entered
    three different cards in 90 seconds, all refused, and the alert told the
    operator Stripe would retry — the sale died 24h later (07-30 15:47:
    invoice.voided + payment_intent.canceled + session expired).
    """
    class _NoRows(FakeQueryBuilder):
        def update(self, vals):
            return self

    fake_db.set_table("users", _NoRows(data=[]))

    msg = _fire_payment_failed(client, {
        "customer": "cus_new",
        "amount_due": 900,
        "billing_reason": "subscription_create",
        "customer_email": "buyer@newco.com",
        "attempt_count": 1,
    })

    assert "FIRST payment FAILED" in msg
    assert "No auto-retry" in msg
    assert "TODAY" in msg
    assert "Smart Retries" not in msg, "must not tell the operator to wait"
    # A first-time buyer has no stripe_customer_id in our DB yet; the invoice
    # carries the address, so the alert must still name them.
    assert "buyer@newco.com" in msg
    assert "unresolved" not in msg


def test_renewal_with_no_further_retry_says_so(client, fake_db):
    """next_payment_attempt=None means Stripe is done trying."""
    class _StableUsers(FakeQueryBuilder):
        def update(self, vals):
            return self

    fake_db.set_table("users", _StableUsers(data=[{
        "id": "u-1", "email": "payer@x.com", "plan": "starter",
        "stripe_customer_id": "cus_f",
    }]))

    msg = _fire_payment_failed(client, {
        "customer": "cus_f",
        "amount_due": 900,
        "billing_reason": "subscription_cycle",
        "attempt_count": 4,
        "next_payment_attempt": None,
    })

    assert "renewal payment FAILED" in msg
    assert "last attempt" in msg
    assert "must update the card" in msg


def test_renewal_with_a_retry_pending_keeps_the_hard_decline_caveat(client, fake_db):
    class _StableUsers(FakeQueryBuilder):
        def update(self, vals):
            return self

    fake_db.set_table("users", _StableUsers(data=[{
        "id": "u-1", "email": "payer@x.com", "plan": "starter",
        "stripe_customer_id": "cus_f",
    }]))

    msg = _fire_payment_failed(client, {
        "customer": "cus_f",
        "amount_due": 900,
        "billing_reason": "subscription_cycle",
        "attempt_count": 1,
        "next_payment_attempt": 1790000000,
    })

    assert "Smart Retries" in msg
    # Faisal's card was a hard decline ("Incorrect number"); retries could
    # never have fixed it, and the old text implied they would.
    assert "hard decline" in msg


def test_create_checkout_emits_session_created_and_plan_metadata(
    client, fake_db, auth_bypass
):
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/pay/cs_new"
    fake_session.id = "cs_new"

    with patch("routers.billing.STRIPE_SECRET_KEY", "sk_test"), \
         patch("routers.billing.STRIPE_STARTER_PRICE_ID", "price_starter"), \
         patch("routers.billing.POSTHOG_API_KEY", "phc_test"), \
         patch("routers.billing.posthog.capture") as capture, \
         patch(
             "routers.billing.stripe.checkout.Session.create",
             return_value=fake_session,
         ) as create:
        resp = client.post("/billing/create-checkout", json={"plan": "starter"})

    assert resp.status_code == 200
    assert resp.json()["checkout_url"] == "https://checkout.stripe.com/pay/cs_new"

    # Plan now rides in metadata so checkout.session.expired can report it
    metadata = create.call_args.kwargs["metadata"]
    assert metadata["plan"] == "starter"
    assert metadata["user_id"] == FAKE_USER["id"]

    capture.assert_called_once()
    kwargs = capture.call_args.kwargs
    assert kwargs["event"] == "checkout_session_created"
    assert kwargs["properties"]["plan"] == "starter"
    assert kwargs["properties"]["session_id"] == "cs_new"
