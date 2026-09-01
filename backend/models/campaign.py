"""
OutMass — Campaign model helpers
"""

from datetime import datetime, timedelta, timezone

from database import get_db


def get_resumable_partial_campaigns() -> list[dict]:
    """Every partial campaign still waiting for quota, at any age.

    Used by the auto_resume_partial_campaigns beat: 'partial' campaigns
    (quota-capped or transiently failed sends) go back to 'scheduled' once
    the owner has headroom again.

    There used to be an age window here, so that a months-old abandoned
    partial could not resurrect itself and surprise-send. It also meant the
    promise broke: a free user whose 10,000-row list needs forty monthly
    batches got one, and then silence, while the panel told them the rest
    would go out automatically. Ali's call, 2026-08-28 — the user should not
    have to come back and press anything, however many months it takes.

    What replaces the age gate is not nothing:

      * `archived` is now the stop switch, and it is one the user can reach
        from Reports. An age window stopped campaigns nobody had abandoned;
        archiving stops exactly the ones somebody did.
      * every capped batch emails the owner (routers/campaigns.py), so a
        campaign that runs for a year announces itself twelve times rather
        than arriving as a surprise on month nine.
      * an owner who has lost their Microsoft connection is skipped by the
        caller until they reconnect.
    """
    result = (
        get_db()
        .table("campaigns")
        .select("*")
        .eq("status", "partial")
        .eq("archived", False)
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
    """Get campaigns that are scheduled and due for sending.

    `archived` is a filter here for the same reason it is one in
    get_resumable_partial_campaigns: it is the user's stop switch. Without it,
    a campaign someone stopped mid-batch comes back the moment anything writes
    'scheduled' over the cancellation — which the daily-cap branch does on
    every paced run — and it comes back invisibly, because archived rows are
    not in the default Reports view.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    result = (
        get_db()
        .table("campaigns")
        .select("*")
        .eq("status", "scheduled")
        .eq("archived", False)
        .lte("scheduled_for", now)
        .execute()
    )
    return result.data


def get_status(campaign_id: str) -> str | None:
    """The campaign's status, one column, for use inside a send loop.

    Cheap on purpose: a send paces at SEND_DELAY_SECONDS per recipient, so
    asking every few contacts costs far less than the wait between them.
    """
    result = (
        get_db()
        .table("campaigns")
        .select("status")
        .eq("id", campaign_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0]["status"] if rows else None


def update_if_status(campaign_id: str, payload: dict, expected: str) -> bool:
    """Write `payload` only while the campaign is still in `expected`.

    Every send loop marks its campaign 'sending' before it starts, so
    `expected='sending'` means "nobody has changed this underneath me". If
    somebody pressed Stop, the row now says 'cancelled', the update matches
    nothing, and the cancellation survives — instead of being overwritten by a
    loop that finished afterwards and had no idea.

    Returns whether it applied, so a caller can tell a normal close-out from
    one that was overtaken.
    """
    result = (
        get_db()
        .table("campaigns")
        .update(payload)
        .eq("id", campaign_id)
        .eq("status", expected)
        .execute()
    )
    return bool(result.data)


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
