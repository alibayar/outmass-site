"""Auto-resume of quota-capped partial campaigns.

A quota-capped send leaves the rest of the list 'pending' and the
campaign 'partial'. The auto_resume_partial_campaigns beat flips such
campaigns back to 'scheduled' once the owner has headroom again
(rolling reset or upgrade) — the regular send beat then finishes them.
Shipped 2026-07-20 after a Starter capped at exactly 2,500 with 250
recipients parked behind a manual Resume click.
"""
from unittest.mock import patch

from config import FREE_PLAN_MONTHLY_LIMIT
from tests.conftest import FAKE_USER


def _campaign(cid="c1"):
    return {"id": cid, "user_id": FAKE_USER["id"], "status": "partial"}


def _run(campaigns, user, resumable, reset_side_effect=None):
    from workers import scheduled_worker

    with patch(
        "models.campaign.get_recent_partial_campaigns", return_value=campaigns
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
