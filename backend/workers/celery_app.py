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

# ── Startup checks, on the worker and the beat too ──
#
# utils/config_guard.py was written after the Railway WORKER service was found
# carrying TEST Stripe keys against the production database — and it ran only
# from main.py, i.e. on web, the one service that incident had not happened
# on. Importing config here also means a missing SUPABASE_URL or JWT_SECRET
# stops the worker at boot instead of at the first task.
#
# Inside its own try: a misconfigured alert channel must not stop the worker
# from sending mail, which has nothing to do with billing.
try:
    from utils.config_guard import run_startup_checks

    run_startup_checks()
except Exception:  # noqa: BLE001
    import logging

    logging.getLogger(__name__).exception("Startup checks could not run")

# ── PostHog for Celery workers ──
POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", "")
if POSTHOG_API_KEY:
    posthog.api_key = POSTHOG_API_KEY
    posthog.host = os.getenv("POSTHOG_HOST", "https://eu.i.posthog.com")

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
        # workers.email_worker was here until 2026-08-14. It POSTed to Graph,
        # marked the contact sent and bumped the campaign counter, and never
        # touched increment_sent_count — the one path that could put a
        # customer's email on the wire charging no quota and reporting
        # nothing. Nothing called it, but being registered here meant it was
        # one celery.send_task() from a shell away from being live. It was a
        # stub from before the real send loops existed ("MVP uses synchronous
        # send in campaigns.py — this is for future scaling"); the scaling
        # arrived and was built elsewhere, with quota, pacing, batching,
        # resume and daily caps. git history has it if it is ever wanted.
        "workers.followup_worker",
        "workers.scheduled_worker",
        "workers.daily_report",
        "workers.inactivity_nudge",
        "workers.reply_detector",
        "workers.green_report",
    ],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    # Redis command budget optimizations — see docs/plans or handoff for
    # the full reasoning. Short version: Upstash charges per command, and
    # Celery's default worker idle polling was burning ~500K commands/month
    # on empty queues before this was tuned.
    #
    # polling_interval=15: workers do one BRPOP every 15s instead of ~1s
    #   when the queue is idle. Worst-case task pickup delay grows from
    #   ~1s to ~15s, which is invisible for our workload (scheduled sends
    #   have minute-level precision; follow-ups hourly).
    # prefetch_multiplier=1: each worker holds one in-flight task instead
    #   of 4. Less aggressive polling, fairer load balancing across
    #   workers, and smaller blast radius on worker crash.
    # acks_late=True: worker ACKs the task AFTER it finishes (not on
    #   receive). If a worker dies mid-task, the broker re-delivers the
    #   task instead of losing it. All our scheduled tasks are idempotent
    #   (they filter by DB status, re-running does nothing new).
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_transport_options={
        "polling_interval": 15.0,
        "visibility_timeout": 3600,  # 1 hour — longest task we run is minutes
    },
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
        # Twice daily: 05:00 + 17:00 UTC = 08:00 + 20:00 Türkiye time (morning +
        # evening), so the operator sees the OutMass pulse at the start and end
        # of the day.
        "schedule": crontab(hour="5,17", minute=0),
    },
    "check-user-tokens": {
        "task": "workers.scheduled_worker.check_user_tokens",
        # 03:00 UTC daily — low traffic window, before EU/Americas workday
        # so users who need to reconnect see the banner before they try
        # to send their morning campaign.
        "schedule": crontab(hour=3, minute=0),
    },
    "reset-stuck-sending-campaigns": {
        "task": "workers.scheduled_worker.reset_stuck_sending_campaigns",
        # Hourly — caps mid-send-crash recovery latency at ~1h while
        # being cheap (single SELECT + a handful of UPDATEs).
        "schedule": 3600.0,
    },
    "anonymize-audit-log-ips": {
        "task": "workers.scheduled_worker.anonymize_audit_log_ips",
        # 03:30 UTC daily — after the token health check. Idempotent, so
        # even if it overlaps a previous run nothing breaks.
        "schedule": crontab(hour=3, minute=30),
    },
    "send-inactivity-nudges": {
        "task": "workers.inactivity_nudge.send_inactivity_nudges",
        # 04:00 UTC daily. Gated by INACTIVITY_NUDGE_ENABLED env var —
        # ships as a no-op until explicitly enabled.
        "schedule": crontab(hour=4, minute=0),
    },
    "send-inactivity-warnings-60d": {
        "task": "workers.inactivity_nudge.send_inactivity_warnings_60d",
        # Same flag, staggered 15 min apart so logs are readable.
        "schedule": crontab(hour=4, minute=15),
    },
    "send-inactivity-warnings-90d": {
        "task": "workers.inactivity_nudge.send_inactivity_warnings_90d",
        "schedule": crontab(hour=4, minute=30),
    },
    "expire-manual-promos": {
        "task": "workers.scheduled_worker.expire_manual_promos",
        # 04:45 UTC daily — after the inactivity tasks, off-peak. Idempotent
        # (reverting clears manual_promo_until) so re-runs are safe no-ops.
        "schedule": crontab(hour=4, minute=45),
    },
    "auto-resume-partial-campaigns": {
        "task": "workers.scheduled_worker.auto_resume_partial_campaigns",
        # 06:00 UTC daily — after the maintenance window. Flips quota-capped
        # 'partial' campaigns back to 'scheduled' once the owner's rolling
        # reset (or an upgrade) restored headroom; the regular send beat then
        # finishes them. Removes the manual Resume click after a quota cap.
        "schedule": crontab(hour=6, minute=0),
    },
    "green-check": {
        "task": "workers.green_report.send_green_report",
        # 07:00 UTC daily — after every other beat has run, so the report
        # describes a settled morning rather than one mid-flight.
        #
        # It runs HERE rather than on a laptop on purpose. The first version
        # was a local script and its first real run read an empty users table
        # from the wrong credentials, reported "0 accounts, ok" for every
        # check, and looked like health. Running it where the production
        # credentials already live removes the question of which ones it used.
        "schedule": crontab(hour=7, minute=0),
    },
    "detect-replies": {
        "task": "workers.reply_detector.detect_replies",
        # Daily at 05:00 UTC — after the morning send-window close
        # (when most replies for yesterday's batches will have arrived)
        # but still off-peak for our own infra.
        "schedule": crontab(hour=5, minute=0),
    },
}
