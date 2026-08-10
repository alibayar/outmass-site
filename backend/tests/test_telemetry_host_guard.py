"""Production telemetry must refuse events from hosts that cannot exist.

conftest.py blanks POSTHOG_API_KEY before importing anything, so `pytest`
cannot emit. But that guard lived entirely in the TEST HARNESS, and on
2026-08-06 a one-off script that drove the app through TestClient outside
pytest — an adversarial review probing the settle-fragment sanitizer —
inherited a real key from a developer's .env and wrote 19 ms_auth_failed
events straight into the live project.

Their payloads were the probe strings: `<script>alert(1)</script>`, `😀💣`,
`中文テスト한글`, a bidi override, a fake support phone number. They sat in
the production sign-in funnel for four days looking like real users failing
to sign in, and were only spotted on 08-10 while trying to answer "why did
today's new users not get in".

These tests pin the guard in the CODE, so it protects any caller rather than
only the ones that remember the fixture.
"""
import pytest


NON_PRODUCTION = ["testserver", "localhost", "127.0.0.1", "0.0.0.0", "::1"]
REAL = ["api.getoutmass.com", "outmass-production.up.railway.app", "getoutmass.com"]


@pytest.mark.parametrize("host", NON_PRODUCTION)
def test_non_production_hosts_are_refused(host):
    from routers import auth

    assert auth._is_reportable_host(host) is False


@pytest.mark.parametrize("host", REAL)
def test_real_hosts_are_reported(host):
    from routers import auth

    assert auth._is_reportable_host(host) is True


def test_unknown_host_is_reported_not_dropped():
    """An exact denylist, deliberately. A hostname we have never seen — a new
    custom domain, a proxy rewriting the header — must still be reported: a
    dropped event is a real user we can no longer account for, which is the
    opposite of what this guard is for."""
    from routers import auth

    assert auth._is_reportable_host("something-new.example.com") is True
    assert auth._is_reportable_host("") is True


def test_every_auth_capture_site_is_guarded():
    """Three server-side events make up the sign-in funnel — ms_auth_failed,
    ms_auth_window_opened and login. All three carry a host, so all three
    must consult the guard. A new capture site added without it would
    reopen exactly the hole this closes.
    """
    import inspect

    from routers import auth

    src = inspect.getsource(auth)
    capture_calls = src.count("posthog.capture(")
    guards = src.count("_is_reportable_host(")
    # One definition + one use per capture site.
    assert capture_calls == 3, (
        f"auth.py has {capture_calls} posthog.capture calls; if a fourth was "
        "added it needs a host guard and this count updating"
    )
    assert guards >= capture_calls + 1, (
        "a posthog.capture in auth.py is not behind _is_reportable_host"
    )


def test_track_ms_auth_failed_drops_a_testserver_event(monkeypatch):
    """End to end through the real function: a TestClient-shaped host emits
    nothing even when a key is present."""
    from routers import auth

    captured = []
    monkeypatch.setattr(auth, "POSTHOG_API_KEY", "phc_fake_but_present")
    monkeypatch.setattr(
        auth.posthog, "capture", lambda **kw: captured.append(kw)
    )

    auth._track_ms_auth_failed(None, "authorize", {"error": "access_denied"},
                               host="testserver")
    assert captured == []

    auth._track_ms_auth_failed(None, "authorize", {"error": "access_denied"},
                               host="api.getoutmass.com")
    assert len(captured) == 1
    assert captured[0]["event"] == "ms_auth_failed"
