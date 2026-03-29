"""
OutMass — User model helpers
"""

from database import get_db


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
