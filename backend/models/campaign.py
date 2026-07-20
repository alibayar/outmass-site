"""
OutMass — Campaign model helpers
"""

from datetime import datetime, timedelta, timezone

from database import get_db


def get_recent_partial_campaigns(max_age_days: int = 14) -> list[dict]:
    """Partial campaigns young enough to auto-resume.

    Used by the auto_resume_partial_campaigns beat: 'partial' campaigns
    (quota-capped or transiently failed sends) get flipped back to
    'scheduled' once the owner has quota headroom again. The age window
    exists so a months-old abandoned partial can never resurrect itself
    and surprise-send — only recent work-in-progress qualifies.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=max_age_days)
    ).isoformat()
    result = (
        get_db()
        .table("campaigns")
        .select("*")
        .eq("status", "partial")
        .gte("created_at", cutoff)
        .execute()
    )
    return result.data or []


def create_campaign(
    user_id: str,
    name: str,
    subject: str,
    body: str,
    scheduled_for: str | None = None,
    attachments: list[dict] | None = None,
    daily_send_cap: int | None = None,
) -> dict:
    """Create a campaign row.

    `attachments` is a list of {name, url} dicts pointing at OneDrive
    sharing links the user added in the sidebar's Attachments section.
    The send pipeline renders these into a footer; the URLs themselves
    live in OneDrive (we don't host).

    `daily_send_cap` (with scheduled_for) spreads the campaign: the
    scheduled worker sends at most this many contacts per day and rolls
    the schedule forward a day until the list is exhausted.
    """
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
        "attachments": attachments or [],
    }
    if scheduled_for:
        data["scheduled_for"] = scheduled_for
    if daily_send_cap:
        data["daily_send_cap"] = daily_send_cap

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


def list_campaigns(user_id: str, archived: bool = False) -> list[dict]:
    result = (
        get_db()
        .table("campaigns")
        .select("*")
        .eq("user_id", user_id)
        .eq("archived", archived)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    rows = result.data or []
    # Hide legacy test-send campaigns (pre-stateless refactor) from all lists.
    # These should no longer be created; this filter is for historical rows
    # still present in the DB.
    return [r for r in rows if r.get("name") != "__test_send__"]


def update_campaign(campaign_id: str, updates: dict):
    get_db().table("campaigns").update(updates).eq("id", campaign_id).execute()


def set_archived(campaign_id: str, archived: bool):
    """Toggle a campaign's archived flag."""
    get_db().table("campaigns").update({"archived": archived}).eq(
        "id", campaign_id
    ).execute()


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
