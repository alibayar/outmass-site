"""
OutMass — Contact model helpers
"""

import re
from datetime import datetime, timezone

from database import get_db

# Simple email regex for validation
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def bulk_insert(campaign_id: str, contacts: list[dict]) -> int:
    """Insert multiple contacts for a campaign. Returns count inserted."""
    rows = []
    for c in contacts:
        email = c.get("email", "").strip()
        # H-03: Skip contacts with empty or invalid email
        if not email or not EMAIL_REGEX.match(email):
            continue
        rows.append(
            {
                "campaign_id": campaign_id,
                "email": email,
                "first_name": c.get("firstName", c.get("first_name", "")),
                "last_name": c.get("lastName", c.get("last_name", "")),
                "company": c.get("company", ""),
                "position": c.get("position", ""),
                "custom_fields": {
                    k: v
                    for k, v in c.items()
                    if k
                    not in (
                        "email",
                        "firstName",
                        "first_name",
                        "lastName",
                        "last_name",
                        "company",
                        "position",
                    )
                },
                "status": "pending",
            }
        )

    if not rows:
        return 0

    result = get_db().table("contacts").insert(rows).execute()
    return len(result.data)


def get_pending_contacts(campaign_id: str) -> list[dict]:
    """Get all pending (unsent) contacts for a campaign."""
    result = (
        get_db()
        .table("contacts")
        .select("*")
        .eq("campaign_id", campaign_id)
        .eq("status", "pending")
        .eq("unsubscribed", False)
        .execute()
    )
    return result.data


def get_contact(contact_id: str) -> dict | None:
    result = (
        get_db()
        .table("contacts")
        .select("*")
        .eq("id", contact_id)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def _now_iso() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def mark_sent(contact_id: str):
    # M-02: Use proper ISO timestamp instead of string "now()"
    get_db().table("contacts").update(
        {"status": "sent", "sent_at": _now_iso()}
    ).eq("id", contact_id).execute()


def mark_opened(contact_id: str):
    get_db().table("contacts").update(
        {"opened_at": _now_iso()}
    ).eq("id", contact_id).is_("opened_at", "null").execute()


def mark_clicked(contact_id: str):
    get_db().table("contacts").update(
        {"clicked_at": _now_iso()}
    ).eq("id", contact_id).is_("clicked_at", "null").execute()


def set_ab_variant(contact_id: str, variant: str):
    """Set the A/B test variant for a contact."""
    get_db().table("contacts").update(
        {"ab_variant": variant}
    ).eq("id", contact_id).execute()


def mark_unsubscribed(contact_id: str):
    get_db().table("contacts").update({"unsubscribed": True}).eq(
        "id", contact_id
    ).execute()


def get_all_contacts(campaign_id: str) -> list[dict]:
    """Get all contacts for a campaign (for CSV export)."""
    result = (
        get_db()
        .table("contacts")
        .select("*")
        .eq("campaign_id", campaign_id)
        .order("created_at")
        .execute()
    )
    return result.data


def get_campaign_contacts_count(campaign_id: str) -> int:
    result = (
        get_db()
        .table("contacts")
        .select("id", count="exact")
        .eq("campaign_id", campaign_id)
        .execute()
    )
    return result.count or 0
