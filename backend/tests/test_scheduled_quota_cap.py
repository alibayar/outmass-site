"""A quota-capped SCHEDULED campaign must land 'partial', not 'sent'.

The send-now path had this bug and it stranded a Starter's 250 recipients
invisibly (fixed 2026-07-20, c1705f2). The scheduled path kept it, and there
it is worse: the truncation happens server-side, so the user never sees the
"N recipients were not included" alert — the campaign simply reports as
complete while contacts sit 'pending' forever, unreachable by the Resume
endpoint (it 409s on non-partial) AND by the auto-resume beat (it queries
status='partial').

Shipping 0.1.27 made this release-blocking: the in-app text now promises the
leftovers send themselves after the monthly reset.
"""

from unittest.mock import patch

from config import FREE_PLAN_MONTHLY_LIMIT
from tests.conftest import FAKE_USER


def _contacts(n):
    return [
        {"id": f"ct-{i}", "email": f"r{i}@example.com", "unsubscribed": False}
        for i in range(n)
    ]


def _campaign(cap=None):
    return {
        "id": "camp-q",
        "user_id": FAKE_USER["id"],
        "subject": "Hi",
        "body": "Hello",
        "daily_send_cap": cap,
        "attachments": [],
    }


def _run(pending_count, already_sent, cap=None, resumable_after=None,
         still_resumable=False):
    """Run one beat pass. `already_sent` sets how much quota is used up."""
    from workers import scheduled_worker

    user = {**FAKE_USER, "emails_sent_this_month": already_sent}
    updates = []
    sent_ids = []
    side_effect = [_contacts(pending_count)]
    if resumable_after is not None:
        side_effect.append(resumable_after)

    with patch("models.campaign.get_due_scheduled_campaigns", return_value=[_campaign(cap)]), \
         patch("models.user.get_by_id", return_value=user), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.get_resumable_contacts", side_effect=side_effect), \
         patch("models.contact.has_resumable_contacts", return_value=still_resumable), \
         patch("models.contact.mark_sent", side_effect=lambda cid: sent_ids.append(cid)), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.update_campaign", side_effect=lambda cid, p: updates.append(p)), \
         patch("models.user.increment_sent_count"), \
         patch("workers.scheduled_worker._send_email", return_value={"success": True}), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.process_scheduled_campaigns()

    return sent_ids, updates


def test_quota_capped_clean_send_lands_partial(fake_db):
    """More recipients than remaining quota, zero send errors → 'partial',
    so the auto-resume beat can find it."""
    remaining = 10
    sent_ids, updates = _run(
        pending_count=25, already_sent=FREE_PLAN_MONTHLY_LIMIT - remaining
    )

    assert len(sent_ids) == remaining, "must send exactly the remaining quota"
    assert updates[-1]["status"] == "partial", (
        "a quota-capped batch that closes as 'sent' strands the leftover "
        "contacts — invisible to both resume paths"
    )


def test_send_within_quota_still_lands_sent(fake_db):
    """No truncation, no errors → 'sent'. The fix must not make every
    campaign look partial."""
    sent_ids, updates = _run(
        pending_count=5, already_sent=FREE_PLAN_MONTHLY_LIMIT - 100
    )

    assert len(sent_ids) == 5
    assert updates[-1]["status"] == "sent"


def test_daily_cap_campaign_within_quota_still_requeues(fake_db):
    """Daily-cap path is unaffected: it reschedules for tomorrow rather than
    closing, and the quota flag must not hijack that."""
    sent_ids, updates = _run(
        pending_count=5,
        already_sent=FREE_PLAN_MONTHLY_LIMIT - 100,
        cap=2,
        resumable_after=_contacts(3),
        still_resumable=True,
    )

    assert len(sent_ids) == 2
    assert updates[-1]["status"] == "scheduled"
    assert updates[-1]["scheduled_for"]
