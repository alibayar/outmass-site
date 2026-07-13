"""
OutMass — Daily Report Worker
Sends a daily summary (users, MRR, email activity) to Telegram.
Runs at 14:00 UTC (before US markets open, good global window).
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from config import (
    POSTHOG_API_HOST,
    POSTHOG_PERSONAL_API_KEY,
    POSTHOG_PROJECT_ID,
    REPORT_HEALTH_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from database import get_db
from workers.celery_app import celery

logger = logging.getLogger(__name__)

# Plan prices (must stay in sync with Stripe)
PRICE_STARTER = 9
PRICE_PRO = 19

# Failure-class telemetry events the 12h error check scans (they live in
# PostHog, not Supabase). HARD ones flag the section ⚠️; INFO ones are shown
# but don't alarm — a lone oauth_failed is usually just a user closing the
# Microsoft popup, and uninstalls are churn signal rather than breakage.
HARD_ERROR_EVENTS = [
    "$exception",
    "send_failed",
    "csv_upload_failed",
    "test_send_failed",
    "ai_email_generate_failed",
]
INFO_ERROR_EVENTS = ["oauth_failed", "extension_uninstall"]


def _error_check_lines() -> list[str]:
    """The "any errors in the last 12h?" section, from PostHog. Never raises —
    the report must go out even when the check itself is broken."""
    if not POSTHOG_PERSONAL_API_KEY:
        return ["🩺 Errors (12h): check not configured"]

    quoted = ", ".join(f"'{e}'" for e in HARD_ERROR_EVENTS + INFO_ERROR_EVENTS)
    hogql = (
        "SELECT event, count() AS n, count(DISTINCT distinct_id) AS users "
        "FROM events WHERE timestamp >= now() - INTERVAL 12 HOUR "
        f"AND event IN ({quoted}) GROUP BY event ORDER BY n DESC"
    )
    try:
        resp = httpx.post(
            f"{POSTHOG_API_HOST}/api/projects/{POSTHOG_PROJECT_ID}/query/",
            headers={"Authorization": f"Bearer {POSTHOG_PERSONAL_API_KEY}"},
            json={"query": {"kind": "HogQLQuery", "query": hogql}},
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.warning(
                "PostHog error-check returned %s: %s",
                resp.status_code,
                resp.text[:200],
            )
            return ["🩺 Errors (12h): check unavailable"]
        rows = resp.json().get("results") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("PostHog error-check failed: %s", e)
        return ["🩺 Errors (12h): check unavailable"]

    if not rows:
        return ["🩺 Errors (12h): ✅ none"]

    has_hard = any(r[0] in HARD_ERROR_EVENTS for r in rows)
    lines = [
        "🩺 Errors (12h): ⚠️" if has_hard else "🩺 Errors (12h): ✅ no hard errors"
    ]
    for i, row in enumerate(rows):
        event, n, users = row[0], int(row[1]), int(row[2])
        branch = "└─" if i == len(rows) - 1 else "├─"
        info = "" if event in HARD_ERROR_EVENTS else " (info)"
        plural = "s" if users != 1 else ""
        lines.append(f"{branch} {event} ×{n} ({users} user{plural}){info}")
    return lines


def _health_line() -> list[str]:
    """Optional "is the API up" ping. Empty when not configured. Never raises."""
    if not REPORT_HEALTH_URL:
        return []
    try:
        resp = httpx.get(REPORT_HEALTH_URL, timeout=8.0)
        if resp.status_code == 200:
            return ["🌐 API: ✅ up"]
        return [f"🌐 API: 🔴 HTTP {resp.status_code}"]
    except Exception as e:  # noqa: BLE001
        logger.warning("Report health ping failed: %s", e)
        return ["🌐 API: 🔴 unreachable"]


def _count(query):
    """Return length of data from a Supabase query result."""
    result = query.execute()
    return len(result.data or [])


def build_report() -> str:
    """Build the daily report as a Telegram-friendly plain-text message."""
    db = get_db()
    now = datetime.now(timezone.utc)
    today = now.date()
    today_iso = today.isoformat()
    d7_iso = (now - timedelta(days=7)).isoformat()
    d30_iso = (now - timedelta(days=30)).isoformat()
    # Morning (05:00 UTC run) vs evening (17:00 UTC run); TRT = UTC+3.
    part = "Morning" if now.hour < 12 else "Evening"
    trt = (now + timedelta(hours=3)).strftime("%H:%M")

    # User counts
    total_users = _count(db.table("users").select("id"))
    new_today = _count(
        db.table("users").select("id").gte("created_at", today_iso)
    )
    free = _count(db.table("users").select("id").eq("plan", "free"))
    starter = _count(db.table("users").select("id").eq("plan", "starter"))
    pro = _count(db.table("users").select("id").eq("plan", "pro"))

    # Engagement + conversions
    active_7d = _count(
        db.table("users").select("id").gte("last_activity_at", d7_iso)
    )
    active_30d = _count(
        db.table("users").select("id").gte("last_activity_at", d30_iso)
    )
    new_paid_today = _count(
        db.table("users")
        .select("id")
        .in_("plan", ["starter", "pro"])
        .gte("plan_updated_at", today_iso)
    )

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
        f"📊 OutMass {part} Report — {today_iso} · {trt} TRT",
        "",
        "👥 Users",
        f"├─ Total: {total_users} (+{new_today} today)",
        f"├─ Active: {active_7d} (7d) · {active_30d} (30d)",
        f"├─ Free: {free}",
        f"├─ Starter: {starter}",
        f"└─ Pro: {pro}",
        "",
        f"💰 MRR: ${mrr}/mo (+{new_paid_today} paid today)",
        f"├─ Starter: {starter} × ${PRICE_STARTER} = ${starter * PRICE_STARTER}",
        f"└─ Pro: {pro} × ${PRICE_PRO} = ${pro * PRICE_PRO}",
        "",
        "📧 Activity (today, UTC)",
        f"├─ Emails sent: {sent}",
        f"├─ Opens: {opens} ({open_rate}%)",
        f"└─ Clicks: {clicks} ({click_rate}%)",
        "",
    ]
    lines += _error_check_lines()
    lines += _health_line()
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
