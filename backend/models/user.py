"""
OutMass — User model helpers
"""

import logging
from datetime import datetime, timedelta, timezone

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


def maybe_touch_activity(user: dict) -> None:
    """Bump last_activity_at if the current value is stale.

    Called from the auth dependency on every authenticated request.
    Mutates the passed-in dict so downstream handlers see the fresh
    timestamp without a re-fetch.
    """
    if _is_activity_fresh(user.get("last_activity_at")):
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        get_db().table("users").update(
            {"last_activity_at": now}
        ).eq("id", user["id"]).execute()
        user["last_activity_at"] = now
    except Exception:  # noqa: BLE001
        logger.exception("maybe_touch_activity failed for user %s", user.get("id"))


def increment_sent_count(user_id: str, count: int = 1):
    """Increment the user's monthly sent count atomically."""
    # C-05: Use RPC for atomic increment to prevent race conditions
    try:
        get_db().rpc(
            "increment_user_sent_count",
            {"user_id_input": user_id, "amount": count},
        ).execute()
    except Exception:
        # Fallback to non-atomic if RPC doesn't exist yet
        user = get_by_id(user_id)
        if not user:
            return
        new_count = user.get("emails_sent_this_month", 0) + count
        get_db().table("users").update(
            {"emails_sent_this_month": new_count}
        ).eq("id", user_id).execute()
