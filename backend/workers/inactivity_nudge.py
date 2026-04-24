"""
OutMass — Inactivity Notification Worker

Three beat tasks, one per escalation tier, that email paid users who
have stopped logging in. None of these modify a Stripe subscription —
the actual cancel+refund path is operator-driven (user replies to
support@, we cancel via the Stripe dashboard).

Tiers:
  * 30 days — friendly "still using OutMass?" heads-up.
  * 60 days — firmer "please cancel if you don't need this" reminder.
  * 90 days — "we'll reach out directly" signal that we're planning
    to contact them for a manual cancel+refund offer.

All three gated by INACTIVITY_NUDGE_ENABLED so the code ships inert
and is flipped on only after manual email-template review.

Idempotency: each tier has its own *_sent_at column on users, and a
row is skipped if the stamp is more recent than last_activity_at.
When the user returns and goes inactive again, the stamp naturally
goes stale and a fresh tier-1 nudge fires.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from config import (
    INACTIVITY_NUDGE_DAYS,
    INACTIVITY_NUDGE_ENABLED,
    MAILERSEND_API_KEY,
    MAILERSEND_FROM_EMAIL,
    MAILERSEND_FROM_NAME,
)
from models import audit
from workers.celery_app import celery

logger = logging.getLogger(__name__)


STORE_URL = "https://chromewebstore.google.com/detail/outmass/adcfddainnkjomddlappnnbeomhlcbmm"
SUPPORT_EMAIL = "support@getoutmass.com"


# ── Tier definitions ──


@dataclass(frozen=True)
class _Tier:
    name: str
    threshold_days: int
    stamp_column: str
    subject: str
    build_html: callable  # (name: str | None, days: int) -> str
    audit_event: str


def _html_tier1(name: str | None, days: int) -> str:
    """30-day heads-up. Warm, no pressure."""
    greeting = f"Hi {name}," if name else "Hi,"
    return (
        "<div style='font-family:sans-serif;max-width:540px;margin:auto;color:#323130;'>"
        "<h2 style='color:#0078d4;'>Still using OutMass?</h2>"
        f"<p>{greeting}</p>"
        f"<p>We noticed you haven't opened OutMass in about {days} days. "
        "Just a quick heads-up: your paid subscription is still active and "
        "continues to be billed each month, regardless of whether you use "
        "the extension.</p>"
        "<p><b>If you're still planning to use OutMass</b>, no action needed — "
        f'you can <a href="{STORE_URL}">reinstall it here</a> if you removed it.</p>'
        "<p><b>If you don't need it anymore</b>, you can cancel anytime:</p>"
        "<ul style='padding-left:22px;'>"
        "<li>Open the OutMass sidebar → <em>Account</em> → <em>Manage Subscription</em>, or</li>"
        f'<li>Email us at <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a> '
        "and we'll cancel + refund the current period.</li>"
        "</ul>"
        "<p style='color:#888;font-size:12px;margin-top:28px;'>"
        "You're receiving this because you have an active paid OutMass "
        "subscription. This is a one-time nudge per inactive period.</p>"
        "<p style='color:#888;font-size:12px;'>— The OutMass team</p>"
        "</div>"
    )


def _html_tier2(name: str | None, days: int) -> str:
    """60-day firmer reminder. Still not a threat — explicit cancel path."""
    greeting = f"Hi {name}," if name else "Hi,"
    return (
        "<div style='font-family:sans-serif;max-width:540px;margin:auto;color:#323130;'>"
        "<h2 style='color:#0078d4;'>Still paying for OutMass without using it?</h2>"
        f"<p>{greeting}</p>"
        f"<p>You haven't logged into OutMass in around {days} days. "
        "Your paid subscription has continued to renew during this time. "
        "We don't want you paying for something you're not getting value from.</p>"
        "<p><b>Two simple options:</b></p>"
        "<ul style='padding-left:22px;'>"
        f'<li><b>Keep it</b> — <a href="{STORE_URL}">reinstall OutMass</a> '
        "(if needed) and we'll stop emailing you as soon as you log in.</li>"
        "<li><b>Cancel it</b> \u2014 reply to this email or contact "
        f'<a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a>'
        " and we'll cancel the subscription plus refund the current "
        "billing period.</li>"
        "</ul>"
        "<p style='color:#888;font-size:12px;margin-top:28px;'>"
        "If we don't hear back, we'll reach out one more time at the "
        "90-day mark before taking any further action.</p>"
        "<p style='color:#888;font-size:12px;'>— The OutMass team</p>"
        "</div>"
    )


def _html_tier3(name: str | None, days: int) -> str:
    """90-day final outreach. Commits to manual follow-up."""
    greeting = f"Hi {name}," if name else "Hi,"
    return (
        "<div style='font-family:sans-serif;max-width:540px;margin:auto;color:#323130;'>"
        "<h2 style='color:#0078d4;'>OutMass — a final check-in</h2>"
        f"<p>{greeting}</p>"
        f"<p>It's been about {days} days since you last used OutMass. "
        "We've reached out twice already and we don't want to keep "
        "charging you for something you clearly aren't using.</p>"
        "<p>Over the next few days, a member of our team will <b>contact "
        "you personally</b> to confirm whether you'd like to cancel your "
        "subscription and receive a prorated refund.</p>"
        "<p>If you'd like to skip that and handle it now, just reply to "
        f'this email or write to <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a>.</p>'
        "<p>Or, if you just haven't had time to use OutMass yet, "
        f'<a href="{STORE_URL}">reinstall it</a>'
        " and these emails stop automatically.</p>"
        "<p style='color:#888;font-size:12px;margin-top:28px;'>— The OutMass team</p>"
        "</div>"
    )


TIERS = (
    _Tier(
        name="30d_nudge",
        threshold_days=INACTIVITY_NUDGE_DAYS,  # 30
        stamp_column="inactivity_nudge_sent_at",
        subject="Still using OutMass?",
        build_html=_html_tier1,
        audit_event="inactivity_nudge_sent",
    ),
    _Tier(
        name="60d_warning",
        threshold_days=60,
        stamp_column="inactivity_warning_60d_sent_at",
        subject="Still paying for OutMass without using it?",
        build_html=_html_tier2,
        audit_event="inactivity_warning_60d_sent",
    ),
    _Tier(
        name="90d_warning",
        threshold_days=90,
        stamp_column="inactivity_warning_90d_sent_at",
        subject="OutMass — a final check-in",
        build_html=_html_tier3,
        audit_event="inactivity_warning_90d_sent",
    ),
)


# ── Shared email dispatch ──


def _send_email(email: str, subject: str, html: str) -> bool:
    """Returns True on successful send, False otherwise.
    Caller uses the return value to decide whether to stamp the
    sent-at timestamp; we don't stamp on failure so the beat task
    retries on the next run."""
    if not MAILERSEND_API_KEY or not email:
        return False
    payload = {
        "from": {"email": MAILERSEND_FROM_EMAIL, "name": MAILERSEND_FROM_NAME},
        "to": [{"email": email}],
        "subject": subject,
        "html": html,
    }
    try:
        resp = httpx.post(
            "https://api.mailersend.com/v1/email",
            headers={
                "Authorization": f"Bearer {MAILERSEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
        return 200 <= resp.status_code < 300
    except Exception as e:  # noqa: BLE001
        logger.warning("Inactivity email dispatch failed: %s", e)
        return False


# ── Finder ──


def _find_inactive_paid_users(db, tier: _Tier) -> list[dict]:
    """Paid users past the tier threshold, not yet stamped for this tier
    in the current inactive streak."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=tier.threshold_days)).isoformat()
    result = (
        db.table("users")
        .select(
            f"id, email, name, last_activity_at, {tier.stamp_column}"
        )
        .neq("plan", "free")
        .not_.is_("stripe_subscription_id", "null")
        .not_.is_("last_activity_at", "null")
        .lt("last_activity_at", cutoff)
        .limit(500)
        .execute()
    )
    rows = result.data or []
    fresh: list[dict] = []
    for r in rows:
        sent = r.get(tier.stamp_column)
        last = r.get("last_activity_at")
        if sent is None or (last and sent < last):
            fresh.append(r)
    return fresh


# ── Tier runner ──


def _run_tier(tier: _Tier) -> dict:
    """Process one escalation tier end-to-end."""
    if not INACTIVITY_NUDGE_ENABLED:
        return {"tier": tier.name, "skipped": "disabled", "notified": 0}

    from database import get_db

    db = get_db()
    targets = _find_inactive_paid_users(db, tier)
    if not targets:
        return {"tier": tier.name, "notified": 0, "considered": 0}

    notified = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for user in targets:
        try:
            last_dt = datetime.fromisoformat(
                user["last_activity_at"].replace("Z", "+00:00")
            )
            days_inactive = (datetime.now(timezone.utc) - last_dt).days
        except Exception:  # noqa: BLE001
            days_inactive = tier.threshold_days

        html = tier.build_html(user.get("name"), days_inactive)
        if not _send_email(user.get("email"), tier.subject, html):
            continue

        try:
            db.table("users").update(
                {tier.stamp_column: now_iso}
            ).eq("id", user["id"]).execute()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to stamp %s for user %s", tier.stamp_column, user["id"]
            )
            continue

        audit.emit(
            tier.audit_event,
            user_id=user["id"],
            email=user.get("email"),
            metadata={
                "days_inactive": days_inactive,
                "threshold": tier.threshold_days,
                "tier": tier.name,
            },
        )
        notified += 1

    return {"tier": tier.name, "notified": notified, "considered": len(targets)}


# ── Celery tasks — one per tier so they can be scheduled independently ──


@celery.task
def send_inactivity_nudges():
    """30-day tier. Retained name for backwards compat with the
    existing beat schedule entry."""
    return _run_tier(TIERS[0])


@celery.task
def send_inactivity_warnings_60d():
    return _run_tier(TIERS[1])


@celery.task
def send_inactivity_warnings_90d():
    return _run_tier(TIERS[2])
