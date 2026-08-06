"""The auth error page must settle the popup, and every server auth event
must say which domain served it.

Both born from the 2026-08-05 Vietnam investigation:

- The error page used to HOLD the auth popup open (launchWebAuthFlow only
  settles on a chromiumapp.org redirect or a closed window). Users parked it,
  the single-flight guard made later Sign-in clicks silently join the dead
  flight, and Chrome filed the eventual close as "user did not approve" —
  burying the AADSTS reason the page was displaying. Now the page redirects
  itself to the owning extension's chromiumapp.org URL after 9s, with the
  error in the FRAGMENT — the one place the frozen 0.1.26 parser looks
  (u.hash → URLSearchParams → params.get("error") → its backend_error path).

- We run one backend behind two domains and some networks filter one of
  them. Which door served a given sign-in was answerable only by Ali reading
  Railway log screenshots; now it is a property on ms_auth_window_opened,
  ms_auth_failed and login.
"""
from unittest.mock import patch

from routers import auth as auth_module
from routers.auth import _encode_state, _settle_fragment

CHROME_EXT = "adcfddainnkjomddlappnnbeomhlcbmm"
EDGE_EXT = "nfgnhhdeninjmnpfbhnggknimhejbelc"


# ── the settle fragment ──


def test_fragment_is_short_ascii_and_dollar_free():
    raw = "AADSTS90094: The <b>grant</b> requires admin permission & $PLACEHOLDER$ tricks"
    out = _settle_fragment(raw)
    assert len(out) <= 64
    assert "$" not in out, "the sidebar's i18n substitution treats $ as a marker"
    assert "<" not in out and "&" not in out
    assert out.startswith("AADSTS90094"), "the AADSTS code must survive — it is the telemetry key"


def test_fragment_never_comes_back_empty():
    assert _settle_fragment("") == "Sign-in failed, please try again"
    assert _settle_fragment("<>&$") == "Sign-in failed, please try again"


# ── the error page ──


def _callback_error(client, state):
    params = {
        "error": "access_denied",
        "error_description": "AADSTS90094: The grant requires admin permission.",
    }
    if state is not None:
        params["state"] = state
    return client.get("/auth/callback", params=params)


def test_error_page_settles_toward_the_owning_extension(client):
    state = _encode_state(EDGE_EXT)
    resp = _callback_error(client, state)
    assert resp.status_code == 400
    assert f"https://{EDGE_EXT}.chromiumapp.org/auth#" in resp.text, (
        "the page must redirect to the EDGE extension's chromiumapp URL — "
        "settling toward the wrong browser's id hangs the popup on an "
        "unresolvable address"
    )
    assert "error=AADSTS90094" in resp.text
    assert "9000" in resp.text, "the message must stay readable ~9s before settling"
    assert "return to OutMass" in resp.text


def test_error_page_without_state_keeps_the_old_behaviour(client):
    resp = _callback_error(client, state=None)
    assert resp.status_code == 400
    assert "chromiumapp.org" not in resp.text
    assert "close this window" in resp.text


def test_error_page_with_forged_state_never_redirects(client):
    """state is unsigned base64 JSON anyone can mint. An unknown extension id
    must not become a redirect target — that is an open redirect into a
    foreign extension's origin."""
    forged = _encode_state("a" * 32)
    resp = _callback_error(client, forged)
    assert resp.status_code == 400
    assert "chromiumapp.org" not in resp.text


def test_aadsts50011_is_classified():
    out = auth_module._classify_ms_error(
        "invalid_request",
        "AADSTS50011: The redirect URI specified in the request does not match.",
    )
    assert out["meaning"] == "redirect_uri_not_registered"


# ── host telemetry ──


def test_window_opened_records_which_domain_served_it(client):
    with patch.object(auth_module, "POSTHOG_API_KEY", "ph-test"), \
         patch.object(auth_module, "posthog") as ph:
        resp = client.get(
            "/auth/login",
            params={"ext": EDGE_EXT, "aid": "abc123def456"},
            headers={"host": "api.getoutmass.com"},
            follow_redirects=False,
        )
    assert resp.status_code == 307
    assert ph.capture.called
    props = ph.capture.call_args.kwargs["properties"]
    assert props["host"] == "api.getoutmass.com"


def test_host_is_normalized_not_trusted(client):
    """Port stripped, case folded, forwarded-chain reduced to its first hop —
    the property is for grouping, and 'Api.GetOutMass.com:443' fragmenting a
    breakdown would hide the very cluster it exists to reveal."""
    with patch.object(auth_module, "POSTHOG_API_KEY", "ph-test"), \
         patch.object(auth_module, "posthog") as ph:
        client.get(
            "/auth/login",
            params={"ext": EDGE_EXT},
            headers={"x-forwarded-host": "Api.GetOutMass.com:443, proxy.internal"},
            follow_redirects=False,
        )
    props = ph.capture.call_args.kwargs["properties"]
    assert props["host"] == "api.getoutmass.com"


def test_ms_auth_failed_carries_the_callback_host(client):
    with patch.object(auth_module, "POSTHOG_API_KEY", "ph-test"), \
         patch.object(auth_module, "posthog") as ph:
        _callback_error(client, _encode_state(CHROME_EXT))
    assert ph.capture.called
    kwargs = ph.capture.call_args.kwargs
    assert kwargs["event"] == "ms_auth_failed"
    assert "host" in kwargs["properties"]
    assert kwargs["properties"]["host"] != ""
