"""A follow-up trails the send; it does not arrive all at once at the end.

"Follow up 3 days later" means three days after the RECIPIENT got it. For a
campaign that goes out at once, that is also three days after the campaign.
For one paced by daily_send_cap it is not, and the difference is the whole
feature: 66 recipients at 5 a day take a fortnight, and bumping everyone
together at the end is 16 days late for the people who received the original
on day one and exactly right for the last five.

Two earlier shapes were wrong, and this file has now pinned all three:

  1. Originally the follow-up came due `delay_days` after it was CREATED,
     found nobody sent yet on a scheduled campaign, and read the empty set as
     "nobody left to bump" — closing itself permanently, having emailed no
     one. A live case on 2026-08-28: 66 recipients scheduled four days out at
     5 a day; a plan gate refused the follow-up, which is the only reason
     that was not the outcome.

  2. Then it waited for the campaign to finish and counted the delay from the
     last delivery. Safe, and still wrong for everyone but the final batch.

  3. Now each recipient is due on their own clock, which requires remembering
     who has already been bumped (migration 033, follow_up_sends). Forgetting
     that means emailing someone twice from their own mailbox, so the closing
     condition and the dedup are what most of these tests are about.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.conftest import FAKE_USER, FakeQueryBuilder

CAMPAIGN_ID = "camp-drip"
FOLLOWUP_ID = "fu-1"


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _contact(n, sent_days_ago=None):
    c = {"id": f"c{n}", "email": f"p{n}@example.com", "unsubscribed": False}
    if sent_days_ago is not None:
        c["sent_at"] = _ago(sent_days_ago)
    return c


def _run(
    *,
    due,
    resumable=(),
    all_targets=None,
    already=(),
    delay_days=3,
    archived=False,
):
    """Drive process_followups once.

    `due` is what the filtered query returns for the delay that has elapsed;
    `all_targets` is what it returns with no delay applied (i.e. everyone the
    condition matches, due or not) and defaults to `due`.
    """
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
    targets = list(due) if all_targets is None else list(all_targets)

    status_calls, sent_to, bumps = [], [], []

    def _filtered(db, campaign_id, condition, delay_days=None):
        # The worker calls this twice per pass: once with the delay to find
        # who is due, once without to ask whether anyone is still coming.
        return list(due) if delay_days is not None else targets

    with patch(
        "models.followup.get_pending_followups", return_value=[followup]
    ), patch(
        "models.campaign.get_campaign", return_value=campaign
    ), patch(
        "models.user.get_by_id", return_value=dict(FAKE_USER)
    ), patch(
        "models.contact.get_resumable_contacts", return_value=list(resumable)
    ), patch(
        "models.followup.get_bumped_contact_ids", return_value=set(already)
    ), patch(
        "models.followup.record_bump",
        side_effect=lambda fid, cid: bumps.append(cid),
    ), patch(
        "models.followup.update_followup_status",
        side_effect=lambda fid, status: status_calls.append((fid, status)),
    ), patch(
        "models.campaign.increment_stat"
    ), patch(
        "models.user.increment_sent_count"
    ), patch.object(
        followup_worker, "_get_filtered_contacts", side_effect=_filtered
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

    return result, status_calls, sent_to, bumps


# ── the trail ──


def test_a_paced_campaign_is_bumped_as_it_goes(fake_db):
    """Day four of a fortnight: the first batch is due, the rest are not."""
    _, status_calls, sent_to, bumps = _run(
        due=[_contact(1), _contact(2)],
        all_targets=[_contact(1), _contact(2), _contact(3)],
        resumable=[_contact(50)],
    )

    assert sent_to == ["p1@example.com", "p2@example.com"]
    assert bumps == ["c1", "c2"], "every delivered bump must be written down"
    assert status_calls == [], (
        "the follow-up closed after today's batch; the rest of the campaign "
        "would never be followed up"
    )


def test_nobody_is_bumped_twice(fake_db):
    """The run after. c1 and c2 already have rows in follow_up_sends, so the
    query that finds them due must not send to them again."""
    _, _, sent_to, bumps = _run(
        due=[_contact(1), _contact(2), _contact(3)],
        already={"c1", "c2"},
        resumable=[_contact(50)],
    )

    assert sent_to == ["p3@example.com"]
    assert bumps == ["c3"]


def test_nothing_due_yet_leaves_the_followup_open(fake_db):
    """Everyone who has received the original is still inside their delay."""
    result, status_calls, sent_to, _ = _run(
        due=[], all_targets=[_contact(1)], resumable=[_contact(50)]
    )

    assert sent_to == []
    assert status_calls == []
    assert result["waiting_on_campaign"] == 1


def test_the_campaign_still_sending_is_enough_to_stay_open(fake_db):
    """Nobody due AND nobody matching yet — but the campaign has 60 people
    left to reach, so their turn is still coming."""
    _, status_calls, _, _ = _run(
        due=[], all_targets=[], resumable=[_contact(n) for n in range(60)]
    )

    assert status_calls == []


# ── closing, which is permanent ──


def test_it_closes_when_the_campaign_is_done_and_everyone_is_covered(fake_db):
    _, status_calls, sent_to, _ = _run(
        due=[_contact(9)], all_targets=[_contact(9)], resumable=[]
    )

    assert sent_to == ["p9@example.com"]
    assert (FOLLOWUP_ID, "sent") in status_calls


def test_it_closes_when_there_was_never_anyone_to_bump(fake_db):
    """The legitimate empty case: campaign finished, everyone opened,
    replied or unsubscribed."""
    _, status_calls, sent_to, _ = _run(due=[], all_targets=[], resumable=[])

    assert status_calls == [(FOLLOWUP_ID, "sent")]
    assert sent_to == []


def test_it_stays_open_when_someone_is_still_inside_their_delay(fake_db):
    """Today's batch went out, the campaign has finished, but three people
    received the original yesterday and are not due until Thursday."""
    _, status_calls, sent_to, _ = _run(
        due=[_contact(1)],
        all_targets=[_contact(1), _contact(2), _contact(3)],
        resumable=[],
    )

    assert sent_to == ["p1@example.com"]
    assert status_calls == [], (
        "closed with two recipients still waiting out their delay"
    )


# ── the user's stop switch ──


def test_archiving_the_campaign_cancels_the_followup(fake_db):
    _, status_calls, sent_to, _ = _run(
        due=[_contact(1)], resumable=[_contact(2)], archived=True
    )

    assert status_calls == [(FOLLOWUP_ID, "cancelled")]
    assert sent_to == []


# ── the filter itself ──


class _RecordingContacts(FakeQueryBuilder):
    def __init__(self):
        super().__init__(data=[])
        self.lte_calls = []

    def lte(self, column, value):
        self.lte_calls.append((column, value))
        return self


def test_the_delay_is_applied_to_each_contacts_own_sent_at(fake_db):
    """The query must bound sent_at, not the campaign. Without this the
    'due' set is everyone the condition matches, and a paced campaign bumps
    its day-one recipients the moment the follow-up first runs."""
    from workers.followup_worker import _get_filtered_contacts

    rec = _RecordingContacts()
    fake_db.set_table("contacts", rec)
    _get_filtered_contacts(fake_db, CAMPAIGN_ID, "not_opened", 3)

    assert any(col == "sent_at" for col, _ in rec.lte_calls), (
        f"sent_at was never bounded; lte calls were {rec.lte_calls}"
    )


def test_no_delay_means_everyone_the_condition_matches(fake_db):
    """The second call the worker makes — 'is anyone still coming?' — must
    NOT apply the delay, or a follow-up would close while people were still
    waiting their turn."""
    from workers.followup_worker import _get_filtered_contacts

    rec = _RecordingContacts()
    fake_db.set_table("contacts", rec)
    _get_filtered_contacts(fake_db, CAMPAIGN_ID, "not_opened")

    assert not any(col == "sent_at" for col, _ in rec.lte_calls)
