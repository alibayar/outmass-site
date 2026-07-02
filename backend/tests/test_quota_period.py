"""Tests for the billing-anchored rolling quota period + lifetime counter.

The quota month used to reset on CALENDAR month change (first login after the
1st), while Stripe bills monthly from the subscription date — so a Starter who
paid on the 25th got a bonus reset every 1st (double quota in one billed
month), and the reset only ran at login (a user with scheduled sends who never
logged back in stayed blocked on last period's counter). These tests lock in:

- check_monthly_reset: rolling month from month_reset_date, anchor day
  preserved (with end-of-month clamping), catch-up after long absence,
  emails_sent_total never touched.
- increment_sent_count fallback: bumps BOTH counters.
- checkout webhook: re-anchors the quota period at payment.
"""
from datetime import date
from unittest.mock import MagicMock, patch

from models.user import _add_months, check_monthly_reset


# ── _add_months ──


def test_add_months_normal():
    assert _add_months(date(2026, 6, 25), 1) == date(2026, 7, 25)


def test_add_months_year_wrap():
    assert _add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


def test_add_months_clamps_to_short_month():
    assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_add_months_leap_february():
    assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


def test_add_months_no_drift_from_original_anchor():
    # Jan 31 + 2 months computed from the ORIGINAL date stays the 31st.
    assert _add_months(date(2026, 1, 31), 2) == date(2026, 3, 31)


# ── check_monthly_reset (rolling) ──


def _user(anchor: str, sent=100, total=500):
    return {
        "id": "u1",
        "month_reset_date": anchor,
        "emails_sent_this_month": sent,
        "ai_generations_this_month": 3,
        "emails_sent_total": total,
    }


def test_no_reset_before_anniversary_even_across_calendar_month():
    """THE Faisal regression: paid the 25th, logs in July 2nd → the old
    calendar rule reset the counter; the rolling rule must NOT."""
    user = _user("2026-06-25")
    with patch("models.user.get_db") as db:
        check_monthly_reset(user, today=date(2026, 7, 2))
        db.assert_not_called()
    assert user["emails_sent_this_month"] == 100  # untouched


def test_reset_fires_on_anniversary():
    user = _user("2026-06-25")
    with patch("models.user.get_db") as db:
        check_monthly_reset(user, today=date(2026, 7, 25))
        db.assert_called()
    assert user["emails_sent_this_month"] == 0
    assert user["month_reset_date"] == "2026-07-25"


def test_catchup_preserves_anchor_day_after_long_absence():
    """Anchor the 25th, first activity 2.5 periods later → new anchor is the
    most recent elapsed 25th, not 'today'."""
    user = _user("2026-06-25")
    with patch("models.user.get_db"):
        check_monthly_reset(user, today=date(2026, 9, 10))
    assert user["month_reset_date"] == "2026-08-25"
    assert user["emails_sent_this_month"] == 0


def test_reset_never_touches_lifetime_total():
    user = _user("2026-06-25", total=1792)
    with patch("models.user.get_db") as db:
        check_monthly_reset(user, today=date(2026, 7, 25))
        # the DB update payload must not contain the lifetime counter
        payload = db.return_value.table.return_value.update.call_args[0][0]
        assert "emails_sent_total" not in payload
    assert user["emails_sent_total"] == 1792


def test_no_anchor_is_a_noop():
    user = {"id": "u1", "emails_sent_this_month": 7}
    with patch("models.user.get_db") as db:
        check_monthly_reset(user, today=date(2026, 7, 25))
        db.assert_not_called()
    assert user["emails_sent_this_month"] == 7


# ── increment_sent_count fallback bumps BOTH counters ──


def test_increment_fallback_bumps_both_counters():
    from models.user import increment_sent_count

    row = {"id": "u1", "emails_sent_this_month": 10, "emails_sent_total": 200}
    with patch("models.user.get_db") as db:
        db.return_value.rpc.side_effect = Exception("no rpc")
        (
            db.return_value.table.return_value.select.return_value
            .eq.return_value.execute.return_value
        ) = MagicMock(data=[row])
        increment_sent_count("u1", 5)
        payload = db.return_value.table.return_value.update.call_args[0][0]
    assert payload["emails_sent_this_month"] == 15
    assert payload["emails_sent_total"] == 205


# ── checkout webhook re-anchors the quota period ──


def _post_checkout_event(client, users_tbl, subscription=None):
    """POST a checkout.session.completed event; return the captured update payload."""
    captured = {}
    orig_update = users_tbl.update

    def capture_update(payload):
        captured.update(payload)
        return orig_update(payload)

    users_tbl.update = capture_update

    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {"user_id": "u-42"},
                "customer": "cus_x",
                "subscription": subscription,
            }
        },
    }
    fake_sub = {"items": {"data": [{"price": {"id": "price_whatever"}}]}}
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.stripe.Subscription.retrieve", return_value=fake_sub), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"):
        resp = client.post(
            "/billing/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
    return resp, captured


def test_checkout_completed_resets_counters_and_anchors_today(client, fake_db):
    """First processing: ALL period counters zeroed, anchor = payment day."""
    from datetime import datetime, timezone

    from tests.conftest import FakeQueryBuilder

    users_tbl = FakeQueryBuilder(data=[])  # no stored subscription → first time
    fake_db.set_table("users", users_tbl)

    resp, captured = _post_checkout_event(client, users_tbl, subscription=None)

    assert resp.status_code == 200
    assert captured["emails_sent_this_month"] == 0
    assert captured["ai_generations_this_month"] == 0  # AI period resets too
    assert captured["month_reset_date"] == datetime.now(timezone.utc).date().isoformat()
    assert captured["plan"] == "pro"


def test_checkout_replay_does_not_refill_quota(client, fake_db):
    """Stripe redelivers webhooks at-least-once: a replay (same subscription id
    already stored) must NOT re-zero the counter or shift the anchor — that
    would hand out bonus quota days after the payment."""
    from tests.conftest import FakeQueryBuilder

    users_tbl = FakeQueryBuilder(
        data=[{"id": "u-42", "stripe_subscription_id": "sub_dup"}]
    )
    fake_db.set_table("users", users_tbl)

    resp, captured = _post_checkout_event(client, users_tbl, subscription="sub_dup")

    assert resp.status_code == 200
    assert captured["plan"] == "pro"  # plan write is idempotent, still happens
    assert "emails_sent_this_month" not in captured  # no quota refill
    assert "month_reset_date" not in captured  # no anchor shift
