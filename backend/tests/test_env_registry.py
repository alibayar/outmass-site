"""The registry has to stay true, or it is worse than not having one.

A list of environment variables that is 90% right reads exactly like one that
is 100% right, and gets trusted the same way. These tests are what make
"one place" survive the next commit: a variable added to config.py and not to
the registry fails here, and so does a registry entry the doc never mentions.
"""
import ast
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from utils import env_registry as reg

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
# docs/plans/ is the one directory docs/_config.yml excludes from the public
# Jekyll site. This file names every setting the infrastructure has; it must
# not become a page on getoutmass.com. See the exclusion test at the bottom.
DOC = REPO / "docs" / "plans" / "railway-env.md"

OUR_SOURCE = ["config.py", "main.py", "database.py", "routers", "workers", "models", "utils"]


def _our_files():
    for entry in OUR_SOURCE:
        path = BACKEND / entry
        if path.is_file():
            yield path
        else:
            yield from path.rglob("*.py")


def _env_names_read_by(source: str) -> set[str]:
    """Every literal os.getenv("NAME") in a file, found by parsing.

    Parsed rather than grepped, for the reason test_config_guard learned the
    hard way: a substring cannot tell live code from a comment, and this
    check's entire job is to notice a real new variable.
    """
    names = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_getenv = (
            isinstance(func, ast.Attribute)
            and func.attr == "getenv"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        )
        if is_getenv and node.args and isinstance(node.args[0], ast.Constant):
            if isinstance(node.args[0].value, str):
                names.add(node.args[0].value)
    return names


def test_the_parser_can_tell_code_from_a_comment():
    """Self-test before trusting it."""
    assert _env_names_read_by('os.getenv("REAL")') == {"REAL"}
    assert _env_names_read_by('# os.getenv("COMMENTED")') == set()
    assert _env_names_read_by('x = \'os.getenv("QUOTED")\'') == set()
    assert _env_names_read_by("os.getenv(name)") == set()


def test_every_variable_the_code_reads_is_in_the_registry():
    """The one that matters. Without it the registry is a snapshot of today
    and the doc starts lying on the next commit that adds a setting."""
    unknown = {}
    for path in _our_files():
        for name in _env_names_read_by(path.read_text(encoding="utf-8")):
            if name not in reg.KNOWN_NAMES:
                unknown.setdefault(name, str(path.relative_to(BACKEND)))

    assert not unknown, (
        "these environment variables are read but are not in "
        f"utils/env_registry.py: {unknown}. Add them there (with which "
        "services need them and what breaks when they are absent) and to "
        f"docs/plans/{DOC.name}, or the next person copying settings between "
        "Railway services has no way to know they exist"
    )


def test_the_registry_invents_nothing():
    """The other direction: an entry for a variable nothing reads sends
    someone to set a value that does nothing. The three with no roles are
    deliberate and documented as such, so they are exempt."""
    read = set()
    for path in _our_files():
        read |= _env_names_read_by(path.read_text(encoding="utf-8"))

    phantom = [v.name for v in reg.REGISTRY if v.name not in read and v.roles]
    assert not phantom, f"registry entries nothing reads: {phantom}"


# ── Role detection, pinned to the real start commands ──


def _procfile_commands() -> dict[str, str]:
    lines = (BACKEND / "Procfile").read_text(encoding="utf-8").splitlines()
    out = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        role, command = line.split(":", 1)
        out[role.strip()] = command.strip()
    return out


def test_the_procfile_still_defines_the_three_services():
    assert set(_procfile_commands()) == set(reg.ROLES)


@pytest.mark.parametrize("role", reg.ROLES)
def test_each_procfile_command_is_recognised_as_its_own_role(role):
    """Read from the Procfile rather than retyped here. A role detector that
    has drifted off the real start commands reports the wrong service's
    requirements, which is worse than reporting none."""
    command = _procfile_commands()[role]
    assert reg.current_role(command.split()) == role


def test_a_local_run_is_not_a_deployment():
    """pytest, a shell, a migration script: none of these are a service, and
    alerting on them would train us to ignore the alert."""
    assert reg.current_role(["pytest", "-q"]) == "unknown"
    assert reg.current_role([]) == "unknown"
    assert reg.missing_for_role("unknown", {}) == []


# ── What it reports ──


def test_only_the_silent_ones_are_reported():
    """SUPABASE_URL and JWT_SECRET are missing from an empty environment too,
    but config.py raises on them — the service never starts, so nobody needs
    reminding. Padding the alert with what cannot happen is how an alert
    stops being read."""
    reported = {v.name for v in reg.missing_for_role(reg.WEB, {})}
    assert "STRIPE_SECRET_KEY" in reported
    assert "JWT_SECRET" not in reported
    assert "SUPABASE_URL" not in reported


def test_each_service_is_told_only_about_itself():
    """The worker has no Stripe keys to miss and the web service has no
    broker. A shared list would send someone setting values that do nothing,
    which is how the unused ones spread in the first place."""
    web = {v.name for v in reg.missing_for_role(reg.WEB, {})}
    worker = {v.name for v in reg.missing_for_role(reg.WORKER, {})}

    assert "REDIS_URL" in worker and "REDIS_URL" not in web
    assert "STRIPE_SECRET_KEY" in web and "STRIPE_SECRET_KEY" not in worker
    # The one that actually bit us: the worker sends mail and raises alerts.
    assert {"MAILERSEND_API_KEY", "TELEGRAM_BOT_TOKEN"} <= worker


def test_the_legacy_alias_still_counts_as_set():
    """SUPABASE_KEY during the service-role rollout, STRIPE_STANDARD_PRICE_ID
    from before the tier was renamed. Reporting a deployment that works as
    broken is a false alarm."""
    env = {"STRIPE_STANDARD_PRICE_ID": "price_x"}
    assert "STRIPE_STARTER_PRICE_ID" not in {
        v.name for v in reg.missing_for_role(reg.WEB, env)
    }


def test_whitespace_is_not_a_value():
    assert "STRIPE_SECRET_KEY" in {
        v.name for v in reg.missing_for_role(reg.WEB, {"STRIPE_SECRET_KEY": "   "})
    }


def test_the_operator_is_told_what_breaks_not_just_what_is_unset():
    """"STRIPE_WEBHOOK_SECRET is unset" reads as housekeeping. "a customer
    pays and never gets their plan" gets acted on."""
    with patch("routers.billing._telegram_alert") as alert:
        message = reg.check_env(reg.WEB, {})

    alert.assert_called_once()
    assert "ENV GAP" in alert.call_args.args[0]
    assert "never gets their plan" in message
    assert "Shared Variables" in message


def test_a_complete_environment_pings_nobody():
    env = {v.name: "set" for v in reg.REGISTRY}
    with patch("routers.billing._telegram_alert") as alert:
        assert reg.check_env(reg.WEB, env) is None
    alert.assert_not_called()


def test_a_broken_alert_channel_cannot_break_startup():
    with patch("routers.billing._telegram_alert",
               side_effect=RuntimeError("telegram down")):
        assert reg.check_env(reg.WEB, {})


# ── Wired into both entry points ──


def _calls_run_startup_checks(source: str) -> bool:
    """A real call, at module level or inside a try. Parsed, not grepped."""
    def walk(body):
        for node in body:
            if (isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "run_startup_checks"):
                return True
            if isinstance(node, ast.Try) and walk(node.body):
                return True
        return False

    return walk(ast.parse(source).body)


def test_the_call_detector_can_tell_code_from_a_comment():
    assert _calls_run_startup_checks("run_startup_checks()")
    assert _calls_run_startup_checks("try:\n    run_startup_checks()\nexcept Exception:\n    pass")
    assert not _calls_run_startup_checks("# run_startup_checks()")
    assert not _calls_run_startup_checks("def f():\n    run_startup_checks()")


@pytest.mark.parametrize("entry", ["main.py", "workers/celery_app.py"])
def test_both_entry_points_run_the_checks(entry):
    """The guard spent its first two days running on web only — the one
    service the incident it was written for had not happened on."""
    source = (BACKEND / entry).read_text(encoding="utf-8")
    assert _calls_run_startup_checks(source), (
        f"{entry} no longer runs the startup checks, so that service boots "
        "with no report of what it is missing"
    )


# ── And the doc says the same thing ──


@pytest.mark.skipif(not DOC.exists(), reason="doc not written yet")
def test_the_doc_lists_every_variable():
    text = DOC.read_text(encoding="utf-8")
    absent = [v.name for v in reg.REGISTRY if v.name not in text]
    assert not absent, f"docs/ops/railway-env.md is missing: {absent}"


@pytest.mark.skipif(not DOC.exists(), reason="doc not written yet")
def test_the_doc_invents_no_variable():
    """Catches the rename: config.py and the registry move together because a
    test forces them to, and the doc silently keeps the old name."""
    text = DOC.read_text(encoding="utf-8")
    mentioned = set(re.findall(r"`([A-Z][A-Z0-9_]{4,})`", text))
    unknown = sorted(n for n in mentioned if n not in reg.KNOWN_NAMES)
    assert not unknown, (
        f"{DOC.name} names variables nothing reads: {unknown}"
    )


def test_the_doc_cannot_become_a_public_page():
    """It lists every setting the infrastructure has, including which secrets
    exist and what each one unlocks. docs/ is a Jekyll site served at
    getoutmass.com, and the only thing keeping this file off it is one line
    in _config.yml — which is exactly the kind of protection that gets
    deleted by someone tidying up."""
    config = (REPO / "docs" / "_config.yml").read_text(encoding="utf-8")
    excluded = re.findall(r"^\s*-\s*(\S+)", config[config.index("exclude:"):], re.M)

    assert DOC.parent.name == "plans", (
        "the Railway env doc moved out of docs/plans/, the only directory "
        "docs/_config.yml excludes from the public site"
    )
    assert "plans/" in excluded, (
        "docs/_config.yml no longer excludes plans/ — every internal doc in "
        "there, including the full list of infrastructure settings, would be "
        "published to getoutmass.com on the next site build"
    )
