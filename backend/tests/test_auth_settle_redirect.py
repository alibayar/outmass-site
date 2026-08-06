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


# ── PII must never reach the fragment ──
#
# Caught by the 2026-08-06 pre-deploy adversarial review, both skeptics
# confirming: the first version derived the fragment from the page message —
# Microsoft's error_description — and the character sanitizer deleted the '@'
# in "User account 'victim@customer.com'" while keeping the parts, shipping
# 'victimcustomer.com' into PostHog and every client within the 64-char cap.
# The repo already had this invariant for the TELEMETRY pipe
# (test_oauth_failure_telemetry.py); the settle redirect was a second pipe
# without the filter.

_LEAKY_DESCRIPTION = (
    "AADSTS50020: User account 'victim@customer.com' from identity provider "
    "'live.com' does not exist in tenant 'Contoso Ltd'."
)


def _settle_url_of(html: str) -> str:
    import re as _re

    m = _re.search(r'location\.replace\("([^"]+)"\)', html)
    assert m, "no settle redirect found in the page"
    return m.group(1)


def test_fragment_carries_the_class_never_the_user(client):
    resp = client.get(
        "/auth/callback",
        params={
            "error": "access_denied",
            "error_description": _LEAKY_DESCRIPTION,
            "state": _encode_state(CHROME_EXT),
        },
    )
    url = _settle_url_of(resp.text)
    assert "victim" not in url and "customer" not in url and "Contoso" not in url, (
        "the settle fragment leaked the user's address or tenant — it must be "
        "built from the classifier, never from the description"
    )
    assert "AADSTS50020" in url, "the class code is the whole point — keep it"


def test_fragment_is_identical_across_users(client):
    """One distinct fragment per user would shatter the PostHog grouping the
    property exists for — tenant-mismatch failures would become uncountable."""
    urls = []
    for who in ("alice@corp-a.com", "bob@corp-b.org"):
        resp = client.get(
            "/auth/callback",
            params={
                "error": "access_denied",
                "error_description": f"AADSTS50020: User account '{who}' does not exist in tenant 'X'.",
                "state": _encode_state(CHROME_EXT),
            },
        )
        urls.append(_settle_url_of(resp.text))
    assert urls[0] == urls[1]


def test_page_message_may_still_show_the_description(client):
    """The page renders only in the user's own window — their own address is
    fine THERE. The separation is message→page, class→fragment."""
    resp = client.get(
        "/auth/callback",
        params={
            "error": "access_denied",
            "error_description": _LEAKY_DESCRIPTION,
            "state": _encode_state(CHROME_EXT),
        },
    )
    assert "victim@customer.com" in resp.text


def test_forgotten_fragment_degrades_to_generic_not_to_message():
    """Structural safety: a future call site that passes only the message must
    produce the generic sentence, never a derivative of the message."""
    from routers.auth import _error_page

    resp = _error_page(_LEAKY_DESCRIPTION, state=_encode_state(CHROME_EXT))
    body = resp.body.decode("utf-8")
    url = _settle_url_of(body)
    assert "victim" not in url and "AADSTS50020" not in url
    assert "Sign-in+failed" in url


def test_the_error_query_param_cannot_smuggle_free_text(client):
    """The `error` param is attacker/Microsoft-controlled free text and feeds
    _ms_settle_code's fallback. It is echoed ONLY if it appears in the RFC 6749
    vocabulary; anything else collapses to the generic sentence.

    Caught by the 2026-08-06 post-fix review: the first version of the PII fix
    echoed this param verbatim, so routing the same tenant sentence through
    `error` instead of `error_description` walked it straight past the fix.
    """
    resp = client.get(
        "/auth/callback",
        params={
            "error": "User bob@corp-internal.com of Contoso Ltd was blocked",
            "error_description": "no aadsts code here",
            "state": _encode_state(CHROME_EXT),
        },
    )
    url = _settle_url_of(resp.text)
    assert "bob" not in url and "corp-internal" not in url and "Contoso" not in url
    assert "Sign-in+failed%2C+please+try+again" in url

    ok = client.get(
        "/auth/callback",
        params={
            "error": "access_denied",
            "error_description": "no aadsts code here",
            "state": _encode_state(CHROME_EXT),
        },
    )
    assert "access+denied" in _settle_url_of(ok.text), (
        "a real RFC 6749 code is worth keeping — it is the only class signal "
        "when Microsoft sends no AADSTS number"
    )


# ── every call site must keep passing a fragment ──


def test_every_error_page_call_site_passes_a_fragment():
    """The PII guard is one-directional: a forgotten fragment cannot LEAK, but
    nothing stopped a call site from silently dropping one — mutation testing
    showed 6 of 8 sites could be stripped with the whole suite still green.
    The failure is invisible in production too: that class of error just
    collapses into the generic sentence and its PostHog grouping disappears,
    which is the very diagnosis this release was built to enable.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "routers" / "auth.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "_error_page"):
            continue
        if not any(kw.arg == "fragment" for kw in node.keywords):
            missing.append(node.lineno)

    assert not missing, (
        f"_error_page called without fragment= at auth.py lines {missing} — "
        "every failure class needs its own stable settle string"
    )


def test_every_aadsts_meaning_survives_the_round_trip():
    """A future entry with a long meaning would truncate mid-word in both
    PostHog and the user's popup, with a green suite."""
    import urllib.parse

    from routers.auth import _AADSTS_MEANINGS, _classify_ms_error, _ms_settle_code

    seen = {}
    for code, meaning in _AADSTS_MEANINGS.items():
        classified = _classify_ms_error("access_denied", f"{code}: some detail.")
        frag = _settle_fragment(_ms_settle_code(classified))
        assert len(frag) <= 64, f"{code} fragment is {len(frag)} chars"
        assert code in frag, f"{code} lost its code in {frag!r}"
        assert meaning.replace("_", " ") in frag, (
            f"{code} meaning truncated: {frag!r} — shorten the meaning or "
            "raise the cap"
        )
        # Survives URL encode/decode unchanged (the client re-parses it).
        assert urllib.parse.parse_qs(
            urllib.parse.urlencode({"error": frag})
        )["error"][0] == frag
        assert frag not in seen, f"{code} collides with {seen.get(frag)}"
        seen[frag] = code


# ── crafted state must never become a 500 ──


def _nested_state(depth):
    import base64 as _b64

    payload = ("[" * depth) + ("]" * depth)
    return _b64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def test_recursion_error_is_swallowed_by_decode_state():
    """json.loads raises RecursionError on deep nesting, and RecursionError is
    NOT a ValueError — it escaped _decode_state's old except tuple, escaped
    _error_page, and became an unauthenticated 500 with no settle script.

    The recursion limit is lowered here so the test asserts the CONTRACT ("a
    bad state is no state") rather than one interpreter's threshold — the
    depth that trips json varies by Python build (~3k on 3.12, ~17k on 3.14),
    which is exactly how a version-pinned depth would rot into a test that
    passes without exercising anything.
    """
    import sys

    from routers.auth import _decode_state

    original = sys.getrecursionlimit()
    sys.setrecursionlimit(120)
    try:
        assert _decode_state(_nested_state(400)) is None
    finally:
        sys.setrecursionlimit(original)


def test_deeply_nested_state_is_a_400_not_a_500(client):
    """The same thing end-to-end through the real endpoint."""
    resp = client.get(
        "/auth/callback",
        params={"error": "access_denied", "state": _nested_state(20000)},
    )
    assert resp.status_code == 400
    assert "chromiumapp.org" not in resp.text, "unparseable state must not redirect"


def test_non_string_ext_never_raises():
    """`ext` is attacker-minted JSON and can be a list or dict.

    Asserted against a SET allowlist on purpose: today's list tolerates an
    unhashable value because `in` falls back to ==, so a list-based test would
    pass with or without the isinstance guard. The day someone tidies
    ALLOWED_EXTENSION_IDS into a set — the natural change for a
    membership-only lookup — an unguarded membership test turns 67 bytes of
    crafted state into a 500.
    """
    import base64 as _b64
    import json as _json
    from unittest.mock import patch

    from routers import auth as auth_module

    with patch.object(auth_module, "ALLOWED_EXTENSION_IDS", {CHROME_EXT, EDGE_EXT}):
        for bad in ([1, 2], {"a": 1}, 5, True, None):
            raw = _json.dumps({"ext": bad, "n": "x"}).encode()
            state = _b64.urlsafe_b64encode(raw).decode().rstrip("=")
            assert auth_module._decode_state_ext(state) is None
        # and the good path still resolves
        good = _b64.urlsafe_b64encode(
            _json.dumps({"ext": CHROME_EXT, "n": "x"}).encode()
        ).decode().rstrip("=")
        assert auth_module._decode_state_ext(good) == CHROME_EXT


# ── a crash before the page is a hung popup ──


def test_non_json_token_response_still_renders_a_settling_page(client):
    """An ISP block page returned with a 4xx/5xx used to raise on .json()
    BEFORE any HTML was produced — 500, no settle script, popup hangs. That is
    the same network-filtering scenario this whole feature line diagnoses.

    AZURE_CLIENT_SECRET must be patched truthy: it is empty in the test env,
    so without this the request returns at the misconfig branch and the test
    passes having never reached the token exchange (it did exactly that when
    first written — mutation testing caught it).
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    blocked = MagicMock()
    blocked.status_code = 502
    blocked.content = b"<html>ISP block page</html>"
    blocked.text = "<html>ISP block page</html>"
    blocked.json.side_effect = ValueError("not json")

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=blocked)))
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch.object(auth_module, "AZURE_CLIENT_SECRET", "test-secret"), \
         patch("routers.auth.httpx.AsyncClient", return_value=ctx):
        resp = client.get(
            "/auth/callback",
            params={"code": "abc", "state": _encode_state(CHROME_EXT)},
        )

    assert resp.status_code == 400, "must render our page, not a bare 500"
    assert "chromiumapp.org" in resp.text, "the popup must still be settled"
    assert "ISP block page" not in resp.text, "never echo a third party's HTML"


def test_null_error_description_does_not_crash_the_page(client):
    """`error_description: null` reached _error_page as None and crashed on
    .replace — again a 500 with no settle script."""
    from routers.auth import _error_page

    resp = _error_page(None, state=_encode_state(CHROME_EXT), fragment="x failed")
    assert resp.status_code == 400
    assert "chromiumapp.org" in resp.body.decode("utf-8")


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
