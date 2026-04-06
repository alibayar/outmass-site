"""Basic health check and error reporting tests."""

from unittest.mock import patch


def test_health_check(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "outmass-api"


def test_error_report_endpoint(client):
    """POST /api/error-report should accept client errors."""
    with patch("main.posthog") as mock_ph:
        with patch("main.POSTHOG_API_KEY", "test-key"):
            resp = client.post(
                "/api/error-report",
                json={
                    "message": "Test error",
                    "source": "extension",
                    "stack": "Error at line 1",
                    "context": {"page": "sidebar"},
                },
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == "received"


def test_error_report_minimal(client):
    """Minimal error report (only message)."""
    resp = client.post("/api/error-report", json={"message": "minimal error"})
    assert resp.status_code == 200
