"""
OutMass — Configuration
All environment variables are read from here.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Supabase ──
#
# Prefer SUPABASE_SERVICE_ROLE_KEY — the server-side key that bypasses
# Row Level Security. After migration 008 enabled RLS on every app
# table, the anon key can no longer read/write our data, which is the
# whole point: defense against accidental anon-key leaks.
#
# SUPABASE_KEY is still read as a fallback so existing deployments keep
# booting during the service_role rollout. New deploys should set
# SUPABASE_SERVICE_ROLE_KEY and leave SUPABASE_KEY unset.
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
    or ""
)

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) "
        "must be set in .env"
    )

# ── Auth ──
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

if not JWT_SECRET or JWT_SECRET.startswith("change-me"):
    raise RuntimeError(
        "JWT_SECRET must be set to a strong random value in .env. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

# ── Stripe ──
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_STARTER_PRICE_ID = os.getenv("STRIPE_STARTER_PRICE_ID", "") or os.getenv("STRIPE_STANDARD_PRICE_ID", "")
STRIPE_PRO_PRICE_ID = os.getenv("STRIPE_PRO_PRICE_ID", "")
STRIPE_TEAM_PRICE_ID = os.getenv("STRIPE_TEAM_PRICE_ID", "")
STRIPE_PORTAL_CONFIG_ID = os.getenv("STRIPE_PORTAL_CONFIG_ID", "")

# ── Redis / Celery ──
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── App ──
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "")

# ── CORS ──
_default_cors = "chrome-extension://adcfddainnkjomddlappnnbeomhlcbmm,http://localhost:3000,http://localhost:5173"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", _default_cors).split(",") if o.strip()]
if BACKEND_URL and BACKEND_URL not in CORS_ORIGINS:
    CORS_ORIGINS.append(BACKEND_URL)

# ── Azure AD ──
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "3b6a9f9b-cbb6-4dcb-a3b6-d993de74a1b5")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", f"{BACKEND_URL}/auth/callback")
AZURE_EXTENSION_ID = os.getenv("AZURE_EXTENSION_ID", "adcfddainnkjomddlappnnbeomhlcbmm")

# Multi-extension allowlist for the OAuth `state` round-trip.
#
# The callback redirects to `https://{ext_id}.chromiumapp.org/auth#jwt=...`.
# For `launchWebAuthFlow` to close correctly, that ext_id must match the
# calling extension's chrome.runtime.id. A single Railway env var
# (AZURE_EXTENSION_ID) can only hold one value — which breaks local dev
# (unpacked extension has a different ID than the store build).
#
# Fix: the extension passes its own ID via `?ext=...` on /auth/login.
# We echo it through Microsoft via the OAuth `state` parameter, then
# redirect to that ID on callback — but only if it's in this allowlist,
# otherwise a malicious page could point our OAuth flow (and the resulting
# JWT fragment) at an attacker-controlled chromiumapp.org subdomain.
#
# Defaults cover: Chrome store build, the handoff-documented dev unpacked ID,
# and the Edge Add-ons build (CRX ID nfgnhh... — Edge assigns its own ID,
# different from Chrome; needed so Edge sign-in closes the OAuth loop).
# Add more by setting `ALLOWED_EXTENSION_IDS=id1,id2,id3` on Railway.
_default_ext_ids = "adcfddainnkjomddlappnnbeomhlcbmm,acdafphnihddolfhabbndfofheokckhl,nfgnhhdeninjmnpfbhnggknimhejbelc"
ALLOWED_EXTENSION_IDS = [
    e.strip()
    for e in os.getenv("ALLOWED_EXTENSION_IDS", _default_ext_ids).split(",")
    if e.strip()
]
if AZURE_EXTENSION_ID and AZURE_EXTENSION_ID not in ALLOWED_EXTENSION_IDS:
    ALLOWED_EXTENSION_IDS.append(AZURE_EXTENSION_ID)
MS_AUTH_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
# The FULL scope set — what an established user has consented to. Value
# deliberately unchanged: it is what every existing user's refresh request
# must keep asking for, or Microsoft issues a narrower token and reply
# detection silently dies for people who already granted Mail.Read.
MS_GRAPH_SCOPES = "https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read offline_access"

# What a BRAND-NEW user is asked for at first sign-in. Mail.Read is absent on
# purpose: Microsoft renders it as "Read your mail", which is the most
# alarming line on the consent screen and the least justifiable for a tool
# the user has not sent a single email with yet. It exists only for reply
# detection, which cannot matter before the first campaign goes out.
# Measured 2026-08-06, with the confounds removed on the same day (commit
# 7b33863): first-time users COMPLETE at 69% on Chrome and 46% on Edge,
# n=32/13, and the gap is not significant. So roughly a third of first-timers
# are lost at the consent screen on BOTH browsers - this is not an Edge
# problem. The earlier "Edge is broken" reading compared Edge first-timers
# against Chrome REPEAT sign-ins, which skip consent entirely.
#
# Publisher verification (done 2026-06-24) did not move the number.
MS_GRAPH_FIRST_SIGNIN_SCOPES = "https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/User.Read offline_access"

# Requested later, on its own, when the user opts into reply detection —
# same incremental-consent mechanism as OneDrive below.
MS_GRAPH_MAIL_READ_SCOPE = "https://graph.microsoft.com/Mail.Read"

# Master switch for the split above. TRUE = today's behaviour, byte for
# byte: first sign-in asks for everything including Mail.Read. Flip to
# false on Railway to start the narrow ask; flip back to recover instantly,
# with no deploy either way. Deliberately defaulting to the old behaviour so
# the code can ship and sit inert until the migration has been run and Ali
# decides to turn it on.
FIRST_SIGNIN_INCLUDE_MAIL_READ = (
    os.getenv("FIRST_SIGNIN_INCLUDE_MAIL_READ", "true").strip().lower()
    not in ("false", "0", "no")
)

# Optional OneDrive scopes — requested only when the user opts into the
# OneDrive-link feature for the first time (incremental consent). Keeping
# these out of the default scope list means a brand-new sign-up does NOT
# see OneDrive permissions on the consent screen, which preserves
# conversion. The /auth/login endpoint accepts ?include_onedrive=true to
# add these to the request.
MS_GRAPH_ONEDRIVE_SCOPES = (
    "https://graph.microsoft.com/Files.Read.All "
    "https://graph.microsoft.com/Files.ReadWrite"
)

# ── Graph API ──
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

# ── PostHog ──
# Project lives on PostHog EU (key phc_kSzE…). Railway sets POSTHOG_HOST=EU,
# but default to EU too so telemetry doesn't silently break if the env is lost.
POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", "")
POSTHOG_HOST = os.getenv("POSTHOG_HOST", "https://eu.i.posthog.com")

# ── AI ──
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── Telegram daily report + feedback alerts ──
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Secret that enables POST /api/admin/trigger-report — a manual fire of the daily
# report (runs on the WORKER via Celery, so it tests the worker's Telegram env),
# for verifying the report without waiting for the cron. Disabled when empty.
REPORT_TRIGGER_KEY = os.getenv("REPORT_TRIGGER_KEY", "")

# ── Report error-check (PostHog Query API) + health ping ──
# Personal API key (scope: Query Read) so the twice-daily Telegram report can
# answer "any error events in the last 12h?" from PostHog. Set on the WORKER
# service (env vars are per-service — the Telegram lesson). Empty → the report
# prints "check not configured" and makes no API call (tests rely on this).
POSTHOG_PERSONAL_API_KEY = os.getenv("POSTHOG_PERSONAL_API_KEY", "")
POSTHOG_PROJECT_ID = os.getenv("POSTHOG_PROJECT_ID", "152466")
POSTHOG_API_HOST = os.getenv("POSTHOG_API_HOST", "https://eu.posthog.com")
# Optional public URL the report pings for an "API up" line. Empty → omitted.
REPORT_HEALTH_URL = os.getenv("REPORT_HEALTH_URL", "")

# Owner/test account emails (comma-separated) excluded from the report's
# paying/gift counts so MRR reflects real revenue. Env, not code — this repo
# serves the public site, so personal addresses stay out of it.
REPORT_OWNER_EMAILS = [
    e.strip().lower()
    for e in os.getenv("REPORT_OWNER_EMAILS", "").split(",")
    if e.strip()
]

# ── MailerSend (transactional email) ──
MAILERSEND_API_KEY = os.getenv("MAILERSEND_API_KEY", "")
MAILERSEND_FROM_EMAIL = os.getenv("MAILERSEND_FROM_EMAIL", "support@getoutmass.com")
MAILERSEND_FROM_NAME = os.getenv("MAILERSEND_FROM_NAME", "OutMass Feedback")
MAILERSEND_TO_EMAIL = os.getenv("MAILERSEND_TO_EMAIL", "support@getoutmass.com")

# Sender name for mail that goes TO a customer.
#
# Deliberately a second name rather than a reuse of MAILERSEND_FROM_NAME
# above, because the two have opposite audiences: that one labels the
# feedback form, which mails US, and "OutMass Feedback" is right there. On
# anything a customer receives it reads as an automation desk — and every
# one of these emails asks the customer to reply ("reply to this email and
# we'll look into it", "if you need help cancelling, reply"). An ask for a
# reply is not credible over a no-reply-shaped name.
#
# Not env-overridable on purpose. It is a voice decision, not deployment
# config, and per-service Railway variables have drifted on us three times
# in one week — a name that differs between web and worker would be worse
# than no variable at all.
MAILERSEND_PERSON_FROM_NAME = "Ali from OutMass"

# ── Inactivity nudge / auto-cancel (Phases 5-6) ──
#
# Paid users who stop logging in represent both a support risk
# (chargeback) and a good-citizen obligation (don't bill people for
# something they're not using). These flags gate user-visible email
# dispatch and subscription modifications — both default OFF so the
# code ships inert and is flipped on only after manual verification.
def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")

INACTIVITY_NUDGE_ENABLED = _env_bool("INACTIVITY_NUDGE_ENABLED", False)
INACTIVITY_NUDGE_DAYS = int(os.getenv("INACTIVITY_NUDGE_DAYS", "30"))

# Phase 6 gates (not used yet — exposed here so the env setup is done
# once and the flip is a single Railway variable change later).
INACTIVITY_AUTOCANCEL_ENABLED = _env_bool("INACTIVITY_AUTOCANCEL_ENABLED", False)
INACTIVITY_PAUSE_DAYS = int(os.getenv("INACTIVITY_PAUSE_DAYS", "60"))
INACTIVITY_CANCEL_DAYS = int(os.getenv("INACTIVITY_CANCEL_DAYS", "90"))

# How far back a send stranded by a dead Microsoft token may be resurrected
# when the user reconnects. Measured on scheduled_for, which reads correctly
# for BOTH campaign shapes: a one-shot carries the moment it was meant to go
# out, and a daily-capped multi-day campaign rolls scheduled_for forward 24h
# after every batch, so it carries the day it was last alive.
#
# Bounded because the codebase already learned this lesson once, in the
# auto-resume beat: "a months-old abandoned partial must never resurrect
# itself and surprise-send a stale list." That rule was retired on
# 2026-08-28 in favour of archiving plus a per-batch email, because an age
# window was also stopping campaigns nobody had abandoned. THIS bound stays:
# a dead token is not a user choosing to wait, and there is no per-batch
# email on that path to keep them informed. Anything older than this
# is left alone AND reported, so "nothing happened" and "deliberately skipped"
# stay distinguishable.
AUTH_RESUME_MAX_AGE_DAYS = int(os.getenv("AUTH_RESUME_MAX_AGE_DAYS", "7"))

# How recently the OWNER must have been here for auto-resume to keep going.
#
# On 2026-08-28 the age window on partial campaigns was removed, because a
# free user whose 10,000-row list needs forty monthly batches got one batch
# and then silence while the panel promised the rest would follow. The
# campaign's age was the wrong thing to measure: it stopped campaigns nobody
# had abandoned.
#
# But something did have to replace it, and `archived` alone does not. It is
# a switch the user has to know about and go press — and the person we are
# worried about is precisely the one who stopped coming back. A list nobody
# has looked at since June should not keep sending itself in September just
# because its owner never found the Archive button.
#
# So the measure moved from the CAMPAIGN's age to the OWNER's. Ali's call,
# 2026-08-30: if they have been here in the last month, keep going; if not,
# hold. Rolling 30 days, deliberately NOT aligned to the billing period —
# quota resets on the anniversary, so "have they been here since the last
# reset?" would be a near-zero window at exactly the moment resume becomes
# possible, and would stop nearly everyone on the very day they qualify.
# Rolling 30 days is also what daily_report already means by "active".
#
# Holding is not stopping. The campaign stays 'partial', so signing in
# refreshes last_activity_at and the next hourly run picks it up again with
# nothing to press. The panel says so on the campaign row, so a returning
# user reads "open OutMass to continue" rather than discovering it.
AUTO_RESUME_DORMANT_DAYS = int(os.getenv("AUTO_RESUME_DORMANT_DAYS", "30"))

# How long to leave a partial campaign alone after its last attempt.
#
# The resume beat went from daily to two-hourly on 2026-08-30, because a
# campaign whose quota came back at 07:00 was waiting twenty-three hours
# while the panel promised it would continue by itself. That fixed the
# waiting and created a different problem: a campaign that cannot succeed
# now gets twelve attempts a day instead of one.
#
# It is not a theoretical cost. The failure we had just found was Graph
# refusing to send from a mailbox at all — and the likeliest reason for that
# is Microsoft already restricting a new account. Retrying twelve times a day
# would be us making a user's standing with their own provider worse, on
# their behalf, without telling them.
#
# campaigns.updated_at (migration 025) is enough to space the attempts out:
# every path that parks a campaign writes it. No new column, no new state to
# keep true. The cost is that a quota-capped campaign whose owner UPGRADES to
# unblock it also waits — the manual Resume button in Reports is the
# immediate path for that, and it does not go through this beat.
AUTO_RESUME_BACKOFF_HOURS = int(os.getenv("AUTO_RESUME_BACKOFF_HOURS", "6"))

# How long the panel keeps saying "your plan ended" after a drop to Free.
#
# The notice is not the notification — the email sent at the moment of the
# drop is. This is context at the moment of USE: you came back, you are
# capped, here is why and here is the way back. That value decays, and a
# banner shown while a condition holds for ever stops being information and
# becomes furniture.
#
# 14 days matches Stripe's own retry window, which is the period where the
# drop can still be a surprise. It lives here rather than in the extension
# so the rule is defined once — same reason the plan catalogue's prices and
# limits are read rather than typed.
PLAN_DROP_NOTICE_DAYS = int(os.getenv("PLAN_DROP_NOTICE_DAYS", "14"))

# ── Plan Limits (env-overridable — raise later in Railway, no code change) ──
FREE_PLAN_MONTHLY_LIMIT = int(os.getenv("FREE_PLAN_MONTHLY_LIMIT", "250"))
STARTER_PLAN_MONTHLY_LIMIT = int(os.getenv("STARTER_PLAN_MONTHLY_LIMIT", "2500"))
PRO_PLAN_MONTHLY_LIMIT = int(os.getenv("PRO_PLAN_MONTHLY_LIMIT", "10000"))

# Legacy alias (keep for back-compat until all code migrated)
STANDARD_PLAN_MONTHLY_LIMIT = STARTER_PLAN_MONTHLY_LIMIT

# AI generation limit (per month, Pro only)
AI_GENERATION_MONTHLY_LIMIT = int(os.getenv("AI_GENERATION_MONTHLY_LIMIT", "50"))

# CSV upload row limits (per upload, not cumulative).
#
# The per-plan shape, still in force until the flag below is switched on.
FREE_UPLOAD_ROW_LIMIT = int(os.getenv("FREE_UPLOAD_ROW_LIMIT", "250"))
STARTER_UPLOAD_ROW_LIMIT = int(os.getenv("STARTER_UPLOAD_ROW_LIMIT", "2500"))
PRO_UPLOAD_ROW_LIMIT = int(os.getenv("PRO_UPLOAD_ROW_LIMIT", "10000"))

# ONE ceiling for every plan (2026-08-25). The per-plan version rejected the
# list at the door — a free user with 800 recipients got a raw English 413 and
# never saw the product work — while protecting no revenue: the monthly quota
# already caps what actually sends and leaves the remainder pending for the
# next reset. The ceiling is still a real ceiling, and the abuse bound that
# sits next to MAX_CSV_SIZE_BYTES.
#
# It ships DARK, like INACTIVITY_NUDGE_ENABLED. The extension only learned to
# say how many months the leftovers really take in 0.3.0; releasing the limit
# before that build reaches both stores would tell users their remainder clears
# in one monthly reset. Set UPLOAD_LIMIT_FOLLOWS_QUOTA=true on the day 0.3.0
# publishes — the flag defaults off so forgetting it changes nothing, which is
# the safe direction to forget in.
#
# The flag is a switch, NOT a number: setting CSV_UPLOAD_ROW_LIMIT=250 to hold
# the change back would have capped Starter and Pro at 250 rows too, since this
# single value replaces all three. Ali caught that before it was deployed.
UPLOAD_LIMIT_FOLLOWS_QUOTA = (
    os.getenv("UPLOAD_LIMIT_FOLLOWS_QUOTA", "false").strip().lower() == "true"
)
CSV_UPLOAD_ROW_LIMIT = int(os.getenv("CSV_UPLOAD_ROW_LIMIT", "10000"))

# PostgREST's server-side ceiling on rows returned by ONE request
# (Supabase dashboard -> Settings -> API -> Max rows; 1000 on this
# project, read 2026-08-31).
#
# It is not ours to choose per query. PostgREST serves
# min(requested_limit, max_rows), so .limit(10000) still yields 1000 and
# a truncation guard written against the larger number can never fire —
# which is exactly what the 2026-08-30 follow-up guards did. Any alarm
# about a short read has to compare against THIS number.
#
# Raising it in the dashboard moves the cliff; it does not remove one.
# The durable fix is that no code decides "finished" from a list read.
SUPABASE_MAX_ROWS = int(os.getenv("SUPABASE_MAX_ROWS", "1000"))
MAX_CSV_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def monthly_limit_for_plan(plan: str) -> int:
    """Monthly send limit for a plan name — single source of truth so the
    settings API and enforcement agree. Unknown/None plan → free."""
    return {
        "pro": PRO_PLAN_MONTHLY_LIMIT,
        "starter": STARTER_PLAN_MONTHLY_LIMIT,
    }.get(plan, FREE_PLAN_MONTHLY_LIMIT)


# The panel that can explain the new ceiling. A list larger than the monthly
# quota is accepted in full and sent over several months, and 0.3.0 is the
# first build that says how many — an older panel implies the remainder
# clears at the next reset, which would be a promise we do not keep.
UPLOAD_LIMIT_MIN_CLIENT = (0, 3, 0)

# The first build that decides for itself whether a sign-in should ask for
# Mail.Read, and says so on the /auth/login URL. Everything older is silent
# on the question and must therefore keep the wide ask: a returning user on
# an older panel who was handed the narrow consent would lose reply
# detection, and their next refresh would request a scope they no longer
# hold (AADSTS65001, a dead sign-in).
FIRST_SIGNIN_MIN_CLIENT = (0, 3, 0)

# From this client on, a follow-up configured without Pro is SAVED
# (status 'locked') and answered 200 instead of 402. Older panels have
# no idea what 'locked' means and would read the 200 as "created" —
# the exact silent failure this feature exists to end — so they keep
# getting the 402 and its alert.
FOLLOWUP_LOCKED_MIN_CLIENT = (0, 3, 1)

# From this client on, the address column is found by header name OR by what
# the column contains. Below it, a header spelled exactly "email" is required,
# which is what every panel up to 0.3.2 enforces on its own side before
# uploading anything.
#
# The gate is here because the change has no upside for an older panel and a
# real downside. 0.3.2 refuses a file without a literal "email" header at the
# file picker, so it never sends one the old server would reject — the alias
# and content passes would only ever CHANGE which column an already-working
# file resolves to. A file headed "First Name,Personal Email,Email,Company"
# would have gone to the private addresses instead of the work ones, silently,
# with a 200 the panel has no way to question. Mail cannot be recalled.
#
# So an old panel keeps the parsing it was written against, exactly, and the
# new parsing arrives with the panel that needs it. Absent or unparseable
# reads as old, which is the safe half here as everywhere.
CSV_COLUMN_DETECT_MIN_CLIENT = (0, 3, 3)


def upload_limit_for_plan(plan: str, client_version: str | None = None) -> int:
    """Per-upload CSV row limit for a plan name.

    The CLIENT decides, not a switch we have to remember to throw. A panel
    that can explain a multi-month send gets the single ceiling; an older one
    keeps the per-plan limits it knows how to describe. Unknown or missing
    version reads as older, which is today's behaviour.

    This used to hang on UPLOAD_LIMIT_FOLLOWS_QUOTA alone, and that flag was
    owed a flip "once 0.3.0 is published on both stores and most people have
    updated" — a condition nothing in the system could evaluate and only a
    human could remember, weeks later, after two store reviews on someone
    else's schedule. The version is in the request already
    (X-Extension-Version, extension/background.js:910), so the question can
    simply be asked per call.

    The flag survives as a one-directional override: true means the new
    ceiling for everyone, including clients that cannot explain it. It can
    widen and never narrow, so leaving it alone is always safe and there is
    nothing to track.

    Read at call time, not import time, so every caller — the upload endpoint
    and /settings — agrees.
    """
    from utils.client_version import client_at_least

    if UPLOAD_LIMIT_FOLLOWS_QUOTA or client_at_least(
        client_version, UPLOAD_LIMIT_MIN_CLIENT
    ):
        return CSV_UPLOAD_ROW_LIMIT
    return {
        "pro": PRO_UPLOAD_ROW_LIMIT,
        "starter": STARTER_UPLOAD_ROW_LIMIT,
    }.get(plan, FREE_UPLOAD_ROW_LIMIT)

# 2s between sends ≈ 30 emails/min — under Microsoft's ~30 messages/minute
# throttle (Exchange Online), so we pace within the provider's limit instead
# of triggering 429s and account spam-flagging on large sends. Slower but
# safer for both throttling and deliverability.
SEND_DELAY_SECONDS = 2

# How soon after delivery a pixel fetch is treated as machinery rather than a
# person opening the email.
#
# Measured, not guessed. Hélène Carpentier's CBRE campaign on 2026-09-01/02
# produced 93 open events for 15 recipients — six each. The first fourteen
# arrived 9 to 16 seconds after their own send, one address five separate
# times (9s, 26s, 36s, 81s, 113s), every one of them from a generic desktop
# Chrome user-agent. The only fetches identifying a mail client
# ("ms-office") arrived at 65, 163, 166 and 202 seconds, from two people.
#
# She wrote: "I do not believe the 100% open rate is correct, as I have
# received so many out of office." She was right, and the evidence for it had
# been recorded since the feature shipped without anyone looking.
#
# 30s is deliberately conservative: it catches the scanner cluster with room
# to spare and leaves the earliest real client fetch (65s) untouched. A real
# open cannot be lost by being late; a false one is only ever early.
AUTOMATED_OPEN_WINDOW_SECONDS = int(
    os.getenv("AUTOMATED_OPEN_WINDOW_SECONDS", "30")
)

# User-agent fragments that identify a real mail client fetching remote
# images. A client naming itself is a real fetch even when it is fast, so
# these are never classed as automated.
MAIL_CLIENT_UA_MARKERS = ("ms-office", "microsoft outlook", "outlook-ios",
                          "outlook-android", "apple mail", "thunderbird")


# How often a running send asks whether it is still wanted.
#
# Both send paths mark their campaign 'sending' and then loop. Before
# 2026-09-01 neither ever re-read the row, so a Stop pressed mid-batch did
# nothing at all: the rest of the list went out and the close-out wrote a
# final status over the cancellation. The conditional close-out is what makes
# a stop stick; this check is what makes it prompt.
#
# The loop already waits SEND_DELAY_SECONDS between recipients, so one narrow
# select every ten of them costs nothing, and it bounds the overshoot after
# Stop to that many emails rather than the whole remaining list.
CANCEL_CHECK_EVERY = 10

# How many recipients may go out before the monthly quota is charged for them.
#
# It used to be the whole batch, charged once after the loop finished — and
# the loop is a FastAPI background task, so the end is not guaranteed to
# arrive. A Railway deploy or an OOM mid-send left every recipient already
# emailed and marked 'sent' uncharged: the durable per-contact state said
# they went out, the counter said they never did, and the resumed remainder
# was later billed against a quota that had never seen the first half.
#
# A SIGKILL runs no handler, so no except block can close that; only having
# already written the number can. 25 bounds the loss to at most 24 emails
# however the process dies, at one extra DB write per 25 sends — against the
# 2s SEND_DELAY_SECONDS between recipients, that is free.
QUOTA_CHARGE_BATCH = 25
RATE_LIMIT_WAIT_SECONDS = 60

# ── HTTPX timeouts for outbound calls ──
#
# httpx defaults to a 5-second connect timeout and *no* read timeout. A
# slow / unhealthy upstream (Microsoft Graph during regional incidents,
# MailerSend) could otherwise hang our worker thread indefinitely,
# blocking the queue. With concurrency=2, two hangs == zero throughput.
#
# We set explicit per-phase timeouts so:
#   - Connect timeout: 10s  → clearly distinguishes DNS/TCP issues from
#                              app-level slowness
#   - Read timeout:    30s  → Microsoft Graph sendMail typically returns
#                              in <2s; 30s gives a generous margin while
#                              still bounding worst-case wait
#   - Write timeout:   10s  → uploads are tiny (email payload <1MB)
#   - Pool timeout:    10s  → connection-pool acquisition
#
# Send paths (workers + immediate API send) and OAuth code-exchange
# both wrap their httpx clients with this default. AI generation has
# its own larger 30s overall timeout (Claude streaming).
import httpx as _httpx_for_timeout

OUTBOUND_HTTP_TIMEOUT = _httpx_for_timeout.Timeout(
    connect=10.0, read=30.0, write=10.0, pool=10.0
)
