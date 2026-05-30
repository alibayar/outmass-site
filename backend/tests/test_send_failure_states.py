"""Tests for failure classification in the send pipeline.

`_classify_failure` maps a Graph send failure (HTTP status code or None for
a network/timeout exception) to a contact status: permanent `failed` vs
transient `deferred`. It lives in utils/send_classify.py and is re-exported
from routers.campaigns for the send loop.
"""
from routers.campaigns import _classify_failure


def test_classify_4xx_is_permanent():
    assert _classify_failure(400) == "failed"
    assert _classify_failure(403) == "failed"
    assert _classify_failure(413) == "failed"


def test_classify_429_is_transient():
    assert _classify_failure(429) == "deferred"


def test_classify_5xx_is_transient():
    assert _classify_failure(500) == "deferred"
    assert _classify_failure(503) == "deferred"


def test_classify_none_is_transient():
    # network/timeout exception → no status_code → transient
    assert _classify_failure(None) == "deferred"


# ── Scheduled worker applies the same classification ──
#
# process_scheduled_campaigns must record each failed contact via
# contact_model.mark_failed using the classified status, so a Resume picks
# up only the transiently-failed (deferred) ones and skips the permanent
# (failed) ones. 4xx → failed (permanent), 5xx → deferred (transient).
from unittest.mock import patch

from tests.conftest import FAKE_USER, FakeQueryBuilder


def _run_scheduled_with_send_result(fake_db, send_result):
    """Drive process_scheduled_campaigns with one due campaign + one contact,
    a stubbed _send_email returning `send_result`. Returns the list of
    (contact_id, status) tuples passed to contact_model.mark_failed."""
    from workers import scheduled_worker

    campaign = {
        "id": "camp-fail",
        "user_id": FAKE_USER["id"],
        "status": "scheduled",
        "subject": "Hi",
        "body": "Body",
    }
    contact = {"id": "contact-1", "email": "x@example.com", "status": "pending"}
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))

    mark_failed_calls = []

    with patch.object(
        scheduled_worker, "get_fresh_access_token", return_value="token-123"
    ), patch(
        "models.campaign.get_due_scheduled_campaigns", return_value=[campaign]
    ), patch(
        "models.user.get_by_id", return_value=dict(FAKE_USER)
    ), patch(
        "models.campaign.update_campaign"
    ), patch(
        "models.campaign.increment_stat"
    ), patch(
        "models.user.increment_sent_count"
    ), patch(
        "models.contact.get_resumable_contacts", return_value=[contact]
    ), patch(
        "models.contact.mark_failed",
        side_effect=lambda cid, status: mark_failed_calls.append((cid, status)),
    ), patch.object(
        scheduled_worker, "_send_email", return_value=send_result
    ), patch(
        "time.sleep", return_value=None
    ):
        scheduled_worker.process_scheduled_campaigns()

    return mark_failed_calls


def test_scheduled_worker_marks_4xx_failure_as_failed(fake_db):
    calls = _run_scheduled_with_send_result(
        fake_db, {"success": False, "error": "bad recipient", "status_code": 400}
    )
    assert calls == [("contact-1", "failed")]


def test_scheduled_worker_marks_5xx_failure_as_deferred(fake_db):
    calls = _run_scheduled_with_send_result(
        fake_db, {"success": False, "error": "server error", "status_code": 503}
    )
    assert calls == [("contact-1", "deferred")]
