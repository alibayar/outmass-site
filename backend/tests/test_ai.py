"""AI router tests."""

from unittest.mock import AsyncMock, patch, MagicMock


def test_ai_generate_free_user_blocked(client, auth_bypass, fake_db):
    """Free plan users should be blocked from AI features."""
    resp = client.post(
        "/ai/generate-email",
        json={"prompt": "Write a cold email", "tone": "professional", "language": "tr"},
    )
    assert resp.status_code == 402


def test_ai_generate_no_api_key(client, auth_bypass_pro, fake_db):
    """Should return 503 when API key is not configured."""
    with patch("routers.ai.ANTHROPIC_API_KEY", ""):
        resp = client.post(
            "/ai/generate-email",
            json={"prompt": "Write a cold email"},
        )
    assert resp.status_code == 503


def test_ai_generate_empty_prompt(client, auth_bypass_pro, fake_db):
    """Empty prompt should return 400."""
    with patch("routers.ai.ANTHROPIC_API_KEY", "sk-test"):
        resp = client.post(
            "/ai/generate-email",
            json={"prompt": "   "},
        )
    assert resp.status_code == 400


def test_ai_generate_success(client, auth_bypass_pro, fake_db):
    """Successful AI generation with mocked Claude response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "content": [
            {
                "type": "text",
                "text": '{"subject": "Test Subject", "body": "<p>Hello {{firstName}}</p>"}'
            }
        ]
    }

    with patch("routers.ai.ANTHROPIC_API_KEY", "sk-test"):
        with patch("routers.ai.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            resp = client.post(
                "/ai/generate-email",
                json={"prompt": "Write a cold email for SaaS"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["subject"] == "Test Subject"
    assert "{{firstName}}" in data["body"]
