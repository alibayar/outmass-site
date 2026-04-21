"""Multi-extension OAuth routing tests.

The extension passes `?ext={chrome.runtime.id}` to /auth/login. We echo
the ID through Microsoft via the OAuth `state` parameter, then route the
final chromiumapp.org redirect back to that extension — but only if the
ID is on the allowlist (otherwise it's an open-redirect vector).
"""
from unittest.mock import patch

import pytest

from routers.auth import _decode_state_ext, _encode_state


STORE_ID = "adcfddainnkjomddlappnnbeomhlcbmm"
DEV_ID = "acdafphnihddolfhabbndfofheokckhl"
UNKNOWN_ID = "unknown_extension_id_1234567890ab"


# ── State codec round-trip ──


def test_state_round_trip_preserves_allowlisted_ext_id():
    """Encoded state decodes back to the same ext_id when allowlisted."""
    state = _encode_state(STORE_ID)
    decoded = _decode_state_ext(state)
    assert decoded == STORE_ID


def test_state_decode_rejects_unknown_extension_id():
    """An ext_id outside ALLOWED_EXTENSION_IDS must decode to None.

    This is the open-redirect guard — without it, a malicious page
    could call /auth/login?ext=attacker and harvest the OAuth JWT via
    attacker.chromiumapp.org.
    """
    state = _encode_state(UNKNOWN_ID)
    assert _decode_state_ext(state) is None


def test_state_decode_rejects_garbage():
    """Malformed / tampered state must decode to None, not raise."""
    for bad in ["", "not-base64!!!", "YWJj", None, "aGVsbG8gd29ybGQ="]:
        assert _decode_state_ext(bad) is None


def test_encoded_state_includes_csrf_nonce():
    """Two encodes of the same ext_id produce different strings (CSRF nonce)."""
    s1 = _encode_state(STORE_ID)
    s2 = _encode_state(STORE_ID)
    assert s1 != s2
    # Both still decode to the same ext_id
    assert _decode_state_ext(s1) == _decode_state_ext(s2) == STORE_ID


# ── /auth/login ── ext_id routing


def test_login_with_allowlisted_ext_encodes_it_into_state(client):
    """Calling /auth/login?ext=<allowed> must put it in the state param."""
    resp = client.get(f"/auth/login?ext={DEV_ID}", follow_redirects=False)
    assert resp.status_code in (302, 307)
    from urllib.parse import parse_qs, urlparse
    target = urlparse(resp.headers["location"])
    state = parse_qs(target.query)["state"][0]
    assert _decode_state_ext(state) == DEV_ID


def test_login_with_unknown_ext_falls_back_to_env_default(client):
    """Unknown ext falls through to AZURE_EXTENSION_ID — legacy safety.

    We don't 400 on unknown IDs because it would break backward compat
    for any client that passes a stale/mistyped ID. The callback
    separately re-validates against the allowlist, so falling through
    here just means the user lands on the default extension.
    """
    from config import AZURE_EXTENSION_ID

    resp = client.get(f"/auth/login?ext={UNKNOWN_ID}", follow_redirects=False)
    assert resp.status_code in (302, 307)
    from urllib.parse import parse_qs, urlparse
    target = urlparse(resp.headers["location"])
    state = parse_qs(target.query)["state"][0]
    assert _decode_state_ext(state) == AZURE_EXTENSION_ID


def test_login_without_ext_param_still_works(client):
    """Legacy clients that don't pass ?ext= must continue to function."""
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    # Location header points at login.microsoftonline.com with `state`
    from urllib.parse import parse_qs, urlparse
    target = urlparse(resp.headers["location"])
    assert target.netloc == "login.microsoftonline.com"
    qs = parse_qs(target.query)
    assert "state" in qs  # state is always set, even on legacy calls
