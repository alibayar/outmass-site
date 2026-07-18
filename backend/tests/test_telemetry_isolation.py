"""Guard: test runs are isolated from production telemetry.

Incident 2026-07-18: local pytest runs loaded the real POSTHOG_API_KEY
from backend/.env, so main.py's global exception handler reported three
failing-test KeyErrors as production $exception events — which surfaced
as a ⚠️ hard error in the daily Telegram report and burned an
investigation. conftest.py now blanks the key (and sets
posthog.disabled) before any project import; these tests keep that from
regressing.
"""
import posthog


def test_posthog_key_is_blank_in_tests():
    from config import POSTHOG_API_KEY

    assert POSTHOG_API_KEY == ""


def test_posthog_client_is_disabled_in_tests():
    assert posthog.disabled is True


def test_global_exception_handler_does_not_capture(fake_db, auth_bypass):
    """End-to-end: an endpoint blowing up during a test must not reach
    posthog.capture (the handler's POSTHOG_API_KEY guard is falsy).

    Uses raise_server_exceptions=False so the global handler's 500
    response is observable instead of the exception re-raising into the
    test (dependency overrides live on the app, so auth_bypass applies).
    """
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from main import app
    from tests.conftest import FAKE_USER, FakeQueryBuilder

    campaign = {
        "id": "cEx1", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "s", "body": "b", "name": "n",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))

    local_client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "routers.campaigns.contact_model.bulk_insert",
        return_value={},  # deliberately malformed -> endpoint KeyError
    ), patch("main.posthog.capture") as capture:
        resp = local_client.post(
            "/campaigns/cEx1/contacts",
            json={"csv_string": "email\na@b.co\n"},
        )

    assert resp.status_code == 500
    capture.assert_not_called()
