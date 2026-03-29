"""
OutMass — Campaigns Router
POST /campaigns                   → create campaign
GET  /campaigns                   → list campaigns
GET  /campaigns/{id}/stats        → campaign statistics
POST /campaigns/{id}/contacts     → upload contacts
POST /campaigns/{id}/send         → start sending
"""

import asyncio
import csv
import io
import re
import urllib.parse

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from config import (
    BACKEND_URL,
    FREE_PLAN_MONTHLY_LIMIT,
    GRAPH_API_BASE,
    RATE_LIMIT_WAIT_SECONDS,
    SEND_DELAY_SECONDS,
)
from models import campaign as campaign_model
from models import contact as contact_model
from models import followup as followup_model
from models import user as user_model
from routers.auth import get_current_user

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


# ── Schemas ──


class CreateCampaignRequest(BaseModel):
    name: str
    subject: str
    body: str


class UploadContactsRequest(BaseModel):
    csv_string: str | None = None
    contacts: list[dict] | None = None


class CreateFollowupRequest(BaseModel):
    delay_days: int = 3
    subject: str
    body: str
    condition: str = "not_opened"


# ── Endpoints ──


@router.post("")
async def create_campaign(
    body: CreateCampaignRequest,
    user: dict = Depends(get_current_user),
):
    campaign = campaign_model.create_campaign(
        user_id=user["id"],
        name=body.name,
        subject=body.subject,
        body=body.body,
    )
    return {"campaign_id": campaign["id"], "status": "draft"}


@router.get("")
async def list_campaigns(user: dict = Depends(get_current_user)):
    campaigns = campaign_model.list_campaigns(user["id"])
    return {"campaigns": campaigns}


@router.get("/{campaign_id}/stats")
async def campaign_stats(
    campaign_id: str,
    user: dict = Depends(get_current_user),
):
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    sent = campaign["sent_count"] or 0
    open_rate = round((campaign["open_count"] / sent) * 100, 1) if sent > 0 else 0.0
    click_rate = round((campaign["click_count"] / sent) * 100, 1) if sent > 0 else 0.0

    followups = followup_model.get_campaign_followups(campaign_id)
    pending_followups = sum(1 for f in followups if f["status"] == "scheduled")

    return {
        "campaign_id": campaign_id,
        "name": campaign["name"],
        "status": campaign["status"],
        "total_contacts": campaign["total_contacts"],
        "sent_count": sent,
        "open_count": campaign["open_count"],
        "click_count": campaign["click_count"],
        "open_rate": open_rate,
        "click_rate": click_rate,
        "pending_followups": pending_followups,
    }


@router.post("/{campaign_id}/contacts")
async def upload_contacts(
    campaign_id: str,
    body: UploadContactsRequest,
    user: dict = Depends(get_current_user),
):
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    contacts = []

    # Parse CSV string
    if body.csv_string:
        reader = csv.DictReader(io.StringIO(body.csv_string))
        for row in reader:
            contacts.append(dict(row))

    # Or use JSON array directly
    elif body.contacts:
        contacts = body.contacts

    if not contacts:
        raise HTTPException(status_code=400, detail="No contacts provided")

    count = contact_model.bulk_insert(campaign_id, contacts)

    # Update campaign total
    total = contact_model.get_campaign_contacts_count(campaign_id)
    campaign_model.update_campaign(campaign_id, {"total_contacts": total})

    # Generate preview for first 3 contacts
    preview = []
    for c in contacts[:3]:
        merged_subject = _merge_template(campaign["subject"], c)
        preview.append(
            {"email": c.get("email", ""), "subject": merged_subject}
        )

    return {"count": count, "preview": preview}


@router.post("/{campaign_id}/send")
async def send_campaign(
    campaign_id: str,
    user: dict = Depends(get_current_user),
    authorization: str = Header(...),
    x_ms_token: str = Header(..., alias="X-MS-Token"),
):
    """
    Start sending emails for a campaign.
    Requires X-MS-Token header with the user's Microsoft access token.
    MVP: synchronous send (no Celery).
    """
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign["status"] == "sending":
        raise HTTPException(status_code=409, detail="Campaign already sending")

    # ── Save access token for follow-up worker ──
    from database import get_db as _get_db

    _db = _get_db()
    _existing = _db.table("user_tokens").select("id").eq("user_id", user["id"]).execute()
    if _existing.data and len(_existing.data) > 0:
        _db.table("user_tokens").update(
            {"access_token": x_ms_token}
        ).eq("user_id", user["id"]).execute()
    else:
        _db.table("user_tokens").insert(
            {"user_id": user["id"], "access_token": x_ms_token}
        ).execute()

    # ── Freemium check ──
    sent_this_month = user.get("emails_sent_this_month", 0)
    plan = user.get("plan", "free")

    pending = contact_model.get_pending_contacts(campaign_id)
    if not pending:
        raise HTTPException(status_code=400, detail="No pending contacts")

    if plan == "free":
        remaining = FREE_PLAN_MONTHLY_LIMIT - sent_this_month
        if remaining <= 0:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "limit_exceeded",
                    "message": "Free planda aylik 50 email limitine ulastiniz",
                    "emails_sent": sent_this_month,
                    "limit": FREE_PLAN_MONTHLY_LIMIT,
                },
            )
        # Cap to remaining quota
        pending = pending[:remaining]

    # ── Mark campaign as sending ──
    campaign_model.update_campaign(campaign_id, {"status": "sending"})

    # ── C-06: Filter out suppressed emails ──
    from database import get_db

    suppressed_result = (
        get_db()
        .table("suppression_list")
        .select("email")
        .eq("user_id", user["id"])
        .execute()
    )
    suppressed_emails = {r["email"].lower() for r in suppressed_result.data}

    # ── Send emails synchronously (MVP, no Celery) ──
    sent_count = 0
    errors = []

    async with httpx.AsyncClient() as client:
        for contact in pending:
            # Check suppression list + contact-level unsubscribe
            if contact.get("unsubscribed"):
                continue
            if contact.get("email", "").lower() in suppressed_emails:
                continue

            try:
                result = await _send_single_email(
                    client=client,
                    access_token=x_ms_token,
                    campaign=campaign,
                    contact=contact,
                )
                if result["success"]:
                    contact_model.mark_sent(contact["id"])
                    campaign_model.increment_stat(campaign_id, "sent_count")
                    sent_count += 1
                else:
                    errors.append(
                        {"email": contact["email"], "error": result["error"]}
                    )
            except Exception as e:
                errors.append({"email": contact["email"], "error": str(e)})

            # C-04: Non-blocking rate limiting between emails
            if sent_count < len(pending):
                await asyncio.sleep(SEND_DELAY_SECONDS)

    # Update user's monthly count
    user_model.increment_sent_count(user["id"], sent_count)

    # Update campaign status
    final_status = "sent" if not errors else "partial"
    campaign_model.update_campaign(campaign_id, {"status": final_status})

    return {
        "queued": sent_count,
        "campaign_id": campaign_id,
        "errors": errors[:10],  # Cap error list
    }


# ── Follow-up Endpoints ──


@router.post("/{campaign_id}/followups")
async def create_followup(
    campaign_id: str,
    body: CreateFollowupRequest,
    user: dict = Depends(get_current_user),
):
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    followup = followup_model.create_followup(
        campaign_id=campaign_id,
        user_id=user["id"],
        delay_days=body.delay_days,
        subject=body.subject,
        body=body.body,
        condition=body.condition,
    )
    return {"followup_id": followup["id"]}


@router.get("/{campaign_id}/followups")
async def list_followups(
    campaign_id: str,
    user: dict = Depends(get_current_user),
):
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    followups = followup_model.get_campaign_followups(campaign_id)
    return {"followups": followups}


@router.delete("/{campaign_id}/followups/{followup_id}")
async def cancel_followup(
    campaign_id: str,
    followup_id: str,
    user: dict = Depends(get_current_user),
):
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    followup_model.delete_followup(followup_id, campaign_id=campaign_id)
    return {"status": "cancelled"}


# ── Helpers ──


async def _send_single_email(
    client: httpx.AsyncClient,
    access_token: str,
    campaign: dict,
    contact: dict,
) -> dict:
    """Send a single email via Microsoft Graph API."""
    # Build merge context
    merge_ctx = {
        "firstName": contact.get("first_name", ""),
        "lastName": contact.get("last_name", ""),
        "email": contact.get("email", ""),
        "company": contact.get("company", ""),
        "position": contact.get("position", ""),
    }
    # Add custom fields
    custom = contact.get("custom_fields") or {}
    merge_ctx.update(custom)

    merged_subject = _merge_template(campaign["subject"], merge_ctx)
    merged_body = _merge_template(campaign["body"], merge_ctx)

    # Add tracking pixel
    tracking_pixel = (
        f'<img src="{BACKEND_URL}/t/{contact["id"]}" '
        f'width="1" height="1" style="display:none" alt="" />'
    )

    # Wrap links for click tracking
    tracked_body = _wrap_links(merged_body, contact["id"])

    # Add unsubscribe footer
    unsubscribe_url = f"{BACKEND_URL}/unsubscribe/{contact['id']}"
    footer = (
        f'<br/><p style="font-size:11px;color:#999;">'
        f'<a href="{unsubscribe_url}">Abonelikten cik</a></p>'
    )

    final_html = tracked_body + footer + tracking_pixel

    payload = {
        "message": {
            "subject": merged_subject,
            "body": {"contentType": "HTML", "content": final_html},
            "toRecipients": [
                {"emailAddress": {"address": contact["email"]}}
            ],
        },
        "saveToSentItems": True,
    }

    resp = await client.post(
        f"{GRAPH_API_BASE}/me/sendMail",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
    )

    # Rate limited — retry once
    if resp.status_code == 429:
        import asyncio

        retry_after = int(resp.headers.get("Retry-After", RATE_LIMIT_WAIT_SECONDS))
        await asyncio.sleep(retry_after)
        resp = await client.post(
            f"{GRAPH_API_BASE}/me/sendMail",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if resp.status_code in (200, 202):
        return {"success": True}

    error_detail = ""
    try:
        error_detail = resp.json().get("error", {}).get("message", "")
    except Exception:
        error_detail = f"HTTP {resp.status_code}"

    return {"success": False, "error": error_detail}


def _merge_template(template_str: str, context: dict) -> str:
    """Replace {{placeholder}} with values from context."""

    def replacer(match):
        key = match.group(1)
        return str(context.get(key, match.group(0)))

    return re.sub(r"\{\{(\w+)\}\}", replacer, template_str)


def _wrap_links(html: str, contact_id: str) -> str:
    """Replace href URLs with click-tracking redirect URLs."""

    def replacer(match):
        original_url = match.group(1)
        # Don't wrap unsubscribe or tracking URLs
        if BACKEND_URL in original_url:
            return match.group(0)
        encoded = urllib.parse.quote(original_url, safe="")
        tracked = f"{BACKEND_URL}/c/{contact_id}?url={encoded}"
        return f'href="{tracked}"'

    return re.sub(r'href="(https?://[^"]+)"', replacer, html)
