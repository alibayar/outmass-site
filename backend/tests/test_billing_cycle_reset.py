"""A paid month starts when it is paid for, not at midnight.

check_monthly_reset compares DATES and runs from the unattended beat, so on a
subscriber's anniversary it fires within minutes of 00:00 UTC. Stripe charges
the renewal at the subscription's CREATION time. For the customer that
surfaced this on 2026-08-14 that is 20:20 UTC — so the new month's quota went
live about twenty hours before the month was paid for, every month, for every
subscriber.

The fix is not a more precise calculation. It is to stop calculating: Stripe
already sends invoice.payment_succeeded with billing_reason
subscription_cycle, the webhook already receives it, and that event IS the
fact we were approximating. No clock of ours is involved, so no timezone of
ours can be wrong about it — which matters, because the report that started
this quoted "Jul 14, 11:20 PM" from a Stripe dashboard rendering UTC+3.

The date anchor stays as a bounded backstop. It is also still the whole rule
for free users, who have no subscription and no renewal to wait for.
"""
from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from models.user import check_monthly_reset
from tests.conftest import FakeQueryBuilder


@pytest.fixture()
def client():
    from main import app
    return TestClient(app)


def _user(anchor="2026-07-14", paid=True, sent=2243, **extra):
    row = {
        "id": "u1",
        "email": "marketing@bellmed.com",
        "month_reset_date": anchor,
        "emails_sent_this_month": sent,
        "ai_generations_this_month": 3,
        "emails_sent_total": 9000,
    }
    if paid:
        row["stripe_subscription_id"] = "sub_live"
    row.update(extra)
    return row


# ── The hold ──


def test_a_subscriber_waits_for_stripe_on_the_anniversary():
    """The whole point. Midnight is not when they paid."""
    user = _user()

    with patch("models.user.get_db") as db:
        check_monthly_reset(user, today=date(2026, 8, 14))
        db.assert_not_called()

    assert user["emails_sent_this_month"] == 2243


def test_the_renewal_event_rolls_it_over_immediately():
    user = _user()

    with patch("models.user.get_db"):
        check_monthly_reset(user, today=date(2026, 8, 14), paid_cycle_confirmed=True)

    assert user["emails_sent_this_month"] == 0
    assert user["month_reset_date"] == "2026-08-14"


def test_the_backstop_rolls_it_over_the_next_day():
    """Bounded, exactly like the cancellation hold. A lost webhook or a long
    Stripe retry must not strand a paying customer at zero quota — that is a
    worse bug than the twenty-hour window being closed."""
    user = _user()

    with patch("models.user.get_db"):
        check_monthly_reset(user, today=date(2026, 8, 15))

    assert user["emails_sent_this_month"] == 0
    assert user["month_reset_date"] == "2026-08-14", (
        "the backstop must land on the real anchor, not on the day it noticed"
    )


def test_a_free_user_is_not_held_at_all():
    """No subscription, no renewal to wait for. For free users the anchor is
    not an approximation of anything — it IS the rule."""
    user = _user(paid=False, sent=250)

    with patch("models.user.get_db"):
        check_monthly_reset(user, today=date(2026, 8, 14))

    assert user["emails_sent_this_month"] == 0


def test_nothing_changes_before_the_anchor():
    user = _user()

    with patch("models.user.get_db") as db:
        check_monthly_reset(user, today=date(2026, 8, 13))
        db.assert_not_called()


def test_a_cancelling_subscriber_is_still_held_first():
    """Two holds now guard the same day and they must not fight. A customer
    who is leaving gets no bonus month even if a renewal invoice somehow
    arrives — the cancellation check runs first, deliberately."""
    user = _user(cancel_at_period_end=True)

    with patch("models.user.get_db") as db:
        check_monthly_reset(user, today=date(2026, 8, 14), paid_cycle_confirmed=True)
        db.assert_not_called()

    assert user["emails_sent_this_month"] == 2243


# ── Through the webhook ──


class _RecordingUsers(FakeQueryBuilder):
    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(dict(vals))
        return super().update(vals)


def _invoice(client, fake_db, users, billing_reason):
    event = {
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "customer": "cus_1",
            "billing_reason": billing_reason,
            "attempt_count": 1,
            "amount_paid": 900,
        }},
    }
    fake_db.set_table("users", users)
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing._telegram_alert"), \
         patch("routers.billing._capture_billing_event"):
        return client.post("/billing/webhook", content=b"{}",
                           headers={"stripe-signature": "sig"})


@pytest.mark.parametrize("reason,should_roll", [
    ("subscription_cycle", True),
    ("subscription_create", False),
    ("subscription_update", False),
])
def test_only_a_renewal_invoice_rolls_the_quota(client, fake_db, reason, should_roll):
    """billing_reason separates the three invoice kinds, and only one is a new
    month. subscription_create is the FIRST invoice — the checkout handler has
    just anchored the quota, and rolling here would zero a counter set seconds
    ago. subscription_update is a mid-cycle plan change: the period did not
    restart, so neither should the quota."""
    users = _RecordingUsers([_user()])

    resp = _invoice(client, fake_db, users, reason)

    assert resp.status_code == 200
    rolled = [c for c in users.update_calls if "emails_sent_this_month" in c]
    assert bool(rolled) is should_roll


def test_the_renewal_is_stamped_so_the_event_path_can_be_audited(client, fake_db):
    """Without the stamp there is no way to tell a rollover Stripe confirmed
    from one the backstop did a day late — and "the event path quietly stopped
    working" is exactly the failure that hid a worker's sends for weeks."""
    users = _RecordingUsers([_user()])

    _invoice(client, fake_db, users, "subscription_cycle")

    stamped = [c for c in users.update_calls if "last_cycle_invoice_at" in c]
    assert stamped, "nothing recorded that Stripe confirmed this renewal"


def test_a_redelivered_renewal_does_not_zero_a_second_time(client, fake_db):
    """Stripe redelivers. If the quota has already rolled for this period the
    stored anchor is current, check_monthly_reset does nothing, and the
    customer does not lose the sends they made since."""
    already_rolled = _user(anchor="2026-08-14", sent=140)
    users = _RecordingUsers([already_rolled])

    _invoice(client, fake_db, users, "subscription_cycle")

    zeroed = [c for c in users.update_calls if "emails_sent_this_month" in c]
    assert not zeroed, "a replayed renewal wiped a counter that was current"


def test_an_unknown_customer_does_not_break_the_webhook(client, fake_db):
    """A renewal for a customer we cannot match must still return 2xx. A
    non-2xx makes Stripe retry the WHOLE event, including the parts that
    already succeeded."""
    users = _RecordingUsers([])

    resp = _invoice(client, fake_db, users, "subscription_cycle")

    assert resp.status_code == 200
