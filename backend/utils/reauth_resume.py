"""Put back the scheduled work a dead Microsoft token took away.

When a scheduled campaign runs and the refresh token is permanently dead,
scheduled_worker marks the campaign 'failed_auth' (and followup_worker does
the same to follow-ups). Before 2026-08-11 that was the end of it:
get_due_scheduled_campaigns selects status='scheduled', nothing anywhere read
'failed_auth' back — grep found two writes and zero reads — and reconnecting
did not bring it back. The campaign sat dead for ever and its recipients
never heard from the customer.

Meanwhile the reconnect email says scheduled campaigns "will pause instead of
sending". Pause implies resumption. This is what makes that true.

Bounded on purpose, and the bound reads correctly for both campaign shapes:

  * A one-shot campaign's scheduled_for is the moment it was meant to go out.
  * A daily-capped multi-day campaign rolls scheduled_for forward 24h after
    every batch (scheduled_worker's daily-cap branch), so its scheduled_for
    is the day it was last alive — not the day it was created. A month-long
    drip stranded yesterday is therefore recent, which is correct.

Resuming does NOT flatten a multi-day campaign into one blast: the worker
re-applies daily_send_cap on every run, so it simply continues at its own
rate. Nothing here touches scheduled_for or daily_send_cap.
"""
import logging
from datetime import datetime, timedelta, timezone

from config import AUTH_RESUME_MAX_AGE_DAYS

logger = logging.getLogger(__name__)

_STRANDED = "failed_auth"
_LIVE = "scheduled"


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _split(rows: list[dict], cutoff: datetime) -> tuple[list, list]:
    """(recent enough to resume, too old to resume).

    A row with no scheduled_for at all counts as too old: we cannot tell when
    it was meant to run, and guessing in the direction of sending is the
    wrong guess.
    """
    fresh, stale = [], []
    for r in rows:
        when = _parse(r.get("scheduled_for"))
        (fresh if when and when >= cutoff else stale).append(r)
    return fresh, stale


def resume_auth_stranded_work(user_id: str) -> dict:
    """Best-effort. Called from both reconnect paths; must never be able to
    break a sign-in, because a sign-in that fails is worse than a campaign
    that stays paused."""
    result = {"campaigns": 0, "followups": 0, "skipped_old": 0}
    if not user_id:
        return result

    try:
        from database import get_db

        db = get_db()
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=AUTH_RESUME_MAX_AGE_DAYS
        )
        stale_all: list[tuple[str, dict]] = []

        for table, key in (("campaigns", "campaigns"), ("follow_ups", "followups")):
            rows = (
                db.table(table)
                .select("id, scheduled_for")
                .eq("user_id", user_id)
                .eq("status", _STRANDED)
                .execute()
            ).data or []
            fresh, stale = _split(rows, cutoff)
            for row in fresh:
                db.table(table).update({"status": _LIVE}).eq(
                    "id", row["id"]
                ).execute()
            result[key] = len(fresh)
            stale_all.extend((table, r) for r in stale)

        result["skipped_old"] = len(stale_all)

        if result["campaigns"] or result["followups"]:
            logger.info(
                "Reconnect resumed %s campaign(s) and %s follow-up(s) for %s",
                result["campaigns"], result["followups"], user_id,
            )

        if stale_all:
            # Reported rather than silently dropped: the whole failure this
            # module exists to fix was silence. An operator seeing this can
            # still resume it by hand.
            _alert_stale(user_id, stale_all)
    except Exception:  # noqa: BLE001
        logger.exception("resume_auth_stranded_work failed for %s", user_id)

    return result


def _alert_stale(user_id: str, stale: list[tuple[str, dict]]) -> None:
    try:
        from routers.billing import _telegram_alert

        lines = "\n".join(
            f"- {table} {row['id']} (scheduled_for {row.get('scheduled_for')})"
            for table, row in stale[:10]
        )
        _telegram_alert(
            "⏸️ OutMass reconnect left older work paused\n\n"
            f"User: {user_id}\n"
            f"{len(stale)} item(s) older than {AUTH_RESUME_MAX_AGE_DAYS} days "
            "were NOT resumed, to avoid surprise-sending a stale list.\n\n"
            f"{lines}\n\n"
            "Resume by hand if the customer still wants them."
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not report stale stranded work for %s", user_id)
