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
    """A future entry too long for the cap would truncate mid-word in both
    PostHog and the user's popup, with a green suite.

    What "survives" means changed on 2026-08-08. The fragment used to be
    diagnostic-only — Chromium discarded it, because the page returned 400 —
    so carrying the raw meaning ("admin consent required") was free. Serving
    the page as 200 made it the string every shipped client shows the user
    verbatim, so a mapped code now carries an INSTRUCTION with the code in
    parentheses. Unmapped codes keep the old shape. Both must fit and stay
    unique.
    """
    import urllib.parse

    from routers.auth import (
        _AADSTS_MEANINGS,
        _SETTLE_MESSAGES,
        _classify_ms_error,
        _ms_settle_code,
    )

    seen = {}
    for code, meaning in _AADSTS_MEANINGS.items():
        classified = _classify_ms_error("access_denied", f"{code}: some detail.")
        frag = _settle_fragment(_ms_settle_code(classified))
        assert len(frag) <= 64, f"{code} fragment is {len(frag)} chars"
        assert code in frag, f"{code} lost its code in {frag!r}"
        expected = _SETTLE_MESSAGES.get(meaning, meaning.replace("_", " "))
        assert expected in frag, (
            f"{code} truncated: {frag!r} — shorten its entry or raise the cap"
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


def test_deeply_nested_state_is_our_page_not_a_500(client):
    """The same thing end-to-end through the real endpoint."""
    resp = client.get(
        "/auth/callback",
        params={"error": "access_denied", "state": _nested_state(20000)},
    )
    assert resp.status_code == 200
    assert "Authentication Failed" in resp.text, "our page, not a stack trace"
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

    assert resp.status_code == 200, "must render our page, not a bare 500"
    assert "chromiumapp.org" in resp.text, "the popup must still be settled"
    assert "ISP block page" not in resp.text, "never echo a third party's HTML"


def test_null_error_description_does_not_crash_the_page(client):
    """`error_description: null` reached _error_page as None and crashed on
    .replace — again a 500 with no settle script."""
    from routers.auth import _error_page

    resp = _error_page(None, state=_encode_state(CHROME_EXT), fragment="x failed")
    assert resp.status_code == 200
    assert "chromiumapp.org" in resp.body.decode("utf-8")


# ── the error page ──


def _callback_error(client, state):
    params = {
        "error": "access_denied",
        "error_description": "AADSTS90094: The grant requires admin permission.",
    }
    if state is not None:
        params["state"] = state
    # A real callback arrives at one of our two public domains — Microsoft
    # redirects to the registered redirect_uri, never to TestClient's default
    # 'testserver'. The host has to be realistic since 2026-08-10, when the
    # telemetry capture sites started refusing hosts that cannot exist in
    # production (see test_telemetry_host_guard.py for why).
    return client.get(
        "/auth/callback", params=params, headers={"host": "api.getoutmass.com"}
    )


def test_error_page_is_served_as_200(client):
    """A 4xx here silently destroys everything the rest of this file tests.

    Chromium aborts a launchWebAuthFlow navigation whose response code is
    >= 400 and surfaces it as "Authorization page could not be loaded". So
    with a 400 the popup was torn down BEFORE the settle script could run,
    the real AADSTS reason never reached the client, and the generic
    load-failure text matched the extension's `auth_page_failed` branch —
    which fires a one-shot auto-retry. A user who had just declined consent
    got a fresh consent screen ~3 seconds later; one fought that loop six
    times over 75 minutes on 2026-08-07 and left.

    This is exactly the kind of line a later tidy-up ("error pages should
    return an error status") would flip back, so it is pinned on its own
    rather than only as a side assertion of the redirect tests.
    """
    resp = _callback_error(client, _encode_state(CHROME_EXT))
    assert resp.status_code == 200
    assert "Authentication Failed" in resp.text


def test_error_page_settles_toward_the_owning_extension(client):
    state = _encode_state(EDGE_EXT)
    resp = _callback_error(client, state)
    assert resp.status_code == 200
    assert f"https://{EDGE_EXT}.chromiumapp.org/auth#" in resp.text, (
        "the page must redirect to the EDGE extension's chromiumapp URL — "
        "settling toward the wrong browser's id hangs the popup on an "
        "unresolvable address"
    )
    assert "IT+admin+must+approve" in resp.text, (
        "the fragment must LEAD with the actionable sentence: every shipped "
        "client renders it verbatim to the user with no way to localize it"
    )
    assert "AADSTS90094" in resp.text, (
        "and must still carry the code, in parentheses — it is the telemetry "
        "grouping key and what support greps for"
    )
    assert "5000" in resp.text, "the message must dwell ~5s before settling"
    assert "return to OutMass" in resp.text


def test_error_page_without_state_keeps_the_old_behaviour(client):
    resp = _callback_error(client, state=None)
    assert resp.status_code == 200
    assert "chromiumapp.org" not in resp.text
    assert "close this window" in resp.text


def test_error_page_with_forged_state_never_redirects(client):
    """state is unsigned base64 JSON anyone can mint. An unknown extension id
    must not become a redirect target — that is an open redirect into a
    foreign extension's origin."""
    forged = _encode_state("a" * 32)
    resp = _callback_error(client, forged)
    assert resp.status_code == 200
    assert "chromiumapp.org" not in resp.text


def test_aadsts50011_is_classified():
    out = auth_module._classify_ms_error(
        "invalid_request",
        "AADSTS50011: The redirect URI specified in the request does not match.",
    )
    assert out["meaning"] == "redirect_uri_not_registered"


# ── the settle fragment is the message, so it has to be deliverable ──


def test_settle_messages_are_deliverable():
    """Four constraints, all of them learned the hard way.

    The fragment is not a diagnostic string: every client in the field
    renders it verbatim to the user. 0.1.26 and 0.1.27 both resolve the
    flight with `{ error: errorMsg }` and no errorCode, so nothing downstream
    can turn it into localized guidance, and it doubles as the PostHog
    grouping key.
    """
    import re

    from routers.auth import _SETTLE_MESSAGES, _settle_fragment

    for meaning, message in _SETTLE_MESSAGES.items():
        assert len(message) <= 48, (
            f"{meaning}: {len(message)} chars — the AADSTS code is appended in "
            "parentheses and the longest one costs 16, so anything over 48 "
            "loses the code or gets truncated mid-word at the client's 64"
        )
        assert _settle_fragment(message) == message, (
            f"{meaning}: the sanitizer rewrites this. Apostrophes are the "
            "usual cause — they are stripped, turning organization's into "
            "organizations mid-word"
        )
        assert "$" not in message, (
            f"{meaning}: the sidebar i18n substitution reads $ as a "
            "placeholder marker"
        )
        assert re.search(r"[a-z]", message), f"{meaning}: not a sentence"


def test_known_aadsts_codes_say_what_to_do():
    """AADSTS90094 means the tenant needs an admin to approve the app. The
    user cannot act on that string; they can act on the sentence."""
    from routers.auth import _classify_ms_error, _ms_settle_code

    cases = {
        "AADSTS90094": "Your IT admin must approve OutMass first",
        "AADSTS65004": "Permission was declined on the Microsoft screen",
        "AADSTS50105": "Your IT admin has not given you access",
        "AADSTS53003": "Your organization blocked this sign-in",
    }
    for code, expected in cases.items():
        classified = _classify_ms_error("access_denied", f"{code}: something happened")
        out = _ms_settle_code(classified)
        assert len(out) <= 64, f"{code} -> {len(out)} chars"
        assert out == f"{expected} ({code})", (
            f"{code} -> {out!r}. The instruction leads because a user cannot "
            "act on a code and this string is shown to them verbatim; the "
            "code trails because it is the grouping key support greps for"
        )


def test_an_unmapped_aadsts_code_still_degrades_safely():
    """A code we have never seen must not produce an empty or raw message."""
    from routers.auth import _classify_ms_error, _ms_settle_code

    out = _ms_settle_code(
        _classify_ms_error("access_denied", "AADSTS999999: brand new failure")
    )
    assert out and len(out) <= 64
    assert "brand new failure" not in out, "never echo Microsoft free text"


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
