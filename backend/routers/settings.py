"""
OutMass — Settings Router
GET    /settings              → get user settings
PUT    /settings              → update user settings
GET    /settings/suppression  → list suppressed emails
POST   /settings/suppression  → add email to suppression list
DELETE /settings/suppression  → remove email from suppression list
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/settings", tags=["settings"])


class UpdateSettingsRequest(BaseModel):
    track_opens: bool | None = None
    track_clicks: bool | None = None
    unsubscribe_text: str | None = None
    timezone: str | None = None


class SuppressionRequest(BaseModel):
    email: str


@router.get("")
async def get_settings(user: dict = Depends(get_current_user)):
    """Get user settings."""
    return {
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "plan": user.get("plan", "free"),
        "emails_sent_this_month": user.get("emails_sent_this_month", 0),
        "track_opens": user.get("track_opens", True),
        "track_clicks": user.get("track_clicks", True),
        "unsubscribe_text": user.get("unsubscribe_text", "Abonelikten cik"),
        "timezone": user.get("timezone", "Europe/Istanbul"),
    }


@router.put("")
async def update_settings(
    body: UpdateSettingsRequest,
    user: dict = Depends(get_current_user),
):
    """Update user settings."""
    updates = {}
    if body.track_opens is not None:
        updates["track_opens"] = body.track_opens
    if body.track_clicks is not None:
        updates["track_clicks"] = body.track_clicks
    if body.unsubscribe_text is not None:
        updates["unsubscribe_text"] = body.unsubscribe_text.strip()[:200]
    if body.timezone is not None:
        updates["timezone"] = body.timezone

    if updates:
        get_db().table("users").update(updates).eq("id", user["id"]).execute()

    return {"status": "updated", **updates}


@router.get("/suppression")
async def list_suppression(user: dict = Depends(get_current_user)):
    """List all suppressed emails."""
    result = (
        get_db()
        .table("suppression_list")
        .select("id, email, reason, created_at")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    return {"emails": result.data, "count": len(result.data)}


@router.post("/suppression")
async def add_suppression(
    body: SuppressionRequest,
    user: dict = Depends(get_current_user),
):
    """Add email to suppression list."""
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    # Check duplicate
    existing = (
        get_db()
        .table("suppression_list")
        .select("id")
        .eq("user_id", user["id"])
        .eq("email", email)
        .execute()
    )
    if existing.data:
        return {"status": "already_exists"}

    get_db().table("suppression_list").insert({
        "user_id": user["id"],
        "email": email,
        "reason": "manual",
    }).execute()
    return {"status": "added", "email": email}


@router.delete("/suppression")
async def remove_suppression(
    body: SuppressionRequest,
    user: dict = Depends(get_current_user),
):
    """Remove email from suppression list."""
    email = body.email.strip().lower()
    get_db().table("suppression_list").delete().eq(
        "user_id", user["id"]
    ).eq("email", email).execute()
    return {"status": "removed", "email": email}
