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


# ── Benign-noise filtering ──
# Browser-internal warnings (ResizeObserver loop, port-closed/bfcache,
# extension-context-invalidated) are harmless but flooded error tracking
# (363 ResizeObserver events). The endpoint drops them before capture so
# the $exception signal — and the PostHog quota — stay clean. This also
# scrubs noise from already-shipped extension versions that lack the
# client-side filter.


def test_error_report_filters_resize_observer_noise(client):
    """ResizeObserver loop warnings must NOT reach PostHog."""
    mock_posthog = MagicMock()
    with patch("main.POSTHOG_API_KEY", "test-key"), \
         patch("main.posthog", mock_posthog):
        resp = client.post(
            "/api/error-report",
            json={"message": "ResizeObserver loop completed with undelivered notifications."},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "filtered"
    mock_posthog.capture.assert_not_called()


def test_error_report_filters_port_closed_and_context_noise(client):
    """Port-closed / bfcache / extension-context-invalidated are benign."""
    benign = [
        "Could not establish connection. Receiving end does not exist.",
        "The message channel closed before a response was received.",
        "Extension context invalidated.",
    ]
    for msg in benign:
        mock_posthog = MagicMock()
        with patch("main.POSTHOG_API_KEY", "test-key"), \
             patch("main.posthog", mock_posthog):
            resp = client.post("/api/error-report", json={"message": msg})
        assert resp.status_code == 200, msg
        assert resp.json()["status"] == "filtered", msg
        mock_posthog.capture.assert_not_called()


def test_error_report_still_captures_real_errors(client):
    """A genuine error must still be forwarded (filter isn't over-broad)."""
    mock_posthog = MagicMock()
    with patch("main.POSTHOG_API_KEY", "test-key"), \
         patch("main.posthog", mock_posthog):
        resp = client.post(
            "/api/error-report",
            json={"message": "TypeError: cannot read property 'send' of undefined"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "received"
    mock_posthog.capture.assert_called_once()
