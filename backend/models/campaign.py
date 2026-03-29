"""
OutMass — Campaign model helpers
"""

from database import get_db


def create_campaign(
    user_id: str,
    name: str,
    subject: str,
    body: str,
    scheduled_for: str | None = None,
) -> dict:
    data = {
        "user_id": user_id,
        "name": name,
        "subject": subject,
        "body": body,
        "status": "scheduled" if scheduled_for else "draft",
        "total_contacts": 0,
        "sent_count": 0,
        "open_count": 0,
        "click_count": 0,
    }
    if scheduled_for:
        data["scheduled_for"] = scheduled_for

    result = get_db().table("campaigns").insert(data).execute()
    return result.data[0]


def get_due_scheduled_campaigns() -> list[dict]:
    """Get campaigns that are scheduled and due for sending."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    result = (
        get_db()
        .table("campaigns")
        .select("*")
        .eq("status", "scheduled")
        .lte("scheduled_for", now)
        .execute()
    )
    return result.data


def get_campaign(campaign_id: str) -> dict | None:
    result = (
        get_db()
        .table("campaigns")
        .select("*")
        .eq("id", campaign_id)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def list_campaigns(user_id: str) -> list[dict]:
    result = (
        get_db()
        .table("campaigns")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return result.data


def update_campaign(campaign_id: str, updates: dict):
    get_db().table("campaigns").update(updates).eq("id", campaign_id).execute()


def increment_stat(campaign_id: str, field: str, count: int = 1):
    """Atomically increment a campaign stat using Supabase RPC."""
    # C-05: Use RPC for atomic increment to prevent race conditions
    try:
        get_db().rpc(
            "increment_campaign_stat",
            {"campaign_id_input": campaign_id, "field_name": field, "amount": count},
        ).execute()
    except Exception:
        # Fallback to non-atomic if RPC doesn't exist yet
        campaign = get_campaign(campaign_id)
        if not campaign:
            return
        new_val = campaign.get(field, 0) + count
        get_db().table("campaigns").update({field: new_val}).eq(
            "id", campaign_id
        ).execute()
