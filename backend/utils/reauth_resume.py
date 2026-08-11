"""Put back the scheduled work a dead Microsoft token took away.

When a scheduled campaign runs and the refresh token is permanently dead,
scheduled_worker marks the campaign 'failed_auth' (and followup_worker does
the same to follow-ups). Before 2026-08-11 that was the end of it:
get_due_scheduled_campaigns selects status='scheduled', nothing anywhere read
'failed_auth' back — three write sites, zero reads — and reconnecting
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
    result = {"campaigns": 0, "followups": 0, "ab_tests": 0, "skipped_old": 0}
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
            q = (
                db.table(table)
                .select("id, scheduled_for")
                .eq("user_id", user_id)
                .eq("status", _STRANDED)
            )
            if table == "campaigns":
                # Archive is the ONLY control on a paused row — there is no
                # cancel-campaign endpoint — so a user who decides the list
                # has gone stale archives it. While failed_auth was terminal
                # that was an effective stop; now that reconnecting revives
                # things, sending a campaign the user filed away would be the
                # exact surprise this module's bound exists to prevent.
                # follow_ups has no archived column.
                q = q.eq("archived", False)
            rows = (q.execute()).data or []
            fresh, stale = _split(rows, cutoff)
            for row in fresh:
                db.table(table).update({"status": _LIVE}).eq(
                    "id", row["id"]
                ).execute()
            result[key] = len(fresh)
            stale_all.extend((table, r) for r in stale)

        # A/B campaigns strand in TWO tables: evaluate_ab_tests writes
        # failed_auth to ab_tests AND to the campaign row. Recovering only
        # the campaign leaves the winner phase permanently unreachable,
        # because evaluate_ab_tests re-queries status='awaiting_winner' and
        # nothing ever puts it back.
        #
        # This was missed when the module was written because the grep that
        # found the write sites piped through `grep -v test` — and the line
        # reads `ab_test["campaign_id"], {"status": "failed_auth"}`, so the
        # variable name matched the filter meant for test FILES. Three write
        # sites, not the two the docstring claimed.
        #
        # Judged on created_at: an A/B campaign is always a send-now
        # campaign, so its scheduled_for is NULL and the freshness split
        # would file every one of them as stale.
        # select("*") rather than naming created_at: ab_tests is not created
        # by any migration in this repo — it was made directly in Supabase —
        # so the column set cannot be verified from here, and naming a column
        # that does not exist is a PostgREST error that the outer except would
        # swallow, leaving A/B recovery silently doing nothing. With "*" the
        # query always succeeds; a missing created_at then reads as None and
        # _split files the row as stale, which alerts an operator instead of
        # surprise-sending. Wrong in the safe direction, and never quiet.
        ab_rows = (
            db.table("ab_tests")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", _STRANDED)
            .execute()
        ).data or []
        ab_fresh, ab_stale = _split(
            [{"id": r["id"], "scheduled_for": r.get("created_at")} for r in ab_rows],
            cutoff,
        )
        for row in ab_fresh:
            # Back to the winner phase, not to 'sent': the strand happens
            # BEFORE any winner-phase send, contacts are still pending, and
            # the next evaluate_ab_tests beat re-picks the winner and writes
            # the campaign row's final status itself.
            db.table("ab_tests").update({"status": "awaiting_winner"}).eq(
                "id", row["id"]
            ).execute()
        result["ab_tests"] = len(ab_fresh)
        stale_all.extend(("ab_tests", r) for r in ab_stale)

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
