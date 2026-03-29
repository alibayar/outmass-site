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

# ── Auth ──
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# ── Stripe ──
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_STANDARD_PRICE_ID = os.getenv("STRIPE_STANDARD_PRICE_ID", "")
STRIPE_PRO_PRICE_ID = os.getenv("STRIPE_PRO_PRICE_ID", "")
STRIPE_TEAM_PRICE_ID = os.getenv("STRIPE_TEAM_PRICE_ID", "")

# ── Redis / Celery ──
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── App ──
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "")

# ── Graph API ──
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

# ── AI ──
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ── Limits ──
FREE_PLAN_MONTHLY_LIMIT = 50
STANDARD_PLAN_MONTHLY_LIMIT = 5000
PRO_PLAN_MONTHLY_LIMIT = 10000
SEND_DELAY_SECONDS = 1
RATE_LIMIT_WAIT_SECONDS = 60
