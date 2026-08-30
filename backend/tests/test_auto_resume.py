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


# ── The owner's dormancy, not the campaign's age ──
#
# The age window came off on 2026-08-28 so a long campaign could finish
# itself. That left nothing measuring whether anyone was still there: a list
# abandoned in May would keep sending itself in September, because `archived`
# is a switch its owner has to know about and go press — and the person we
# worry about is exactly the one who stopped coming back.
#
# So the measure moved from the campaign to the owner. Rolling 30 days from
# last_activity_at, deliberately NOT the billing period: quota resets on the
# anniversary, so "seen since the last reset?" would be a near-zero window at
# the very moment resume becomes possible.
#
# Holding is not stopping. The campaign stays 'partial', so one sign-in
# refreshes last_activity_at and the next hourly run resumes it.


def _seen(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_holds_when_owner_has_been_away_too_long():
    user = {**FAKE_USER, "emails_sent_this_month": 0, "last_activity_at": _seen(45)}
    result, update = _run([_campaign()], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 0
    assert result["held_owner_dormant"] == 1
    # Held, not stopped: nothing was written, so the campaign is still
    # 'partial' and still a candidate the moment they come back.
    update.assert_not_called()


def test_resumes_for_an_owner_seen_recently():
    user = {**FAKE_USER, "emails_sent_this_month": 0, "last_activity_at": _seen(3)}
    result, update = _run([_campaign()], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 1
    assert result["held_owner_dormant"] == 0
    assert update.call_args.args[1]["status"] == "scheduled"


def test_a_months_old_campaign_still_resumes_for_an_active_owner():
    """The 08-28 promise, unchanged: age is not the measure. A campaign from
    May finishes itself as long as its owner is still around."""
    user = {**FAKE_USER, "emails_sent_this_month": 0, "last_activity_at": _seen(1)}
    result, _ = _run(
        [_campaign(created_days_ago=117)], user, resumable=[{"id": "k1"}]
    )

    assert result["resumed"] == 1


def test_missing_last_activity_holds():
    """NULL is not 'assume they are here'. last_activity_at is stamped on
    login and on authenticated activity, so anyone who owns a campaign has
    one; a missing value is a row we cannot vouch for, and the safe direction
    for a decision that puts mail in someone else's outbox is 'not yet'."""
    user = {**FAKE_USER, "emails_sent_this_month": 0}
    user.pop("last_activity_at", None)
    result, update = _run([_campaign()], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 0
    assert result["held_owner_dormant"] == 1
    update.assert_not_called()


def test_unparseable_last_activity_holds():
    user = {**FAKE_USER, "emails_sent_this_month": 0, "last_activity_at": "yesterday"}
    result, _ = _run([_campaign()], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 0
    assert result["held_owner_dormant"] == 1


def test_naive_last_activity_is_read_as_utc():
    """Postgres can hand back a timestamp without an offset. Treating that as
    naive-local would raise on the subtraction and take the unparseable path,
    holding a user who is in fact here."""
    naive = (datetime.now(timezone.utc) - timedelta(days=2)).replace(tzinfo=None)
    user = {
        **FAKE_USER,
        "emails_sent_this_month": 0,
        "last_activity_at": naive.isoformat(),
    }
    result, _ = _run([_campaign()], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 1


def test_the_quota_period_still_rolls_for_a_dormant_owner():
    """The dormancy check sits AFTER check_monthly_reset on purpose.

    Rolling the quota period is the one thing this beat does for a user who
    never logs in on their anniversary day — that is why the reset is called
    here at all. Skipping dormant owners any earlier would take the property
    away from exactly the people it was written for. This test exists because
    the first draft of the dormancy gate deleted the call outright.
    """
    from unittest.mock import patch

    from workers import scheduled_worker

    user = {**FAKE_USER, "emails_sent_this_month": 10, "last_activity_at": _seen(60)}

    with patch(
        "models.campaign.get_resumable_partial_campaigns", return_value=[_campaign()]
    ), patch("models.user.get_by_id", return_value=user), patch(
        "models.user.check_monthly_reset"
    ) as reset, patch(
        "models.contact.get_resumable_contacts", return_value=[{"id": "k1"}]
    ), patch("models.campaign.update_campaign"):
        result = scheduled_worker.auto_resume_partial_campaigns()

    reset.assert_called_once()
    assert result["held_owner_dormant"] == 1


def test_dormancy_is_checked_after_the_reauth_guard():
    """A dormant owner who ALSO needs to reconnect is counted once, as a
    reauth skip. Otherwise the two counters double-count the same row and
    'held_owner_dormant' stops meaning what its name says."""
    user = {
        **FAKE_USER,
        "emails_sent_this_month": 0,
        "requires_reauth": True,
        "last_activity_at": _seen(90),
    }
    result, _ = _run([_campaign()], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 0
    assert result["held_owner_dormant"] == 0


# ── Spacing the attempts out ──
#
# The beat went from daily to two-hourly on 2026-08-30 so a campaign whose
# quota came back at 07:00 would not wait twenty-three hours while the panel
# promised it would continue by itself.
#
# That turns one attempt a day into twelve at a campaign that cannot succeed.
# The failure that prompted it was Graph refusing to send from a mailbox at
# all — most likely Microsoft already restricting a new account — so twelve
# attempts a day would be us worsening a user's standing with their own
# provider, on their behalf, silently.
#
# campaigns.updated_at (migration 025) already records the last attempt:
# every path that parks a campaign writes it. No new column.


def _campaign_attempted(hours_ago, cid="c1"):
    c = _campaign(cid)
    c["updated_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ).isoformat()
    return c


def test_a_campaign_attempted_an_hour_ago_is_left_alone():
    user = {**FAKE_USER, "emails_sent_this_month": 0}
    result, update = _run([_campaign_attempted(1)], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 0
    assert result["held_backoff"] == 1
    update.assert_not_called()


def test_a_campaign_attempted_long_enough_ago_resumes():
    user = {**FAKE_USER, "emails_sent_this_month": 0}
    result, update = _run([_campaign_attempted(10)], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 1
    assert result["held_backoff"] == 0
    assert update.call_args.args[1]["status"] == "scheduled"


def test_a_missing_updated_at_does_not_hold():
    """The opposite reading of a missing field from _owner_is_dormant, on
    purpose. There, absence meant 'we cannot vouch that anyone is here' and
    holding was safe. Here it means 'no evidence of a recent attempt', and
    holding on that would strand a campaign forever on a row we cannot read.
    """
    user = {**FAKE_USER, "emails_sent_this_month": 0}
    campaign = _campaign()
    campaign.pop("updated_at", None)
    result, _ = _run([campaign], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 1
    assert result["held_backoff"] == 0


def test_an_unreadable_updated_at_does_not_hold():
    user = {**FAKE_USER, "emails_sent_this_month": 0}
    campaign = _campaign()
    campaign["updated_at"] = "sometime last week"
    result, _ = _run([campaign], user, resumable=[{"id": "k1"}])

    assert result["resumed"] == 1


def test_a_naive_updated_at_is_read_as_utc():
    """Postgres can hand back a timestamp with no offset. Treating it as
    naive-local would raise on the subtraction, take the unreadable path, and
    retry a campaign the backoff was meant to space out."""
    naive = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
    campaign = _campaign()
    campaign["updated_at"] = naive.isoformat()
    user = {**FAKE_USER, "emails_sent_this_month": 0}
    result, _ = _run([campaign], user, resumable=[{"id": "k1"}])

    assert result["held_backoff"] == 1


def test_the_backoff_is_checked_before_the_user_is_loaded():
    """Cheapest guard first: a backed-off campaign must cost no DB read.

    With a two-hourly beat this is the common path, not the rare one — most
    passes will find nothing due and should do almost nothing.
    """
    from unittest.mock import patch

    from workers import scheduled_worker

    with patch(
        "models.campaign.get_resumable_partial_campaigns",
        return_value=[_campaign_attempted(1)],
    ), patch("models.user.get_by_id") as get_by_id, patch(
        "models.user.check_monthly_reset"
    ), patch(
        "models.contact.get_resumable_contacts", return_value=[{"id": "k1"}]
    ), patch("models.campaign.update_campaign"):
        result = scheduled_worker.auto_resume_partial_campaigns()

    get_by_id.assert_not_called()
    assert result["held_backoff"] == 1


def test_backoff_and_dormancy_are_counted_separately():
    """A dormant owner whose campaign was also just attempted is counted once,
    under the backoff — otherwise the two numbers double-count one row and
    neither means what its name says."""
    user = {**FAKE_USER, "emails_sent_this_month": 0, "last_activity_at": _seen(90)}
    result, _ = _run([_campaign_attempted(1)], user, resumable=[{"id": "k1"}])

    assert result["held_backoff"] == 1
    assert result["held_owner_dormant"] == 0
