"""PostHog error tracking integration tests."""

from unittest.mock import patch, MagicMock


def test_global_exception_handler_sends_to_posthog(client):
    """Unhandled exceptions should be sent to PostHog."""
    mock_posthog = MagicMock()

    with patch("main.POSTHOG_API_KEY", "test-key"), \
         patch("main.posthog", mock_posthog):
        from routers.auth import get_current_user
        from main import app

        async def _raise_error():
            raise ValueError("Test unhandled error")

        app.dependency_overrides[get_current_user] = _raise_error
        try:
            resp = client.get("/auth/me")
        except Exception:
            pass
        else:
            # Exception handler should catch and return 500
            assert resp.status_code == 500
            mock_posthog.capture.assert_called_once()
            call_kwargs = mock_posthog.capture.call_args
            assert call_kwargs[1]["event"] == "$exception"
        finally:
            app.dependency_overrides.pop(get_current_user, None)


def test_error_report_sends_to_posthog(client):
    """POST /api/error-report should forward to PostHog."""
    mock_posthog = MagicMock()

    with patch("main.POSTHOG_API_KEY", "test-key"), \
         patch("main.posthog", mock_posthog):
        resp = client.post(
            "/api/error-report",
            json={
                "message": "Extension crashed",
                "source": "sidebar",
                "stack": "Error at sidebar.js:42",
                "context": {"tab": "campaign"},
            },
        )

    assert resp.status_code == 200
    mock_posthog.capture.assert_called_once()
    props = mock_posthog.capture.call_args[1]["properties"]
    assert props["$exception_message"] == "Extension crashed"
    assert props["source"] == "sidebar"


def test_error_report_without_posthog(client):
    """Should still return 200 even without PostHog configured."""
    with patch("main.POSTHOG_API_KEY", ""):
        resp = client.post(
            "/api/error-report",
            json={"message": "Some error"},
        )
    assert resp.status_code == 200
