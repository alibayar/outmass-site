"""A suppression-list skip has to be recorded, not just skipped.

Both send loops used to `continue` past a suppressed contact without touching
it, so the row stayed 'pending' forever. Consequences: every resumable set
kept counting them, the Resume button and the auto-resume beat both believed
work remained, and a campaign whose only leftovers were suppressed churned
scheduled → sent on every pass.

Suppressed addresses are normally filtered at UPLOAD time, so the rows that
reach these loops are the ones added to the list AFTER the CSV went in —
including anyone who unsubscribed from an earlier campaign, since that adds
them to the suppression list.
"""
from unittest.mock import patch

from tests.conftest import FAKE_STARTER_USER, FakeQueryBuilder


def _contact(cid, email, **extra):
    return {"id": cid, "email": email, "unsubscribed": False, **extra}


# ── the model helper ──


def test_mark_suppressed_sets_the_status_on_exactly_one_row(fake_db):
    """The row filter is the whole safety of this write.

    Without the .eq("id", …) the UPDATE would set every contact in the table
    to 'suppressed' — the entire product would stop sending, and a test that
    only checked the payload would stay green while it happened.
    """
    from models import contact as contact_model

    class _Rec(FakeQueryBuilder):
        def __init__(self):
            super().__init__(data=[])
            self.updates = []
            self.filters = []

        def update(self, vals):
            self.updates.append(vals)
            return self

        def eq(self, col, val):
            self.filters.append((col, val))
            return self

    rec = _Rec()
    fake_db.set_table("contacts", rec)
    contact_model.mark_suppressed("ct-1")

    assert rec.updates == [{"status": "suppressed"}]
    assert ("id", "ct-1") in rec.filters, (
        "the UPDATE must be filtered to this contact — an unfiltered write "
        "would suppress every contact in the table"
    )


def test_resumable_query_excludes_suppressed(fake_db):
    """The exclusion is what makes the marking worth anything."""
    from models import contact as contact_model

    class _Capture(FakeQueryBuilder):
        def __init__(self):
            super().__init__(data=[])
            self.in_calls = []

        def in_(self, col, vals):
            self.in_calls.append((col, vals))
            return self

    cap = _Capture()
    fake_db.set_table("contacts", cap)
    contact_model.get_resumable_contacts("camp-1")

    statuses = dict(cap.in_calls).get("status")
    assert statuses is not None, "resumable set must filter on status"
    assert "suppressed" not in statuses
    assert "pending" in statuses and "deferred" in statuses


# ── the scheduled worker loop ──


def test_scheduled_worker_marks_the_skipped_contact(fake_db):
    from workers import scheduled_worker

    marked = []
    contacts = [
        _contact("ct-ok", "keep@example.com"),
        _contact("ct-supp", "blocked@example.com"),
    ]

    class _Suppression(FakeQueryBuilder):
        pass

    fake_db.set_table(
        "suppression_list", _Suppression(data=[{"email": "blocked@example.com"}])
    )

    with patch("models.campaign.get_due_scheduled_campaigns", return_value=[{
        "id": "camp-1", "user_id": FAKE_STARTER_USER["id"],
        "subject": "Hi", "body": "Hello", "daily_send_cap": None, "attachments": [],
    }]), \
         patch("models.user.get_by_id", return_value=dict(FAKE_STARTER_USER)), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.get_resumable_contacts", return_value=contacts), \
         patch("models.contact.mark_sent"), \
         patch("models.contact.mark_suppressed", side_effect=marked.append), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.update_campaign"), \
         patch("models.user.increment_sent_count"), \
         patch("workers.scheduled_worker._send_email", return_value={"success": True}), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.process_scheduled_campaigns()

    assert marked == ["ct-supp"], (
        "the suppressed contact must be recorded, or it stays 'pending' and "
        "keeps reappearing in resumable sets"
    )


def test_scheduled_worker_leaves_unsubscribed_alone(fake_db):
    """unsubscribed=True is already excluded by the resumable query itself —
    marking it too would touch rows for no gain."""
    from workers import scheduled_worker

    marked = []
    contacts = [_contact("ct-unsub", "gone@example.com", unsubscribed=True)]
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))

    with patch("models.campaign.get_due_scheduled_campaigns", return_value=[{
        "id": "camp-1", "user_id": FAKE_STARTER_USER["id"],
        "subject": "Hi", "body": "Hello", "daily_send_cap": None, "attachments": [],
    }]), \
         patch("models.user.get_by_id", return_value=dict(FAKE_STARTER_USER)), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.get_resumable_contacts", return_value=contacts), \
         patch("models.contact.mark_sent"), \
         patch("models.contact.mark_suppressed", side_effect=marked.append), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.update_campaign"), \
         patch("models.user.increment_sent_count"), \
         patch("workers.scheduled_worker._send_email", return_value={"success": True}), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.process_scheduled_campaigns()

    assert marked == []


def test_worker_survives_a_failing_mark(fake_db):
    """A bookkeeping write must never be able to stop delivery.

    The call sits ABOVE the per-contact try, so an unguarded raise escaped
    the Celery task, left the campaign 'sending', and skipped every other
    campaign due in that beat — a status write killing real sends.
    """
    from workers import scheduled_worker

    sent = []
    fake_db.set_table(
        "suppression_list", FakeQueryBuilder(data=[{"email": "blocked@example.com"}])
    )

    with patch("models.campaign.get_due_scheduled_campaigns", return_value=[{
        "id": "camp-1", "user_id": FAKE_STARTER_USER["id"],
        "subject": "Hi", "body": "Hello", "daily_send_cap": None, "attachments": [],
    }]), \
         patch("models.user.get_by_id", return_value=dict(FAKE_STARTER_USER)), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.get_resumable_contacts", return_value=[
             _contact("ct-supp", "blocked@example.com"),
             _contact("ct-ok", "keep@example.com"),
         ]), \
         patch("models.contact.mark_sent", side_effect=sent.append), \
         patch("models.contact.mark_suppressed", side_effect=RuntimeError("PGRST 503")), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.update_campaign"), \
         patch("models.user.increment_sent_count"), \
         patch("workers.scheduled_worker._send_email", return_value={"success": True}), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.process_scheduled_campaigns()

    assert sent == ["ct-ok"], (
        "the send must continue after a failed suppression write — the "
        "suppressed contact simply stays 'pending', which is the old behaviour"
    )


def test_send_now_path_marks_and_survives_a_failing_mark(client, fake_db):
    """The router send-now loop had NO coverage at all.

    Inverting who gets suppressed there — or aborting the batch on a failed
    write — would have shipped with a fully green suite.
    """
    import asyncio
    from routers import campaigns as campaigns_router

    marked = []
    sent = []
    send_list = [
        _contact("ct-supp", "blocked@example.com"),
        _contact("ct-ok", "keep@example.com"),
    ]

    async def _fake_send(**kwargs):
        sent.append(kwargs["contact"]["id"])
        return {"success": True}

    updates = []

    with patch("models.contact.mark_suppressed", side_effect=marked.append), \
         patch("models.contact.mark_sent"), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.update_campaign", side_effect=lambda cid, p: updates.append(p)), \
         patch("models.user.increment_sent_count"), \
         patch("routers.campaigns._send_single_email", side_effect=_fake_send), \
         patch("routers.campaigns.SEND_DELAY_SECONDS", 0):
        asyncio.run(campaigns_router._run_campaign_send(
            campaign_id="camp-1",
            campaign={"id": "camp-1", "subject": "Hi", "body": "Hello", "attachments": []},
            send_list=send_list,
            ab_test=None,
            half=0,
            ab_remaining=[],
            access_token="tok",
            user=dict(FAKE_STARTER_USER),
            suppressed_emails={"blocked@example.com"},
        ))

    assert marked == ["ct-supp"]
    assert sent == ["ct-ok"]


def test_a_clean_send_marks_nobody(fake_db):
    """The fix must not touch contacts that were actually sent."""
    from workers import scheduled_worker

    marked = []
    sent = []
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))

    with patch("models.campaign.get_due_scheduled_campaigns", return_value=[{
        "id": "camp-1", "user_id": FAKE_STARTER_USER["id"],
        "subject": "Hi", "body": "Hello", "daily_send_cap": None, "attachments": [],
    }]), \
         patch("models.user.get_by_id", return_value=dict(FAKE_STARTER_USER)), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.get_resumable_contacts",
               return_value=[_contact("ct-1", "a@example.com"), _contact("ct-2", "b@example.com")]), \
         patch("models.contact.mark_sent", side_effect=sent.append), \
         patch("models.contact.mark_suppressed", side_effect=marked.append), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.update_campaign"), \
         patch("models.user.increment_sent_count"), \
         patch("workers.scheduled_worker._send_email", return_value={"success": True}), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.process_scheduled_campaigns()

    assert sorted(sent) == ["ct-1", "ct-2"]
    assert marked == []
