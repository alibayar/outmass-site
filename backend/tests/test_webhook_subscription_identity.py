"""A subscription event may only act on the subscription the account runs on.

The downgrade branches match users on stripe_customer_id, but a Stripe
customer can carry more than one subscription over time: the pre-2026-08-08
dual-checkout bug created orphans, and the ordinary cancel-then-resubscribe
flow does it legitimately — the old subscription dies at period end AFTER the
new one exists, and its deleted event used to downgrade the freshly
re-paying customer. Second half of the 2026-07-03 review's item 4; the first
half (502 on a failed Subscription.retrieve) shipped separately.

The guard fails toward the OLD behaviour on purpose: an event with no id, a
customer with no row, a stored id of NULL, or a read error all act exactly
as before. Only a stored id that is present and DIFFERENT is refused —
a wrongly-processed event is bounded and visible, a silently immortal plan
is neither.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from routers.billing import _event_subscription_is_current
from tests.conftest import FakeQueryBuilder


@pytest.fixture()
def client():
    from main import app
    return TestClient(app)


class _RecordingUsers(FakeQueryBuilder):
    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(dict(vals))
        return super().update(vals)


def _row(stored="sub_live"):
    return {
        "id": "u1",
        "email": "x@y.com",
        "plan": "starter",
        "stripe_subscription_id": stored,
        # Overdue anchor so a renewal that IS accepted visibly rolls.
        "month_reset_date": "2026-07-14",
        "emails_sent_this_month": 2243,
        "ai_generations_this_month": 3,
    }


def _post(client, fake_db, users, event, alerts=None):
    fake_db.set_table("users", users)
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing._promo_shield", return_value=None), \
         patch("routers.billing._user_for_customer", return_value=None), \
         patch("routers.billing._telegram_alert",
               side_effect=(alerts.append if alerts is not None else None)), \
         patch("routers.billing._capture_billing_event"):
        return client.post("/billing/webhook", content=b"{}",
                           headers={"stripe-signature": "sig"})


def _deleted(sub_id):
    obj = {"customer": "cus_1"}
    if sub_id is not None:
        obj["id"] = sub_id
    return {"type": "customer.subscription.deleted", "data": {"object": obj}}


# ── customer.subscription.deleted ──


def test_a_stale_subscriptions_death_does_not_downgrade(client, fake_db):
    """The resubscribe scenario: the account runs on sub_new; sub_old dies at
    its period end. Until 2026-08-15 this downgraded a paying customer."""
    users = _RecordingUsers([_row(stored="sub_new")])
    alerts = []

    resp = _post(client, fake_db, users, _deleted("sub_old"), alerts=alerts)

    assert resp.status_code == 200, "a refused event is still a handled event"
    assert users.update_calls == [], "the account must be left untouched"
    assert alerts and "sub_old" in alerts[0] and "sub_new" in alerts[0], (
        "two subscriptions on one customer is a thing an operator should see"
    )


def test_the_current_subscriptions_death_still_downgrades(client, fake_db):
    users = _RecordingUsers([_row(stored="sub_live")])

    _post(client, fake_db, users, _deleted("sub_live"))

    dropped = [c for c in users.update_calls if c.get("plan") == "free"]
    assert dropped, "the real cancellation must still land"


def test_a_row_with_no_stored_subscription_still_downgrades(client, fake_db):
    """Legacy rows and lost checkout webhooks have NULL stored ids. Refusing
    those would mean nothing ever downgrades them."""
    users = _RecordingUsers([_row(stored=None)])

    _post(client, fake_db, users, _deleted("sub_whatever"))

    assert any(c.get("plan") == "free" for c in users.update_calls)


def test_an_event_with_no_id_keeps_the_old_behaviour(client, fake_db):
    users = _RecordingUsers([_row(stored="sub_live")])

    _post(client, fake_db, users, _deleted(None))

    assert any(c.get("plan") == "free" for c in users.update_calls)


# ── customer.subscription.updated ──


def test_a_stale_subscription_update_is_ignored(client, fake_db):
    """The orphan's status churn must not write anything — not a plan, and
    not its cancel_at_period_end flag onto an account it does not describe."""
    users = _RecordingUsers([_row(stored="sub_new")])

    _post(client, fake_db, users, {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_old", "customer": "cus_1", "status": "canceled",
            "cancel_at_period_end": True,
        }},
    })

    assert users.update_calls == []


def test_the_current_subscriptions_update_still_lands(client, fake_db):
    users = _RecordingUsers([_row(stored="sub_live")])

    _post(client, fake_db, users, {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_live", "customer": "cus_1", "status": "canceled",
            "cancel_at_period_end": False,
        }},
    })

    assert any(c.get("plan") == "free" for c in users.update_calls)


# ── invoice.payment_succeeded (the renewal roll) ──


def _invoice(sub_id):
    return {
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "customer": "cus_1",
            "billing_reason": "subscription_cycle",
            "subscription": sub_id,
            "attempt_count": 1,
            "amount_paid": 900,
        }},
    }


def test_an_orphan_renewal_invoice_neither_rolls_nor_stamps(client, fake_db):
    """The orphan's cycle differs from the real one: rolling on both would
    hand out two resets a month, and stamping last_cycle_invoice_at on the
    orphan's invoice would tell the green report the real renewal arrived
    when it did not."""
    users = _RecordingUsers([_row(stored="sub_live")])

    resp = _post(client, fake_db, users, _invoice("sub_orphan"))

    assert resp.status_code == 200
    assert users.update_calls == []


def test_the_real_renewal_invoice_still_rolls_and_stamps(client, fake_db):
    users = _RecordingUsers([_row(stored="sub_live")])

    _post(client, fake_db, users, _invoice("sub_live"))

    assert any("emails_sent_this_month" in c for c in users.update_calls)
    assert any("last_cycle_invoice_at" in c for c in users.update_calls)


# ── The Basil shape ──
#
# Webhook payloads take the shape of the ENDPOINT's pinned API version, not
# this library's: from 2025-03-31.basil the invoice's subscription id moved
# from the top level to parent.subscription_details. A guard that reads only
# one location is silently inert on the other — found by the 2026-08-15
# review, precisely because the fixtures above hand-build the OLD shape.


def _basil_invoice(sub_id):
    return {
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "customer": "cus_1",
            "billing_reason": "subscription_cycle",
            "parent": {"subscription_details": {"subscription": sub_id}},
            "attempt_count": 1,
            "amount_paid": 900,
        }},
    }


def test_an_orphan_renewal_is_refused_in_the_basil_shape_too(client, fake_db):
    users = _RecordingUsers([_row(stored="sub_live")])

    resp = _post(client, fake_db, users, _basil_invoice("sub_orphan"))

    assert resp.status_code == 200
    assert users.update_calls == []


def test_the_real_renewal_rolls_in_the_basil_shape_too(client, fake_db):
    users = _RecordingUsers([_row(stored="sub_live")])

    _post(client, fake_db, users, _basil_invoice("sub_live"))

    assert any("emails_sent_this_month" in c for c in users.update_calls)


# ── checkout.session.completed, hardened by the same review ──


def _checkout(client, fake_db, users, *, created=None, subscription="sub_new",
              current_period_start=None, alerts=None):
    obj = {
        "metadata": {"user_id": "u1"},
        "customer": "cus_1",
        "subscription": subscription,
        "payment_status": "paid",
    }
    if created is not None:
        obj["created"] = created
    event = {"type": "checkout.session.completed", "data": {"object": obj}}
    fake_sub = {"items": {"data": [{"price": {"id": "price_x"}}]}}
    if current_period_start is not None:
        fake_sub["current_period_start"] = current_period_start
    fake_db.set_table("users", users)
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.stripe.Subscription.retrieve", return_value=fake_sub), \
         patch("routers.billing.STRIPE_STARTER_PRICE_ID", "price_x"), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing._telegram_alert",
               side_effect=(alerts.append if alerts is not None else None)), \
         patch("routers.billing._capture_billing_event"):
        return client.post("/billing/webhook", content=b"{}",
                           headers={"stripe-signature": "sig"})


def test_a_historical_checkout_event_changes_nothing(client, fake_db):
    """A dashboard "Resend" of a weeks-old activation must not resurrect a
    plan a later cancellation took away. The id-based replay guard cannot
    see this case, because the cancellation NULLed the stored id — so age
    is the discriminator: no organic delivery is this old."""
    users = _RecordingUsers([_row(stored=None)])  # cancelled account
    alerts = []
    old = int(datetime.now(timezone.utc).timestamp()) - 40 * 86400

    resp = _checkout(client, fake_db, users, created=old, alerts=alerts)

    assert resp.status_code == 200
    assert users.update_calls == [], "history must not write anything"
    assert alerts and "historical" in alerts[0]


def test_a_fresh_checkout_event_still_activates(client, fake_db):
    users = _RecordingUsers([_row(stored=None)])
    now_ish = int(datetime.now(timezone.utc).timestamp()) - 60

    _checkout(client, fake_db, users, created=now_ish)

    assert any(c.get("plan") == "starter" for c in users.update_calls)


def test_the_anchor_comes_from_stripes_clock_not_ours(client, fake_db):
    """The webhook can arrive after UTC midnight or days late on a retry;
    the quota cycle must anchor where the BILLING cycle starts, which is the
    subscription's own period start, not our processing moment."""
    users = _RecordingUsers([_row(stored=None)])
    period_start = int(
        datetime(2026, 8, 12, 20, 20, tzinfo=timezone.utc).timestamp()
    )

    _checkout(client, fake_db, users, current_period_start=period_start)

    anchored = [c for c in users.update_calls if "month_reset_date" in c]
    assert anchored and anchored[0]["month_reset_date"] == "2026-08-12"
    assert anchored[0]["month_reset_anchor_day"] == 12


def test_a_subscriptionless_session_does_not_null_the_stored_id(client, fake_db):
    """NULL is the one state every identity guard reads as "act on
    anything" — an anomalous session must not write the customer into it."""
    users = _RecordingUsers([_row(stored="sub_live")])
    alerts = []

    _checkout(client, fake_db, users, subscription=None, alerts=alerts)

    assert all(
        "stripe_subscription_id" not in c for c in users.update_calls
    ), "the anomalous session overwrote a live subscription id"


# ── The guard itself fails open ──


def test_a_read_error_fails_toward_acting():
    """A wrongly-processed event is bounded; a silently immortal plan is
    not. When the comparison cannot be made, the old behaviour wins."""
    db = MagicMock()
    db.table.side_effect = RuntimeError("supabase hiccup")

    assert _event_subscription_is_current(db, "cus_1", "sub_x", "t") is True
