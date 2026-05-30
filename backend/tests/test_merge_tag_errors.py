"""Structured merge-tag validation error tests (v0.1.10 Fix 1).

The send_campaign + test-send merge-tag validation paths return a STRUCTURED
HTTPException detail (matching the existing feature_locked / limit_exceeded
pattern that background.js parses via detail.error), with an English `message`
fallback kept identical to the legacy raw string for un-upgraded clients.

Mocking pattern: override get_current_user via the `auth_bypass` fixture, seed
the campaigns/contacts/suppression_list/ab_tests/users fake tables, and patch
get_fresh_access_token so execution reaches the validation block (which runs
AFTER the resumable-contacts check).
"""
from unittest.mock import patch

from tests.conftest import FAKE_USER, FakeQueryBuilder


def _install_campaign(fake_db, campaign, pending_contacts):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    fake_db.set_table("contacts", FakeQueryBuilder(data=pending_contacts))
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))
    fake_db.set_table("ab_tests", FakeQueryBuilder(data=[]))
    fake_db.set_table("users", FakeQueryBuilder(data=[FAKE_USER]))


# A single resumable contact so get_resumable_contacts returns a row and
# execution reaches the merge-tag validation block.
_PENDING = [
    {
        "id": "k1", "email": "a@b.com", "status": "pending", "unsubscribed": False,
        "first_name": "A", "last_name": "B", "company": "", "position": "",
        "custom_fields": {},
    },
]


# ── unknown merge tags (send_campaign) ──


def test_unknown_merge_tag_returns_structured_error(client, fake_db, auth_bypass):
    campaign = {
        "id": "mt-unknown", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{firstName}}", "body": "Hello {{FirstName}}", "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 1,
    }
    _install_campaign(fake_db, campaign, _PENDING)
    with patch("models.ms_token.get_fresh_access_token", return_value="tok"):
        resp = client.post(
            "/campaigns/mt-unknown/send",
            headers={"Authorization": "Bearer t"},
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["error"] == "unknown_merge_tags"
    assert "FirstName" in detail["tags"]
    assert detail["field"] in ("subject", "body")
    # available_tags lists the CSV-derived columns the user CAN use
    # (filled standard contact fields + custom), never the unknown tag.
    assert "firstName" in detail["available_tags"]
    assert "FirstName" not in detail["available_tags"]
    # English message starts with the legacy raw string, then appends the
    # available-tags hint.
    assert detail["message"].startswith(
        "Unknown merge tags (not in CSV): FirstName"
    )
    assert "Available:" in detail["message"]


# ── malformed merge tag (send_campaign) ──


def test_malformed_merge_tag_returns_structured_error(client, fake_db, auth_bypass):
    campaign = {
        "id": "mt-malformed", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{First Name}}", "body": "Body ok", "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 1,
    }
    _install_campaign(fake_db, campaign, _PENDING)
    with patch("models.ms_token.get_fresh_access_token", return_value="tok"):
        resp = client.post(
            "/campaigns/mt-malformed/send",
            headers={"Authorization": "Bearer t"},
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["error"] == "malformed_merge_tag"
    assert detail["field"] == "subject"
    assert "{{First Name}}" in detail["tag"]
    assert detail["message"] == (
        "Malformed merge tag in subject: " + detail["tag"]
    )


def test_malformed_merge_tag_in_body_reports_body_field(
    client, fake_db, auth_bypass
):
    campaign = {
        "id": "mt-malformed-body", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{firstName}}", "body": "Hello {{First Name}}", "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 1,
    }
    _install_campaign(fake_db, campaign, _PENDING)
    with patch("models.ms_token.get_fresh_access_token", return_value="tok"):
        resp = client.post(
            "/campaigns/mt-malformed-body/send",
            headers={"Authorization": "Bearer t"},
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "malformed_merge_tag"
    assert detail["field"] == "body"
    assert detail["message"] == "Malformed merge tag in body: " + detail["tag"]


# ── malformed merge tag (test-send / _run_test_send) ──


def test_test_send_malformed_merge_tag_returns_structured_error(
    client, fake_db, auth_bypass
):
    campaign = {
        "id": "mt-ts", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{First Name}}", "body": "ok", "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    with patch("models.ms_token.get_fresh_access_token", return_value="tok"):
        resp = client.post(
            "/campaigns/mt-ts/test-send",
            headers={"Authorization": "Bearer t"},
            json={"sample": {}},
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["error"] == "malformed_merge_tag"
    assert detail["field"] == "subject"
    assert detail["message"] == "Malformed merge tag in subject: " + detail["tag"]


def test_test_send_unknown_merge_tag_returns_structured_error(
    client, fake_db, auth_bypass
):
    """Test Send must also catch unknown (well-formed but not-in-CSV) tags,
    using the sample row's columns, since onboarding tells users to Test Send
    first. available_tags lists the sample columns."""
    campaign = {
        "id": "mt-ts-unknown", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{FistName}}", "body": "ok", "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    with patch("models.ms_token.get_fresh_access_token", return_value="tok"):
        resp = client.post(
            "/campaigns/mt-ts-unknown/test-send",
            headers={"Authorization": "Bearer t"},
            json={"sample": {"firstName": "Ali", "adSoyad": "Ali B"}},
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "unknown_merge_tags"
    assert "FistName" in detail["tags"]
    # available_tags = the sample (CSV) columns the user actually has
    assert "firstName" in detail["available_tags"]
    assert "adSoyad" in detail["available_tags"]
    assert "FistName" not in detail["available_tags"]
