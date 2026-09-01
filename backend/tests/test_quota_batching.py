"""Quota must be charged DURING a send loop, not only after it.

routers/campaigns.py has charged in batches of QUOTA_CHARGE_BATCH since the
send-now path was written; the three worker loops each called
increment_sent_count once, at the end. The end is not guaranteed to arrive.
A Railway deploy or an OOM kills a beat task mid-loop, and every recipient
already emailed and marked 'sent' was then free: the durable per-contact
state said they went out while the counter said they never did. A SIGKILL
runs no handler at all, so no except block can repair it — only having
already written the number can.

The batch total is NOT the thing to assert. Charging 60 at the end and
charging 25+25+10 along the way both add up, and only one of them survives
being killed at contact 40. So these tests pin the SHAPE of the calls.
"""
from unittest.mock import patch

import pytest

from config import QUOTA_CHARGE_BATCH
from tests.conftest import FAKE_STARTER_USER

N = 60  # two full batches of 25 plus a remainder, at the default


def _contacts(n):
    return [
        {"id": f"ct-{i}", "email": f"r{i}@example.com", "unsubscribed": False}
        for i in range(n)
    ]


def _campaign():
    return {
        "id": "camp-1",
        "user_id": FAKE_STARTER_USER["id"],
        "subject": "Hi",
        "body": "Hello",
        "daily_send_cap": 0,
        "attachments": [],
    }


def _run_campaign_loop(fail_at=None):
    """Returns the list of amounts passed to increment_sent_count."""
    from workers import scheduled_worker

    charges = []
    sent = {"n": 0}

    def _send(**kwargs):
        sent["n"] += 1
        if fail_at is not None and sent["n"] > fail_at:
            raise RuntimeError("process killed mid-loop")
        return {"success": True}

    with patch("models.campaign.get_due_scheduled_campaigns",
               return_value=[_campaign()]), \
         patch("models.user.get_by_id", return_value=dict(FAKE_STARTER_USER)), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.get_resumable_contacts",
               side_effect=[_contacts(N), []]), \
         patch("models.contact.mark_sent"), \
         patch("models.contact.mark_failed"), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.get_status", return_value="sending"), \
         patch("models.campaign.update_campaign"), \
         patch("models.campaign.update_if_status", return_value=True), \
         patch("models.user.increment_sent_count",
               side_effect=lambda uid, n, **kw: charges.append(n)), \
         patch("workers.scheduled_worker._send_email", side_effect=_send), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.process_scheduled_campaigns()

    return charges


def test_the_campaign_loop_charges_as_it_goes(fake_db):
    charges = _run_campaign_loop()

    assert sum(charges) == N, "the total must still be right"
    assert len(charges) > 1, (
        "a single charge means the whole run is still lost on a mid-loop kill"
    )
    assert all(c == QUOTA_CHARGE_BATCH for c in charges[:-1]), (
        f"expected full batches of {QUOTA_CHARGE_BATCH}, got {charges}"
    )


def test_a_kill_mid_loop_leaves_most_of_the_quota_already_charged(fake_db):
    """The scenario the batching exists for. Sends blow up at contact 41;
    the batches already written must cover everything except the tail."""
    charges = _run_campaign_loop(fail_at=40)

    charged = sum(charges)
    assert charged >= 40 - QUOTA_CHARGE_BATCH, (
        f"only {charged} of 40 delivered emails were charged before the "
        f"failure — the loss must be bounded by one batch"
    )


# ── Follow-ups ──


def _followup():
    return {
        "id": "fu-1",
        "campaign_id": "camp-1",
        "user_id": FAKE_STARTER_USER["id"],
        "condition": "all",
        "subject": "Following up",
        "body": "Hello again",
        "attachments": [],
    }


def test_the_followup_loop_charges_as_it_goes(fake_db):
    """A follow-up run can cover an entire campaign's list in one pass, so it
    has the same exposure as the campaign loop and had the same shape."""
    from workers import followup_worker

    charges = []
    with patch("models.followup.get_pending_followups",
               return_value=[_followup()]), \
         patch("models.campaign.get_campaign", return_value=_campaign()), \
         patch("models.user.get_by_id", return_value=dict(FAKE_STARTER_USER)), \
         patch("workers.followup_worker.get_fresh_access_token", return_value="tok"), \
         patch("workers.followup_worker._get_filtered_contacts",
               return_value=_contacts(N)), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.get_status", return_value="sending"), \
         patch("models.followup.update_followup_status"), \
         patch("models.user.increment_sent_count",
               side_effect=lambda uid, n, **kw: charges.append(n)), \
         patch("workers.followup_worker._send_followup_email"), \
         patch("workers.followup_worker.time.sleep"):
        followup_worker.process_followups()

    assert sum(charges) == N
    assert len(charges) > 1, f"follow-ups still charge once at the end: {charges}"


# ── The constant itself ──


def test_the_batch_size_is_shared_with_the_send_now_path():
    """Three loops and routers/campaigns.py must not drift apart on this —
    a per-loop literal is how one of them silently goes back to charging
    once."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for module in ("workers/scheduled_worker.py", "workers/followup_worker.py",
                   "routers/campaigns.py"):
        src = (root / module).read_text(encoding="utf-8")
        assert "QUOTA_CHARGE_BATCH" in src, f"{module} lost the shared constant"
        assert not re.search(r">= *\d+ *:\s*\n\s*user_model\.increment_sent_count",
                             src), f"{module} hardcodes a batch size"
    assert QUOTA_CHARGE_BATCH > 0


# ── The batch charge must not be able to un-send a delivered recipient ──


def test_a_failing_quota_write_does_not_defer_a_delivered_contact(fake_db):
    """Found by the 0.2.1 release review. The batch charge sits inside the
    per-contact try whose except calls mark_failed(..., "deferred") — and
    mark_sent has already committed by then. Letting the charge raise into
    that except rewinds a recipient Graph accepted, which puts them back in
    get_resumable_contacts and gets them emailed a second time."""
    from workers import scheduled_worker

    deferred = []
    charges = []

    def _explode(uid, n, **kw):
        charges.append(n)
        raise RuntimeError("users row write failed")

    with patch("models.campaign.get_due_scheduled_campaigns",
               return_value=[_campaign()]), \
         patch("models.user.get_by_id", return_value=dict(FAKE_STARTER_USER)), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.get_resumable_contacts",
               side_effect=[_contacts(N), []]), \
         patch("models.contact.mark_sent"), \
         patch("models.contact.mark_failed",
               side_effect=lambda cid, status="failed": deferred.append((cid, status))), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.get_status", return_value="sending"), \
         patch("models.campaign.update_campaign"), \
         patch("models.campaign.update_if_status", return_value=True), \
         patch("models.user.increment_sent_count", side_effect=_explode), \
         patch("workers.scheduled_worker._send_email",
               return_value={"success": True}), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.process_scheduled_campaigns()

    assert charges, "the batch charge never ran, so this proves nothing"
    assert deferred == [], (
        f"a quota-write failure marked delivered contacts failed: {deferred}"
    )


def test_mark_failed_refuses_to_rewind_a_sent_contact(fake_db):
    """The one-line guard that closes the whole class, including the
    pre-existing send-now loop: whatever goes wrong after a send, a contact
    already marked 'sent' must never become resumable again."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "models" / "contact.py").read_text(
        encoding="utf-8"
    )
    marker = src[src.index("def mark_failed"):]
    marker = marker[:marker.index("\ndef ", 1)] if "\ndef " in marker[1:] else marker
    assert '.neq("status", "sent")' in marker, (
        "mark_failed can rewind a delivered contact into the resumable set"
    )
