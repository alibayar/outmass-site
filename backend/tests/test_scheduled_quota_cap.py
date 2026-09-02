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
         patch("models.campaign.get_status", return_value="sending"), \
         patch("models.campaign.update_campaign", side_effect=lambda cid, p: updates.append(p)), \
         patch("models.campaign.update_if_status",
               side_effect=lambda cid, p, expected=None: updates.append(p) or True), \
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


# ── which days a campaign may send on ──
#
# Hélène Carpentier, 2026-09-02: "with the scheduling it would be great to have
# the option to pick the days on which it sends - like for example I do not
# need to send emails on saturdays and sundays."


def test_the_weekday_roll_keeps_the_time_of_day():
    """Moving a weekend send to Monday must not also move it to midnight.

    A campaign set for 08:30 is an 08:30 campaign; the day is what changes.
    """
    from datetime import datetime, timezone

    from workers.scheduled_worker import next_allowed_day

    WEEKDAYS = [1, 2, 3, 4, 5]
    sat = datetime(2026, 9, 5, 8, 30, 15, tzinfo=timezone.utc)
    sun = datetime(2026, 9, 6, 8, 30, 15, tzinfo=timezone.utc)

    for weekend_day in (sat, sun):
        moved = next_allowed_day(weekend_day, WEEKDAYS)
        assert moved.isoweekday() == 1, f"{weekend_day} did not move to Monday"
        assert (moved.hour, moved.minute, moved.second) == (8, 30, 15), (
            f"the time of day changed: {moved}"
        )


def test_a_permitted_day_is_left_alone():
    from datetime import datetime, timezone

    from workers.scheduled_worker import next_allowed_day

    fri = datetime(2026, 9, 4, 8, 30, tzinfo=timezone.utc)
    assert next_allowed_day(fri, [1, 2, 3, 4, 5]) == fri


def test_no_restriction_means_every_day():
    """NULL is what every campaign carried before migration 035, and what a
    rollback restores. It must not move anything."""
    from datetime import datetime, timezone

    from workers.scheduled_worker import next_allowed_day

    sun = datetime(2026, 9, 6, 8, 30, tzinfo=timezone.utc)
    for empty in (None, [], ()):
        assert next_allowed_day(sun, empty) == sun, repr(empty)


def test_the_search_is_bounded():
    """An impossible set must return rather than loop. The column's CHECK
    constraint refuses an empty array; this is the belt behind it."""
    from datetime import datetime, timezone

    from workers.scheduled_worker import next_allowed_day

    sun = datetime(2026, 9, 6, 8, 30, tzinfo=timezone.utc)
    out = next_allowed_day(sun, [99])
    assert (out - sun).days <= 7


def test_a_campaign_due_on_an_excluded_day_is_moved_not_sent(fake_db):
    """The whole point: Saturday arrives, nothing goes out, and the campaign
    is still there on Monday with its own time intact."""
    from datetime import datetime, timezone
    from unittest.mock import patch

    from workers import scheduled_worker

    campaign = {
        "id": "camp-weekend", "user_id": FAKE_USER["id"], "subject": "Hi",
        "body": "Hello", "daily_send_cap": 5, "attachments": [],
        "send_days": [1, 2, 3, 4, 5],
        "scheduled_for": "2026-09-05T08:30:00+00:00",
    }
    writes, sent = [], []
    saturday = datetime(2026, 9, 5, 8, 31, tzinfo=timezone.utc)

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return saturday

    with patch("models.campaign.get_due_scheduled_campaigns", return_value=[campaign]), \
         patch("models.user.get_by_id", return_value={**FAKE_USER, "emails_sent_this_month": 0}), \
         patch("workers.scheduled_worker.datetime", _Clock), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.mark_sent", side_effect=sent.append), \
         patch("models.campaign.update_campaign"), \
         patch("models.campaign.update_if_status",
               side_effect=lambda cid, p, expected=None: writes.append(p) or True), \
         patch("workers.scheduled_worker._send_email", return_value={"success": True}):
        scheduled_worker.process_scheduled_campaigns()

    assert sent == [], "a campaign that does not send on Saturday sent on Saturday"
    assert writes, "the campaign was skipped without being rescheduled"
    moved = writes[-1]["scheduled_for"]
    assert moved.startswith("2026-09-07"), f"moved to {moved}, not Monday"
    assert "08:30" in moved, f"the time of day was lost: {moved}"
    assert "status" not in writes[-1], (
        "the campaign was claimed as 'sending' on a day it does not send"
    )


def test_a_friday_batch_reschedules_to_monday_not_saturday(fake_db):
    """The daily-cap reschedule has to know about send_days too.

    Without it, Friday's batch writes scheduled_for = Saturday. The skip-day
    guard at the top of the next beat would still rescue it on Monday, so
    nothing is sent on the wrong day either way — but the campaign spends the
    weekend claiming a date it cannot use, the owner sees the wrong next-send
    date, and the correction costs a beat cycle and a write. The reschedule is
    the place that knows the campaign has more to send; it should land on a day
    it can.
    """
    from datetime import datetime, timezone
    from unittest.mock import patch

    from workers import scheduled_worker

    campaign = {
        "id": "camp-fri", "user_id": FAKE_USER["id"], "subject": "Hi",
        "body": "Hello", "daily_send_cap": 2, "attachments": [],
        "send_days": [1, 2, 3, 4, 5],
        "scheduled_for": "2026-09-04T08:30:00+00:00",
    }
    writes = []
    friday = datetime(2026, 9, 4, 8, 30, tzinfo=timezone.utc)

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return friday

    with patch("models.campaign.get_due_scheduled_campaigns", return_value=[campaign]), \
         patch("models.user.get_by_id", return_value={**FAKE_USER, "emails_sent_this_month": 0}), \
         patch("workers.scheduled_worker.datetime", _Clock), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.get_resumable_contacts", side_effect=[_contacts(5), _contacts(3)]), \
         patch("models.contact.has_resumable_contacts", return_value=True), \
         patch("models.contact.mark_sent"), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.get_status", return_value="sending"), \
         patch("models.campaign.update_campaign"), \
         patch("models.campaign.update_if_status",
               side_effect=lambda cid, p, expected=None: writes.append(p) or True), \
         patch("models.user.increment_sent_count"), \
         patch("workers.scheduled_worker._send_email", return_value={"success": True}), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.process_scheduled_campaigns()

    rescheduled = [w for w in writes if w.get("status") == "scheduled"]
    assert rescheduled, f"the paced campaign was not requeued: {writes!r}"
    when = rescheduled[-1]["scheduled_for"]
    assert when.startswith("2026-09-07"), (
        f"Friday's batch requeued for {when} — Saturday is not a day this "
        f"campaign sends on"
    )
