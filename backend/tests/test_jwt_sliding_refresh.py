"""Sliding JWT refresh tests.

A valid token past half its 24h life must come back with a fresh
replacement in the X-Refresh-JWT response header; a young token must
not. Legacy tokens without an iat claim refresh unconditionally.
Expired tokens still 401 (the sliding window only helps ACTIVE users —
idle-past-TTL still re-authenticates, so security posture is unchanged).

Field motivation: hrcargo signed in 07-16 12:04, JWT died silently, and
their 07-17 18:02 test send failed with not_authenticated (2026-07-17
report investigation).
"""
from datetime import datetime, timedelta, timezone

import jwt as pyjwt

from config import JWT_ALGORITHM, JWT_SECRET
from tests.conftest import FAKE_USER, FakeQueryBuilder


def _token(age_hours: float, ttl_hours: float = 24, include_iat: bool = True) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": FAKE_USER["id"],
        "email": FAKE_USER["email"],
        "exp": now - timedelta(hours=age_hours) + timedelta(hours=ttl_hours),
    }
    if include_iat:
        payload["iat"] = now - timedelta(hours=age_hours)
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _call_status(client, fake_db, token):
    fake_db.set_table("users", FakeQueryBuilder(data=[dict(FAKE_USER)]))
    return client.get(
        "/billing/status",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_young_token_gets_no_refresh_header(client, fake_db):
    resp = _call_status(client, fake_db, _token(age_hours=1))
    assert resp.status_code == 200
    assert "x-refresh-jwt" not in resp.headers


def test_token_past_half_life_gets_refreshed(client, fake_db):
    resp = _call_status(client, fake_db, _token(age_hours=13))
    assert resp.status_code == 200
    refreshed = resp.headers.get("x-refresh-jwt")
    assert refreshed

    decoded = pyjwt.decode(refreshed, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert decoded["sub"] == FAKE_USER["id"]
    assert decoded["email"] == FAKE_USER["email"]
    # Fresh token: minted just now with a full TTL ahead
    assert decoded["iat"] >= int(datetime.now(timezone.utc).timestamp()) - 60


def test_legacy_token_without_iat_gets_refreshed(client, fake_db):
    resp = _call_status(client, fake_db, _token(age_hours=1, include_iat=False))
    assert resp.status_code == 200
    assert resp.headers.get("x-refresh-jwt")


def test_expired_token_still_401s(client, fake_db):
    resp = _call_status(client, fake_db, _token(age_hours=25))
    assert resp.status_code == 401
    assert "x-refresh-jwt" not in resp.headers
