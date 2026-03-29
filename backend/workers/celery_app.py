"""
OutMass — Celery Application Configuration
"""
import os
import ssl

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

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
}
