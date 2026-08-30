"""Tests for the requires_reauth flag workflow.

When Microsoft's refresh_token exchange returns 4xx, the user must be
flagged as requires_reauth so the sidebar can show a banner. A successful
fresh OAuth callback must clear the flag. The /settings response must
surface the flag so the sidebar can read it.
"""
from unittest.mock import MagicMock, patch

from tests.conftest import FAKE_USER, FakeQueryBuilder


class _UserTable(FakeQueryBuilder):
    """Capture updates to the users table for assertion."""

    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(vals)
        self._data = [vals]
        return self


class _UserTokensTable(FakeQueryBuilder):
    def __init__(self, rows):
        super().__init__(data=rows)


def test_refresh_failure_flags_user_as_requires_reauth(fake_db):
    """A 401 from the Microsoft token endpoint must mark the user."""
    from models.ms_token import get_fresh_access_token

    user_id = FAKE_USER["id"]
    fake_db.set_table(
        "user_tokens",
        _UserTokensTable(rows=[{
            "access_token": "expired",
            "refresh_token": "dead_refresh_token",
        }]),
    )
    user_table = _UserTable(rows=[FAKE_USER])
    fake_db.set_table("users", user_table)

    def _mock_httpx_get(*a, **kw):
        # /me call returns 401 (expired access_token)
        return MagicMock(status_code=401)

    def _mock_httpx_post(*a, **kw):
        # Refresh endpoint returns 400 invalid_grant
        resp = MagicMock()
        resp.status_code = 400
        resp.text = '{"error":"invalid_grant","error_description":"AADSTS70008"}'
        return resp

    with patch("httpx.get", side_effect=_mock_httpx_get), \
         patch("httpx.post", side_effect=_mock_httpx_post):
        token = get_fresh_access_token(user_id)

    assert token is None
    # Look for the flag update among all captured updates
    flag_updates = [u for u in user_table.update_calls
                    if u.get("requires_reauth") is True]
    assert len(flag_updates) == 1, f"Expected requires_reauth=True update, got: {user_table.update_calls}"
    assert flag_updates[0]["reauth_reason"] == "invalid_grant"


def test_successful_refresh_does_not_flag_user(fake_db):
    from models.ms_token import get_fresh_access_token

    user_id = FAKE_USER["id"]
    fake_db.set_table(
        "user_tokens",
        _UserTokensTable(rows=[{
            "access_token": "expired",
            "refresh_token": "valid_refresh",
        }]),
    )
    user_table = _UserTable(rows=[FAKE_USER])
    fake_db.set_table("users", user_table)

    def _mock_get(*a, **kw):
        return MagicMock(status_code=401)

    def _mock_post(*a, **kw):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
        }
        return resp

    with patch("httpx.get", side_effect=_mock_get), \
         patch("httpx.post", side_effect=_mock_post):
        token = get_fresh_access_token(user_id)

    assert token == "new_access"
    flag_updates = [u for u in user_table.update_calls
                    if "requires_reauth" in u and u.get("requires_reauth") is True]
    assert flag_updates == [], "Successful refresh must not flag the user"


def test_settings_get_exposes_requires_reauth(client, fake_db, auth_bypass):
    """The sidebar reads requires_reauth from /settings."""
    # auth_bypass injects FAKE_USER. requires_reauth defaults to False there.
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert "requires_reauth" in body
    assert body["requires_reauth"] is False


def test_settings_get_exposes_requires_reauth_when_flagged(client, fake_db):
    """Flagged users see requires_reauth=true in settings response."""
    from routers.auth import get_current_user
    from main import app

    flagged_user = {**FAKE_USER, "requires_reauth": True, "reauth_reason": "invalid_grant"}

    async def _override():
        return flagged_user

    app.dependency_overrides[get_current_user] = _override
    try:
        resp = client.get("/settings")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_reauth"] is True
    assert body["reauth_reason"] == "invalid_grant"


def test_refresh_5xx_does_not_flag_user(fake_db):
    """Microsoft server errors are transient — don't flag the user for those."""
    from models.ms_token import get_fresh_access_token

    user_id = FAKE_USER["id"]
    fake_db.set_table(
        "user_tokens",
        _UserTokensTable(rows=[{
            "access_token": "expired",
            "refresh_token": "probably_fine",
        }]),
    )
    user_table = _UserTable(rows=[FAKE_USER])
    fake_db.set_table("users", user_table)

    def _mock_get(*a, **kw):
        return MagicMock(status_code=401)

    def _mock_post(*a, **kw):
        resp = MagicMock()
        resp.status_code = 503  # transient
        resp.text = "Service unavailable"
        return resp

    with patch("httpx.get", side_effect=_mock_get), \
         patch("httpx.post", side_effect=_mock_post):
        token = get_fresh_access_token(user_id)

    assert token is None  # request failed, but don't require re-auth
    flag_updates = [u for u in user_table.update_calls
                    if u.get("requires_reauth") is True]
    assert flag_updates == [], "5xx failure must not flag the user"


def test_invalid_client_flags_with_its_own_reason(fake_db):
    """The branch the registry entry for AZURE_CLIENT_SECRET is about.

    invalid_client is what Microsoft answers when a confidential app sends a
    refresh without its secret — a SERVER-side fault wearing the same 4xx as
    a genuinely dead user token. It is classified separately so an operator
    reading reauth_reason can tell "this user must reconnect" from "we are
    misconfigured", which are opposite instructions.
    """
    from models.ms_token import get_fresh_access_token

    user_id = FAKE_USER["id"]
    fake_db.set_table(
        "user_tokens",
        _UserTokensTable(rows=[{
            "access_token": "expired",
            "refresh_token": "a_perfectly_good_refresh_token",
        }]),
    )
    user_table = _UserTable(rows=[FAKE_USER])
    fake_db.set_table("users", user_table)

    def _mock_httpx_post(*a, **kw):
        resp = MagicMock()
        resp.status_code = 400
        resp.text = '{"error":"invalid_client","error_description":"AADSTS7000218"}'
        return resp

    with patch("httpx.get", side_effect=lambda *a, **kw: MagicMock(status_code=401)), \
         patch("httpx.post", side_effect=_mock_httpx_post):
        token = get_fresh_access_token(user_id)

    assert token is None
    flag_updates = [u for u in user_table.update_calls
                    if u.get("requires_reauth") is True]
    assert len(flag_updates) == 1, user_table.update_calls
    assert flag_updates[0]["reauth_reason"] == "invalid_client"


def test_a_missing_client_secret_pauses_instead_of_blaming_every_user(fake_db):
    """One unset variable on one service must not email the whole base.

    Without the guard this path sends a secretless refresh, Microsoft answers
    invalid_client, and the handler above flags requires_reauth and sends a
    "reconnect your account" email — to a user whose account is fine, and
    then to the next one, daily, for as long as the variable is unset. The
    startup check names the variable and alerts, but it cannot stop the beat
    that runs before anyone reads it.

    So: no HTTP call at all, and — the load-bearing assertion — no write to
    the user row.
    """
    from models.ms_token import get_fresh_access_token

    user_id = FAKE_USER["id"]
    fake_db.set_table(
        "user_tokens",
        _UserTokensTable(rows=[{
            "access_token": "expired",
            "refresh_token": "a_perfectly_good_refresh_token",
        }]),
    )
    user_table = _UserTable(rows=[FAKE_USER])
    fake_db.set_table("users", user_table)

    posts = []

    with patch("httpx.get", side_effect=lambda *a, **kw: MagicMock(status_code=401)), \
         patch("httpx.post", side_effect=lambda *a, **kw: posts.append(kw) or MagicMock()), \
         patch("models.ms_token.AZURE_CLIENT_SECRET", ""):
        token = get_fresh_access_token(user_id)

    assert token is None, "the caller must still see a failed refresh"
    assert posts == [], "no secretless request should reach Microsoft"
    assert not [u for u in user_table.update_calls if "requires_reauth" in u], (
        "our own misconfiguration was written onto the user: "
        f"{user_table.update_calls}"
    )


def test_the_refresh_actually_carries_the_client_secret(fake_db):
    """Nothing else asserts the secret reaches Microsoft.

    Found by mutation: deleting the client_secret line from the refresh
    payload left the whole suite green. In production that is the same
    outcome as the unset variable — a confidential app sending a secretless
    refresh, 400 invalid_client, and every active user flagged
    requires_reauth and emailed to reconnect an account that is fine — except
    that no startup check would name it and no operator alert would fire,
    because from the environment's point of view nothing is missing.

    So the guard above protects against a missing VARIABLE and this protects
    against a missing LINE. They fail the same way and only one of them
    announces itself.
    """
    from models.ms_token import get_fresh_access_token

    fake_db.set_table(
        "user_tokens",
        _UserTokensTable(rows=[{
            "access_token": "expired",
            "refresh_token": "a_perfectly_good_refresh_token",
        }]),
    )
    fake_db.set_table("users", _UserTable(rows=[FAKE_USER]))

    sent = {}

    def _capture(*a, **kw):
        sent.update(kw.get("data") or {})
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"access_token": "fresh", "refresh_token": "rotated"}
        return resp

    with patch("httpx.get", side_effect=lambda *a, **kw: MagicMock(status_code=401)), \
         patch("httpx.post", side_effect=_capture), \
         patch("models.ms_token.AZURE_CLIENT_SECRET", "the-configured-secret"):
        token = get_fresh_access_token(FAKE_USER["id"])

    assert token == "fresh"
    assert sent.get("client_secret") == "the-configured-secret", (
        "the refresh went to Microsoft without its client_secret; this is the "
        f"Web (confidential) flow, so it will be rejected. Sent: {sorted(sent)}"
    )
    assert sent.get("grant_type") == "refresh_token"
