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
# Defaults cover the store build + the handoff-documented dev unpacked ID.
# Add more by setting `ALLOWED_EXTENSION_IDS=id1,id2,id3` on Railway.
_default_ext_ids = "adcfddainnkjomddlappnnbeomhlcbmm,acdafphnihddolfhabbndfofheokckhl"
ALLOWED_EXTENSION_IDS = [
    e.strip()
    for e in os.getenv("ALLOWED_EXTENSION_IDS", _default_ext_ids).split(",")
    if e.strip()
]
if AZURE_EXTENSION_ID and AZURE_EXTENSION_ID not in ALLOWED_EXTENSION_IDS:
    ALLOWED_EXTENSION_IDS.append(AZURE_EXTENSION_ID)
MS_AUTH_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_GRAPH_SCOPES = "https://graph.microsoft.com/Mail.Send https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read offline_access"

# ── Graph API ──
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

# ── PostHog ──
POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", "")
POSTHOG_HOST = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")

# ── AI ──
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── Telegram daily report + feedback alerts ──
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── MailerSend (transactional email) ──
MAILERSEND_API_KEY = os.getenv("MAILERSEND_API_KEY", "")
MAILERSEND_FROM_EMAIL = os.getenv("MAILERSEND_FROM_EMAIL", "support@getoutmass.com")
MAILERSEND_FROM_NAME = os.getenv("MAILERSEND_FROM_NAME", "OutMass Feedback")
MAILERSEND_TO_EMAIL = os.getenv("MAILERSEND_TO_EMAIL", "support@getoutmass.com")

# ── Plan Limits ──
FREE_PLAN_MONTHLY_LIMIT = 50
STARTER_PLAN_MONTHLY_LIMIT = 2000
PRO_PLAN_MONTHLY_LIMIT = 10000

# Legacy alias (keep for back-compat until all code migrated)
STANDARD_PLAN_MONTHLY_LIMIT = STARTER_PLAN_MONTHLY_LIMIT

# AI generation limit (per month, Pro only)
AI_GENERATION_MONTHLY_LIMIT = 50

# CSV upload limits (per upload, not cumulative)
FREE_UPLOAD_ROW_LIMIT = 100
STARTER_UPLOAD_ROW_LIMIT = 2_000
PRO_UPLOAD_ROW_LIMIT = 5_000
MAX_CSV_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

SEND_DELAY_SECONDS = 1
RATE_LIMIT_WAIT_SECONDS = 60
