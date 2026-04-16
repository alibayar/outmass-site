"""Tracking router tests (open pixel, click redirect, unsubscribe)."""

from unittest.mock import patch, MagicMock

from tests.conftest import FakeQueryBuilder


FAKE_CONTACT = {
    "id": "contact-001",
    "campaign_id": "campaign-001",
    "email": "user@example.com",
    "first_name": "Ali",
    "status": "sent",
    "opened_at": None,
    "clicked_at": None,
    "ab_variant": None,
    "unsubscribed": False,
}

FAKE_CAMPAIGN = {
    "id": "campaign-001",
    "user_id": "user-001",
    "name": "Test Campaign",
}


def test_open_pixel_returns_gif(client, fake_db):
    """GET /t/{contact_id} should return 1x1 transparent GIF."""
    fake_db.set_table("events", FakeQueryBuilder([{"id": "evt-1"}]))
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.contact_model.mark_opened"), \
         patch("routers.tracking.campaign_model.increment_stat"):
        resp = client.get("/t/contact-001")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/gif"
    assert len(resp.content) == 42  # 1x1 transparent GIF


def test_open_pixel_unknown_contact(client, fake_db):
    """Unknown contact should still return GIF (no 404)."""
    with patch("routers.tracking.contact_model.get_contact", return_value=None), \
         patch("routers.tracking._record_event"):
        resp = client.get("/t/nonexistent")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/gif"


def test_click_redirect(client, fake_db):
    """GET /c/{contact_id}?url=... should 302 redirect."""
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.contact_model.mark_clicked"), \
         patch("routers.tracking.campaign_model.increment_stat"), \
         patch("routers.tracking._record_event"):
        resp = client.get(
            "/c/contact-001?url=https://example.com",
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://example.com"


def test_click_redirect_invalid_url(client, fake_db):
    """Non-http(s) URLs should be rejected."""
    with patch("routers.tracking.contact_model.get_contact", return_value=None):
        resp = client.get("/c/contact-001?url=javascript:alert(1)")
    assert resp.status_code == 400


def test_click_redirect_missing_url(client, fake_db):
    """Missing url param should fail."""
    resp = client.get("/c/contact-001")
    assert resp.status_code == 422


def test_unsubscribe_page_get(client, fake_db):
    """GET /unsubscribe/{id} should return HTML form with contact's email."""
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.get("/unsubscribe/contact-001")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    # Default lang is English (no Accept-Language header)
    assert "Unsubscribe" in resp.text
    # Contact's email should appear on the page
    assert "user@example.com" in resp.text


def test_unsubscribe_post(client, fake_db):
    """POST /unsubscribe/{id} should unsubscribe and return success HTML."""
    fake_db.set_table("suppression_list", FakeQueryBuilder([]))
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.contact_model.mark_unsubscribed"), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.post("/unsubscribe/contact-001")
    assert resp.status_code == 200
    assert "Successfully Unsubscribed" in resp.text


def test_unsubscribe_post_not_found(client, fake_db):
    """POST /unsubscribe with unknown contact returns 'invalid link' page (200)."""
    with patch("routers.tracking.contact_model.get_contact", return_value=None):
        resp = client.post("/unsubscribe/nonexistent")
    # Returns 200 with 'invalid or expired' page (better UX than 404)
    assert resp.status_code == 200
    assert "invalid" in resp.text.lower() or "expired" in resp.text.lower()


def test_unsubscribe_undo(client, fake_db):
    """POST /unsubscribe/{id}/undo should reverse the unsubscribe."""
    UNSUBBED = {**FAKE_CONTACT, "unsubscribed": True}
    fake_db.set_table("contacts", FakeQueryBuilder([UNSUBBED]))
    fake_db.set_table("suppression_list", FakeQueryBuilder([]))
    with patch("routers.tracking.contact_model.get_contact", return_value=UNSUBBED), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.post("/unsubscribe/contact-001/undo")
    assert resp.status_code == 200
    assert "restored" in resp.text.lower()
