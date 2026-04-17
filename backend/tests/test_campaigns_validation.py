"""Validation tests for campaign create/send paths.

Covers:
- malformed / unknown merge tag rejection before send
- whitespace-only campaign name rejection
- CSV upload: mandatory email column, row limit, BOM strip, dedup
- test-send endpoint delivery to sender
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import FAKE_USER, FakeQueryBuilder


# ── C.2: merge-tag validation at send ──


def _install_campaign(fake_db, campaign, pending_contacts):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    fake_db.set_table("contacts", FakeQueryBuilder(data=pending_contacts))
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))
    fake_db.set_table("ab_tests", FakeQueryBuilder(data=[]))
    fake_db.set_table("users", FakeQueryBuilder(data=[FAKE_USER]))


def test_send_rejects_malformed_merge_tag_in_subject(client, fake_db, auth_bypass):
    campaign = {
        "id": "c1", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{firstName}", "body": "Body ok", "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 1,
    }
    _install_campaign(fake_db, campaign, [
        {"id": "k1", "email": "a@b.com", "status": "pending", "unsubscribed": False,
         "first_name": "A", "last_name": "B", "company": "", "position": "",
         "custom_fields": {}},
    ])
    with patch("models.ms_token.get_fresh_access_token", return_value="fake-token"):
        resp = client.post("/campaigns/c1/send",
                           headers={"Authorization": "Bearer t"})
    assert resp.status_code == 400
    assert "merge" in resp.json()["detail"].lower() or \
           "firstName" in resp.json()["detail"]


def test_send_rejects_unknown_merge_tag_in_body(client, fake_db, auth_bypass):
    campaign = {
        "id": "c2", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{firstName}}", "body": "Hi {{fname}}", "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 1,
    }
    _install_campaign(fake_db, campaign, [
        {"id": "k1", "email": "a@b.com", "status": "pending", "unsubscribed": False,
         "first_name": "A", "last_name": "", "company": "", "position": "",
         "custom_fields": {}},
    ])
    with patch("models.ms_token.get_fresh_access_token", return_value="fake-token"):
        resp = client.post("/campaigns/c2/send",
                           headers={"Authorization": "Bearer t"})
    assert resp.status_code == 400
    assert "fname" in resp.json()["detail"]


def test_send_accepts_clean_merge_tags(client, fake_db, auth_bypass):
    """Sanity: a valid campaign still sends (we mock the Graph API call)."""
    campaign = {
        "id": "c3", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{firstName}}", "body": "Welcome {{firstName}}",
        "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 1,
    }
    _install_campaign(fake_db, campaign, [
        {"id": "k1", "email": "a@b.com", "status": "pending", "unsubscribed": False,
         "first_name": "A", "last_name": "B", "company": "Acme", "position": "CEO",
         "custom_fields": {}},
    ])
    with patch("models.ms_token.get_fresh_access_token", return_value="fake-token"), \
         patch("routers.campaigns._send_single_email",
               new=AsyncMock(return_value={"success": True})):
        resp = client.post("/campaigns/c3/send",
                           headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    assert resp.json().get("campaign_id") == "c3"


# ── C.3: test-send endpoint ──


def test_test_send_delivers_to_sender(client, fake_db, auth_bypass):
    """POST /campaigns/{id}/test-send sends one email to the authenticated user."""
    campaign = {
        "id": "c4", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{firstName}}", "body": "Hi {{firstName}}",
        "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    with patch("models.ms_token.get_fresh_access_token", return_value="fake-token"), \
         patch("routers.campaigns._send_single_email",
               new=AsyncMock(return_value={"success": True})):
        resp = client.post("/campaigns/c4/test-send",
                           headers={"Authorization": "Bearer t"},
                           json={"sample": {"firstName": "Alice"}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["sent_to"] == FAKE_USER["email"]


def test_test_send_rejects_malformed_tag(client, fake_db, auth_bypass):
    campaign = {
        "id": "c5", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{firstName}", "body": "ok",
        "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    with patch("models.ms_token.get_fresh_access_token", return_value="fake-token"):
        resp = client.post("/campaigns/c5/test-send",
                           headers={"Authorization": "Bearer t"},
                           json={"sample": {}})
    assert resp.status_code == 400


# ── B.1: whitespace-only campaign name ──


def test_create_rejects_whitespace_only_name(client, fake_db, auth_bypass):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[]))
    resp = client.post("/campaigns",
                       json={"name": "   ", "subject": "s", "body": "b"})
    assert resp.status_code == 400


def test_create_rejects_empty_name(client, fake_db, auth_bypass):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[]))
    resp = client.post("/campaigns",
                       json={"name": "", "subject": "s", "body": "b"})
    assert resp.status_code == 400


# ── A.2: upload_contacts validation ──


def test_upload_rejects_missing_email_column(client, fake_db, auth_bypass):
    campaign = {
        "id": "cU1", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "s", "body": "b", "name": "n",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    csv_text = "name,company\nAlice,Acme\n"
    resp = client.post("/campaigns/cU1/contacts", json={"csv_string": csv_text})
    assert resp.status_code == 400
    assert "email" in resp.json()["detail"].lower()


def test_upload_rejects_oversized_csv(client, fake_db, auth_bypass):
    """Over 5 MB CSV string rejected."""
    campaign = {
        "id": "cU2", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "s", "body": "b", "name": "n",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    # Build a CSV just over 5 MB
    header = "email\n"
    line = "x@example.com\n"
    body = line * ((5 * 1024 * 1024) // len(line) + 10)
    csv_text = header + body
    resp = client.post("/campaigns/cU2/contacts", json={"csv_string": csv_text})
    assert resp.status_code == 413


def test_upload_rejects_too_many_rows_for_free_plan(client, fake_db, auth_bypass):
    campaign = {
        "id": "cU3", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "s", "body": "b", "name": "n",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    # Free plan = 100 row limit
    rows = "\n".join(f"user{i}@example.com" for i in range(150))
    csv_text = "email\n" + rows + "\n"
    resp = client.post("/campaigns/cU3/contacts", json={"csv_string": csv_text})
    assert resp.status_code == 413


def test_archive_campaign_sets_flag(client, fake_db, auth_bypass):
    campaign = {
        "id": "cA1", "user_id": FAKE_USER["id"], "status": "sent",
        "archived": False, "subject": "s", "body": "b", "name": "n",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    resp = client.post("/campaigns/cA1/archive")
    assert resp.status_code == 200
    assert resp.json()["archived"] is True


def test_unarchive_campaign_clears_flag(client, fake_db, auth_bypass):
    campaign = {
        "id": "cA2", "user_id": FAKE_USER["id"], "status": "sent",
        "archived": True, "subject": "s", "body": "b", "name": "n",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    resp = client.post("/campaigns/cA2/unarchive")
    assert resp.status_code == 200
    assert resp.json()["archived"] is False


def test_archive_404_for_other_user(client, fake_db, auth_bypass):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[]))
    resp = client.post("/campaigns/nonexistent/archive")
    assert resp.status_code == 404


def test_export_campaign_list_returns_csv(client, fake_db, auth_bypass):
    campaigns = [
        {"id": "cE1", "user_id": FAKE_USER["id"], "name": "First",
         "status": "sent", "created_at": "2026-04-10T10:00:00Z",
         "sent_count": 5, "open_count": 3, "click_count": 1,
         "total_contacts": 5, "archived": False},
    ]
    fake_db.set_table("campaigns", FakeQueryBuilder(data=campaigns))
    resp = client.get("/campaigns/export-list")
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "outmass_campaigns.csv"
    assert "First" in body["csv_data"]
    assert "name,status" in body["csv_data"]


def test_upload_strips_utf8_bom(client, fake_db, auth_bypass):
    campaign = {
        "id": "cU4", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "s", "body": "b", "name": "n",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    fake_db.set_table("contacts", FakeQueryBuilder(data=[]))
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))
    csv_text = "\ufeffemail,firstName\nalice@example.com,Alice\n"
    resp = client.post("/campaigns/cU4/contacts", json={"csv_string": csv_text})
    assert resp.status_code == 200
    # The email column should be correctly recognized despite BOM.
    assert "count" in resp.json()
