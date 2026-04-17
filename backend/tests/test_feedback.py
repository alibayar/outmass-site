"""Feedback endpoint tests — Telegram + Resend mail dispatch."""

from unittest.mock import patch, MagicMock


# ── Basic acceptance ──


def test_feedback_returns_received_on_valid_message(client):
    """POST /api/feedback with a non-empty message should return success."""
    resp = client.post(
        "/api/feedback",
        json={"message": "Great extension!", "email": "user@example.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] in ("received", "sent")


def test_feedback_empty_message_returns_empty(client):
    """Empty message should not trigger any side effects."""
    with patch("main.httpx") as mock_httpx:
        resp = client.post(
            "/api/feedback",
            json={"message": "   ", "email": "user@example.com"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "empty"
    assert not mock_httpx.post.called


# ── Telegram dispatch ──


def test_feedback_sends_to_telegram_when_configured(client):
    """When Telegram is configured, feedback should POST to Bot API."""
    with patch("main.TELEGRAM_BOT_TOKEN", "test-bot-token"), \
         patch("main.TELEGRAM_CHAT_ID", "test-chat-id"), \
         patch("main.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        resp = client.post(
            "/api/feedback",
            json={
                "message": "Found a bug in send button",
                "email": "ali@example.com",
            },
        )

    assert resp.status_code == 200
    # Telegram should have been called
    telegram_calls = [
        c for c in mock_post.call_args_list
        if c[0] and "api.telegram.org" in c[0][0]
    ]
    assert len(telegram_calls) >= 1
    # Payload should contain the message and the user email
    call = telegram_calls[0]
    data = call.kwargs.get("data") or call.kwargs.get("json") or {}
    assert "Found a bug" in str(data.get("text", ""))
    assert "ali@example.com" in str(data.get("text", ""))


def test_feedback_skips_telegram_when_not_configured(client):
    """Without Telegram credentials, feedback should still succeed (no Telegram call)."""
    with patch("main.TELEGRAM_BOT_TOKEN", ""), \
         patch("main.TELEGRAM_CHAT_ID", ""), \
         patch("main.MAILERSEND_API_KEY", ""), \
         patch("main.httpx.post") as mock_post:
        resp = client.post(
            "/api/feedback",
            json={"message": "test", "email": "x@y.com"},
        )

    assert resp.status_code == 200
    assert not mock_post.called


def test_feedback_survives_telegram_error(client):
    """If Telegram returns 500, feedback endpoint should still return 200."""
    with patch("main.TELEGRAM_BOT_TOKEN", "tok"), \
         patch("main.TELEGRAM_CHAT_ID", "chat"), \
         patch("main.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=500, text="error")
        resp = client.post(
            "/api/feedback",
            json={"message": "test", "email": "x@y.com"},
        )

    # Should not propagate Telegram error to the user
    assert resp.status_code == 200


# ── Resend (email) dispatch ──


def test_feedback_sends_email_via_mailersend_when_configured(client):
    """When MailerSend is configured, feedback should POST to MailerSend API."""
    with patch("main.MAILERSEND_API_KEY", "ms_test_key"), \
         patch("main.MAILERSEND_FROM_EMAIL", "feedback@getoutmass.com"), \
         patch("main.MAILERSEND_FROM_NAME", "OutMass"), \
         patch("main.MAILERSEND_TO_EMAIL", "support@getoutmass.com"), \
         patch("main.TELEGRAM_BOT_TOKEN", ""), \
         patch("main.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=202, json=lambda: {"id": "abc"})
        resp = client.post(
            "/api/feedback",
            json={"message": "Love it!", "email": "user@example.com"},
        )

    assert resp.status_code == 200
    ms_calls = [
        c for c in mock_post.call_args_list
        if c[0] and "api.mailersend.com" in c[0][0]
    ]
    assert len(ms_calls) >= 1
    call = ms_calls[0]
    json_payload = call.kwargs.get("json", {})
    # MailerSend requires from as an object {email, name}
    assert json_payload.get("from", {}).get("email") == "feedback@getoutmass.com"
    assert json_payload.get("to") == [{"email": "support@getoutmass.com"}]
    # Reply-To object form
    assert json_payload.get("reply_to", {}).get("email") == "user@example.com"
    # Body should contain the message and the user email
    html = json_payload.get("html", "") + json_payload.get("text", "")
    assert "Love it" in html
    assert "user@example.com" in html


def test_feedback_skips_mailersend_when_no_api_key(client):
    """Without MailerSend API key, no MailerSend call should happen."""
    with patch("main.MAILERSEND_API_KEY", ""), \
         patch("main.TELEGRAM_BOT_TOKEN", ""), \
         patch("main.httpx.post") as mock_post:
        resp = client.post(
            "/api/feedback",
            json={"message": "test", "email": "x@y.com"},
        )

    assert resp.status_code == 200
    ms_calls = [
        c for c in mock_post.call_args_list
        if c[0] and "api.mailersend.com" in c[0][0]
    ]
    assert len(ms_calls) == 0


def test_feedback_works_with_anonymous_user(client):
    """Feedback without email should still be accepted (anonymous)."""
    with patch("main.TELEGRAM_BOT_TOKEN", "tok"), \
         patch("main.TELEGRAM_CHAT_ID", "chat"), \
         patch("main.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        resp = client.post(
            "/api/feedback",
            json={"message": "Anonymous feedback", "email": ""},
        )

    assert resp.status_code == 200
    # Telegram should still be called
    telegram_calls = [
        c for c in mock_post.call_args_list
        if c[0] and "api.telegram.org" in c[0][0]
    ]
    assert len(telegram_calls) >= 1
