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
         patch("main.RESEND_API_KEY", ""), \
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


def test_feedback_sends_email_via_resend_when_configured(client):
    """When Resend is configured, feedback should POST to Resend API."""
    with patch("main.RESEND_API_KEY", "re_test_key"), \
         patch("main.RESEND_FROM_EMAIL", "feedback@getoutmass.com"), \
         patch("main.RESEND_TO_EMAIL", "support@getoutmass.com"), \
         patch("main.TELEGRAM_BOT_TOKEN", ""), \
         patch("main.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"id": "abc"})
        resp = client.post(
            "/api/feedback",
            json={"message": "Love it!", "email": "user@example.com"},
        )

    assert resp.status_code == 200
    resend_calls = [
        c for c in mock_post.call_args_list
        if c[0] and "api.resend.com" in c[0][0]
    ]
    assert len(resend_calls) >= 1
    call = resend_calls[0]
    json_payload = call.kwargs.get("json", {})
    assert json_payload.get("from") == "feedback@getoutmass.com"
    assert json_payload.get("to") == ["support@getoutmass.com"]
    # Reply-To should be the user's email so we can reply directly
    assert json_payload.get("reply_to") == "user@example.com"
    # Body should contain the message and the user email
    html = json_payload.get("html", "") + json_payload.get("text", "")
    assert "Love it" in html
    assert "user@example.com" in html


def test_feedback_skips_resend_when_no_api_key(client):
    """Without Resend API key, no Resend call should happen."""
    with patch("main.RESEND_API_KEY", ""), \
         patch("main.TELEGRAM_BOT_TOKEN", ""), \
         patch("main.httpx.post") as mock_post:
        resp = client.post(
            "/api/feedback",
            json={"message": "test", "email": "x@y.com"},
        )

    assert resp.status_code == 200
    resend_calls = [
        c for c in mock_post.call_args_list
        if c[0] and "api.resend.com" in c[0][0]
    ]
    assert len(resend_calls) == 0


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
