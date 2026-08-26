"""One place that knows which service needs which environment variable.

Railway gives every service its own Variables panel. We run three off the same
image — web, worker and beat (see backend/Procfile) — so every setting exists
in triplicate and is copied by hand. That has cost us three times:

  * 2026-07  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID were set on web and not on
             the worker, so the daily report simply never arrived. Nothing
             errored; the report was just absent.
  * 2026-08-10  the worker still carried TEST Stripe keys beside the
             production database. config_guard.py exists because of this.
  * 2026-08-08  BACKEND_URL could not be confirmed on any service, and it is
             what stamps tracking pixels and unsubscribe links into outgoing
             mail — a wrong value is invisible to us and broken for everyone
             who received the mail.

Every one of those was silence. SUPABASE_URL and JWT_SECRET are not in that
class: config.py raises on them, so a service missing those never boots and
the failure announces itself. The hazard is the setting with a plausible
default, which turns a whole feature off while everything reports healthy.

This registry is the single source of truth for that. It drives three things:

  1. the startup check below, which names what THIS service is missing
  2. docs/ops/railway-env.md, which is generated from it
  3. a test that fails when config.py reads a variable this file has not
     heard of — without which "one place" lasts until the next commit
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

WEB = "web"
WORKER = "worker"
BEAT = "beat"
ROLES = (WEB, WORKER, BEAT)


@dataclass(frozen=True)
class Var:
    """One environment variable, and what its absence costs.

    `silent` is the field that matters. False means config.py refuses to boot
    without it, or its default is genuinely correct everywhere — either way
    nobody has to remember it. True means the service starts, reports healthy,
    and quietly does less than it should.
    """

    name: str
    roles: tuple[str, ...]
    silent: bool
    breaks: str
    shared: bool = True  # safe to define once at project level
    aliases: tuple[str, ...] = field(default_factory=tuple)


REGISTRY: tuple[Var, ...] = (
    # ── Refuses to boot without these; failure is loud, no reminder needed ──
    Var("SUPABASE_URL", ROLES, False, "config.py raises — the service will not start"),
    Var("SUPABASE_SERVICE_ROLE_KEY", ROLES, False,
        "config.py raises unless the legacy SUPABASE_KEY is set instead",
        aliases=("SUPABASE_KEY",)),
    Var("JWT_SECRET", ROLES, False, "config.py raises — the service will not start"),

    # ── Silent when missing: this is the whole reason the file exists ──
    Var("STRIPE_SECRET_KEY", (WEB,), True,
        "checkout, the portal and every webhook stop working; the panel keeps "
        "its Upgrade button and nobody can pay"),
    Var("STRIPE_WEBHOOK_SECRET", (WEB,), True,
        "every Stripe webhook is rejected — a customer pays and never gets "
        "their plan"),
    Var("STRIPE_STARTER_PRICE_ID", (WEB,), True,
        "the plan catalogue comes back empty and the panel silently falls "
        "back to its old single hardcoded-Starter button",
        aliases=("STRIPE_STANDARD_PRICE_ID",)),
    Var("STRIPE_PRO_PRICE_ID", (WEB,), True, "same as STRIPE_STARTER_PRICE_ID — the catalogue is all-or-nothing"),
    Var("AZURE_CLIENT_SECRET", (WEB,), True, "the OAuth token exchange fails and nobody can sign in"),
    Var("REDIS_URL", (WORKER, BEAT), True,
        "the worker talks to a localhost broker that is not there — no "
        "scheduled send, no follow-up, no auto-resume, and no error anywhere"),
    Var("BACKEND_URL", ROLES, True,
        "tracking pixels, click links, unsubscribe links and Stripe redirect "
        "URLs are stamped into outgoing mail pointing at localhost"),
    Var("MAILERSEND_API_KEY", (WEB, WORKER), True,
        "every transactional email is skipped — welcome, reconnect, "
        "quota-cap, plan-drop, the 30-day nudge and feedback forwarding"),
    Var("TELEGRAM_BOT_TOKEN", (WEB, WORKER, BEAT), True,
        "every operator alert is dropped, including the ones that report a "
        "misconfiguration — this is how the daily report went missing"),
    Var("TELEGRAM_CHAT_ID", (WEB, WORKER, BEAT), True, "same as TELEGRAM_BOT_TOKEN"),
    Var("POSTHOG_API_KEY", (WEB, WORKER), True,
        "server-side funnel events stop; the funnel looks smaller than it is "
        "and nothing says so"),

    # ── Has a real default; drift is possible but cheap ──
    Var("STRIPE_PORTAL_CONFIG_ID", (WEB,), False, "Stripe's default portal configuration is used"),
    Var("STRIPE_TEAM_PRICE_ID", (WEB,), False, "the unsold Team tier is unbuyable, which it already is"),
    Var("AZURE_CLIENT_ID", (WEB,), False, "falls back to the live app registration id"),
    Var("AZURE_REDIRECT_URI", (WEB,), False, "derived from BACKEND_URL"),
    Var("AZURE_EXTENSION_ID", (WEB,), False, "falls back to the store extension id"),
    Var("ALLOWED_EXTENSION_IDS", (WEB,), False, "falls back to the store extension id"),
    Var("CORS_ORIGINS", (WEB,), False, "falls back to the store extension plus localhost"),
    Var("ANTHROPIC_API_KEY", (WEB,), True, "the AI writer fails for Pro users"),
    Var("POSTHOG_HOST", (WEB, WORKER), False, "defaults to the EU ingest host"),
    Var("POSTHOG_API_HOST", (WORKER,), False, "defaults to the EU query host"),
    Var("POSTHOG_PERSONAL_API_KEY", (WORKER,), True, "the daily report cannot read funnel numbers"),
    Var("POSTHOG_PROJECT_ID", (WORKER,), False, "defaults to the live project"),
    Var("REPORT_OWNER_EMAILS", (WORKER,), True, "the daily report is generated and sent to nobody"),
    Var("REPORT_HEALTH_URL", (WORKER,), False, "the report skips its health probe"),
    Var("REPORT_TRIGGER_KEY", (WEB,), False, "the manual report trigger endpoint stays closed"),
    Var("MAILERSEND_FROM_EMAIL", (WEB, WORKER), False, "defaults to support@getoutmass.com"),
    Var("MAILERSEND_FROM_NAME", (WEB, WORKER), False, "defaults to the support sender name"),
    Var("MAILERSEND_TO_EMAIL", (WEB,), False, "feedback forwarding defaults to support@getoutmass.com"),
    Var("FIRST_SIGNIN_INCLUDE_MAIL_READ", (WEB, WORKER), False, "defaults to true (see task #24)"),
    Var("FREE_PLAN_MONTHLY_LIMIT", (WEB, WORKER), False, "defaults to 250"),
    Var("STARTER_PLAN_MONTHLY_LIMIT", (WEB, WORKER), False, "defaults to 2500"),
    Var("PRO_PLAN_MONTHLY_LIMIT", (WEB, WORKER), False, "defaults to 10000"),
    Var("CSV_UPLOAD_ROW_LIMIT", (WEB,), False, "defaults to 10000, same for every plan; set it to roll back the 2026-08-25 change"),
    Var("AI_GENERATION_MONTHLY_LIMIT", (WEB,), False, "defaults to 50"),
    Var("PLAN_DROP_NOTICE_DAYS", (WEB,), False, "defaults to 14"),
    Var("AUTH_RESUME_MAX_AGE_DAYS", (WEB, WORKER), False, "defaults to 7"),
    Var("INACTIVITY_NUDGE_DAYS", (WORKER,), False, "defaults to 30"),

    # ── Read by config.py and consumed by nothing ──
    #
    # Listed so nobody copies them into a third service believing they matter.
    # Deliberately not deleted: two of them are the config for inactivity
    # tiers that are designed but not built.
    Var("FRONTEND_URL", (), False, "nothing reads it", shared=False),
    Var("INACTIVITY_PAUSE_DAYS", (), False, "the 60-day pause tier is not implemented", shared=False),
    Var("INACTIVITY_CANCEL_DAYS", (), False, "the 90-day cancel tier is not implemented", shared=False),
)

BY_NAME = {v.name: v for v in REGISTRY}
KNOWN_NAMES = {v.name for v in REGISTRY} | {a for v in REGISTRY for a in v.aliases}


def current_role(argv: list[str] | None = None) -> str:
    """Which of the three services this process is.

    Read from the command line because that is the only thing that actually
    differs between them — same repo, same image, same config.py. Anything
    unrecognised (pytest, a shell, a migration script) returns "unknown" and
    every check below stays quiet, because a local run is not a deployment.
    """
    joined = " ".join(argv if argv is not None else sys.argv).lower()
    if "beat" in joined:
        return BEAT
    if "celery" in joined and "worker" in joined:
        return WORKER
    if "uvicorn" in joined or "main:app" in joined:
        return WEB
    return "unknown"


def missing_for_role(role: str, environ: dict) -> list[Var]:
    """Variables this role needs, whose absence would pass unnoticed.

    Only the silent ones: the loud ones already stop the process, and
    repeating them here would pad the alert with things that cannot happen.
    An alias counts as set — SUPABASE_KEY still satisfies the service-role
    entry during that rollout.
    """
    if role not in ROLES:
        return []
    missing = []
    for var in REGISTRY:
        if role not in var.roles or not var.silent:
            continue
        names = (var.name,) + var.aliases
        if not any((environ.get(n) or "").strip() for n in names):
            missing.append(var)
    return missing


def check_env(role: str, environ: dict) -> str | None:
    """Report what this service is quietly missing. Returns the message so
    callers can test it; reporting is a side effect, never an exception."""
    missing = missing_for_role(role, environ)
    if not missing:
        return None

    lines = [f"{v.name} — {v.breaks}" for v in missing]
    message = (
        f"The {role} service is missing {len(missing)} setting(s) whose "
        "absence produces no error:\n\n" + "\n\n".join(lines) +
        "\n\nRailway → Variables. Define them as project-level Shared "
        "Variables and reference them from all three services, so this can "
        "only be wrong in one place."
    )

    from utils.config_guard import _report

    _report("ENV GAP", message)
    return message
