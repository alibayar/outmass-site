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
