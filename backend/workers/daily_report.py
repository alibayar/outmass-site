"""
OutMass — Daily Report Worker
Sends a daily summary (users, MRR, email activity) to Telegram.
Runs at 14:00 UTC (before US markets open, good global window).
"""

import logging
from datetime import datetime, timezone

import httpx

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from database import get_db
from workers.celery_app import celery

logger = logging.getLogger(__name__)

# Plan prices (must stay in sync with Stripe)
PRICE_STARTER = 9
PRICE_PRO = 19


def _count(query):
    """Return length of data from a Supabase query result."""
    result = query.execute()
    return len(result.data or [])


def build_report() -> str:
    """Build the daily report as a Telegram-friendly plain-text message."""
    db = get_db()
    today = datetime.now(timezone.utc).date()
    today_iso = today.isoformat()

    # User counts
    total_users = _count(db.table("users").select("id"))
    new_today = _count(
        db.table("users").select("id").gte("created_at", today_iso)
    )
    free = _count(db.table("users").select("id").eq("plan", "free"))
    starter = _count(db.table("users").select("id").eq("plan", "starter"))
    pro = _count(db.table("users").select("id").eq("plan", "pro"))

    # MRR
    mrr = starter * PRICE_STARTER + pro * PRICE_PRO

    # Email activity today
    sent = _count(
        db.table("events")
        .select("id")
        .eq("event_type", "sent")
        .gte("created_at", today_iso)
    )
    opens = _count(
        db.table("events")
        .select("id")
        .eq("event_type", "open")
        .gte("created_at", today_iso)
    )
    clicks = _count(
        db.table("events")
        .select("id")
        .eq("event_type", "click")
        .gte("created_at", today_iso)
    )

    # Rates (handle divide-by-zero)
    if sent > 0:
        open_rate = round(opens / sent * 100, 1)
        click_rate = round(clicks / sent * 100, 1)
    else:
        open_rate = 0.0
        click_rate = 0.0

    # Build message
    lines = [
        f"📊 OutMass Daily Report — {today_iso}",
        "",
        "👥 Users",
        f"├─ Total: {total_users} (+{new_today} today)",
        f"├─ Free: {free}",
        f"├─ Starter: {starter}",
        f"└─ Pro: {pro}",
        "",
        f"💰 MRR: ${mrr}/mo",
        f"├─ Starter: {starter} × ${PRICE_STARTER} = ${starter * PRICE_STARTER}",
        f"└─ Pro: {pro} × ${PRICE_PRO} = ${pro * PRICE_PRO}",
        "",
        "📧 Activity (today, UTC)",
        f"├─ Emails sent: {sent}",
        f"├─ Opens: {opens} ({open_rate}%)",
        f"└─ Clicks: {clicks} ({click_rate}%)",
    ]
    return "\n".join(lines)


@celery.task(name="workers.daily_report.send_daily_report")
def send_daily_report():
    """Build and send the daily report to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.info("Telegram not configured, skipping daily report")
        return "skipped"

    try:
        message = build_report()
    except Exception as e:
        logger.exception("Failed to build daily report: %s", e)
        return "build_failed"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = httpx.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": "true",
            },
            timeout=10.0,
        )
        if resp.status_code != 200:
            logger.error(
                "Telegram API returned %s: %s", resp.status_code, resp.text[:200]
            )
            return "telegram_error"
    except httpx.HTTPError as e:
        logger.exception("Telegram request failed: %s", e)
        return "network_error"

    logger.info("Daily report sent successfully")
    return "sent"
