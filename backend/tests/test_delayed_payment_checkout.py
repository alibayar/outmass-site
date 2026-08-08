"""ACH Direct Debit: do not fulfil before the money clears.

ACH was enabled on 2026-08-08. Unlike a card, where checkout.session.completed
IS the payment, a bank debit only *authorises* at that moment — the money
arrives days later and can bounce. Stripe says so on the enablement dialog:
"To ensure you don't fulfil an order before payment clears, use webhooks."

Until this change the handler granted the plan on completed regardless. That
would hand out a full Starter month — 2,500 sends, counters re-zeroed — against
a debit that may never settle. The cash at risk is $9 and our marginal cost is
near zero (mail leaves through the customer's own Microsoft mailbox), but a
mass-email tool that opens 2,500 sends on an unverified bank instruction is an
abuse target, and a plan we grant is a plan we report as revenue.

The ordering these tests pin:

  card:  completed(paid)                       -> granted
  ACH:   completed(unpaid) -> async_succeeded  -> granted once, at the end
  ACH:   completed(unpaid) -> async_failed     -> never granted, operator told
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeQueryBuilder


class _RecordingUsers(FakeQueryBuilder):
    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(dict(vals))
        return super().update(vals)


@pytest.fixture()
def client():
    from main import app
    return TestClient(app)


def _user_row():
    return {
        "id": "u-ach",
        "email": "ach@example.com",
        "name": "ACH Buyer",
        "plan": "free",
        "stripe_subscription_id": None,
        "emails_sent_this_month": 180,
    }


def _session(payment_status, session_id="cs_test_ach"):
    return {
        "id": session_id,
        "metadata": {"user_id": "u-ach", "plan": "starter"},
        "customer": "cus_ach",
        "subscription": "sub_ach",
        "payment_status": payment_status,
        "amount_total": 900,
        "currency": "usd",
    }


def _post(client, event):
    fake_sub = {"items": {"data": [{"price": {"id": "price_whatever"}}]}}
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.stripe.Subscription.retrieve", return_value=fake_sub), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing.welcome_email.send_upgrade_email"), \
         patch("routers.billing._telegram_alert") as alert, \
         patch("routers.billing._capture_billing_event") as capture:
        resp = client.post(
            "/billing/webhook", content=b"{}",
            headers={"stripe-signature": "sig"},
        )
    return resp, alert, capture


def _completed(payment_status):
    return {
        "type": "checkout.session.completed",
        "data": {"object": _session(payment_status)},
    }


# ── The card path must be untouched ──


@pytest.mark.parametrize("status", ["paid", "no_payment_required"])
def test_settled_session_still_grants_the_plan(client, fake_db, status):
    """A card session, and a 100%-coupon session, both settle immediately.
    This change must be invisible to every existing customer."""
    users = _RecordingUsers(rows=[_user_row()])
    fake_db.set_table("users", users)

    resp, _, _ = _post(client, _completed(status))

    assert resp.status_code == 200
    granted = [c for c in users.update_calls if c.get("plan")]
    assert len(granted) == 1
    assert granted[0]["stripe_subscription_id"] == "sub_ach"
    # Quota period re-anchored on first purchase.
    assert granted[0]["emails_sent_this_month"] == 0


# ── The delayed path must withhold ──


def test_unpaid_session_grants_nothing(client, fake_db):
    """The whole point. ACH completes while still unpaid."""
    users = _RecordingUsers(rows=[_user_row()])
    fake_db.set_table("users", users)

    resp, _, _ = _post(client, _completed("unpaid"))

    assert resp.status_code == 200
    assert users.update_calls == [], (
        "a plan was granted against a bank debit that has not cleared"
    )


def test_async_success_grants_the_plan(client, fake_db):
    """The real moment of purchase for a bank debit."""
    users = _RecordingUsers(rows=[_user_row()])
    fake_db.set_table("users", users)

    resp, _, _ = _post(client, {
        "type": "checkout.session.async_payment_succeeded",
        "data": {"object": _session("paid")},
    })

    assert resp.status_code == 200
    granted = [c for c in users.update_calls if c.get("plan")]
    assert len(granted) == 1
    assert granted[0]["emails_sent_this_month"] == 0


def test_full_ach_sequence_activates_exactly_once(client, fake_db):
    """completed(unpaid) then async_succeeded is ONE purchase.

    The replay guard keys off stripe_subscription_id already being stored,
    so the quota must be re-anchored once — not once per event.
    """
    users = _RecordingUsers(rows=[_user_row()])
    fake_db.set_table("users", users)

    _post(client, _completed("unpaid"))
    assert users.update_calls == []

    # The fake table does not persist writes back into the row, so model the
    # subscription id landing before the redelivery below.
    _post(client, {
        "type": "checkout.session.async_payment_succeeded",
        "data": {"object": _session("paid")},
    })

    anchored = [c for c in users.update_calls if "emails_sent_this_month" in c]
    assert len(anchored) == 1


def test_async_success_replay_does_not_refill_quota(client, fake_db):
    """Stripe redelivers. A second async_payment_succeeded for a
    subscription we already stored must not hand out a bonus month."""
    users = _RecordingUsers(rows=[dict(_user_row(), stripe_subscription_id="sub_ach")])
    fake_db.set_table("users", users)

    _post(client, {
        "type": "checkout.session.async_payment_succeeded",
        "data": {"object": _session("paid")},
    })

    assert not any("emails_sent_this_month" in c for c in users.update_calls)


# ── The debit bounced ──


def test_async_failure_grants_nothing_and_tells_the_operator(client, fake_db):
    """Nothing to revoke — but the customer went through checkout days ago
    and believes they subscribed. Only a human can tell them."""
    users = _RecordingUsers(rows=[_user_row()])
    fake_db.set_table("users", users)

    resp, alert, capture = _post(client, {
        "type": "checkout.session.async_payment_failed",
        "data": {"object": _session("unpaid")},
    })

    assert resp.status_code == 200
    assert users.update_calls == []
    alert.assert_called_once()
    assert "FAILED" in alert.call_args.args[0]
    capture.assert_called_once()
    assert capture.call_args.args[1] == "checkout_async_payment_failed"
