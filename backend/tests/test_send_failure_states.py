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


def test_classify_408_409_are_transient():
    # 408 (timeout) and 409 (conflict) are retryable, not permanent.
    assert _classify_failure(408) == "deferred"
    assert _classify_failure(409) == "deferred"


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
        "models.campaign.update_if_status"
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


# ── 401/403 stops the run; it does not condemn the recipients ──
#
# _classify_failure maps every 4xx to 'failed', which is permanent:
# get_resumable_contacts only ever returns 'pending' and 'deferred'. That is
# right for a bad recipient and catastrophic for an auth failure, because a
# 401/403 is about the MAILBOX, not the person being written to.
#
# Until 2026-08-30 the two send paths disagreed. routers/campaigns.py has
# always broken out of the loop on 401/403, leaving the rest 'pending'. The
# scheduled worker did not: it ran _classify_failure on every remaining
# contact and marked them all 'failed' — unreachable forever, by the Resume
# button and the auto-resume beat alike. The beat would then find nothing
# resumable and close the campaign as 'sent'.
#
# Found before it fired. On 2026-08-30 a new user's first two campaigns
# stopped in the immediate path (which leaves 'pending'): 2 of 9 and 4 of 7
# delivered. The 06:00 UTC resume the next morning would have pushed the
# remaining 10 through THIS loop, and the user would have been left reading
# "sent" over a list that was half delivered.


def _run_scheduled_multi(fake_db, contacts, send_results):
    """Drive process_scheduled_campaigns over several contacts.

    `send_results` is consumed one per contact, so a stop can be placed at an
    exact position and the contacts after it observed to be untouched.
    Returns (mark_failed_calls, update_campaign_calls).
    """
    from workers import scheduled_worker

    campaign = {
        "id": "camp-auth",
        "user_id": FAKE_USER["id"],
        "status": "scheduled",
        "subject": "Hi",
        "body": "Body",
    }
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))

    mark_failed_calls = []
    update_calls = []
    results = list(send_results)

    with patch.object(
        scheduled_worker, "get_fresh_access_token", return_value="token-123"
    ), patch(
        "models.campaign.get_due_scheduled_campaigns", return_value=[campaign]
    ), patch(
        "models.user.get_by_id", return_value=dict(FAKE_USER)
    ), patch(
        "models.campaign.update_if_status",
        side_effect=lambda cid, payload, expected=None: update_calls.append((cid, payload)) or True,
    ), patch(
        "models.campaign.increment_stat"
    ), patch(
        "models.user.increment_sent_count"
    ), patch(
        "models.contact.mark_sent"
    ), patch(
        "models.contact.get_resumable_contacts", return_value=contacts
    ), patch(
        "models.contact.mark_failed",
        side_effect=lambda cid, status: mark_failed_calls.append((cid, status)),
    ), patch.object(
        scheduled_worker, "_send_email", side_effect=lambda **kw: results.pop(0)
    ), patch(
        "time.sleep", return_value=None
    ):
        scheduled_worker.process_scheduled_campaigns()

    return mark_failed_calls, update_calls


def _c(n):
    return {"id": f"contact-{n}", "email": f"x{n}@example.com", "status": "pending"}


_OK = {"success": True}
_403 = {"success": False, "error": "SubmissionQuotaExceeded", "status_code": 403}
_401 = {"success": False, "error": "InvalidAuthenticationToken", "status_code": 401}


def test_scheduled_worker_does_not_condemn_recipients_on_403(fake_db):
    """The recipient is not the problem, so the recipient is not marked."""
    calls, _ = _run_scheduled_multi(fake_db, [_c(1)], [_403])
    assert calls == []


def test_scheduled_worker_does_not_condemn_recipients_on_401(fake_db):
    calls, _ = _run_scheduled_multi(fake_db, [_c(1)], [_401])
    assert calls == []


def test_scheduled_worker_stops_at_the_403_and_leaves_the_rest_alone(fake_db):
    """Two delivered, then a 403 — contacts 3 and 4 are never attempted and
    never written to, so they stay 'pending' and resumable."""
    calls, _ = _run_scheduled_multi(
        fake_db, [_c(1), _c(2), _c(3), _c(4)], [_OK, _OK, _403, _OK]
    )
    assert calls == []


def test_an_auth_stop_parks_the_campaign_as_partial(fake_db):
    """The trap this flag exists for.

    An auth stop appends nothing to `errors`, and the final status used to be
    computed from `errors` alone — so a campaign that sent two of nine would
    have been written back as 'sent'.
    """
    _, updates = _run_scheduled_multi(
        fake_db, [_c(1), _c(2), _c(3)], [_OK, _403, _OK]
    )
    statuses = [p.get("status") for _, p in updates if "status" in p]
    assert statuses[-1] == "partial", statuses


def test_a_clean_run_still_closes_as_sent(fake_db):
    """The flag must not make every campaign partial."""
    _, updates = _run_scheduled_multi(fake_db, [_c(1), _c(2)], [_OK, _OK])
    statuses = [p.get("status") for _, p in updates if "status" in p]
    assert statuses[-1] == "sent", statuses


def test_a_genuine_per_recipient_4xx_is_still_permanent(fake_db):
    """400 is about the address, not the mailbox: unchanged, still 'failed',
    and the loop carries on to the next contact."""
    bad = {"success": False, "error": "bad recipient", "status_code": 400}
    calls, _ = _run_scheduled_multi(fake_db, [_c(1), _c(2)], [bad, _OK])
    assert calls == [("contact-1", "failed")]
