"""Auto-resume of quota-capped partial campaigns.

A quota-capped send leaves the rest of the list 'pending' and the
campaign 'partial'. The auto_resume_partial_campaigns beat flips such
campaigns back to 'scheduled' once the owner has headroom again
(rolling reset or upgrade) — the regular send beat then finishes them.
Shipped 2026-07-20 after a Starter capped at exactly 2,500 with 250
recipients parked behind a manual Resume click.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from config import FREE_PLAN_MONTHLY_LIMIT
from tests.conftest import FAKE_USER


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _campaign(cid="c1", created_days_ago=1):
    return {
        "id": cid,
        "user_id": FAKE_USER["id"],
        "status": "partial",
        "created_at": _iso(created_days_ago),
    }


def _run(campaigns, user, resumable, reset_side_effect=None):
    from workers import scheduled_worker

    with patch(
        "models.campaign.get_resumable_partial_campaigns", return_value=campaigns
    ), patch(
        "models.user.get_by_id", return_value=user
    ), patch(
        "models.user.check_monthly_reset", side_effect=reset_side_effect
    ), patch(
        "models.contact.get_resumable_contacts", return_value=resumable
    ), patch(
        "models.campaign.update_campaign"
    ) as update:
        result = scheduled_worker.auto_resume_partial_campaigns()
    return result, update


def test_resumes_partial_campaign_when_headroom_exists():
    user = {**FAKE_USER, "emails_sent_this_month": 100}
    result, update = _run([_campaign()], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 1
    args = update.call_args
    assert args.args[0] == "c1"
    updates = args.args[1]
    assert updates["status"] == "scheduled"
    assert updates["scheduled_for"]  # now-ish ISO timestamp


def test_skips_when_no_headroom():
    user = {**FAKE_USER, "emails_sent_this_month": FREE_PLAN_MONTHLY_LIMIT}
    result, update = _run([_campaign()], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 0
    update.assert_not_called()


def test_skips_requires_reauth_owner():
    user = {**FAKE_USER, "emails_sent_this_month": 0, "requires_reauth": True}
    result, update = _run([_campaign()], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 0
    update.assert_not_called()


def test_skips_when_owner_row_missing():
    result, update = _run([_campaign()], user=None, resumable=[{"id": "k1"}])

    assert result["resumed"] == 0
    update.assert_not_called()


def test_closes_out_campaign_with_nothing_resumable():
    """Mirrors the manual Resume endpoint: no resumable contacts left →
    the partial campaign is finished, mark it 'sent'."""
    user = {**FAKE_USER, "emails_sent_this_month": 0}
    result, update = _run([_campaign()], user, resumable=[])

    assert result["closed_as_sent"] == 1
    assert result["resumed"] == 0
    update.assert_called_once_with("c1", {"status": "sent"})


def test_rolling_reset_runs_before_headroom_check():
    """A user sitting exactly at the limit whose anniversary has passed
    must be resumed: check_monthly_reset zeroes the counter first, even
    if they never log in on their reset day."""
    user = {**FAKE_USER, "emails_sent_this_month": FREE_PLAN_MONTHLY_LIMIT}

    def _reset(u):
        u["emails_sent_this_month"] = 0

    result, update = _run(
        [_campaign()], user, resumable=[{"id": "k1"}], reset_side_effect=_reset
    )

    assert result["resumed"] == 1
    assert update.call_args.args[1]["status"] == "scheduled"


# ── Age rule: rolling cycle, not a fixed day count ──
#
# The original guard was `created_at >= now - 14 days`. Because the quota
# period is a rolling month anchored on the user's own month_reset_date, the
# gap between hitting the cap and the next reset is 0-31 days. A user who
# burned their quota early in their cycle was already outside the 14-day
# window on reset day — and stayed outside it forever, while the in-app text
# promised the leftovers would send themselves. These tests pin the fix.


def _user_with_anchor(anchor_days_ago: int, sent: int = 0) -> dict:
    """User whose current cycle started `anchor_days_ago` days ago."""
    anchor = (datetime.now(timezone.utc) - timedelta(days=anchor_days_ago)).date()
    return {
        **FAKE_USER,
        "emails_sent_this_month": sent,
        "month_reset_date": anchor.isoformat(),
    }


def test_resumes_campaign_capped_early_in_the_previous_cycle():
    """THE REGRESSION. Cap on day 1 of a cycle, reset 30 days later: the
    campaign is 30 days old on reset day and a 14-day window missed it."""
    user = _user_with_anchor(anchor_days_ago=1)  # reset just happened
    result, update = _run(
        [_campaign(created_days_ago=29)], user, resumable=[{"id": "k1"}]
    )

    assert result["resumed"] == 1, "29-day-old capped campaign must still resume"
    assert update.call_args.args[1]["status"] == "scheduled"


def test_an_old_partial_still_resumes():
    """Retired 2026-08-28: the age rule this test used to guard.

    It asked whether the campaign was created inside the user's current or
    previous quota cycle, which capped auto-resume at ONE extra monthly batch
    while the panel promised the rest would go out automatically. A 10,000-row
    list on the free plan needs forty batches and was getting two.

    Ali's call: the user should not have to come back and press anything,
    however many months it takes. The surprise-send that age window guarded
    is now guarded by archiving, by an email on every capped batch, and by
    skipping accounts whose Microsoft connection is dead.
    """
    user = _user_with_anchor(anchor_days_ago=1)
    result, update = _run(
        [_campaign(created_days_ago=400)], user, resumable=[{"id": "k1"}]
    )

    assert result["resumed"] == 1
    update.assert_called()


def test_the_query_asks_for_unarchived_partials_at_any_age():
    """Archiving is the stop switch now, so the QUERY has to be the thing that
    respects it - the beat never sees an archived row to skip."""
    import inspect
    from models import campaign as campaign_model

    src = inspect.getsource(campaign_model.get_resumable_partial_campaigns)
    assert '.eq("archived", False)' in src, "archived rows would resume"
    assert "created_at" not in src, "an age filter is back in the query"


def test_resumes_campaign_capped_late_in_the_cycle():
    """The case that happened to work under the old rule — must keep working."""
    user = _user_with_anchor(anchor_days_ago=2)
    result, update = _run(
        [_campaign(created_days_ago=6)], user, resumable=[{"id": "k1"}]
    )

    assert result["resumed"] == 1


