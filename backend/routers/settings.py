"""
OutMass — Settings Router
GET    /settings              → get user settings
PUT    /settings              → update user settings
GET    /settings/suppression  → list suppressed emails
POST   /settings/suppression  → add email to suppression list
DELETE /settings/suppression  → remove email from suppression list
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from config import monthly_limit_for_plan, upload_limit_for_plan
from database import get_db
from models import announcement as ann
from models import ms_token
from models import user as user_model
from routers.auth import get_current_user

router = APIRouter(prefix="/settings", tags=["settings"])


class UpdateSettingsRequest(BaseModel):
    track_opens: bool | None = None
    track_clicks: bool | None = None
    unsubscribe_text: str | None = None
    timezone: str | None = None
    sender_name: str | None = None
    sender_position: str | None = None
    sender_company: str | None = None
    sender_phone: str | None = None
    sender_logo_url: str | None = None
    # Cross-campaign dedup (Pro only; still stored for Free so plan upgrades keep the choice)
    cross_campaign_dedup_enabled: bool | None = None
    cross_campaign_dedup_days: int | None = None


class SuppressionRequest(BaseModel):
    email: str


@router.get("")
async def get_settings(
    user: dict = Depends(get_current_user),
    # The panel draws its upload limit from this response, so it has to be
    # told the number that will actually be enforced for the build asking.
    x_extension_version: Annotated[str | None, Header()] = None,
):
    """Get user settings."""
    # Roll the quota period over if it elapsed. The sidebar polls THIS
    # endpoint for the quota bar and its client-side pre-send guard — without
    # the check here, a user who maxed out last period keeps seeing (and being
    # blocked by) last period's counter until they happen to re-login.
    user_model.check_monthly_reset(user)
    # What they may DO. The subscription is returned beside it as
    # billing_plan; the panel has drawn its plan label and quota bar from this
    # one field since 0.1.x, and a comped user reading "Starter, 2,500" while
    # the server lets them send 10,000 would be the confusing half of honest.
    plan = user_model.effective_plan(user)
    # Announcements live on a hot, critical path (the sidebar polls /settings
    # for quota + reauth state). Never let an announcements-table hiccup — e.g.
    # migration 020 lagging a backend deploy, or a transient DB error — take
    # down the whole settings response. Degrade to "no announcements" instead.
    try:
        announcements_summary = ann.get_summary_for_user(user["id"])
    except Exception:
        announcements_summary = {"unread": 0, "banner": None}
    return {
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "plan": plan,
        # The subscription itself, for anything that must speak about money
        # rather than about features. No shipped client reads it yet.
        "billing_plan": user.get("plan") or "free",
        "emails_sent_this_month": user.get("emails_sent_this_month", 0),
        # Plan-derived limits, so the extension reads them from the backend
        # instead of hardcoding — raising a limit needs no extension update.
        "monthly_limit": monthly_limit_for_plan(plan),
        "upload_limit": upload_limit_for_plan(plan, x_extension_version),
        "track_opens": user.get("track_opens", True),
        "track_clicks": user.get("track_clicks", True),
        "unsubscribe_text": user.get("unsubscribe_text", "Unsubscribe"),
        "timezone": user.get("timezone", "UTC"),
        "sender_name": user.get("sender_name", ""),
        "sender_position": user.get("sender_position", ""),
        "sender_company": user.get("sender_company", ""),
        "sender_phone": user.get("sender_phone", ""),
        "sender_logo_url": user.get("sender_logo_url") or "",
        "cross_campaign_dedup_enabled": user.get("cross_campaign_dedup_enabled", True),
        "cross_campaign_dedup_days": user.get("cross_campaign_dedup_days", 60),
        "requires_reauth": bool(user.get("requires_reauth", False)),
        "reauth_reason": user.get("reauth_reason"),
        "announcements_summary": announcements_summary,
        # False only for users who signed in after Mail.Read left the
        # first-sign-in ask and have not opted into reply detection since.
        # The panel uses it to offer the one-click upgrade
        # (/auth/login?include_mail_read=true) instead of silently never
        # detecting replies. Degrades to True on any error, which is the
        # safe direction: at worst we don't offer an upgrade nobody needs.
        "has_mail_read_scope": ms_token.user_has_mail_read_scope(user["id"]),
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
    if body.sender_name is not None:
        updates["sender_name"] = body.sender_name.strip()[:100]
    if body.sender_position is not None:
        updates["sender_position"] = body.sender_position.strip()[:100]
    if body.sender_company is not None:
        updates["sender_company"] = body.sender_company.strip()[:100]
    if body.sender_phone is not None:
        updates["sender_phone"] = body.sender_phone.strip()[:50]
    if body.sender_logo_url is not None:
        # https only. The value is pasted by the user and then written into an
        # <img src> in mail they send from their own mailbox, so the blast
        # radius is their own recipients - but javascript: and data: have no
        # business in a src we generate, and http: would strip the padlock off
        # every message that carries it.
        raw = body.sender_logo_url.strip()[:500]
        if raw and not raw.lower().startswith("https://"):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "logo_url_invalid",
                    "message": "The logo address must start with https://",
                },
            )
        updates["sender_logo_url"] = raw
    if body.cross_campaign_dedup_enabled is not None:
        updates["cross_campaign_dedup_enabled"] = bool(body.cross_campaign_dedup_enabled)
    if body.cross_campaign_dedup_days is not None:
        # Clamp to a sensible range: 7..730 days
        updates["cross_campaign_dedup_days"] = max(7, min(730, int(body.cross_campaign_dedup_days)))

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
