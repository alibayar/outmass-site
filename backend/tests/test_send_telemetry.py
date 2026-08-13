"""A send has to be visible wherever it happened.

Written 2026-08-13, after reading marketing@bellmed.com two ways at once and
getting two different customers. PostHog said: last send 2026-07-27, six
sign-ins since with nothing after them — a customer about to churn. Supabase
said: emails_sent_this_month 2243, climbing that same day — our heaviest user.
Supabase was right. `send_completed` is emitted by extension/sidebar.js and by
nothing else, so a campaign that sends itself while the panel is closed moved
the counter and left no trace.

These tests hold three things in place:

  * the choke point — instrumentation lives in increment_sent_count, the one
    function every send path already passes through, so the next send path
    someone writes is instrumented without them remembering to
  * the identity — the event must land on the SAME person as the login event
    or the sends are recorded against a stranger, which is the original bug
    wearing a different hat
  * the no-raise guarantee — this one is not defensive politeness, it is the
    difference between charging a customer's quota once and charging it twice
"""
import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from models import user as user_model
from utils import send_telemetry

BACKEND = Path(__file__).resolve().parents[1]
SOURCES = ["routers/campaigns.py", "workers/scheduled_worker.py",
           "workers/followup_worker.py"]


@pytest.fixture
def captured():
    """Every posthog.capture call, with a live API key so the guard passes."""
    calls = []
    with patch("config.POSTHOG_API_KEY", "phc_test"), \
         patch("posthog.capture", side_effect=lambda **kw: calls.append(kw)):
        yield calls


# ── What it reports ──


def test_a_send_is_reported_with_its_count_and_reason(captured):
    send_telemetry.report_emails_sent("u1", 25, "scheduled", "a@b.com")

    assert len(captured) == 1
    assert captured[0]["event"] == "emails_sent"
    assert captured[0]["properties"]["count"] == 25
    assert captured[0]["properties"]["reason"] == "scheduled"
    # Tells these apart from the panel's send_completed, which keeps its own
    # meaning: a human watched this go out.
    assert captured[0]["properties"]["surface"] == "server"


def test_the_event_lands_on_the_same_person_as_the_login(captured):
    """routers/auth.py captures `login` with the email as distinct_id. A user
    id here would open a second person and the sends would be invisible
    against the customer who made them — the original bug, one layer over."""
    send_telemetry.report_emails_sent("user-uuid", 10, "followup", "tony@x.com")

    assert captured[0]["distinct_id"] == "tony@x.com"
    assert captured[0]["properties"]["identified"] is True


def test_a_send_with_no_email_is_still_reported_and_says_so(captured):
    """A send we cannot attribute is worth more than a send we cannot see.
    `identified: False` makes the stranded event visible rather than a
    silently-wrong person count."""
    send_telemetry.report_emails_sent("user-uuid", 10, "followup", None)

    assert captured[0]["distinct_id"] == "user-uuid"
    assert captured[0]["properties"]["identified"] is False


def test_extra_properties_ride_along(captured):
    """The daily-cap continuation is the scheduled loop running again, so it
    is told apart by a property rather than by a reason of its own."""
    send_telemetry.report_emails_sent(
        "u1", 25, "scheduled", "a@b.com", {"daily_capped": True}
    )
    assert captured[0]["properties"]["daily_capped"] is True


# ── What it refuses to report ──


@pytest.mark.parametrize("count", [0, -5])
def test_a_zero_or_negative_charge_is_not_a_send(captured, count):
    send_telemetry.report_emails_sent("u1", count, "scheduled", "a@b.com")
    assert captured == []


def test_no_api_key_means_no_event():
    """The guard that keeps the test suite out of the live project.
    conftest.py blanks POSTHOG_API_KEY before importing anything, and the key
    is read at call time rather than import time so that blanking works."""
    calls = []
    with patch("config.POSTHOG_API_KEY", ""), \
         patch("posthog.capture", side_effect=lambda **kw: calls.append(kw)):
        send_telemetry.report_emails_sent("u1", 25, "scheduled", "a@b.com")
    assert calls == []


def test_an_unknown_reason_is_still_reported(captured):
    """A new send path must not be silent just because nobody updated the
    vocabulary. It is logged as unlabelled, not dropped."""
    send_telemetry.report_emails_sent("u1", 25, "teleportation", "a@b.com")

    assert len(captured) == 1
    assert captured[0]["properties"]["reason"] == "teleportation"


# ── The guarantee that protects a customer's quota ──


def test_telemetry_can_never_raise_into_a_send_loop():
    """Load-bearing, not defensive.

    Every caller wraps increment_sent_count in a try whose except deliberately
    leaves `quota_charged` unadvanced so an end-of-loop flush recharges it
    (workers/scheduled_worker.py). If telemetry raised AFTER the counter was
    written, that flush would charge the same emails to the customer a second
    time. So this must swallow everything, including the unthinkable.
    """
    for boom in (RuntimeError("posthog is down"),
                 ValueError("bad payload"),
                 OSError("network gone")):
        with patch("config.POSTHOG_API_KEY", "phc_test"), \
             patch("posthog.capture", side_effect=boom):
            send_telemetry.report_emails_sent("u1", 25, "scheduled", "a@b.com")


def test_cancellation_is_deliberately_NOT_swallowed():
    """The limit of the guarantee above, and it is a deliberate one.

    The catch is `except Exception`, not `except BaseException`, so
    CancelledError and KeyboardInterrupt still propagate. routers/campaigns.py
    runs the send-now path as an async background task and handles
    CancelledError explicitly — "swallowing cancellation would leave the event
    loop shutting down while this task claims to still be running". Telemetry
    must not quietly undo that.

    Written after the first version of the test asserted the opposite and
    would have argued someone into catching BaseException here.
    """
    import asyncio

    for escapes in (asyncio.CancelledError(), KeyboardInterrupt()):
        with patch("config.POSTHOG_API_KEY", "phc_test"), \
             patch("posthog.capture", side_effect=escapes):
            with pytest.raises(type(escapes)):
                send_telemetry.report_emails_sent("u1", 25, "scheduled", "a@b.com")


def test_the_counter_still_advances_when_telemetry_dies():
    """The same guarantee, one level up: increment_sent_count must return
    normally so the caller reaches `quota_charged = sent_count`."""
    with patch("models.user.get_db"), \
         patch("utils.send_telemetry.report_emails_sent",
               side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            # Proves the double is actually wired in — without this the next
            # assertion would pass on a function that never calls telemetry.
            user_model.send_telemetry.report_emails_sent("u", 1, "x")

    with patch("models.user.get_db"), \
         patch("utils.send_telemetry.report_emails_sent") as reporter:
        user_model.increment_sent_count("u1", 25, reason="scheduled")

    reporter.assert_called_once()


# ── The choke point, checked against the real source ──


def _increment_calls(source: str):
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "increment_sent_count"):
            yield node


def test_the_counter_reports_every_time_it_moves():
    """increment_sent_count must call the reporter. Parsed rather than
    trusted: this function is the single point the whole design rests on."""
    source = (BACKEND / "models" / "user.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef) and n.name == "increment_sent_count")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "report_emails_sent"]
    assert calls, "increment_sent_count no longer reports the send"


def test_every_send_path_says_why():
    """The reason is what makes the event answer a question. A call site
    without one still emits, so nothing goes dark — but it goes into the data
    unlabelled, and that is worth failing a build over while it is cheap."""
    unlabelled = []
    for rel in SOURCES:
        source = (BACKEND / rel).read_text(encoding="utf-8")
        for node in _increment_calls(source):
            if not any(k.arg == "reason" for k in node.keywords):
                unlabelled.append(f"{rel}:{node.lineno}")

    assert not unlabelled, (
        f"these send paths charge the quota without saying why: {unlabelled}. "
        "Pass reason= (see utils/send_telemetry.REASONS) so the send can be "
        "told apart from the other four in the data"
    )


def test_every_send_path_passes_an_identity():
    missing = []
    for rel in SOURCES:
        source = (BACKEND / rel).read_text(encoding="utf-8")
        for node in _increment_calls(source):
            if not any(k.arg == "email" for k in node.keywords):
                missing.append(f"{rel}:{node.lineno}")

    assert not missing, (
        f"these send paths report against a user id rather than an email: "
        f"{missing}. The event would open a second PostHog person and the "
        "sends would not show against the customer who made them"
    )


def test_the_vocabulary_matches_the_code_in_both_directions():
    """Neither an unlabelled path nor an invented category.

    A reason nothing emits is its own kind of wrong number: a dashboard slice
    that can never be non-zero reads as a feature nobody uses rather than a
    category that was never real. auto_resume was exactly that — it flips a
    campaign back to 'scheduled' and sends nothing itself.
    """
    used = set()
    for rel in SOURCES:
        source = (BACKEND / rel).read_text(encoding="utf-8")
        for node in _increment_calls(source):
            for kw in node.keywords:
                if kw.arg == "reason" and isinstance(kw.value, ast.Constant):
                    used.add(kw.value.value)

    assert used <= send_telemetry.REASONS, (
        f"send paths use reasons the vocabulary does not know: "
        f"{sorted(used - send_telemetry.REASONS)}"
    )
    assert send_telemetry.REASONS <= used, (
        f"the vocabulary carries reasons no send path emits: "
        f"{sorted(send_telemetry.REASONS - used)}. Remove them — a category "
        "that can never appear is worse than no category"
    )
