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
    STANDARD_PLAN_MONTHLY_LIMIT,
    PRO_PLAN_MONTHLY_LIMIT,
    GRAPH_API_BASE,
    RATE_LIMIT_WAIT_SECONDS,
    SEND_DELAY_SECONDS,
)
from models import ab_test as ab_test_model
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
    scheduled_for: str | None = None  # ISO datetime string, e.g. "2026-03-30T09:00:00Z"


class UploadContactsRequest(BaseModel):
    csv_string: str | None = None
    contacts: list[dict] | None = None


class CreateFollowupRequest(BaseModel):
    delay_days: int = 3
    subject: str
    body: str
    condition: str = "not_opened"


class CreateAbTestRequest(BaseModel):
    subject_a: str
    subject_b: str
    test_percentage: int = 20  # % of contacts for testing


# ── Endpoints ──


@router.post("")
async def create_campaign(
    body: CreateCampaignRequest,
    user: dict = Depends(get_current_user),
):
    # Scheduled sending requires Standard+ plan
    if body.scheduled_for:
        plan = user.get("plan", "free")
        if plan == "free":
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "feature_locked",
                    "message": "Zamanli gonderim Standard ve Pro planlarda kullanilabilir",
                    "required_plan": "standard",
                },
            )

    campaign = campaign_model.create_campaign(
        user_id=user["id"],
        name=body.name,
        subject=body.subject,
        body=body.body,
        scheduled_for=body.scheduled_for,
    )
    return {"campaign_id": campaign["id"], "status": campaign["status"]}


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


@router.get("/{campaign_id}/export")
async def export_campaign_csv(
    campaign_id: str,
    user: dict = Depends(get_current_user),
):
    """Export campaign contacts as CSV. Requires Standard+ plan."""
    plan = user.get("plan", "free")
    if plan == "free":
        raise HTTPException(
            status_code=402,
            detail={
                "error": "feature_locked",
                "message": "CSV export Standard ve Pro planlarda kullanilabilir",
                "required_plan": "standard",
            },
        )

    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    contacts = contact_model.get_all_contacts(campaign_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "email", "first_name", "last_name", "company", "position",
        "status", "sent_at", "opened_at", "clicked_at", "unsubscribed",
    ])
    for c in contacts:
        writer.writerow([
            c.get("email", ""),
            c.get("first_name", ""),
            c.get("last_name", ""),
            c.get("company", ""),
            c.get("position", ""),
            c.get("status", ""),
            c.get("sent_at", ""),
            c.get("opened_at", ""),
            c.get("clicked_at", ""),
            c.get("unsubscribed", False),
        ])

    output.seek(0)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", campaign.get("name", "export"))

    return {
        "csv_data": output.getvalue(),
        "filename": f"outmass_{safe_name}.csv",
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
    if campaign["status"] == "sent":
        raise HTTPException(status_code=409, detail="Campaign already sent")

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
        limit = FREE_PLAN_MONTHLY_LIMIT
    elif plan == "standard":
        limit = STANDARD_PLAN_MONTHLY_LIMIT
    else:
        limit = PRO_PLAN_MONTHLY_LIMIT

    remaining = limit - sent_this_month
    if remaining <= 0:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "limit_exceeded",
                "message": f"Aylik {limit} email limitine ulastiniz",
                "emails_sent": sent_this_month,
                "limit": limit,
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

    # ── A/B Test setup ──
    ab_test = ab_test_model.get_ab_test(campaign_id)
    ab_test_size = 0
    ab_group_a = []
    ab_group_b = []
    ab_remaining = []

    if ab_test and ab_test["status"] == "testing":
        test_pct = ab_test.get("test_percentage", 20)
        ab_test_size = max(2, int(len(pending) * test_pct / 100))
        half = ab_test_size // 2
        ab_group_a = pending[:half]
        ab_group_b = pending[half:ab_test_size]
        ab_remaining = pending[ab_test_size:]
    else:
        ab_test = None  # Ignore non-testing AB tests

    # ── Send emails synchronously (MVP, no Celery) ──
    sent_count = 0
    errors = []

    async with httpx.AsyncClient() as client:
        send_list = pending if not ab_test else ab_group_a + ab_group_b
        for idx, contact in enumerate(send_list):
            # Check suppression list + contact-level unsubscribe
            if contact.get("unsubscribed"):
                continue
            if contact.get("email", "").lower() in suppressed_emails:
                continue

            # Determine subject for A/B testing
            subject_override = None
            ab_variant = None
            if ab_test:
                if idx < half:
                    subject_override = ab_test["subject_a"]
                    ab_variant = "A"
                else:
                    subject_override = ab_test["subject_b"]
                    ab_variant = "B"

            try:
                result = await _send_single_email(
                    client=client,
                    access_token=x_ms_token,
                    campaign=campaign,
                    contact=contact,
                    subject_override=subject_override,
                    track_opens=user.get("track_opens", True),
                    track_clicks=user.get("track_clicks", True),
                    unsubscribe_text=user.get("unsubscribe_text", "Abonelikten cik"),
                    sender_info=user,
                )
                if result["success"]:
                    contact_model.mark_sent(contact["id"])
                    if ab_variant:
                        contact_model.set_ab_variant(contact["id"], ab_variant)
                    campaign_model.increment_stat(campaign_id, "sent_count")
                    sent_count += 1
                else:
                    errors.append(
                        {"email": contact["email"], "error": result["error"]}
                    )
            except Exception as e:
                errors.append({"email": contact["email"], "error": str(e)})

            # C-04: Non-blocking rate limiting between emails
            if sent_count < len(send_list):
                await asyncio.sleep(SEND_DELAY_SECONDS)

    # Update user's monthly count
    user_model.increment_sent_count(user["id"], sent_count)

    # Handle A/B test: if test phase done, mark status (winner evaluated later by worker)
    if ab_test and ab_remaining:
        ab_test_model.update_ab_test(ab_test["id"], {"status": "awaiting_winner"})
        # Update campaign to "ab_testing" — remaining contacts will be sent by worker
        campaign_model.update_campaign(campaign_id, {"status": "ab_testing"})
    else:
        # Update campaign status
        final_status = "sent" if not errors else "partial"
        campaign_model.update_campaign(campaign_id, {"status": final_status})

    return {
        "queued": sent_count,
        "campaign_id": campaign_id,
        "errors": errors[:10],  # Cap error list
        "ab_test": bool(ab_test),
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

    if user.get("plan", "free") not in ("pro",):
        raise HTTPException(
            status_code=402,
            detail={
                "error": "feature_locked",
                "message": "Follow-up ozelligi sadece Pro planda kullanilabilir",
                "required_plan": "pro",
            },
        )

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


# ── A/B Testing Endpoints ──


@router.post("/{campaign_id}/ab-test")
async def create_ab_test(
    campaign_id: str,
    body: CreateAbTestRequest,
    user: dict = Depends(get_current_user),
):
    """Create an A/B test for a campaign. Pro plan only."""
    if user.get("plan", "free") != "pro":
        raise HTTPException(
            status_code=402,
            detail={
                "error": "feature_locked",
                "message": "A/B testing sadece Pro planda kullanilabilir",
                "required_plan": "pro",
            },
        )

    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Check if AB test already exists
    existing = ab_test_model.get_ab_test(campaign_id)
    if existing:
        raise HTTPException(status_code=409, detail="A/B test already exists for this campaign")

    test_pct = max(10, min(50, body.test_percentage))

    ab_test = ab_test_model.create_ab_test(
        campaign_id=campaign_id,
        user_id=user["id"],
        subject_a=body.subject_a,
        subject_b=body.subject_b,
        test_percentage=test_pct,
    )
    return {"ab_test_id": ab_test["id"], "test_percentage": test_pct}


@router.get("/{campaign_id}/ab-test")
async def get_ab_test_status(
    campaign_id: str,
    user: dict = Depends(get_current_user),
):
    """Get A/B test results for a campaign."""
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    ab_test = ab_test_model.get_ab_test(campaign_id)
    if not ab_test:
        raise HTTPException(status_code=404, detail="No A/B test found")

    return {
        "ab_test_id": ab_test["id"],
        "subject_a": ab_test["subject_a"],
        "subject_b": ab_test["subject_b"],
        "opens_a": ab_test["opens_a"],
        "opens_b": ab_test["opens_b"],
        "winner": ab_test["winner"],
        "status": ab_test["status"],
        "test_percentage": ab_test["test_percentage"],
    }


# ── Helpers ──


async def _send_single_email(
    client: httpx.AsyncClient,
    access_token: str,
    campaign: dict,
    contact: dict,
    subject_override: str | None = None,
    track_opens: bool = True,
    track_clicks: bool = True,
    unsubscribe_text: str = "Abonelikten cik",
    sender_info: dict | None = None,
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
    # Add sender fields
    if sender_info:
        merge_ctx["senderName"] = sender_info.get("sender_name", "")
        merge_ctx["senderPosition"] = sender_info.get("sender_position", "")
        merge_ctx["senderCompany"] = sender_info.get("sender_company", "")
        merge_ctx["senderPhone"] = sender_info.get("sender_phone", "")
    # Add custom fields
    custom = contact.get("custom_fields") or {}
    merge_ctx.update(custom)

    subject_text = subject_override or campaign["subject"]
    merged_subject = _merge_template(subject_text, merge_ctx)
    merged_body = _merge_template(campaign["body"], merge_ctx)

    # Add tracking pixel (if enabled)
    tracking_pixel = ""
    if track_opens:
        tracking_pixel = (
            f'<img src="{BACKEND_URL}/t/{contact["id"]}" '
            f'width="1" height="1" style="display:none" alt="" />'
        )

    # Wrap links for click tracking (if enabled)
    tracked_body = _wrap_links(merged_body, contact["id"]) if track_clicks else merged_body

    # Add unsubscribe footer
    unsubscribe_url = f"{BACKEND_URL}/unsubscribe/{contact['id']}"
    footer = (
        f'<br/><p style="font-size:11px;color:#999;">'
        f'<a href="{unsubscribe_url}">{unsubscribe_text}</a></p>'
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
