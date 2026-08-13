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

The copy lives in emails/strings/<lang>.json and is rendered into both a
text and an HTML part by emails.render — these three were HTML-only until
2026-08-14, which is worse for spam scoring and shows up as an empty message
in a text-only client.
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
    MAILERSEND_PERSON_FROM_NAME,
)
from emails import SUPPORT_EMAIL, render  # noqa: F401 — SUPPORT_EMAIL re-exported
from models import audit
from workers.celery_app import celery

logger = logging.getLogger(__name__)


# There is deliberately no store URL in these emails any more.
#
# It used to be the Chrome Web Store link, sent to everyone. We cannot tell
# a Chrome install from an Edge one at this point: install_source is captured
# for PostHog (auth.py) but never stored on the users row, so the worker has
# nothing to branch on — and Edge is a real channel, so an Edge customer
# would have been pointed at the wrong store.
#
# The 30-day mail no longer needs one at all: inactivity is not uninstalling,
# and the recipient most likely still has the extension (2026-08-10: the one
# customer this would have reached had been silent for 33 days and had
# nonetheless auto-updated through four releases to 0.2.0). Telling them to
# reinstall describes something that did not happen.
#
# The later tiers say "the browser store you installed it from" instead: no
# link, but nothing that can be wrong either. Put a link back only once
# install_source lives on the user row.


# ── Tier definitions ──


@dataclass(frozen=True)
class _Tier:
    name: str
    threshold_days: int
    stamp_column: str
    #: Key into emails.catalog.TEMPLATES. Subject and body both come from
    #: there, in whichever language the user reads.
    template: str
    audit_event: str


# Why these three read the way they do. The words moved to the string table
# on 2026-08-14; the reasoning did not, and it is the reason nobody should
# tidy them into something brisker.
#
#   30d — warm, no pressure, and it ASKS. The first version offered two
#     doors, keep or cancel, and never asked why they stopped. For a product
#     with a handful of paying customers that is the most expensive omission
#     in the whole sequence: the answer is worth more than the subscription.
#     Someone who tried it hard for one day and never returned hit
#     something, and only they know what.
#
#   60d — firmer. Still not a threat: an explicit cancel path, and an
#     explicit invitation to tell us what went wrong instead.
#
#   90d — promises nothing it cannot keep. The first version said a member
#     of the team would contact them personally. There is one person here,
#     and a promise of manual outreach is the kind that quietly goes unkept —
#     the failure mode this whole sequence exists to avoid. "We will write to
#     you once more" was the proposed replacement, but this IS the last tier:
#     there is nothing after 90 days, so that would have been the same
#     unkeepable shape in gentler words. Saying the emails stop here is both
#     true and kinder — it tells them the nagging ends.

TIERS = (
    _Tier(
        name="30d_nudge",
        threshold_days=INACTIVITY_NUDGE_DAYS,  # 30
        stamp_column="inactivity_nudge_sent_at",
        template="inactivity_30d_nudge",
        audit_event="inactivity_nudge_sent",
    ),
    _Tier(
        name="60d_warning",
        threshold_days=60,
        stamp_column="inactivity_warning_60d_sent_at",
        template="inactivity_60d_warning",
        audit_event="inactivity_warning_60d_sent",
    ),
    _Tier(
        name="90d_warning",
        threshold_days=90,
        stamp_column="inactivity_warning_90d_sent_at",
        template="inactivity_90d_warning",
        audit_event="inactivity_warning_90d_sent",
    ),
)


# ── Shared email dispatch ──


def _send_email(email: str, subject: str, text: str, html: str) -> bool:
    """Returns True on successful send, False otherwise.
    Caller uses the return value to decide whether to stamp the
    sent-at timestamp; we don't stamp on failure so the beat task
    retries on the next run."""
    if not MAILERSEND_API_KEY or not email:
        return False
    payload = {
        # Not MAILERSEND_FROM_NAME — see the rationale on the constant in
        # config.py. Short version: that one belongs to the feedback form,
        # which mails US.
        "from": {"email": MAILERSEND_FROM_EMAIL, "name": MAILERSEND_PERSON_FROM_NAME},
        "to": [{"email": email}],
        "subject": subject,
        "text": text,
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
            f"id, email, name, preferred_language, last_activity_at, "
            f"{tier.stamp_column}"
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

        msg = render(
            tier.template,
            lang=user.get("preferred_language"),
            name=user.get("name"),
            days=days_inactive,
        )
        if not _send_email(user.get("email"), msg.subject, msg.text, msg.html):
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
