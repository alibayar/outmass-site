"""
OutMass — Configuration
All environment variables are read from here.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Supabase ──
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")

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
_default_cors = "chrome-extension://acdafphnihddolfhabbndfofheokckhl,http://localhost:3000,http://localhost:5173"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", _default_cors).split(",") if o.strip()]
if BACKEND_URL and BACKEND_URL not in CORS_ORIGINS:
    CORS_ORIGINS.append(BACKEND_URL)

# ── Azure AD ──
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "3b6a9f9b-cbb6-4dcb-a3b6-d993de74a1b5")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", f"{BACKEND_URL}/auth/callback")
AZURE_EXTENSION_ID = os.getenv("AZURE_EXTENSION_ID", "acdafphnihddolfhabbndfofheokckhl")
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

# ── Plan Limits ──
FREE_PLAN_MONTHLY_LIMIT = 50
STARTER_PLAN_MONTHLY_LIMIT = 2000
PRO_PLAN_MONTHLY_LIMIT = 10000

# Legacy alias (keep for back-compat until all code migrated)
STANDARD_PLAN_MONTHLY_LIMIT = STARTER_PLAN_MONTHLY_LIMIT

# AI generation limit (per month, Pro only)
AI_GENERATION_MONTHLY_LIMIT = 50

SEND_DELAY_SECONDS = 1
RATE_LIMIT_WAIT_SECONDS = 60
