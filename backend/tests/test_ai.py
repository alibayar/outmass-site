"""AI router tests."""

from unittest.mock import AsyncMock, patch, MagicMock

from tests.conftest import FAKE_PRO_USER, FakeQueryBuilder


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


# ── Monthly AI generation limit tests ──


def test_ai_limit_reached_returns_402(client, fake_db):
    """When ai_generations_this_month >= AI_GENERATION_MONTHLY_LIMIT, return 402."""
    from routers.auth import get_current_user
    from main import app

    # Pro user who has already used their monthly AI quota
    user_at_limit = {**FAKE_PRO_USER, "ai_generations_this_month": 50}

    async def _override():
        return user_at_limit

    app.dependency_overrides[get_current_user] = _override
    try:
        with patch("routers.ai.ANTHROPIC_API_KEY", "sk-test"):
            resp = client.post(
                "/ai/generate-email",
                json={"prompt": "Write a cold email"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 402
    detail = resp.json().get("detail", {})
    assert detail.get("error") == "ai_limit_reached"
    assert detail.get("used") == 50
    assert detail.get("limit") == 50


def test_ai_limit_exceeded_returns_402(client, fake_db):
    """When ai_generations_this_month > limit, still returns 402 (defensive)."""
    from routers.auth import get_current_user
    from main import app

    user_over_limit = {**FAKE_PRO_USER, "ai_generations_this_month": 999}

    async def _override():
        return user_over_limit

    app.dependency_overrides[get_current_user] = _override
    try:
        with patch("routers.ai.ANTHROPIC_API_KEY", "sk-test"):
            resp = client.post(
                "/ai/generate-email",
                json={"prompt": "Write a cold email"},
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 402


def test_ai_counter_incremented_after_success(client, fake_db):
    """Successful AI generation should increment ai_generations_this_month in DB."""
    from routers.auth import get_current_user
    from main import app

    user_below_limit = {**FAKE_PRO_USER, "ai_generations_this_month": 10}

    async def _override():
        return user_below_limit

    # Track DB update calls
    update_calls = []

    class CapturingBuilder(FakeQueryBuilder):
        def update(self, vals):
            update_calls.append(vals)
            return super().update(vals)

    fake_db.set_table("users", CapturingBuilder())

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "content": [{"type": "text", "text": '{"subject": "S", "body": "<p>B</p>"}'}]
    }

    app.dependency_overrides[get_current_user] = _override
    try:
        with patch("routers.ai.ANTHROPIC_API_KEY", "sk-test"):
            with patch("routers.ai.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                resp = client.post(
                    "/ai/generate-email",
                    json={"prompt": "Write a cold email"},
                )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    # Response should include updated usage
    data = resp.json()
    assert data["ai_used"] == 11
    assert data["ai_limit"] == 50

    # DB should have been updated with incremented counter
    assert any(
        call.get("ai_generations_this_month") == 11 for call in update_calls
    ), f"Expected ai_generations_this_month=11 in update calls, got: {update_calls}"


def test_ai_counter_not_incremented_when_api_fails(client, fake_db):
    """If Claude API returns error, counter should NOT be incremented."""
    from routers.auth import get_current_user
    from main import app

    user_below_limit = {**FAKE_PRO_USER, "ai_generations_this_month": 10}

    async def _override():
        return user_below_limit

    update_calls = []

    class CapturingBuilder(FakeQueryBuilder):
        def update(self, vals):
            update_calls.append(vals)
            return super().update(vals)

    fake_db.set_table("users", CapturingBuilder())

    mock_response = MagicMock()
    mock_response.status_code = 500  # Claude API failure
    mock_response.text = "Internal Server Error"

    app.dependency_overrides[get_current_user] = _override
    try:
        with patch("routers.ai.ANTHROPIC_API_KEY", "sk-test"):
            with patch("routers.ai.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                resp = client.post(
                    "/ai/generate-email",
                    json={"prompt": "Write a cold email"},
                )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 502
    # Counter should NOT have been incremented
    assert not any(
        "ai_generations_this_month" in call for call in update_calls
    ), f"Counter incorrectly incremented on API failure: {update_calls}"
