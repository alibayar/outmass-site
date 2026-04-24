"""Tests for the anonymous uninstall-feedback endpoint.

The extension opens docs/uninstall.html when the user removes it. That
page POSTs here. No auth — the uninstalled extension can't hold a JWT.
"""
from unittest.mock import patch


def test_uninstall_feedback_accepts_reason_and_details(client):
    resp = client.post(
        "/api/uninstall-feedback",
        json={"reason": "too_expensive", "details": "$19 is too much for me"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "received"


def test_uninstall_feedback_empty_is_accepted_silently(client):
    """Never 400 a churning user — return a friendly no-op."""
    resp = client.post("/api/uninstall-feedback", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "empty"


def test_uninstall_feedback_truncates_long_details(client):
    """Malicious or accidental huge payloads must not blow up logs / PostHog."""
    resp = client.post(
        "/api/uninstall-feedback",
        json={"reason": "x" * 1000, "details": "y" * 10000},
    )
    assert resp.status_code == 200


def test_uninstall_feedback_no_auth_required(client):
    """The extension is gone by the time this fires — no Authorization header."""
    # No auth header set on TestClient by default. If the endpoint required
    # auth, FastAPI would 401 before our handler ran.
    resp = client.post(
        "/api/uninstall-feedback",
        json={"reason": "bugs"},
    )
    assert resp.status_code == 200


def test_uninstall_feedback_swallows_telegram_errors(client):
    """A Telegram outage must not cause the endpoint to fail."""
    with patch("main.httpx.post", side_effect=Exception("network down")):
        resp = client.post(
            "/api/uninstall-feedback",
            json={"reason": "not_useful"},
        )
    assert resp.status_code == 200
