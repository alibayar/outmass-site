"""
OutMass — Celery Application Configuration
"""
import os
import ssl
import sys
from pathlib import Path

# Ensure the backend/ directory is importable regardless of where Celery is
# invoked from. When Railway runs `celery -A workers.celery_app worker`
# from /app, the CWD is /app but Python does NOT automatically add it to
# sys.path when celery forks pool workers — which broke the deferred
# `from models import ...` imports inside task functions. Explicit path
# insert guarantees `models`, `routers`, etc. are always importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import posthog
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

# ── PostHog for Celery workers ──
POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", "")
if POSTHOG_API_KEY:
    posthog.api_key = POSTHOG_API_KEY
    posthog.host = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Upstash requires ssl_cert_reqs parameter in the URL for rediss://
broker_url = REDIS_URL
backend_url = REDIS_URL

if REDIS_URL.startswith("rediss://"):
    # Append ssl_cert_reqs=CERT_NONE if not already present
    separator = "&" if "?" in REDIS_URL else "?"
    if "ssl_cert_reqs" not in REDIS_URL:
        broker_url = REDIS_URL + separator + "ssl_cert_reqs=CERT_NONE"
        backend_url = REDIS_URL + separator + "ssl_cert_reqs=CERT_NONE"

celery = Celery(
    "outmass",
    broker=broker_url,
    backend=backend_url,
    include=[
        "workers.email_worker",
        "workers.followup_worker",
        "workers.scheduled_worker",
        "workers.daily_report",
    ],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

# SSL config for Upstash Redis (rediss:// URLs)
# Upstash Redis requires CERT_NONE because their rediss:// endpoint
# uses a certificate not in standard CA bundles.
# See: https://upstash.com/docs/redis/howto/celeryintegration
if REDIS_URL.startswith("rediss://"):
    celery.conf.update(
        broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
        redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    )

# Beat schedule
celery.conf.beat_schedule = {
    "process-followups-hourly": {
        "task": "workers.followup_worker.process_followups",
        "schedule": 3600.0,  # every hour
    },
    "process-scheduled-campaigns": {
        "task": "workers.scheduled_worker.process_scheduled_campaigns",
        "schedule": 300.0,  # every 5 minutes
    },
    "evaluate-ab-tests": {
        "task": "workers.scheduled_worker.evaluate_ab_tests",
        "schedule": 600.0,  # every 10 minutes
    },
    "daily-report": {
        "task": "workers.daily_report.send_daily_report",
        # 14:00 UTC daily — before US market open (09:30 EST), after EU lunch,
        # morning in Americas, afternoon in Europe, evening in Asia.
        "schedule": crontab(hour=14, minute=0),
    },
}
