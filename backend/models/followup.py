"""
OutMass — Follow-up model helpers
"""

from datetime import datetime, timedelta, timezone

from database import get_db


def create_followup(
    campaign_id: str,
    user_id: str,
    delay_days: int,
    subject: str,
    body: str,
    condition: str = "not_opened",
) -> dict:
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
                "status": "scheduled",
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
