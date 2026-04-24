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
