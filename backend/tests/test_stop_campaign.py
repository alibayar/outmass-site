"""A user must be able to stop their own campaign.

Until 2026-09-01 there was no way to. No endpoint, no button, nothing hidden
in a menu. `Helene@circularworkplaces.com` found that out five recipients into
a 66-person send and wrote:

    "Now I see nowhere to edit the campaign or even stop it! Please could you
    let me know how to do that or I will have to close the account to stop it."

Revoking OAuth was accurately her only lever. Her campaign was stopped by hand
with an UPDATE while she waited.

Stopping is two writes and both matter. 'cancelled' removes it from
get_due_scheduled_campaigns, which selects 'scheduled'. archived=true removes
it from get_resumable_partial_campaigns so auto-resume cannot pick it back up,
and it is what makes the follow-up worker cancel a pending follow-up for the
same campaign — a bump for a campaign someone stopped is the same mistake
arriving three days late.
"""
from unittest.mock import patch

from tests.conftest import FAKE_USER


def _campaign(**over):
    row = {
        "id": "camp-1",
        "user_id": FAKE_USER["id"],
        "name": "C",
        "status": "scheduled",
        "sent_count": 5,
        "total_contacts": 66,
        "archived": False,
    }
    row.update(over)
    return row


def test_stopping_writes_both_cancelled_and_archived(client, fake_db, auth_bypass):
    """One without the other leaves a door open.

    Only 'cancelled': the auto-resume beat still sees a resumable campaign.
    Only archived: the scheduled beat still selects status 'scheduled'.
    """
    updates = {}
    with patch("models.campaign.get_campaign", return_value=_campaign()), \
         patch("models.contact.count_resumable_contacts", return_value=61), \
         patch("models.campaign.update_campaign",
               side_effect=lambda cid, payload: updates.update(payload)):
        resp = client.post("/campaigns/camp-1/stop")

    assert resp.status_code == 200, resp.text
    assert updates.get("status") == "cancelled", (
        f"status was not cancelled, got {updates!r} — the scheduled beat "
        f"selects 'scheduled' and would send the rest anyway"
    )
    assert updates.get("archived") is True, (
        "archived was not set — auto-resume would pick the campaign back up, "
        "and the pending follow-up would still go out"
    )


def test_the_response_says_how_many_were_already_reached(client, fake_db, auth_bypass):
    """Stopping is not undoing, and the difference has to be visible.

    The panel puts this number in front of the user, because it is the one
    part of the situation nobody can take back.
    """
    with patch("models.campaign.get_campaign", return_value=_campaign(sent_count=5)), \
         patch("models.contact.count_resumable_contacts", return_value=61), \
         patch("models.campaign.update_campaign"):
        resp = client.post("/campaigns/camp-1/stop")

    body = resp.json()
    assert body["already_sent"] == 5, "the reached count must be reported"
    assert body["not_contacted"] == 61, "the spared count must be reported"


def test_a_finished_campaign_cannot_be_stopped(client, fake_db, auth_bypass):
    """409, not a quiet success.

    The caller believes something is running. Answering "stopped" when there
    was nothing to stop is a lie about the thing they are anxious about.
    """
    with patch("models.campaign.get_campaign", return_value=_campaign(status="sent")), \
         patch("models.campaign.update_campaign") as upd:
        resp = client.post("/campaigns/camp-1/stop")

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "not_stoppable"
    assert upd.call_count == 0


def test_an_already_stopped_campaign_cannot_be_stopped_again(client, fake_db, auth_bypass):
    with patch("models.campaign.get_campaign", return_value=_campaign(status="cancelled")), \
         patch("models.campaign.update_campaign") as upd:
        resp = client.post("/campaigns/camp-1/stop")

    assert resp.status_code == 409
    assert upd.call_count == 0


def test_every_status_a_send_can_be_in_is_stoppable(client, fake_db, auth_bypass):
    """The list is the whole promise.

    A status missing from it is a campaign the user watches running with a
    button that refuses. 'sending' and 'partial' matter most — those are the
    two a person is looking at when they want it to stop.
    """
    from routers.campaigns import STOPPABLE_STATUSES

    for status in ("scheduled", "sending", "partial", "failed_auth",
                   "ab_testing", "awaiting_winner", "sending_winner"):
        assert status in STOPPABLE_STATUSES, (
            f"a campaign in status {status!r} cannot be stopped — that is a "
            f"live send with no brake"
        )

    for status in ("sent", "cancelled"):
        assert status not in STOPPABLE_STATUSES, (
            f"{status!r} is terminal; offering to stop it promises something "
            f"that does not happen"
        )


def test_somebody_else_s_campaign_is_a_404(client, fake_db, auth_bypass):
    with patch("models.campaign.get_campaign",
               return_value=_campaign(user_id="someone-else")), \
         patch("models.campaign.update_campaign") as upd:
        resp = client.post("/campaigns/camp-1/stop")

    assert resp.status_code == 404
    assert upd.call_count == 0


# ── the half that was missing: Stop has to survive a running loop ──


def test_the_due_query_skips_archived_campaigns():
    """The one-line gap that made Stop fail permanently on a paced campaign.

    get_due_scheduled_campaigns selected status='scheduled' and nothing else,
    while its sibling get_resumable_partial_campaigns has always filtered
    archived. So a stop landing mid-batch was overwritten by the daily-cap
    branch writing 'scheduled' back, and the beat then picked it up again the
    next day, and every day after — invisibly, because archived rows are not in
    the default Reports view.
    """
    import inspect

    from models import campaign as campaign_model

    src = inspect.getsource(campaign_model.get_due_scheduled_campaigns)
    assert '.eq("archived", False)' in src, (
        "the due query no longer skips archived campaigns — a stopped campaign "
        "comes back the moment anything writes 'scheduled' over the "
        "cancellation, and comes back where the owner cannot see it"
    )


def test_a_close_out_cannot_overwrite_a_cancellation():
    """update_if_status is the durable protection, not the in-loop check.

    Every send loop marks its campaign 'sending' before it starts. If the owner
    presses Stop while it runs, the row says 'cancelled' — and the close-out
    must find nothing to update rather than writing 'sent' over their decision.
    """
    from unittest.mock import MagicMock

    from models import campaign as campaign_model

    chain = MagicMock()
    chain.update.return_value = chain
    chain.eq.return_value = chain
    chain.execute.return_value = MagicMock(data=[])   # nothing matched
    db = MagicMock()
    db.table.return_value = chain

    with patch("models.campaign.get_db", return_value=db):
        applied = campaign_model.update_if_status(
            "camp-1", {"status": "sent"}, expected="sending"
        )

    assert applied is False, (
        "a close-out that matched no row must report that it did not apply"
    )
    eq_args = [c.args for c in chain.eq.call_args_list]
    assert ("status", "sending") in eq_args, (
        "update_if_status did not constrain on the expected status — it is an "
        "unconditional write wearing a conditional name, and a finishing loop "
        "would resurrect a stopped campaign"
    )


def test_every_close_out_in_the_send_paths_is_conditional():
    """Structural, because the omission was structural.

    Both send loops write a status when they end, and they do it from several
    branches: clean finish, quota cap, auth stop, A/B hand-off, deploy
    cancellation, unhandled error. Any single branch left on the
    unconditional update_campaign reopens the hole for its own path only —
    which is exactly how the plain-text conversion went missing from two
    paths out of three and stayed missing for months.

    So this does not ask whether the conditional form appears somewhere in
    the function. It asks whether the unconditional one still writes a status
    anywhere in it.
    """
    import inspect
    import re

    from routers import campaigns as router
    from workers import scheduled_worker

    for label, fn in {
        "send-now": router._run_campaign_send,
        "scheduled campaigns": scheduled_worker.process_scheduled_campaigns,
    }.items():
        src = inspect.getsource(fn)
        assert "update_if_status" in src, (
            f"the {label} path no longer closes out conditionally — a loop "
            f"finishing after Stop writes over the cancellation"
        )
        unconditional = [
            " ".join(m.group(0).split())
            for m in re.finditer(
                r"update_campaign\([^)]{0,200}?\"status\"[^)]{0,120}?\)", src
            )
        ]
        assert not unconditional, (
            f"the {label} path writes a status unconditionally: "
            f"{unconditional!r} — whichever branch that is lands on top of a "
            f"cancellation the owner asked for, and stopping is one-way"
        )


def test_a_stop_pressed_during_a_send_now_halts_that_loop_too(fake_db):
    """The send-now path is where the Stop button's own wording came from.

    "$1 people have already received this campaign... Stop now so nobody else
    does?" — with no cancellation check in this loop, every one of the
    remaining recipients still got the email while the panel showed the
    campaign stopped. The close-out being conditional keeps the STATUS honest;
    only this check keeps the SENTENCE honest.
    """
    import asyncio
    from unittest.mock import AsyncMock

    from config import CANCEL_CHECK_EVERY
    from routers import campaigns as router

    sent = []

    async def _ok(**kwargs):
        return {"success": True}

    contacts = [
        {"id": f"ct-{i}", "email": f"r{i}@example.com", "unsubscribed": False}
        for i in range(30)
    ]

    with patch("models.contact.mark_sent", side_effect=sent.append), \
         patch("models.contact.mark_failed"), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.get_status", return_value="cancelled"), \
         patch("models.campaign.update_campaign"), \
         patch("models.campaign.update_if_status", return_value=False), \
         patch("models.contact.has_resumable_contacts", return_value=True), \
         patch("models.user.increment_sent_count"), \
         patch("routers.campaigns._send_single_email", new=AsyncMock(side_effect=_ok)), \
         patch("routers.campaigns.SEND_DELAY_SECONDS", 0):
        asyncio.run(router._run_campaign_send(
            campaign_id="camp-stop-now",
            campaign={"id": "camp-stop-now", "subject": "Hi", "body": "Hello",
                      "attachments": []},
            send_list=contacts,
            ab_test=None,
            half=0,
            ab_remaining=[],
            access_token="tok",
            user=dict(FAKE_USER),
            suppressed_emails=set(),
        ))

    assert len(sent) <= CANCEL_CHECK_EVERY, (
        f"{len(sent)} of 30 recipients went out after the owner stopped the "
        f"campaign; the overshoot must be at most one check interval "
        f"({CANCEL_CHECK_EVERY})"
    )


# ── and the loop has to notice, not just be unable to overwrite ──


def _contacts(n):
    return [
        {"id": f"ct-{i}", "email": f"r{i}@example.com", "unsubscribed": False}
        for i in range(n)
    ]


def _beat(pending_count, status_reads, cap=None, resumable_after=None,
          still_resumable=False):
    """Run one scheduled beat over `pending_count` recipients.

    `status_reads` is what models.campaign.get_status returns (or raises) on
    each cancellation check, in order. The worker checks every
    CANCEL_CHECK_EVERY recipients.

    Returns (sent contact ids, [(fn, payload, expected)] in write order).
    """
    from workers import scheduled_worker

    user = {**FAKE_USER, "emails_sent_this_month": 0}
    writes = []
    sent_ids = []
    contacts = [_contacts(pending_count)]
    if resumable_after is not None:
        contacts.append(resumable_after)

    campaign = {
        "id": "camp-stop",
        "user_id": FAKE_USER["id"],
        "subject": "Hi",
        "body": "Hello",
        "daily_send_cap": cap,
        "attachments": [],
    }

    with patch("models.campaign.get_due_scheduled_campaigns", return_value=[campaign]), \
         patch("models.user.get_by_id", return_value=user), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.get_resumable_contacts", side_effect=contacts), \
         patch("models.contact.has_resumable_contacts", return_value=still_resumable), \
         patch("models.contact.mark_sent", side_effect=sent_ids.append), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.get_status", side_effect=status_reads), \
         patch("models.campaign.update_campaign",
               side_effect=lambda cid, p: writes.append(("update_campaign", p, None))), \
         patch("models.campaign.update_if_status",
               side_effect=lambda cid, p, expected=None: writes.append(
                   ("update_if_status", p, expected)) or True), \
         patch("models.user.increment_sent_count"), \
         patch("workers.scheduled_worker._send_email", return_value={"success": True}), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.process_scheduled_campaigns()

    return sent_ids, writes


def test_a_stop_pressed_mid_batch_halts_the_send(fake_db):
    """The point of the whole feature.

    Before 2026-09-01 no loop in the send paths ever re-read the campaign row,
    so pressing Stop while a batch ran did nothing at all: the remaining
    recipients went out anyway, and the close-out then wrote a final status
    over the cancellation. The overshoot after Stop must be bounded by
    CANCEL_CHECK_EVERY, not by the length of the list.
    """
    from workers.scheduled_worker import CANCEL_CHECK_EVERY

    sent_ids, _ = _beat(30, status_reads=["cancelled", "cancelled", "cancelled"])

    assert len(sent_ids) < 30, (
        "the batch ran to completion after the owner stopped it — the "
        "cancellation check is not halting the loop"
    )
    assert len(sent_ids) <= CANCEL_CHECK_EVERY, (
        f"{len(sent_ids)} went out after Stop; the overshoot must be at most "
        f"one check interval ({CANCEL_CHECK_EVERY})"
    )


def test_a_stopped_campaign_is_not_rescheduled_for_tomorrow(fake_db):
    """Helene's exact shape: 5/day, stopped on day one.

    The daily-cap branch rewrites {'status': 'scheduled', scheduled_for: +1d}
    whenever recipients remain — which is always true for a campaign someone
    stopped early. Writing that is what made a stop last exactly one day.
    """
    _, writes = _beat(
        30, status_reads=["cancelled"], cap=25,
        resumable_after=_contacts(20), still_resumable=True,
    )

    rescheduled = [w for w in writes if w[1].get("status") == "scheduled"]
    assert not rescheduled, (
        f"a stopped campaign was put back in the queue: {rescheduled!r} — it "
        f"would run again tomorrow, and every day after"
    )


def test_the_close_out_after_a_stop_is_conditional(fake_db):
    """Even the halted loop still falls through to a close-out."""
    _, writes = _beat(30, status_reads=["cancelled"])

    finals = [w for w in writes if w[1].get("status") in ("sent", "partial")]
    for fn, payload, expected in finals:
        assert fn == "update_if_status" and expected == "sending", (
            f"{payload!r} was written unconditionally — it lands on top of the "
            f"'cancelled' the owner just asked for"
        )


def test_a_failing_cancellation_check_does_not_halt_the_send(fake_db):
    """The check is an optimisation; update_if_status is the guarantee.

    Halting every send on one flaky select would trade a bounded overshoot for
    an outage, so a read that raises means "keep going".
    """
    sent_ids, _ = _beat(30, status_reads=Exception("supabase down"))

    assert len(sent_ids) == 30, (
        "a failed cancellation check stopped a campaign nobody cancelled"
    )
