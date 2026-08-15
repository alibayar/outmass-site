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
import ast
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from fastapi.testclient import TestClient

from models.user import check_monthly_reset, next_reset_date, upsert_user
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


# ── Three: the anchor column had readers but no writers ──
#
# Migration 029 backfilled month_reset_anchor_day once, and for a day nothing
# in application code ever wrote it again: rows created after the backfill
# carried NULL forever, and the checkout re-anchor moved the DATE while
# leaving the DAY behind — so a customer who paid on a different day than
# they signed up computed every later period from the wrong anchor (signup
# on the 5th, pay Aug 31 → next due Sep 5, a five-day quota "month"). Found
# 2026-08-15 by the skeptic pass of the backlog audit, one day after the
# read path shipped and was called done.


def test_a_rollover_persists_the_anchor_day_it_used():
    """A legacy NULL-anchor row heals on its first rollover: the fallback
    the period was just computed from is written down, not used and
    discarded."""
    user = _user("2026-07-25")  # no anchor_day stored → fallback is the 25th

    with patch("models.user.get_db") as gdb:
        check_monthly_reset(user, today=date(2026, 8, 25))

    payload = gdb.return_value.table.return_value.update.call_args[0][0]
    assert payload["month_reset_anchor_day"] == 25
    assert user["month_reset_anchor_day"] == 25, (
        "the in-memory row must see what the DB row now says"
    )


def test_a_rollover_does_not_disturb_a_stored_anchor():
    """The unconditional write is a no-op for a healthy row: the 31 goes
    back in, never the clamped 28 the stored date happens to sit on."""
    user = _user("2026-02-28", anchor_day=31)

    with patch("models.user.get_db") as gdb:
        check_monthly_reset(user, today=date(2026, 3, 31))

    payload = gdb.return_value.table.return_value.update.call_args[0][0]
    assert payload["month_reset_anchor_day"] == 31


def test_a_new_user_is_born_with_both_halves_of_the_anchor():
    """Creation used to leave the date to the schema's DEFAULT CURRENT_DATE
    and the day to nobody. Both are explicit now, from the same clock."""
    with patch("models.user.find_by_microsoft_id", return_value=None), \
         patch("models.user.get_db") as gdb:
        insert = gdb.return_value.table.return_value.insert
        insert.return_value.execute.return_value.data = [{"id": "u9"}]
        upsert_user("ms-new", "new@user.com", "New User")

    row = insert.call_args[0][0]
    today = datetime.now(timezone.utc).date()
    assert row["month_reset_date"] == today.isoformat()
    assert row["month_reset_anchor_day"] == today.day


# ── The invariant, enforced at the source ──
#
# The defect was not a wrong line, it was a MISSING line — nothing a test of
# existing behaviour can see. So the rule is structural: no dict in
# application code may carry month_reset_date without month_reset_anchor_day.
# check_monthly_reset writes the (possibly identical) anchor back on purpose
# so this rule can be absolute instead of carrying exemptions.


_APP_DIRS = ("models", "routers", "workers", "utils")


def _dict_writes_missing_anchor(source: str) -> list[int]:
    """Line numbers of dict literals that carry month_reset_date without
    month_reset_anchor_day."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            keys = {
                k.value
                for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            if "month_reset_date" in keys and "month_reset_anchor_day" not in keys:
                bad.append(node.lineno)
    return bad


def test_the_scanner_flags_a_planted_lone_write():
    """A scanner that cannot fail is not a scanner — before trusting the
    sweep below, prove the matcher fires on a known-bad snippet."""
    assert _dict_writes_missing_anchor('x = {"month_reset_date": d}') == [1]


def test_the_scanner_accepts_a_paired_write():
    src = 'x = {"month_reset_date": d, "month_reset_anchor_day": n}'
    assert _dict_writes_missing_anchor(src) == []


def test_no_app_code_writes_the_date_without_its_anchor():
    backend = Path(__file__).resolve().parent.parent
    offenders = []
    files = [p for d in _APP_DIRS for p in (backend / d).rglob("*.py")]
    files += backend.glob("*.py")
    for path in files:
        for line in _dict_writes_missing_anchor(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(backend)}:{line}")
    assert offenders == [], (
        f"month_reset_date written without its anchor day at: {offenders}"
    )
