"""'sent' may never be written from a list the code is holding in memory.

Supabase caps a single PostgREST response at SUPABASE_MAX_ROWS (1000 on this
project). `get_resumable_contacts` returns a short list with no error and
nothing compares its length to a real count, so on a campaign larger than the
cap a pass can look perfect — no errors, no quota cap, no auth stop — while
recipients it never read sit untouched in the table.

That is not a delay. `sent` is terminal by construction: send 409s, Resume
wants 'partial', auto-resume selects 'partial', the due beat 'scheduled', the
stuck sweep 'sending', reauth-resume 'failed_auth'. Nothing selects 'sent' and
nothing compares sent_count to total_contacts, so those people are gone.

It has already happened, twice, to the same customer:

  91e7ce08  1020 recipients, exactly 1000 sent, closed 'sent'   2026-06-30
  49587d65  1210 recipients, 999 sent + 120 failed, closed 'sent'  2026-07-20

110 people, silently. Daily-capped campaigns escaped only by accident: their
branch re-queries the database before deciding, and `continue`s past the status
write. Every close-out now does what that branch always did.

Each test below pins one close-out. The count is stubbed rather than the DB,
because the point is not what the database holds — it is that the decision is
taken from a count at all.
"""
from unittest.mock import patch

from tests.conftest import FAKE_STARTER_USER


def _contacts(n):
    return [
        {"id": f"ct-{i}", "email": f"r{i}@example.com", "unsubscribed": False}
        for i in range(n)
    ]


def _campaign(cap=None):
    return {
        "id": "camp-cap",
        "user_id": FAKE_STARTER_USER["id"],
        "subject": "Hi",
        "body": "Hello",
        "daily_send_cap": cap,
        "attachments": [],
    }


def _run_scheduled(still_resumable, cap=None, send_ok=True):
    """One pass of the scheduled beat over one campaign."""
    from workers import scheduled_worker

    updates = []
    result = {"success": True} if send_ok else {"success": False, "error": "boom"}

    with patch("models.campaign.get_due_scheduled_campaigns", return_value=[_campaign(cap)]), \
         patch("models.user.get_by_id", return_value=dict(FAKE_STARTER_USER)), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.get_resumable_contacts", return_value=_contacts(3)), \
         patch("models.contact.has_resumable_contacts", return_value=still_resumable), \
         patch("models.contact.mark_sent"), \
         patch("models.contact.mark_failed"), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.get_status", return_value="sending"), \
         patch("models.campaign.update_campaign",
               side_effect=lambda cid, payload: updates.append(payload)), \
         patch("models.campaign.update_if_status",
               side_effect=lambda cid, payload, expected=None: updates.append(payload) or True), \
         patch("models.user.increment_sent_count"), \
         patch("workers.scheduled_worker._send_email", return_value=result), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.process_scheduled_campaigns()

    return updates


def test_scheduled_uncapped_clean_pass_with_people_left_is_partial(fake_db):
    """Faisal's campaign, exactly.

    No daily cap, so the reschedule branch above never runs. Every recipient
    the pass could see went out cleanly. The old code read that as finished
    and wrote 'sent' — and the twenty it had never fetched were unreachable
    from that moment on.
    """
    updates = _run_scheduled(still_resumable=True)

    assert updates[-1]["status"] == "partial", (
        f"an uncapped pass that left resumable recipients must close 'partial', "
        f"got {updates[-1]} — 'sent' is terminal and nothing reopens it"
    )


def test_scheduled_uncapped_clean_pass_with_nobody_left_is_sent(fake_db):
    """The other side of it: a genuinely finished campaign must still close.

    Without this, the guard above could be satisfied by never writing 'sent'
    at all, and every campaign in the product would sit in 'partial' forever
    being re-attempted by auto-resume.
    """
    updates = _run_scheduled(still_resumable=False)

    assert updates[-1] == {"status": "sent"}, (
        f"a finished campaign must close 'sent', got {updates[-1]}"
    )


def test_scheduled_capped_pass_still_reschedules_rather_than_closing(fake_db):
    """The branch that was always right, kept right.

    A daily-capped campaign with people left goes back to 'scheduled' for
    tomorrow instead of closing either way. This is the behaviour that made
    bellmed's 1,822-recipient campaign deliver 1,820 while faisal's uncapped
    1,020 delivered 1,000.
    """
    updates = _run_scheduled(still_resumable=True, cap=2)

    assert updates[-1]["status"] == "scheduled", (
        f"a capped campaign with recipients left must requeue, got {updates[-1]}"
    )
    assert "scheduled_for" in updates[-1], "requeue must carry the next run time"


def test_a_failed_pass_is_partial_regardless_of_the_count(fake_db):
    """Errors still win, and the count must not be able to override them.

    Ordering matters: the count runs last precisely so a pass that already
    knows it failed does not pay for a database round trip — but it must also
    never turn a failed pass into a successful one.
    """
    updates = _run_scheduled(still_resumable=False, send_ok=False)

    assert updates[-1]["status"] == "partial", (
        f"a pass with send errors must close 'partial' whatever the count says, "
        f"got {updates[-1]}"
    )


# ── the A/B paths, which had the weakest guard of the three ──


def _ab_row():
    return {
        "id": "ab-1",
        "campaign_id": "camp-cap",
        "user_id": FAKE_STARTER_USER["id"],
        "status": "awaiting_winner",
        "created_at": "2020-01-01T00:00:00+00:00",
        "opens_a": 5,
        "opens_b": 1,
        "subject_a": "A",
        "subject_b": "B",
        "test_percentage": 20,
    }


def _run_ab(db, pending, still_resumable):
    from tests.conftest import FakeQueryBuilder
    from workers import scheduled_worker

    updates = []
    db.set_table("ab_tests", FakeQueryBuilder([_ab_row()]))
    db.set_table("suppression_list", FakeQueryBuilder([]))

    with patch("models.campaign.get_campaign", return_value=_campaign()), \
         patch("models.user.get_by_id", return_value=dict(FAKE_STARTER_USER)), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.ab_test.update_ab_test"), \
         patch("models.contact.get_pending_contacts", return_value=pending), \
         patch("models.contact.has_resumable_contacts", return_value=still_resumable), \
         patch("models.contact.mark_sent"), \
         patch("models.contact.mark_failed"), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.get_status", return_value="ab_testing"), \
         patch("models.campaign.update_campaign",
               side_effect=lambda cid, payload: updates.append(payload)), \
         patch("models.campaign.update_if_status",
               side_effect=lambda cid, payload, expected=None:
                   updates.append(payload) or True), \
         patch("models.user.increment_sent_count"), \
         patch("workers.scheduled_worker._send_email", return_value={"success": True}), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.evaluate_ab_tests()

    return updates


def test_ab_with_no_pending_but_deferred_left_is_not_sent(fake_db):
    """The weakest guard in the file, before this.

    This branch asked get_pending_contacts, which selects status 'pending'
    only. 'deferred' — a transient failure queued for retry — is resumable
    everywhere else in the product but invisible here, so a campaign holding
    nothing but deferred recipients read as finished and closed 'sent',
    putting them permanently out of reach of the retry they were queued for.
    """
    updates = _run_ab(fake_db, pending=[], still_resumable=True)

    assert updates and updates[-1]["status"] == "partial", (
        f"no 'pending' does not mean nothing left — deferred recipients are "
        f"resumable, got {updates}"
    )


def test_ab_with_nothing_left_at_all_still_closes_sent(fake_db):
    """And the finished case must still close, or nothing ever completes."""
    updates = _run_ab(fake_db, pending=[], still_resumable=False)

    assert updates and updates[-1] == {"status": "sent"}, (
        f"an A/B campaign with nothing resumable must close 'sent', got {updates}"
    )


def test_ab_winner_send_that_left_people_behind_is_partial(fake_db):
    """The winner broadcast is a full send and gets the same guard.

    It used to close on `"sent" if not errors else "partial"` — the same
    in-memory reasoning as the two paths above, over a recipient list read
    with the same page cap.
    """
    updates = _run_ab(fake_db, pending=_contacts(2), still_resumable=True)

    assert updates and updates[-1]["status"] == "partial", (
        f"an A/B winner send with recipients left must close 'partial', got "
        f"{updates}"
    )


def test_ab_winner_send_that_finished_closes_sent(fake_db):
    updates = _run_ab(fake_db, pending=_contacts(2), still_resumable=False)

    assert updates and updates[-1]["status"] == "sent", (
        f"a finished A/B winner send must close 'sent', got {updates}"
    )


# ── the fail-safe direction ──


def test_an_uncountable_campaign_is_treated_as_unfinished():
    """When the count cannot be taken, the safe answer is "there is more".

    Every caller is deciding whether to write 'sent', and 'sent' is a
    one-way door: no beat, sweep or endpoint in this product selects it.
    'partial' is recoverable — auto-resume picks it up and closes it properly
    once a later count comes back zero. So a database hiccup during the
    close-out must cost a redundant resume pass, never a lost recipient.
    """
    from models import contact as contact_model

    with patch("models.contact.count_resumable_contacts",
               side_effect=RuntimeError("supabase is having a moment")):
        assert contact_model.has_resumable_contacts("camp-x") is True, (
            "a failed count must read as 'unfinished' — failing open writes "
            "'sent' on a campaign nobody has counted, and nothing reopens it"
        )


def test_a_countable_empty_campaign_is_finished():
    """And the happy path still closes, or nothing ever completes."""
    from models import contact as contact_model

    with patch("models.contact.count_resumable_contacts", return_value=0):
        assert contact_model.has_resumable_contacts("camp-x") is False
