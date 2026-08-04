"""Uninstall feedback carries the funnel stage the install reached.

Chrome only lets the extension register a STATIC uninstall URL, ahead of time,
so the extension re-points it at the furthest stage the user reached. This
endpoint is where that lands.

The whole feature is an observability feature, which means every way it can
break is invisible: a stage the backend doesn't recognise, a ladder that drifts
between the JS and the Python, a crafted query string writing whatever it likes
into our Telegram alerts. None of those would produce a single symptom in
production — the extension keeps working and the reports just quietly get less
useful, which is exactly the failure mode this feature exists to fight.
"""
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import main


REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYTICS_JS = REPO_ROOT / "extension" / "analytics.js"


# ── The stage cleaner ──


def test_known_stage_passes_through():
    assert main._clean_stage("signin_clicked") == "signin_clicked"
    assert main._clean_stage("  sent  ") == "sent"


def test_absent_stage_is_unknown_not_invalid():
    """Every install that predates this field reports no stage at all.

    If those were filed as 'invalid' the breakdown would look like we were
    under attack for the first weeks after rollout.
    """
    assert main._clean_stage(None) == "unknown"
    assert main._clean_stage("") == "unknown"
    assert main._clean_stage("   ") == "unknown"


def test_made_up_stage_is_rejected():
    assert main._clean_stage("emperor_of_mars") == "invalid"
    assert main._clean_stage("SENT") == "invalid"  # ladder is lowercase


def test_crafted_stage_cannot_inject_into_alerts():
    """The endpoint is unauthenticated and the value comes from a query string
    anyone can edit. Nothing off the ladder may reach the alert body."""
    hostile = "sent\n\n💰 PAYMENT RECEIVED $9999 — https://evil.example"
    assert main._clean_stage(hostile) == "invalid"


# ── Ladder parity with the extension ──


def test_python_ladder_matches_the_javascript_ladder():
    """The two lists are maintained in different languages, in different
    directories, by different halves of the release process.

    If someone adds a stage to analytics.js and not here, every user who
    reaches it is filed as 'invalid' — the data silently degrades while both
    sides look correct in isolation.
    """
    src = ANALYTICS_JS.read_text(encoding="utf-8")
    match = re.search(r"_PH_STAGE_LADDER\s*=\s*\[(.*?)\]", src, re.S)
    assert match, "could not find _PH_STAGE_LADDER in extension/analytics.js"
    js_stages = set(re.findall(r'"([a-z_]+)"', match.group(1)))

    assert js_stages, "parsed an empty ladder — the regex above needs updating"
    assert js_stages == set(main._UNINSTALL_STAGES), (
        "stage ladder drifted between extension/analytics.js and main.py: "
        f"js-only={sorted(js_stages - set(main._UNINSTALL_STAGES))} "
        f"py-only={sorted(set(main._UNINSTALL_STAGES) - js_stages)}"
    )


def test_uninstall_page_forwards_the_stage_params():
    """The page is the only thing between the URL and this endpoint.

    It was shipping for months sending reason/details only; if the body keys
    ever stop matching the model, FastAPI silently defaults them to None and
    every uninstall reads 'unknown'.
    """
    page = (REPO_ROOT / "docs" / "uninstall.html").read_text(encoding="utf-8")
    assert 'params.get("stage")' in page, "uninstall page no longer reads ?stage"
    assert "stage: stage" in page, "uninstall page no longer POSTs the stage"
    assert "version: extVersion" in page, "uninstall page no longer POSTs the version"


# ── The endpoint ──


def _capture_props(client, payload):
    with patch.object(main, "POSTHOG_API_KEY", "ph-test"), \
         patch.object(main, "posthog") as ph:
        resp = client.post("/api/uninstall-feedback", json=payload)
    assert resp.status_code == 200
    assert ph.capture.called, "uninstall feedback did not reach PostHog"
    return ph.capture.call_args.kwargs["properties"]


def test_stage_and_version_reach_posthog(client):
    props = _capture_props(
        client,
        {"reason": "bugs", "details": "", "stage": "signin_clicked", "version": "0.1.28"},
    )
    assert props["stage"] == "signin_clicked"
    assert props["extension_version"] == "0.1.28"


def test_missing_version_is_labelled_not_blank(client):
    """An empty string in a PostHog breakdown renders as a nameless bucket."""
    props = _capture_props(client, {"reason": "bugs", "stage": "sent"})
    assert props["extension_version"] == "unknown"


def test_stage_appears_in_the_telegram_alert(client):
    """The alert is how Ali sees churn in real time. 'bugs' means something
    very different at signin_clicked than at sent, and the free-text box
    usually says nothing."""
    with patch.object(main, "TELEGRAM_BOT_TOKEN", "tok"), \
         patch.object(main, "TELEGRAM_CHAT_ID", "chat"), \
         patch.object(main.httpx, "post") as post:
        post.return_value = MagicMock(status_code=200)
        resp = client.post(
            "/api/uninstall-feedback",
            json={"reason": "bugs", "stage": "signin_clicked", "version": "0.1.28"},
        )

    assert resp.status_code == 200
    text = post.call_args.kwargs["data"]["text"]
    assert "signin_clicked" in text
    assert "0.1.28" in text


def test_stage_alone_is_not_enough_to_report(client):
    """A stage with no reason and no details is a page load, not feedback.

    Without this the endpoint would emit a churn event for anyone who merely
    opened the page — including us, testing it.
    """
    with patch.object(main, "POSTHOG_API_KEY", "ph-test"), \
         patch.object(main, "posthog") as ph:
        resp = client.post(
            "/api/uninstall-feedback",
            json={"reason": "", "details": "", "stage": "sent", "version": "0.1.28"},
        )
    assert resp.json()["status"] == "empty"
    assert not ph.capture.called


def test_legacy_payload_without_stage_still_accepted(client):
    """Already-installed extensions POST the old three-field body for weeks
    after this ships. They must not start 422-ing."""
    props = _capture_props(client, {"reason": "too_expensive", "user_agent": "Chrome"})
    assert props["stage"] == "unknown"

