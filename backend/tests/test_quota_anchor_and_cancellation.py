"""Two quota defects that only bite specific customers, on specific days.

Both were deferred from the 2026-07-03 billing-anchored quota review, both
verified still real on 2026-08-14, and both are now unblocked by migrations
029 and 028.

ONE — the anchor decayed. _add_months clamps a 31st to Feb 28, which is
correct, and check_monthly_reset then stored the clamped value back into the
only anchor column there was. So the next period computed from the 28th and
the 31st was gone for good: three days of quota month lost every year, for
anyone who subscribed on the 29th, 30th or 31st. _add_months' own docstring
warns to "always call with the ORIGINAL anchor date"; its caller was the one
place that could not.

TWO — a leaving customer got one more month first. This function compares
DATES and runs from the unattended scheduled-campaign beat, so on the
anniversary it fires within minutes of 00:00 UTC. Stripe ends a cancelling
subscription at the subscription's creation TIME that day, hours later. In
between, we re-zeroed the counter of the one person we already knew was
leaving.
"""
from datetime import date
from unittest.mock import patch

import pytest

from fastapi.testclient import TestClient

from models.user import check_monthly_reset, next_reset_date
from tests.conftest import FakeQueryBuilder


@pytest.fixture()
def client():
    from main import app
    return TestClient(app)


def _user(anchor, anchor_day=None, cancelling=False, sent=100):
    row = {
        "id": "u1",
        "month_reset_date": anchor,
        "emails_sent_this_month": sent,
        "ai_generations_this_month": 3,
        "emails_sent_total": 500,
    }
    if anchor_day is not None:
        row["month_reset_anchor_day"] = anchor_day
    if cancelling:
        row["cancel_at_period_end"] = True
    return row


# ── One: the anchor that decayed ──


def test_a_31st_anchor_comes_back_after_february():
    """The defect, in one assertion. Stored date is the clamped Feb 28; the
    real anchor is the 31st, and March has one."""
    user = _user("2026-02-28", anchor_day=31)

    with patch("models.user.get_db"):
        check_monthly_reset(user, today=date(2026, 3, 31))

    assert user["month_reset_date"] == "2026-03-31", (
        "the anchor stayed on the clamped day and lost three days of quota"
    )


def test_the_clamped_period_does_not_reset_early():
    """The other half of the same rule: with a 31st anchor, February's period
    runs to the 31st of March, not the 28th of March. Resetting on the 28th
    would hand out three free days rather than lose them."""
    user = _user("2026-02-28", anchor_day=31)

    with patch("models.user.get_db") as db:
        check_monthly_reset(user, today=date(2026, 3, 28))
        db.assert_not_called()

    assert user["emails_sent_this_month"] == 100


def test_a_30th_anchor_survives_february_too():
    user = _user("2026-02-28", anchor_day=30)

    with patch("models.user.get_db"):
        check_monthly_reset(user, today=date(2026, 3, 30))

    assert user["month_reset_date"] == "2026-03-30"


def test_a_long_absence_still_lands_on_the_real_anchor():
    """Catch-up and the anchor day have to agree. Three periods later, the
    new anchor is the most recent elapsed 31st — not the 28th, not today."""
    user = _user("2026-01-31", anchor_day=31)

    with patch("models.user.get_db"):
        check_monthly_reset(user, today=date(2026, 4, 15))

    assert user["month_reset_date"] == "2026-03-31"


@pytest.mark.parametrize("bad", [None, "", 0, 32, "thirty-one", -1])
def test_a_missing_or_nonsense_anchor_day_behaves_exactly_as_before(bad):
    """Every row written before migration 029 has NULL here, and NULL must be
    indistinguishable from the old code — a fallback that changed behaviour
    would be a migration that broke every existing customer."""
    user = _user("2026-06-25", anchor_day=bad)

    with patch("models.user.get_db"):
        check_monthly_reset(user, today=date(2026, 7, 25))

    assert user["month_reset_date"] == "2026-07-25"


def test_the_date_quoted_to_the_user_uses_the_real_anchor():
    """next_reset_date is what the quota-cap email tells someone their pending
    recipients will resume on. Promising the 28th and resuming on the 31st is
    worse than promising nothing."""
    user = _user("2026-02-28", anchor_day=31)

    assert next_reset_date(user) == date(2026, 3, 31)


# ── Two: the customer who is already leaving ──


def test_a_cancelling_subscription_does_not_roll_over_on_its_last_day():
    """The window is real: this runs from the beat at 00:00 UTC and Stripe
    ends the subscription at its creation time later the same day."""
    user = _user("2026-06-25", cancelling=True)

    with patch("models.user.get_db") as db:
        check_monthly_reset(user, today=date(2026, 7, 25))
        db.assert_not_called()

    assert user["emails_sent_this_month"] == 100
    assert user["month_reset_date"] == "2026-06-25"


def test_the_same_day_without_the_flag_rolls_over_as_always():
    """The common case — a renewal — must be untouched by this."""
    user = _user("2026-06-25")

    with patch("models.user.get_db"):
        check_monthly_reset(user, today=date(2026, 7, 25))

    assert user["emails_sent_this_month"] == 0


def test_the_hold_lasts_one_day_and_no_longer():
    """Bounded on purpose. If customer.subscription.deleted never arrives —
    a lost webhook, or they un-cancelled and we were not told — a permanent
    hold would be a paying customer stuck at zero quota with nothing on
    screen to explain it. Withholding for a few hours fixes the bonus month;
    withholding forever invents a worse bug."""
    user = _user("2026-06-25", cancelling=True)

    with patch("models.user.get_db"):
        check_monthly_reset(user, today=date(2026, 7, 26))

    assert user["emails_sent_this_month"] == 0, (
        "the hold outlived the day it was meant to cover"
    )


def test_a_cancelling_customer_mid_period_is_unaffected():
    """Nothing is due, so nothing is held — the flag only matters on the one
    day the two clocks disagree."""
    user = _user("2026-06-25", cancelling=True)

    with patch("models.user.get_db") as db:
        check_monthly_reset(user, today=date(2026, 7, 10))
        db.assert_not_called()

    assert user["emails_sent_this_month"] == 100


def test_both_fixes_apply_together():
    """A 31st anchor AND a cancellation: held on the real anchor day, which
    the old code would not even have recognised as the anchor."""
    user = _user("2026-02-28", anchor_day=31, cancelling=True)

    with patch("models.user.get_db") as db:
        check_monthly_reset(user, today=date(2026, 3, 31))
        db.assert_not_called()

    assert user["emails_sent_this_month"] == 100


# ── The other half: something has to set the flag, and clear it ──


class _RecordingUsers(FakeQueryBuilder):
    def __init__(self):
        super().__init__(data=[{"id": "u1", "email": "x@y.com", "plan": "starter"}])
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(dict(vals))
        return super().update(vals)


def _webhook(client, event):
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing._promo_shield", return_value=None), \
         patch("routers.billing._user_for_customer", return_value=None), \
         patch("routers.billing._telegram_alert"), \
         patch("routers.billing._capture_billing_event"):
        return client.post("/billing/webhook", content=b"{}",
                           headers={"stripe-signature": "sig"})


@pytest.mark.parametrize("flag", [True, False])
def test_subscription_updated_records_the_cancellation_flag(client, fake_db, flag):
    """Written on every subscription.updated, in BOTH directions. Stripe sends
    this event for the portal toggle that sets a cancellation and for the one
    that undoes it; recording only the first would leave a customer who
    changed their mind permanently held."""
    users = _RecordingUsers()
    fake_db.set_table("users", users)

    _webhook(client, {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "customer": "cus_1", "status": "active",
            "cancel_at_period_end": flag,
            "items": {"data": [{"price": {"id": "price_x"}}]},
        }},
    })

    written = [c for c in users.update_calls if "cancel_at_period_end" in c]
    assert written and written[0]["cancel_at_period_end"] is flag


def test_subscription_deleted_clears_the_flag(client, fake_db):
    """The cancellation it warned about has happened. A flag left set would
    hold this person's FREE quota rollover one day a month, every month, for
    a subscription that ended long ago."""
    users = _RecordingUsers()
    fake_db.set_table("users", users)

    _webhook(client, {
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_1"}},
    })

    written = [c for c in users.update_calls if "cancel_at_period_end" in c]
    assert written and written[0]["cancel_at_period_end"] is False
