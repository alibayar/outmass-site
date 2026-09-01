"""A campaign must never end up in a state nothing queries.

Four recovery paths exist and each looks at exactly one status:

    get_due_scheduled_campaigns      status='scheduled' AND archived=False
    get_resumable_partial_campaigns  status='partial'   AND archived=False
    reset_stuck_sending_campaigns    status='sending'
    POST /{id}/resume                409s on anything but 'partial'

Any (status, archived) pair outside that set is a campaign whose remaining
recipients are reachable by nobody — not by a beat, not by a sweep, not by the
owner, who is usually looking at a success message. The product has landed in
one three times: 'scheduled' with a NULL scheduled_for (2026-07-20),
'sending' after a crash with the sweep off the air (2026-08-08 to 09-01), and
the two this file was written for.

These were found by a multi-lens review of the 2026-09-01 stop fixes, and both
came in through the same door: a write that used to be unconditional became
conditional, and a caller that had been relying on the old behaviour was not
updated with it.
"""
from unittest.mock import patch

from tests.conftest import FAKE_USER


# ── Resume on an archived campaign ──


def _archived_partial(**over):
    row = {
        "id": "camp-arch",
        "user_id": FAKE_USER["id"],
        "name": "C",
        "status": "partial",
        "sent_count": 7,
        "total_contacts": 100,
        "archived": True,
    }
    row.update(over)
    return row


def test_resuming_an_archived_campaign_clears_the_archive_flag(
    client, fake_db, auth_bypass
):
    """Otherwise Resume promises a send that can never happen.

    get_due_scheduled_campaigns began filtering archived on 2026-09-01 so a
    stopped campaign could not come back. The panel offers Resume for any
    'partial' campaign including archived ones, the endpoint checks status and
    not archived, and the response says "N recipient(s) queued". Without this
    the row lands on 'scheduled' AND archived, which the due query skips,
    auto-resume skips, the sweep skips, and this endpoint then 409s on.
    """
    updates = {}
    with patch("models.campaign.get_campaign", return_value=_archived_partial()), \
         patch("models.contact.get_resumable_contacts",
               return_value=[{"id": "c1", "email": "a@example.com"}]), \
         patch("models.campaign.update_campaign",
               side_effect=lambda cid, payload: updates.update(payload)):
        resp = client.post("/campaigns/camp-arch/resume")

    assert resp.status_code == 200, resp.text
    assert updates.get("status") == "scheduled"
    assert updates.get("archived") is False, (
        f"resume left archived set: {updates!r} — the campaign is now in a "
        f"status the due query filters out, and the endpoint answered "
        f"{resp.json()!r}, which tells the owner the opposite"
    )


def test_resume_still_works_normally_on_an_unarchived_campaign(
    client, fake_db, auth_bypass
):
    """The flag is cleared, not toggled: a normal resume is unchanged."""
    updates = {}
    with patch("models.campaign.get_campaign",
               return_value=_archived_partial(archived=False)), \
         patch("models.contact.get_resumable_contacts",
               return_value=[{"id": "c1", "email": "a@example.com"}]), \
         patch("models.campaign.update_campaign",
               side_effect=lambda cid, payload: updates.update(payload)):
        resp = client.post("/campaigns/camp-arch/resume")

    assert resp.status_code == 200
    assert updates.get("status") == "scheduled"
    assert updates.get("scheduled_for")


# ── A failed A/B hand-off ──


def test_a_failed_ab_handoff_rolls_the_campaign_back_to_sending():
    """The close-out that follows is conditional on 'sending'.

    The hand-off moves the campaign to 'ab_testing' first and arms the
    experiment second, so that a stopped campaign never gets an experiment
    waiting for a winner. But if arming the experiment then fails, the
    function's error handler writes 'partial' expecting 'sending' — and the
    row already says 'ab_testing', so the write silently does nothing. The
    campaign would sit in 'ab_testing' with its ab_tests row still 'testing',
    a pair evaluate_ab_tests never selects because it queries
    'awaiting_winner'.

    Rolling back before re-raising is what keeps the ordering safe.
    """
    import asyncio
    from unittest.mock import AsyncMock

    from routers import campaigns as router

    writes = []

    async def _ok(**kwargs):
        return {"success": True}

    def _record(cid, payload, expected=None):
        writes.append((payload.get("status"), expected))
        return True

    with patch("models.contact.mark_sent"), \
         patch("models.contact.mark_failed"), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.get_status", return_value="sending"), \
         patch("models.campaign.update_campaign"), \
         patch("models.campaign.update_if_status", side_effect=_record), \
         patch("models.ab_test.update_ab_test",
               side_effect=RuntimeError("postgrest 503")), \
         patch("models.contact.has_resumable_contacts", return_value=True), \
         patch("models.user.increment_sent_count"), \
         patch("routers.campaigns._send_single_email", new=AsyncMock(side_effect=_ok)), \
         patch("routers.campaigns.SEND_DELAY_SECONDS", 0):
        asyncio.run(router._run_campaign_send(
            campaign_id="camp-ab",
            campaign={"id": "camp-ab", "subject": "Hi", "body": "Hello",
                      "attachments": []},
            send_list=[{"id": "c1", "email": "a@example.com", "unsubscribed": False},
                       {"id": "c2", "email": "b@example.com", "unsubscribed": False}],
            ab_test={"id": "ab-1", "campaign_id": "camp-ab",
                     "subject_a": "A", "subject_b": "B"},
            half=1,
            ab_remaining=[{"id": "c3", "email": "c@example.com"}],
            access_token="tok",
            user=dict(FAKE_USER),
            suppressed_emails=set(),
        ))

    assert ("sending", "ab_testing") in writes, (
        f"the campaign was not rolled back after the experiment failed to "
        f"arm: {writes!r} — it stays 'ab_testing' with a 'testing' experiment, "
        f"which no beat, sweep or endpoint selects"
    )
    assert writes[-1][0] == "partial", (
        f"after the rollback the error handler must be able to park the "
        f"campaign where recovery can see it, got {writes!r}"
    )


# ── The A/B winner send is a third send loop ──


def _ab_row(**over):
    row = {
        "id": "ab-1",
        "campaign_id": "camp-win",
        "user_id": FAKE_USER["id"],
        "status": "awaiting_winner",
        "created_at": "2020-01-01T00:00:00+00:00",
        "opens_a": 5,
        "opens_b": 1,
        "subject_a": "A",
        "subject_b": "B",
        "test_percentage": 20,
    }
    row.update(over)
    return row


def _run_winner(db, remaining, status_during_loop):
    from tests.conftest import FakeQueryBuilder
    from workers import scheduled_worker

    writes = []
    sent = []
    db.set_table("ab_tests", FakeQueryBuilder([_ab_row()]))
    db.set_table("suppression_list", FakeQueryBuilder([]))

    campaign = {
        "id": "camp-win", "user_id": FAKE_USER["id"], "subject": "Hi",
        "body": "Hello", "status": "ab_testing", "archived": False,
        "attachments": [],
    }

    with patch("models.campaign.get_campaign", return_value=campaign), \
         patch("models.user.get_by_id", return_value=dict(FAKE_USER)), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.ab_test.update_ab_test"), \
         patch("models.contact.get_pending_contacts", return_value=remaining), \
         patch("models.contact.has_resumable_contacts", return_value=True), \
         patch("models.contact.mark_sent", side_effect=sent.append), \
         patch("models.contact.mark_failed"), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.get_status", return_value=status_during_loop), \
         patch("models.campaign.update_campaign",
               side_effect=lambda cid, p: writes.append(("update_campaign", p, None))), \
         patch("models.campaign.update_if_status",
               side_effect=lambda cid, p, expected=None:
                   writes.append(("update_if_status", p, expected)) or True), \
         patch("models.user.increment_sent_count"), \
         patch("workers.scheduled_worker._send_email", return_value={"success": True}), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.evaluate_ab_tests()

    return sent, writes


def _contacts(n):
    return [
        {"id": f"ct-{i}", "email": f"r{i}@example.com", "unsubscribed": False}
        for i in range(n)
    ]


def test_the_winner_send_stops_when_the_owner_stops_the_campaign(fake_db):
    """The campaign reads 'ab_testing' for the whole winner send, and
    STOPPABLE_STATUSES contains it — so the panel offers Stop for exactly this
    window. Before 2026-09-01 the loop re-read nothing, so the rest of the list
    went out anyway.
    """
    from config import CANCEL_CHECK_EVERY

    sent, _ = _run_winner(fake_db, _contacts(30), status_during_loop="cancelled")

    assert len(sent) <= CANCEL_CHECK_EVERY, (
        f"{len(sent)} of 30 winner recipients went out after the owner "
        f"stopped the campaign"
    )


def test_the_winner_close_out_cannot_overwrite_a_cancellation(fake_db):
    _, writes = _run_winner(fake_db, _contacts(30), status_during_loop="cancelled")

    finals = [w for w in writes if w[1].get("status") in ("sent", "partial")]
    for fn, payload, expected in finals:
        assert fn == "update_if_status" and expected == "ab_testing", (
            f"{payload!r} was written unconditionally over whatever the "
            f"campaign row says, including a 'cancelled' the owner asked for"
        )


def test_an_uncancelled_winner_send_still_completes(fake_db):
    """The check must not stop a campaign nobody stopped."""
    sent, writes = _run_winner(
        fake_db, _contacts(30), status_during_loop="ab_testing"
    )

    assert len(sent) == 30, "the winner send was cut short with no cancellation"
    assert any(w[1].get("status") in ("sent", "partial") for w in writes), (
        "the winner send never closed the campaign out"
    )


def test_every_send_loop_in_the_product_closes_out_conditionally():
    """Three loops, not two.

    The 2026-09-01 fix covered _run_campaign_send and
    process_scheduled_campaigns and left evaluate_ab_tests alone — which is
    the same shape as the plain-text bug that was fixed in one send path and
    missed in the other two. Naming all three here is the point.
    """
    import inspect
    import re

    from routers import campaigns as router
    from workers import scheduled_worker

    for label, fn in {
        "send-now": router._run_campaign_send,
        "scheduled campaigns": scheduled_worker.process_scheduled_campaigns,
        "A/B winner": scheduled_worker.evaluate_ab_tests,
    }.items():
        src = inspect.getsource(fn)
        unconditional = [
            " ".join(m.group(0).split())
            for m in re.finditer(
                r"update_campaign\([^)]{0,200}?\"status\"[^)]{0,120}?\)", src
            )
        ]
        assert not unconditional, (
            f"the {label} loop writes a status unconditionally: "
            f"{unconditional!r}"
        )
        assert "CANCEL_CHECK_EVERY" in src, (
            f"the {label} loop never asks whether it is still wanted — a Stop "
            f"pressed while it runs does nothing until it finishes"
        )
