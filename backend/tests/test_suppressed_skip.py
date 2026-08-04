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


def test_mark_suppressed_sets_the_status(fake_db):
    from models import contact as contact_model

    class _Rec(FakeQueryBuilder):
        def __init__(self):
            super().__init__(data=[])
            self.updates = []

        def update(self, vals):
            self.updates.append(vals)
            return self

    rec = _Rec()
    fake_db.set_table("contacts", rec)
    contact_model.mark_suppressed("ct-1")

    assert rec.updates == [{"status": "suppressed"}]


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
