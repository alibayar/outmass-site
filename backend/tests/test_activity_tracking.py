"""Tests for last_login_at / last_activity_at tracking.

These timestamps feed Phase 5's inactivity-detection beat, so their
freshness guarantees matter:

  * touch_login fires on every JWT issue, setting BOTH timestamps.
  * maybe_touch_activity fires on every authenticated request but is
    rate-limited to one write per 15 minutes to avoid DB write amplification.
  * Neither ever raises — a failing activity update must not turn a
    successful request into a 500.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from models import user as user_model
from tests.conftest import FAKE_USER, FakeQueryBuilder


class _RecordingUsersTable(FakeQueryBuilder):
    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(vals)
        self._data = [vals]
        return self


# ── touch_login ──


def test_touch_login_sets_both_timestamps(fake_db):
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    user_model.touch_login(FAKE_USER["id"])

    assert len(users.update_calls) == 1
    call = users.update_calls[0]
    assert "last_login_at" in call
    assert "last_activity_at" in call
    # Both set to the same moment
    assert call["last_login_at"] == call["last_activity_at"]


def test_touch_login_swallows_db_errors(fake_db):
    """A failing DB write must not propagate out of the auth flow."""

    class _Broken(FakeQueryBuilder):
        def update(self, _vals):
            raise RuntimeError("supabase offline")

    fake_db.set_table("users", _Broken())
    # Must not raise
    user_model.touch_login(FAKE_USER["id"])


# ── _is_activity_fresh ──


def test_activity_fresh_returns_false_for_null():
    assert user_model._is_activity_fresh(None) is False
    assert user_model._is_activity_fresh("") is False


def test_activity_fresh_returns_false_for_malformed():
    assert user_model._is_activity_fresh("not a date") is False


def test_activity_fresh_returns_true_for_recent():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(minutes=5)).isoformat()
    assert user_model._is_activity_fresh(recent) is True


def test_activity_fresh_returns_false_for_stale():
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(hours=2)).isoformat()
    assert user_model._is_activity_fresh(stale) is False


def test_activity_fresh_handles_z_suffix():
    """Postgres returns timestamps with 'Z' when serialised — must parse."""
    now = datetime.now(timezone.utc)
    iso_z = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    assert user_model._is_activity_fresh(iso_z) is True


# ── maybe_touch_activity ──


def test_maybe_touch_activity_writes_when_stale(fake_db):
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    user = {**FAKE_USER, "last_activity_at": stale}
    user_model.maybe_touch_activity(user)

    assert len(users.update_calls) == 1
    assert "last_activity_at" in users.update_calls[0]
    # The dict passed in is mutated so downstream handlers see fresh value
    assert user["last_activity_at"] != stale


def test_maybe_touch_activity_skips_when_fresh(fake_db):
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    fresh = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    user = {**FAKE_USER, "last_activity_at": fresh}
    user_model.maybe_touch_activity(user)

    # No write attempted
    assert users.update_calls == []
    # User dict unchanged
    assert user["last_activity_at"] == fresh


def test_maybe_touch_activity_writes_when_null(fake_db):
    """NULL last_activity_at — new user who's never been tracked."""
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    user = {**FAKE_USER, "last_activity_at": None}
    user_model.maybe_touch_activity(user)

    assert len(users.update_calls) == 1


def test_maybe_touch_activity_swallows_errors(fake_db):
    """DB hiccup → skip silently; don't break the request."""

    class _Broken(FakeQueryBuilder):
        def update(self, _vals):
            raise RuntimeError("down")

    fake_db.set_table("users", _Broken())
    # No exception propagates
    user = {**FAKE_USER, "last_activity_at": None}
    user_model.maybe_touch_activity(user)


# ── get_current_user integration ──


def test_get_current_user_calls_maybe_touch_activity(fake_db):
    """Every authenticated request goes through get_current_user, so
    hooking maybe_touch_activity there is what makes activity tracking
    actually work end-to-end."""
    from routers.auth import get_current_user

    with patch("models.user.get_by_id", return_value={**FAKE_USER, "last_activity_at": None}), \
         patch("models.user.maybe_touch_activity") as mock_touch, \
         patch("routers.auth.decode_jwt", return_value={"sub": FAKE_USER["id"]}):
        import asyncio
        user = asyncio.run(get_current_user(authorization=f"Bearer faketoken"))

    assert user is not None
    mock_touch.assert_called_once()


# ── extension version tracking ──


def test_maybe_touch_activity_writes_version_when_provided(fake_db):
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    user = {**FAKE_USER, "last_activity_at": None,
            "last_seen_extension_version": None}
    user_model.maybe_touch_activity(user, extension_version="0.1.9")

    assert len(users.update_calls) == 1
    assert users.update_calls[0].get("last_seen_extension_version") == "0.1.9"
    assert user["last_seen_extension_version"] == "0.1.9"


def test_maybe_touch_activity_skips_version_when_unchanged(fake_db):
    """If version matches what's already on the row, no need to write it
    (saves a roundtrip when the rate-limiter would otherwise have skipped)."""
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    fresh = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    user = {**FAKE_USER,
            "last_activity_at": fresh,
            "last_seen_extension_version": "0.1.9"}
    user_model.maybe_touch_activity(user, extension_version="0.1.9")

    # Activity is fresh AND version matches → no write
    assert users.update_calls == []


def test_maybe_touch_activity_writes_version_change_even_when_activity_fresh(fake_db):
    """Version change is rare but always interesting — bypass the
    activity-freshness rate limiter when the version differs."""
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    fresh = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    user = {**FAKE_USER,
            "last_activity_at": fresh,
            "last_seen_extension_version": "0.1.8"}
    user_model.maybe_touch_activity(user, extension_version="0.1.9")

    assert len(users.update_calls) == 1
    assert users.update_calls[0].get("last_seen_extension_version") == "0.1.9"


def test_maybe_touch_activity_no_version_param_keeps_existing(fake_db):
    """Backward compat — callers that don't pass extension_version still work."""
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    user = {**FAKE_USER,
            "last_activity_at": None,
            "last_seen_extension_version": "0.1.5"}
    user_model.maybe_touch_activity(user)  # no version arg

    # Activity is stale → writes activity, but does NOT touch version
    assert len(users.update_calls) == 1
    assert "last_seen_extension_version" not in users.update_calls[0]


def test_maybe_touch_activity_ignores_too_long_version(fake_db):
    """Defensive: a malicious or accidental huge header value must not
    bloat the DB. Cap at a reasonable length (e.g. 32 chars)."""
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    user = {**FAKE_USER, "last_activity_at": None,
            "last_seen_extension_version": None}
    huge = "X" * 5000
    user_model.maybe_touch_activity(user, extension_version=huge)

    # Either rejected entirely OR truncated — but never written full-length
    written = users.update_calls[0].get("last_seen_extension_version", "")
    assert len(written) <= 32


def test_get_current_user_passes_extension_version_header(fake_db):
    """The X-Extension-Version header should reach maybe_touch_activity
    so the user's last_seen_extension_version stays current."""
    from routers.auth import get_current_user

    with patch("models.user.get_by_id",
               return_value={**FAKE_USER,
                             "last_activity_at": None,
                             "last_seen_extension_version": None}), \
         patch("models.user.maybe_touch_activity") as mock_touch, \
         patch("routers.auth.decode_jwt", return_value={"sub": FAKE_USER["id"]}):
        import asyncio
        asyncio.run(get_current_user(
            authorization="Bearer faketoken",
            x_extension_version="0.1.9",
        ))

    mock_touch.assert_called_once()
    call_kwargs = mock_touch.call_args
    assert call_kwargs.kwargs.get("extension_version") == "0.1.9"


def test_get_current_user_no_header_passes_none(fake_db):
    """Backward compat: requests without the header (legacy clients,
    direct API calls) should still succeed."""
    from routers.auth import get_current_user

    with patch("models.user.get_by_id",
               return_value={**FAKE_USER, "last_activity_at": None}), \
         patch("models.user.maybe_touch_activity") as mock_touch, \
         patch("routers.auth.decode_jwt", return_value={"sub": FAKE_USER["id"]}):
        import asyncio
        asyncio.run(get_current_user(authorization="Bearer faketoken"))

    mock_touch.assert_called_once()
    call_kwargs = mock_touch.call_args
    assert call_kwargs.kwargs.get("extension_version") is None
