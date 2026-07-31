"""Microsoft-side sign-in failures must be reportable.

Before this, /auth/callback received Microsoft's `error` and
`error_description`, rendered an error page, and returned. The reason was
thrown away. The consequence was not "less data" but WRONG data: a tenant
that blocks unverified apps (AADSTS90094) left the user parked on our error
page until they closed the window, and Chrome then reported "the user did not
approve access" — indistinguishable from a genuine refusal. 24 of 26 sign-in
failures in the 30 days to 2026-07-31 carried that single label.

The reason is now captured. `error_description` is free text that can name
the user, their tenant and their app registration, so only the AADSTS code
travels — never the raw description.
"""
from unittest.mock import patch

import pytest

from routers.auth import (
    _classify_ms_error,
    _decode_state,
    _encode_state,
    _track_ms_auth_failed,
)

EXT = "adcfddainnkjomddlappnnbeomhlcbmm"


# ── classification ──


def test_extracts_the_aadsts_code_and_names_the_common_ones():
    out = _classify_ms_error(
        "access_denied",
        "AADSTS90094: The grant requires admin permission.",
    )
    assert out["aadsts"] == "AADSTS90094"
    assert out["meaning"] == "admin_consent_required"
    assert out["error"] == "access_denied"


def test_unknown_aadsts_code_is_still_reported_by_number():
    out = _classify_ms_error("access_denied", "AADSTS99999: Something new.")
    assert out["aadsts"] == "AADSTS99999"
    assert out["meaning"] == "unclassified", "unknown codes must not be dropped"


def test_missing_description_does_not_crash():
    out = _classify_ms_error("access_denied", None)
    assert out["aadsts"] is None
    assert out["error"] == "access_denied"

    out = _classify_ms_error(None, None)
    assert out["error"] == "unknown"


def test_raw_description_is_never_returned():
    """The description routinely embeds the signing-in user's address."""
    described = (
        "AADSTS50020: User account 'victim@customer.com' from identity provider "
        "'live.com' does not exist in tenant 'Contoso' with object id 9f8e..."
    )
    out = _classify_ms_error("access_denied", described)

    flat = " ".join(str(v) for v in out.values())
    assert "victim@customer.com" not in flat
    assert "Contoso" not in flat
    assert "9f8e" not in flat
    assert out["aadsts"] == "AADSTS50020"
    assert out["meaning"] == "account_from_other_tenant"


# ── attempt id plumbing ──


def test_attempt_id_round_trips_through_state():
    state = _encode_state(EXT, attempt_id="abc123def456")
    assert _decode_state(state)["aid"] == "abc123def456"


def test_state_without_attempt_id_still_decodes():
    """Clients before 0.1.27 don't send one — the failure must still report."""
    state = _encode_state(EXT)
    data = _decode_state(state)
    assert data["ext"] == EXT
    assert "aid" not in data


def test_attempt_id_is_length_capped():
    state = _encode_state(EXT, attempt_id="x" * 500)
    assert len(_decode_state(state)["aid"]) == 40


# ── capture ──


def _capture_for(state, stage="authorize", fields=None):
    with patch("routers.auth.POSTHOG_API_KEY", "phc_test"), \
         patch("routers.auth.posthog.capture") as cap:
        _track_ms_auth_failed(state, stage, fields or {"error": "access_denied"})
    return cap


def test_capture_uses_the_attempt_id_as_identity():
    cap = _capture_for(_encode_state(EXT, attempt_id="attempt-77"))

    cap.assert_called_once()
    kwargs = cap.call_args.kwargs
    assert kwargs["distinct_id"] == "attempt-77"
    assert kwargs["event"] == "ms_auth_failed"
    assert kwargs["properties"]["install_source"] == "chrome"
    assert kwargs["properties"]["stage"] == "authorize"


def test_capture_falls_back_when_the_client_sent_no_attempt_id():
    cap = _capture_for(_encode_state(EXT))

    kwargs = cap.call_args.kwargs
    assert kwargs["distinct_id"] == "anonymous_auth_failure"
    assert kwargs["properties"]["attempt_id"] is None


def test_capture_survives_a_corrupt_state():
    """Microsoft echoes state verbatim; a mangled one must not 500 the page."""
    cap = _capture_for("not-valid-base64!!")

    cap.assert_called_once()
    assert cap.call_args.kwargs["properties"]["install_source"] == "other"


def test_capture_is_skipped_without_a_posthog_key():
    with patch("routers.auth.POSTHOG_API_KEY", ""), \
         patch("routers.auth.posthog.capture") as cap:
        _track_ms_auth_failed(_encode_state(EXT), "authorize", {"error": "x"})
    cap.assert_not_called()


def test_capture_never_raises_into_the_request():
    """Telemetry must not be able to break a user's sign-in page."""
    with patch("routers.auth.POSTHOG_API_KEY", "phc_test"), \
         patch("routers.auth.posthog.capture", side_effect=RuntimeError("boom")):
        _track_ms_auth_failed(_encode_state(EXT), "authorize", {"error": "x"})


# ── endpoint wiring ──


def test_callback_error_redirect_is_reported(client, fake_db):
    state = _encode_state(EXT, attempt_id="from-endpoint")
    with patch("routers.auth.POSTHOG_API_KEY", "phc_test"), \
         patch("routers.auth.posthog.capture") as cap:
        resp = client.get(
            "/auth/callback",
            params={
                "error": "access_denied",
                "error_description": "AADSTS65004: User declined to consent.",
                "state": state,
            },
        )

    # The user-facing error page (400), never a 500 — telemetry must not
    # change what the person in the auth window sees.
    assert resp.status_code == 400
    assert "Authentication Failed" in resp.text

    events = [c.kwargs for c in cap.call_args_list if c.kwargs.get("event") == "ms_auth_failed"]
    assert len(events) == 1
    props = events[0]["properties"]
    assert props["aadsts"] == "AADSTS65004"
    assert props["meaning"] == "user_declined_consent"
    assert props["stage"] == "authorize"


def test_login_redirect_accepts_and_forwards_a_valid_attempt_id(client, fake_db):
    resp = client.get(
        "/auth/login",
        params={"ext": EXT, "aid": "abc123DEF456"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 307)

    import urllib.parse

    qs = urllib.parse.parse_qs(urllib.parse.urlparse(resp.headers["location"]).query)
    assert _decode_state(qs["state"][0])["aid"] == "abc123DEF456"


@pytest.mark.parametrize("bad", ["short", "has spaces", "a" * 60, "semi;colon", "<script>"])
def test_login_redirect_rejects_a_malformed_attempt_id(client, fake_db, bad):
    """The id lands in an OAuth state we echo back — only opaque tokens."""
    resp = client.get(
        "/auth/login",
        params={"ext": EXT, "aid": bad},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 307)

    import urllib.parse

    qs = urllib.parse.parse_qs(urllib.parse.urlparse(resp.headers["location"]).query)
    assert "aid" not in _decode_state(qs["state"][0])
