"""
OutMass — Follow-up model helpers
"""

from datetime import datetime, timedelta, timezone

import logging

from config import SUPABASE_MAX_ROWS
from database import get_db

logger = logging.getLogger(__name__)


def create_followup(
    campaign_id: str,
    user_id: str,
    delay_days: int,
    subject: str,
    body: str,
    condition: str = "not_opened",
    status: str = "scheduled",
) -> dict:
    """Create a follow-up.

    `status='locked'` stores a configuration the account cannot run yet. The
    worker's queries select 'scheduled', so a locked row is inert — it sends
    nothing, is counted in no pending total, and waits to be activated.
    """
    scheduled_for = datetime.now(timezone.utc) + timedelta(days=delay_days)
    result = (
        get_db()
        .table("follow_ups")
        .insert(
            {
                "campaign_id": campaign_id,
                "user_id": user_id,
                "delay_days": delay_days,
                "subject": subject,
                "body": body,
                "condition": condition,
                "status": status,
                "scheduled_for": scheduled_for.isoformat(),
            }
        )
        .execute()
    )
    return result.data[0]


def get_campaign_followups(campaign_id: str) -> list[dict]:
    result = (
        get_db()
        .table("follow_ups")
        .select("*")
        .eq("campaign_id", campaign_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data


def count_due_immediately(campaign_id: str, delay_days: int) -> int:
    """How many recipients a follow-up activated NOW would go to at once.

    A follow-up is due per recipient at their own sent_at + delay_days. On a
    campaign that finished weeks ago every one of those moments is already in
    the past, so activating it is not scheduling anything — it is sending,
    immediately, to everyone. Nobody may discover that after the fact.

    An upper bound: it does not subtract people who have replied or already
    been bumped, both of which the worker excludes. Overstating the number is
    the safe direction for a confirmation prompt.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=delay_days)).isoformat()
    result = (
        get_db()
        .table("contacts")
        .select("id", count="exact")
        .eq("campaign_id", campaign_id)
        .eq("status", "sent")
        .eq("unsubscribed", False)
        .lte("sent_at", cutoff)
        .limit(1)
        .execute()
    )
    return result.count or 0


def get_pending_followups() -> list[dict]:
    """Get follow-ups where scheduled_for <= NOW() and status = 'scheduled'."""
    now = datetime.now(timezone.utc).isoformat()
    result = (
        get_db()
        .table("follow_ups")
        .select("*")
        .eq("status", "scheduled")
        .lte("scheduled_for", now)
        .execute()
    )
    return result.data


def get_bumped_contact_ids(followup_id: str) -> set[str]:
    """Contacts this follow-up has already emailed.

    A follow-up no longer runs once. On a paced campaign it trails the send,
    bumping each recipient on their own clock, so every run has to know who
    it has already covered — otherwise the people bumped on Monday are
    bumped again on Tuesday, from their own mailbox, which is the worst
    outcome this feature has available.

    Returned as a set because the caller does one membership test per
    candidate contact.
    """
    # Bounded explicitly, like every other large read in this codebase
    # (routers/campaigns.py uses the same ceiling for a campaign's contacts).
    # PostgREST applies a server-side maximum whether or not we ask for one,
    # and this is the query that must never come back short: a missing id
    # here reads as "not bumped yet", which is a second email from someone
    # else's mailbox.
    result = (
        get_db()
        .table("follow_up_sends")
        .select("contact_id")
        .eq("follow_up_id", followup_id)
        .limit(SUPABASE_MAX_ROWS)
        .execute()
    )
    rows = result.data or []
    if len(rows) >= SUPABASE_MAX_ROWS:
        # Fail CLOSED, not loudly. This set is the memory of who has already
        # been followed up; a contact missing from it reads as "not bumped
        # yet" and gets a second email from the customer's own mailbox. An
        # earlier version logged this and returned the truncated set anyway,
        # which is a warning in a log nobody is reading at the moment the
        # duplicate goes out.
        #
        # Raising skips this follow-up for this run and leaves it for the next
        # beat. That is a delay; the alternative is mail somebody twice.
        raise RuntimeError(
            f"follow-up {followup_id} has at least {SUPABASE_MAX_ROWS} recorded "
            f"bumps, so this read is at the server ceiling and cannot be "
            f"trusted as the full set. Refusing to compute who still needs a "
            f"follow-up from a partial memory."
        )
    return {row["contact_id"] for row in rows}


def record_bump(followup_id: str, contact_id: str) -> None:
    """Write down that this contact has been followed up.

    Called immediately after the send succeeds, never before: a row here
    that did not correspond to a delivered email would silently drop someone
    from the campaign's follow-up for good, and a missing row costs at most
    one duplicate that the primary key then refuses anyway.
    """
    (
        get_db()
        .table("follow_up_sends")
        .insert({"follow_up_id": followup_id, "contact_id": contact_id})
        .execute()
    )


def update_followup_status(followup_id: str, status: str):
    get_db().table("follow_ups").update({"status": status}).eq(
        "id", followup_id
    ).execute()


def delete_followup(followup_id: str, campaign_id: str = None):
    """Cancel a followup. If campaign_id provided, verify ownership (H-02 IDOR fix)."""
    query = get_db().table("follow_ups").update({"status": "cancelled"}).eq(
        "id", followup_id
    )
    if campaign_id:
        query = query.eq("campaign_id", campaign_id)
    query.execute()
