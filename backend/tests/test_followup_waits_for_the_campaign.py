"""A follow-up must not close over a campaign that has not finished sending.

follow_ups.scheduled_for is stamped `now + delay_days` at CREATION
(models/followup.py), which quietly assumed a campaign goes out at once.
Scheduled sends and daily caps break that assumption, and the worker then
closed the follow-up over the gap: no contact was 'sent' yet, the filtered
set came back empty, and the empty set was read as "nobody left to bump" —
so the follow-up was marked 'sent', permanently, having emailed nobody.

The live example, 2026-08-28. A customer signed up, scheduled 66 recipients
for four days later, paced at 5 a day — a fortnight of sending — and turned
on a follow-up for non-openers. A plan gate refused the follow-up, which is
the only reason this was not the outcome; had it been created it would have
come due on day three, found zero sent recipients, and closed itself. She
would have been told nothing, and the toggle would still have read as on.

Two guards, and the ordering between them matters:

  * while the parent campaign still has resumable contacts, the follow-up is
    left ALONE — not rescheduled, not closed. The row stays due and the next
    hourly run looks again.
  * once the campaign has finished, the delay is measured from when the LAST
    recipient actually received it, not from when the follow-up row was
    written. For an ordinary instant send those two are the same moment, so
    nothing changes for the common case — which the last test here pins.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.conftest import FAKE_USER

CAMPAIGN_ID = "camp-drip"
FOLLOWUP_ID = "fu-1"


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _run(
    *,
    resumable,
    last_sent,
    targets=None,
    delay_days=3,
    archived=False,
):
    """Drive process_followups over one follow-up and report what happened."""
    from workers import followup_worker

    followup = {
        "id": FOLLOWUP_ID,
        "campaign_id": CAMPAIGN_ID,
        "user_id": FAKE_USER["id"],
        "delay_days": delay_days,
        "subject": "Did you see this?",
        "body": "Hello {{firstName}}",
        "condition": "not_opened",
        "status": "scheduled",
    }
    campaign = {
        "id": CAMPAIGN_ID,
        "user_id": FAKE_USER["id"],
        "archived": archived,
        "attachments": [],
    }

    status_calls = []
    sent_to = []

    with patch(
        "models.followup.get_pending_followups", return_value=[followup]
    ), patch(
        "models.campaign.get_campaign", return_value=campaign
    ), patch(
        "models.user.get_by_id", return_value=dict(FAKE_USER)
    ), patch(
        "models.contact.get_resumable_contacts", return_value=resumable
    ), patch(
        "models.contact.get_last_sent_at", return_value=last_sent
    ), patch(
        "models.followup.update_followup_status",
        side_effect=lambda fid, status: status_calls.append((fid, status)),
    ), patch(
        "models.campaign.increment_stat"
    ), patch(
        "models.user.increment_sent_count"
    ), patch.object(
        followup_worker, "_get_filtered_contacts", return_value=targets or []
    ), patch.object(
        followup_worker, "get_fresh_access_token", return_value="token-123"
    ), patch.object(
        followup_worker,
        "_send_followup_email",
        side_effect=lambda **kw: sent_to.append(kw["contact"]["email"]),
    ), patch(
        "time.sleep", return_value=None
    ):
        result = followup_worker.process_followups()

    return result, status_calls, sent_to


def _contact(n):
    return {"id": f"c{n}", "email": f"p{n}@example.com", "unsubscribed": False}


# ── the campaign is still going out ──


def test_a_campaign_still_sending_leaves_the_followup_alone(fake_db):
    """The Helene case. 66 recipients pending, none sent yet."""
    result, status_calls, sent_to = _run(
        resumable=[_contact(n) for n in range(66)],
        last_sent=None,
        targets=[],
    )

    assert status_calls == [], (
        "the follow-up was written to while its campaign had not started; "
        f"got {status_calls}"
    )
    assert sent_to == []
    assert result["waiting_on_campaign"] == 1


def test_a_partly_sent_drip_still_leaves_the_followup_alone(fake_db):
    """Five delivered, sixty-one to go. Bumping the five now would close the
    follow-up for the other sixty-one."""
    result, status_calls, sent_to = _run(
        resumable=[_contact(n) for n in range(61)],
        last_sent=_iso(4),
        targets=[_contact(100), _contact(101)],
    )

    assert status_calls == []
    assert sent_to == []
    assert result["waiting_on_campaign"] == 1


# ── finished, but the delay has not elapsed ──


def test_the_delay_is_measured_from_the_last_delivery(fake_db):
    """Campaign finished one day ago, delay is three days: not yet."""
    result, status_calls, sent_to = _run(
        resumable=[], last_sent=_iso(1), delay_days=3, targets=[_contact(1)]
    )

    assert status_calls == []
    assert sent_to == []
    assert result["waiting_on_delay"] == 1


def test_it_goes_out_once_the_delay_has_elapsed(fake_db):
    result, status_calls, sent_to = _run(
        resumable=[],
        last_sent=_iso(4),
        delay_days=3,
        targets=[_contact(1), _contact(2)],
    )

    assert sent_to == ["p1@example.com", "p2@example.com"]
    assert (FOLLOWUP_ID, "sent") in status_calls
    assert result["sent"] == 2


# ── the ordinary instant send is unchanged ──


def test_an_instant_campaign_behaves_exactly_as_before(fake_db):
    """The common case: everything delivered within seconds, so the last
    delivery IS the send. A follow-up whose delay has elapsed goes out on
    the first run that finds it due, as it always did."""
    result, status_calls, sent_to = _run(
        resumable=[],
        last_sent=_iso(3.5),
        delay_days=3,
        targets=[_contact(1)],
    )

    assert sent_to == ["p1@example.com"]
    assert (FOLLOWUP_ID, "sent") in status_calls


def test_a_finished_campaign_with_nobody_to_bump_still_closes(fake_db):
    """The legitimate close, which must survive: everyone opened, replied or
    unsubscribed. Reached only once both guards have ruled out 'not yet'."""
    result, status_calls, sent_to = _run(
        resumable=[], last_sent=_iso(9), delay_days=3, targets=[]
    )

    assert status_calls == [(FOLLOWUP_ID, "sent")]
    assert sent_to == []


# ── the user's stop switch ──


def test_archiving_the_campaign_cancels_the_followup(fake_db):
    """Archiving stops a campaign everywhere else; a pending bump for one the
    user has put away must not sit waiting to fire."""
    result, status_calls, sent_to = _run(
        resumable=[_contact(1)], last_sent=None, archived=True
    )

    assert status_calls == [(FOLLOWUP_ID, "cancelled")]
    assert sent_to == []
    assert result["waiting_on_campaign"] == 0


def test_archived_is_checked_before_the_campaign_is_waited_on(fake_db):
    """Order matters: an archived campaign that is also mid-send must be
    cancelled, not parked forever behind the wait."""
    result, status_calls, _ = _run(
        resumable=[_contact(n) for n in range(40)],
        last_sent=_iso(1),
        archived=True,
    )

    assert status_calls == [(FOLLOWUP_ID, "cancelled")]


# ── a timestamp we cannot read must not strand the follow-up ──


def test_an_unreadable_last_sent_falls_through_to_the_old_behaviour(fake_db):
    """Before this change every follow-up ran on scheduled_for alone. If the
    delivery timestamp cannot be parsed, that is what we fall back to —
    sending late is recoverable, never sending is not."""
    result, status_calls, sent_to = _run(
        resumable=[], last_sent="whenever", targets=[_contact(1)]
    )

    assert sent_to == ["p1@example.com"]
    assert (FOLLOWUP_ID, "sent") in status_calls
