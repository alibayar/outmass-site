"""
OutMass — User model helpers
"""

import calendar
import logging
from datetime import date, datetime, timedelta, timezone

from database import get_db

logger = logging.getLogger(__name__)

# last_activity_at is written at most once per ACTIVITY_TOUCH_INTERVAL
# to avoid a DB write on every single authenticated request. The
# inactivity-detection beat task (Phase 5+) only cares about
# day-level freshness, so a 15-minute resolution is plenty.
_ACTIVITY_TOUCH_INTERVAL = timedelta(minutes=15)


def find_by_microsoft_id(microsoft_id: str) -> dict | None:
    """Find a user by their Microsoft account ID."""
    result = (
        get_db()
        .table("users")
        .select("*")
        .eq("microsoft_id", microsoft_id)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def upsert_user(microsoft_id: str, email: str, name: str) -> dict:
    """Create or update a user. Returns the user row."""
    existing = find_by_microsoft_id(microsoft_id)

    if existing:
        result = (
            get_db()
            .table("users")
            .update({"email": email, "name": name})
            .eq("microsoft_id", microsoft_id)
            .execute()
        )
        return result.data[0]

    result = (
        get_db()
        .table("users")
        .insert(
            {
                "microsoft_id": microsoft_id,
                "email": email,
                "name": name,
                "plan": "free",
                "emails_sent_this_month": 0,
            }
        )
        .execute()
    )
    return result.data[0]


def get_by_id(user_id: str) -> dict | None:
    result = (
        get_db()
        .table("users")
        .select("*")
        .eq("id", user_id)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def touch_login(user_id: str) -> None:
    """Record a fresh JWT issue on the users row. Called once per login,
    so it's cheap to write unconditionally. Never raises — a failure
    here must not block the actual login.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        get_db().table("users").update({
            "last_login_at": now,
            "last_activity_at": now,
        }).eq("id", user_id).execute()
    except Exception:  # noqa: BLE001
        logger.exception("touch_login failed for user %s", user_id)


def _is_activity_fresh(last_activity_iso: str | None) -> bool:
    """True if last_activity_at is recent enough to skip a DB write.

    Malformed / missing timestamps count as stale so we err on the side
    of writing — the beat task that consumes this field would otherwise
    never see new activity.
    """
    if not last_activity_iso:
        return False
    try:
        last = datetime.fromisoformat(last_activity_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return (datetime.now(timezone.utc) - last) < _ACTIVITY_TOUCH_INTERVAL


_MAX_VERSION_LEN = 32  # semver + suffix is well under this; defensive cap


def _is_valid_version(v: str | None) -> str | None:
    """Sanitize a version string: must be non-empty, ASCII semver charset
    (alphanumerics + ``.-+_``), capped at 32 chars. Returns the cleaned
    value or None.

    Charset is checked on the full input BEFORE truncation, so a 50-char
    input ending in a bad character is rejected entirely (not silently
    truncated to a clean-looking prefix)."""
    if not v or not isinstance(v, str):
        return None
    candidate = v.strip()
    if not candidate:
        return None
    if not all(c.isalnum() or c in ".-+_" for c in candidate):
        return None
    return candidate[:_MAX_VERSION_LEN]


def maybe_touch_activity(user: dict, extension_version: str | None = None) -> None:
    """Bump last_activity_at if stale, and/or update last_seen_extension_version
    if it changed.

    Called from the auth dependency on every authenticated request. Mutates
    the passed-in dict so downstream handlers see the fresh values without
    a re-fetch.
    """
    activity_fresh = _is_activity_fresh(user.get("last_activity_at"))
    cleaned_version = _is_valid_version(extension_version)
    version_changed = (
        cleaned_version is not None
        and cleaned_version != user.get("last_seen_extension_version")
    )

    if activity_fresh and not version_changed:
        return

    updates: dict = {}
    if not activity_fresh:
        now = datetime.now(timezone.utc).isoformat()
        updates["last_activity_at"] = now
        user["last_activity_at"] = now  # mutate so downstream sees fresh
    if version_changed:
        updates["last_seen_extension_version"] = cleaned_version
        user["last_seen_extension_version"] = cleaned_version

    if not updates:
        return
    try:
        get_db().table("users").update(updates).eq("id", user["id"]).execute()
    except Exception:  # noqa: BLE001
        logger.exception("maybe_touch_activity failed for user %s", user.get("id"))


def increment_sent_count(user_id: str, count: int = 1):
    """Increment the user's sent counters atomically.

    Maintains TWO counters: emails_sent_this_month (the quota counter,
    reset each billing-anchored month) and emails_sent_total (lifetime,
    never reset — the operator's tracking metric).
    """
    # C-05: Use RPC for atomic increment to prevent race conditions.
    # Migration 021 makes the RPC bump both counters.
    try:
        get_db().rpc(
            "increment_user_sent_count",
            {"user_id_input": user_id, "amount": count},
        ).execute()
    except Exception:
        # Fallback to non-atomic if the RPC doesn't exist / errors. Log it —
        # a permanently-failing RPC (e.g. a signature-mismatch overload after
        # a migration) would otherwise silently reintroduce the C-05 race.
        logger.warning(
            "increment_user_sent_count RPC failed; using non-atomic fallback",
            exc_info=True,
        )
        user = get_by_id(user_id)
        if not user:
            return
        try:
            get_db().table("users").update(
                {
                    "emails_sent_this_month": user.get("emails_sent_this_month", 0) + count,
                    "emails_sent_total": user.get("emails_sent_total", 0) + count,
                }
            ).eq("id", user_id).execute()
        except Exception:
            # emails_sent_total may not exist yet (migration 021 not applied).
            # NEVER lose the quota increment over the lifetime counter.
            get_db().table("users").update(
                {"emails_sent_this_month": user.get("emails_sent_this_month", 0) + count}
            ).eq("id", user_id).execute()


def _add_months(d: date, months: int) -> date:
    """`d` plus N calendar months, clamping the day to the target month's
    length (Jan 31 + 1mo → Feb 28/29) — mirrors how Stripe anchors monthly
    billing. Always call with the ORIGINAL anchor date so the day doesn't
    drift after a clamp (Jan 31 + 2mo = Mar 31, not Mar 28)."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def check_monthly_reset(user: dict, today: date | None = None):
    """Reset the quota counters when the user's billing-anchored month rolls
    over.

    The quota period is a ROLLING month from month_reset_date (set at signup
    and re-anchored at each paid checkout) — NOT the calendar month. A Starter
    who pays on the 25th gets exactly one quota-month per billed month; the
    old calendar rule handed out a bonus reset every 1st.

    Mutates the passed-in dict so callers (login, /send gate, workers) see the
    fresh values without a re-fetch. emails_sent_total is deliberately NEVER
    touched here. `today` is injectable for tests only.
    """
    reset_date = user.get("month_reset_date")
    if not reset_date:
        return
    if isinstance(reset_date, str):
        reset_date = date.fromisoformat(reset_date)
    if today is None:
        today = datetime.now(timezone.utc).date()

    if today < _add_months(reset_date, 1):
        return  # still inside the current quota month

    # Advance in whole months FROM THE ORIGINAL anchor (day preserved even
    # across a long absence): anchor the 25th + first login two periods later
    # → new anchor is still a 25th, of the most recent elapsed period.
    months = 1
    while _add_months(reset_date, months + 1) <= today:
        months += 1
    new_anchor = _add_months(reset_date, months)

    get_db().table("users").update(
        {
            "emails_sent_this_month": 0,
            "ai_generations_this_month": 0,
            "month_reset_date": new_anchor.isoformat(),
        }
    ).eq("id", user["id"]).execute()
    user["emails_sent_this_month"] = 0
    user["ai_generations_this_month"] = 0
    user["month_reset_date"] = new_anchor.isoformat()
