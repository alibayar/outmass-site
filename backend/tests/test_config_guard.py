"""The startup guard against a Stripe key pointed at the wrong database.

Written 2026-08-11 after finding that outmass.review@outlook.com had carried
a Stripe customer and subscription id since 2026-04-17 that exist in no live
Stripe account — written by a TEST-mode key running against the production
database. It cost no money and did real damage anyway: daily_report counts a
real payer as "paid plan + non-null stripe_subscription_id", so that row sat
in the revenue figure as a Pro subscriber for four months.

The same shape had reappeared the night before on the Railway worker
service. Both times the failure mode was silence, which is the whole reason
this guard exists and the reason it errs toward false alarms.
"""
from unittest.mock import patch

import pytest

from utils import config_guard

PROD_DB = "https://qhfefazyfhyqnjcmfmdd.supabase.co"
FAKE_DB = "https://fake.supabase.co"


# ── The incident, as a test ──


def test_test_key_against_the_production_database_is_caught():
    msg = config_guard.stripe_mode_mismatch("sk_test_abc123", PROD_DB)
    assert msg and "TEST key" in msg


def test_live_key_against_a_throwaway_database_is_caught():
    """The reverse hazard: real cards charged against data nobody keeps."""
    msg = config_guard.stripe_mode_mismatch("sk_live_abc123", FAKE_DB)
    assert msg and "LIVE key" in msg


# ── The pairings that are fine ──


@pytest.mark.parametrize("key,url", [
    ("sk_live_abc123", PROD_DB),   # production, as intended
    ("sk_test_abc123", FAKE_DB),   # a dev machine, as intended
])
def test_coherent_pairings_are_silent(key, url):
    assert config_guard.stripe_mode_mismatch(key, url) is None


@pytest.mark.parametrize("key", ["", None, "whsec_notasecretkey", "abc"])
def test_an_unconfigured_or_unreadable_key_never_alarms(key):
    """Most services do not touch Stripe. Guessing at an unrecognised value
    would make every one of them alert on every boot, and an alert channel
    that cries wolf is the same as no alert channel."""
    assert config_guard.stripe_mode_mismatch(key, PROD_DB) is None


def test_restricted_keys_are_read_the_same_way():
    """rk_ keys carry the same mode marker and the same hazard."""
    assert config_guard.stripe_mode_mismatch("rk_test_abc", PROD_DB)
    assert config_guard.stripe_mode_mismatch("rk_live_abc", FAKE_DB)


# ── The bias that makes it useful ──


def test_an_unrecognised_host_counts_as_production():
    """The point of the guard is that the failure is silent, so an unknown
    host must raise a false alarm rather than wave a real misconfiguration
    through. A staging project nobody told this file about is exactly where
    the next occurrence would hide."""
    assert config_guard._db_looks_production("https://some-new-ref.supabase.co")
    msg = config_guard.stripe_mode_mismatch(
        "sk_test_abc", "https://some-new-ref.supabase.co"
    )
    assert msg is not None


@pytest.mark.parametrize("url", [
    FAKE_DB, "https://test.supabase.co", "http://localhost:54321",
    "http://127.0.0.1:54321",
])
def test_known_non_production_hosts_are_recognised(url):
    assert not config_guard._db_looks_production(url)


def test_an_empty_url_is_not_production():
    """An unset SUPABASE_URL cannot be the production database, and treating
    it as one would alarm on every misconfigured local run for the wrong
    reason."""
    assert not config_guard._db_looks_production("")


# ── Reporting is a side effect, never an exception ──


def test_the_operator_is_pinged_on_a_mismatch():
    with patch("routers.billing._telegram_alert") as alert:
        config_guard.check_stripe_mode("sk_test_abc", PROD_DB)
    alert.assert_called_once()
    assert "CONFIG MISMATCH" in alert.call_args.args[0]


def test_a_broken_alert_channel_cannot_break_startup():
    """The guard runs at import time in main.py. If it could raise, a
    Telegram outage would take the API down — which is precisely the
    disproportionate failure this design refuses."""
    with patch("routers.billing._telegram_alert",
               side_effect=RuntimeError("telegram down")):
        assert config_guard.check_stripe_mode("sk_test_abc", PROD_DB)


def test_a_coherent_pairing_does_not_ping_anyone():
    with patch("routers.billing._telegram_alert") as alert:
        config_guard.check_stripe_mode("sk_live_abc", PROD_DB)
    alert.assert_not_called()


# ── Wired into the app ──


def test_startup_reads_the_real_config_names():
    """Guards against the check drifting off the variables it claims to
    read — a guard pointed at a renamed setting is worse than none, because
    it reports all-clear forever."""
    called = {}

    def _capture(secret_key, supabase_url):
        called["key"] = secret_key
        called["url"] = supabase_url

    with patch.object(config_guard, "check_stripe_mode", _capture), \
         patch.object(config_guard, "check_plan_price_ids"):
        config_guard.run_startup_checks()

    import config

    assert called["key"] == config.STRIPE_SECRET_KEY
    assert called["url"] == config.SUPABASE_URL


# ── The price id whose absence turns the plan picker off ──
#
# Added 2026-08-13. Same family as everything above: the setting is missing,
# nothing fails, the feature is simply not there.


PRICE_IDS = ("price_starter_live", "price_pro_live")


@pytest.mark.parametrize("starter,pro,expected", [
    ("", "price_pro", ["STRIPE_STARTER_PRICE_ID"]),
    ("price_starter", "", ["STRIPE_PRO_PRICE_ID"]),
    ("", "", ["STRIPE_STARTER_PRICE_ID", "STRIPE_PRO_PRICE_ID"]),
    ("   ", "price_pro", ["STRIPE_STARTER_PRICE_ID"]),  # whitespace is unset
    (None, "price_pro", ["STRIPE_STARTER_PRICE_ID"]),
])
def test_a_missing_price_id_is_named(starter, pro, expected):
    """Named, not merely counted — the operator has to know WHICH variable to
    go and set, and the two live in different Railway services."""
    assert config_guard.missing_plan_price_ids("sk_live_abc", starter, pro) == expected


def test_both_price_ids_present_is_silent():
    assert config_guard.missing_plan_price_ids("sk_live_abc", *PRICE_IDS) == []


@pytest.mark.parametrize("key", ["", None, "   "])
def test_a_service_that_does_no_billing_never_alarms(key):
    """The worker carries no Stripe key and needs no price ids. Alerting on
    it would make every boot shout, which mutes the channel for the case that
    matters."""
    assert config_guard.missing_plan_price_ids(key, "", "") == []


def test_the_operator_is_pinged_and_told_the_consequence():
    with patch("routers.billing._telegram_alert") as alert:
        msg = config_guard.check_plan_price_ids("sk_live_abc", "price_starter", "")

    alert.assert_called_once()
    sent = alert.call_args.args[0]
    assert "CONFIG GAP" in sent
    assert "STRIPE_PRO_PRICE_ID" in sent
    # The alert has to say what the user experiences, not just which variable
    # is empty — "unset" alone reads as harmless.
    assert "hardcoded Starter" in msg


def test_a_complete_price_config_does_not_ping_anyone():
    with patch("routers.billing._telegram_alert") as alert:
        assert config_guard.check_plan_price_ids("sk_live_abc", *PRICE_IDS) is None
    alert.assert_not_called()


def test_a_broken_alert_channel_cannot_break_startup_here_either():
    with patch("routers.billing._telegram_alert",
               side_effect=RuntimeError("telegram down")):
        assert config_guard.check_plan_price_ids("sk_live_abc", "price_starter", "")


def test_startup_reads_the_real_price_id_names():
    """The twin of test_startup_reads_the_real_config_names, for the same
    reason: a guard reading a renamed setting reports all-clear forever."""
    called = {}

    def _capture(secret_key, starter_price_id, pro_price_id):
        called["key"] = secret_key
        called["starter"] = starter_price_id
        called["pro"] = pro_price_id

    with patch.object(config_guard, "check_stripe_mode"), \
         patch.object(config_guard, "check_plan_price_ids", _capture):
        config_guard.run_startup_checks()

    import config

    assert called["key"] == config.STRIPE_SECRET_KEY
    assert called["starter"] == config.STRIPE_STARTER_PRICE_ID
    assert called["pro"] == config.STRIPE_PRO_PRICE_ID


def _calls_startup_checks(source: str) -> bool:
    """True only if run_startup_checks() is a real module-level statement.

    Parsed rather than grepped. The first version of this test asserted
    `"run_startup_checks()" in src`, and mutation testing caught it dead:
    commenting the call out leaves the substring in place, so the guard
    reported all-clear for the one mutation it existed to catch. Same
    mistake as the terms.html quota check earlier the same day — a
    substring cannot tell live code from a comment.
    """
    import ast

    for node in ast.parse(source).body:
        if (isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "run_startup_checks"):
            return True
    return False


def test_the_call_detector_can_tell_code_from_a_comment():
    """Self-test before trusting it."""
    assert _calls_startup_checks("run_startup_checks()")
    assert not _calls_startup_checks("# run_startup_checks()")
    assert not _calls_startup_checks("x = 'run_startup_checks()'")
    assert not _calls_startup_checks("def f():\n    run_startup_checks()")


def test_main_actually_calls_it():
    """The pure functions above all pass whether or not anything runs them.
    Mutation testing on 2026-08-10 found three guards that were correct and
    never called."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8"
    )
    assert _calls_startup_checks(src), (
        "main.py no longer runs the startup checks at module level"
    )
