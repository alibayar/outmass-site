"""Signups and payments must reach the operator's phone as they happen.

Requested 2026-08-19 ("aklım hep burada kalıyor"): a new user and a paid
renewal used to surface only in the next morning's report. These pings ride
existing guards — the checkout ping shares the activation replay guard, and
the renewal ping deliberately fires even when the backstop already rolled
the month, because the invoice is still real money.
"""
from unittest.mock import MagicMock, patch

from routers import auth as auth_router
from routers import billing


# ── New-user ping ──


def test_new_user_ping_carries_email_and_count():
    count_result = MagicMock()
    count_result.count = 56
    db = MagicMock()
    db.table.return_value.select.return_value.limit.return_value.execute.return_value = (
        count_result
    )

    with patch("routers.billing._telegram_alert") as alert, \
         patch("database.get_db", return_value=db):
        auth_router._notify_new_user("charlotte@aeezo.com")

    alert.assert_called_once()
    msg = alert.call_args.args[0]
    assert "New user" in msg
    assert "charlotte@aeezo.com" in msg
    assert "user #56" in msg


def test_new_user_ping_survives_a_broken_count():
    """The count is garnish. A DB hiccup must not eat the ping itself."""
    with patch("routers.billing._telegram_alert") as alert, \
         patch("database.get_db", side_effect=Exception("down")):
        auth_router._notify_new_user("a@b.com")

    alert.assert_called_once()
    msg = alert.call_args.args[0]
    assert "a@b.com" in msg
    assert "user #" not in msg


# ── Renewal ping ──


def _renewal_db(row):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[row]
    )
    return db


def test_renewal_pings_even_when_backstop_already_rolled():
    """rolled=False is still a paid invoice — the ping must not be gated
    on the quota actually moving."""
    row = {
        "id": "u1",
        "email": "lucia@skylineprp.com",
        "month_reset_date": "2026-08-16",
        "stripe_subscription_id": "sub_1",
    }
    with patch.object(billing, "_telegram_alert") as alert, \
         patch.object(billing.user_model, "check_monthly_reset"):
        billing._roll_quota_on_renewal(_renewal_db(row), "cus_1", invoice_sub_id="sub_1")

    alert.assert_called_once()
    msg = alert.call_args.args[0]
    assert "Renewal paid" in msg
    assert "lucia@skylineprp.com" in msg
    assert "already current" in msg


def test_renewal_ping_says_rolled_when_the_quota_moved():
    row = {
        "id": "u1",
        "email": "tony@skylineprp.com",
        "month_reset_date": "2026-07-20",
        "stripe_subscription_id": "sub_2",
    }

    def _roll(user, paid_cycle_confirmed=False):
        user["month_reset_date"] = "2026-08-20"

    with patch.object(billing, "_telegram_alert") as alert, \
         patch.object(billing.user_model, "check_monthly_reset", side_effect=_roll):
        billing._roll_quota_on_renewal(_renewal_db(row), "cus_2", invoice_sub_id="sub_2")

    alert.assert_called_once()
    msg = alert.call_args.args[0]
    assert "Renewal paid" in msg
    assert "already current" not in msg


def test_orphan_invoice_does_not_ping():
    """The subscription-identity guard must silence the ping too — an
    orphan subscription's invoice is not this account's renewal."""
    row = {
        "id": "u1",
        "email": "x@y.com",
        "month_reset_date": "2026-08-01",
        "stripe_subscription_id": "sub_real",
    }
    with patch.object(billing, "_telegram_alert") as alert, \
         patch.object(billing.user_model, "check_monthly_reset"):
        billing._roll_quota_on_renewal(
            _renewal_db(row), "cus_3", invoice_sub_id="sub_orphan"
        )

    alert.assert_not_called()
