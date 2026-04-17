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


# ── i18n tests (Accept-Language language detection) ──


def test_unsubscribe_page_accept_language_turkish(client, fake_db):
    """GET /unsubscribe with Accept-Language: tr should render Turkish UI."""
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.get(
            "/unsubscribe/contact-001",
            headers={"Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"},
        )
    assert resp.status_code == 200
    # Turkish strings should be present; English should NOT appear as the title
    assert "Abonelikten Cik" in resp.text
    assert "<title>OutMass — Unsubscribe</title>" not in resp.text


def test_unsubscribe_page_accept_language_german(client, fake_db):
    """GET /unsubscribe with Accept-Language: de should render German UI."""
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.get(
            "/unsubscribe/contact-001",
            headers={"Accept-Language": "de-DE,de;q=0.9"},
        )
    assert resp.status_code == 200
    assert "Abmelden" in resp.text


def test_unsubscribe_page_accept_language_arabic_sets_rtl(client, fake_db):
    """GET /unsubscribe with Accept-Language: ar should set dir=rtl."""
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.get(
            "/unsubscribe/contact-001",
            headers={"Accept-Language": "ar"},
        )
    assert resp.status_code == 200
    assert 'dir="rtl"' in resp.text


def test_unsubscribe_page_unsupported_language_falls_back_to_english(client, fake_db):
    """Accept-Language for unsupported locale should fall back to English."""
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.get(
            "/unsubscribe/contact-001",
            headers={"Accept-Language": "pt-BR"},  # not in our 10 supported
        )
    assert resp.status_code == 200
    # Falls back to English
    assert "Unsubscribe" in resp.text
    assert 'dir="rtl"' not in resp.text


# ── Sender fallback chain tests ──


def test_unsubscribe_uses_sender_company_when_available(client, fake_db):
    """Should show sender_company as the 'from' label when set."""
    user_with_company = {
        "id": "user-001",
        "sender_company": "Acme Corp",
        "sender_name": "John Doe",
        "name": "John D.",
        "email": "john@acme.com",
    }
    fake_db.set_table("users", FakeQueryBuilder([user_with_company]))
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.get("/unsubscribe/contact-001")
    assert resp.status_code == 200
    assert "Acme Corp" in resp.text
    # sender_company wins — other fields must not appear
    assert "John Doe" not in resp.text


def test_unsubscribe_falls_back_to_sender_name_when_no_company(client, fake_db):
    """Should show sender_name when sender_company is empty."""
    user_no_company = {
        "id": "user-001",
        "sender_company": "",
        "sender_name": "Jane Smith",
        "name": "J. Smith",
        "email": "jane@example.com",
    }
    fake_db.set_table("users", FakeQueryBuilder([user_no_company]))
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.get("/unsubscribe/contact-001")
    assert resp.status_code == 200
    assert "Jane Smith" in resp.text


def test_unsubscribe_falls_back_to_user_name_when_no_sender_info(client, fake_db):
    """Should show user's name field when no sender_* fields set."""
    user_name_only = {
        "id": "user-001",
        "sender_company": "",
        "sender_name": "",
        "name": "Ali Bayar",
        "email": "ali@example.com",
    }
    fake_db.set_table("users", FakeQueryBuilder([user_name_only]))
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.get("/unsubscribe/contact-001")
    assert resp.status_code == 200
    assert "Ali Bayar" in resp.text


def test_unsubscribe_falls_back_to_email_when_all_empty(client, fake_db):
    """Should show user's email when all sender/name fields are empty."""
    user_email_only = {
        "id": "user-001",
        "sender_company": "",
        "sender_name": "",
        "name": "",
        "email": "lonely@example.com",
    }
    fake_db.set_table("users", FakeQueryBuilder([user_email_only]))
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.get("/unsubscribe/contact-001")
    assert resp.status_code == 200
    assert "lonely@example.com" in resp.text


# ── Idempotent / already-unsubscribed tests ──


def test_unsubscribe_already_unsubscribed_shows_status_with_undo(client, fake_db):
    """GET on an already-unsubscribed contact should show status + undo button."""
    unsubbed = {**FAKE_CONTACT, "unsubscribed": True}
    with patch("routers.tracking.contact_model.get_contact", return_value=unsubbed), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp = client.get("/unsubscribe/contact-001")
    assert resp.status_code == 200
    # The status page should reference successful unsubscription
    assert "Successfully Unsubscribed" in resp.text
    # And offer an undo action
    assert "/undo" in resp.text
    assert "Undo" in resp.text


def test_unsubscribe_post_twice_is_idempotent(client, fake_db):
    """POST /unsubscribe twice should not throw — second time is a no-op-ish success."""
    # Same contact marked unsubscribed
    calls = []

    def fake_mark(contact_id):
        calls.append(contact_id)

    fake_db.set_table("suppression_list", FakeQueryBuilder([]))
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.contact_model.mark_unsubscribed", side_effect=fake_mark), \
         patch("routers.tracking.campaign_model.get_campaign", return_value=FAKE_CAMPAIGN):
        resp1 = client.post("/unsubscribe/contact-001")
        resp2 = client.post("/unsubscribe/contact-001")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert "Successfully Unsubscribed" in resp2.text


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
