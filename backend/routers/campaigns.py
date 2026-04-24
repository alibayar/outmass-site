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
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from config import (
    BACKEND_URL,
    FREE_PLAN_MONTHLY_LIMIT,
    STARTER_PLAN_MONTHLY_LIMIT,
    PRO_PLAN_MONTHLY_LIMIT,
    GRAPH_API_BASE,
    RATE_LIMIT_WAIT_SECONDS,
    SEND_DELAY_SECONDS,
    FREE_UPLOAD_ROW_LIMIT,
    STARTER_UPLOAD_ROW_LIMIT,
    PRO_UPLOAD_ROW_LIMIT,
    MAX_CSV_SIZE_BYTES,
)
from database import get_db
from models import ab_test as ab_test_model
from models import audit
from models import campaign as campaign_model
from models import contact as contact_model
from models import followup as followup_model
from models import user as user_model
from routers.auth import get_current_user
from utils.merge_tags import find_malformed_tags, find_unknown_tags

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
    request: Request,
    user: dict = Depends(get_current_user),
):
    # B.1: Reject whitespace-only / empty campaign names
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="Campaign name is required")
    body.name = body.name.strip()

    # Scheduled sending requires Starter+ plan
    if body.scheduled_for:
        plan = user.get("plan", "free")
        if plan == "free":
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "feature_locked",
                    "feature": "scheduled_sending",
                    "message": "Scheduled sending is a Starter/Pro feature. Upgrade to unlock it.",
                    "required_plan": "starter",
                },
            )

    campaign = campaign_model.create_campaign(
        user_id=user["id"],
        name=body.name,
        subject=body.subject,
        body=body.body,
        scheduled_for=body.scheduled_for,
    )
    # Store subject+body hashes (not content) so we can later prove
    # "this campaign was created with these parameters" without the
    # audit log itself carrying potentially personal content.
    audit.emit(
        audit.EVENT_CAMPAIGN_CREATED,
        user_id=user["id"],
        email=user["email"],
        metadata={
            "campaign_id": campaign["id"],
            "subject_hash": audit.hash_bytes(body.subject),
            "body_hash": audit.hash_bytes(body.body),
            "scheduled_for": body.scheduled_for,
            "status": campaign["status"],
        },
        request=request,
    )
    return {"campaign_id": campaign["id"], "status": campaign["status"]}


@router.get("")
async def list_campaigns(
    archived: bool = False,
    user: dict = Depends(get_current_user),
):
    campaigns = campaign_model.list_campaigns(user["id"], archived=archived)
    return {"campaigns": campaigns}


@router.get("/export-list")
async def export_campaign_list(user: dict = Depends(get_current_user)):
    """Export all of the user's campaigns + summary stats as CSV."""
    active = campaign_model.list_campaigns(user["id"], archived=False)
    archived = campaign_model.list_campaigns(user["id"], archived=True)
    all_campaigns = active + archived

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "name", "status", "created_at", "sent_count",
        "open_count", "click_count", "total_contacts", "archived",
    ])
    for c in all_campaigns:
        writer.writerow([
            c.get("name", ""),
            c.get("status", ""),
            c.get("created_at", ""),
            c.get("sent_count", 0),
            c.get("open_count", 0),
            c.get("click_count", 0),
            c.get("total_contacts", 0),
            c.get("archived", False),
        ])
    return {"csv_data": output.getvalue(), "filename": "outmass_campaigns.csv"}


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
                "required_plan": "starter",
            },
        )

    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    contacts = contact_model.get_all_contacts(campaign_id)

    output = io.StringIO()
    writer = csv.writer(output)
    # camelCase headers — consistent with merge tags ({{firstName}}) and CSV upload template
    writer.writerow([
        "email", "firstName", "lastName", "company", "position",
        "status", "sentAt", "openedAt", "clickedAt", "unsubscribed",
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
    request: Request,
    user: dict = Depends(get_current_user),
):
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    plan = user.get("plan", "free")
    row_limit = {
        "pro": PRO_UPLOAD_ROW_LIMIT,
        "starter": STARTER_UPLOAD_ROW_LIMIT,
    }.get(plan, FREE_UPLOAD_ROW_LIMIT)

    contacts: list[dict] = []

    if body.csv_string:
        # A.2: File size check (UTF-8 byte length)
        if len(body.csv_string.encode("utf-8")) > MAX_CSV_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"CSV file exceeds {MAX_CSV_SIZE_BYTES // (1024 * 1024)} MB limit",
            )
        # A.2: Strip UTF-8 BOM
        text = body.csv_string.lstrip("\ufeff")
        # A.2: Reject botched encoding (replacement characters)
        if "\ufffd" in text:
            raise HTTPException(
                status_code=400,
                detail="CSV encoding not recognized. Please save as UTF-8.",
            )
        reader = csv.DictReader(io.StringIO(text))
        # A.2: Mandatory 'email' column (case-insensitive)
        headers = [h.lower() for h in (reader.fieldnames or [])]
        if "email" not in headers:
            raise HTTPException(
                status_code=400,
                detail="Column 'email' is required in the CSV header",
            )
        for row in reader:
            normalized: dict = {}
            for k, v in row.items():
                if k and k.lower() == "email":
                    normalized["email"] = v
                else:
                    normalized[k] = v
            contacts.append(normalized)

    elif body.contacts:
        contacts = body.contacts
        if contacts and not any("email" in c for c in contacts):
            raise HTTPException(
                status_code=400, detail="'email' field required"
            )

    if not contacts:
        raise HTTPException(status_code=400, detail="No contacts provided")

    # A.2: Plan-based row limit
    if len(contacts) > row_limit:
        raise HTTPException(
            status_code=413,
            detail=f"CSV has {len(contacts)} rows; plan limit is {row_limit}",
        )

    # A.1 / A.3: Cross-check against the user's suppression list
    suppressed_rows = (
        get_db()
        .table("suppression_list")
        .select("email")
        .eq("user_id", user["id"])
        .execute()
    )
    suppressed_set = {r["email"].lower() for r in (suppressed_rows.data or [])}

    # A.5 (Pro): Cross-campaign dedup — skip addresses the user has emailed
    # (sent or still pending) in previous campaigns within the lookback window.
    skipped_previous = 0
    if plan == "pro" and user.get("cross_campaign_dedup_enabled", True):
        lookback_days = int(user.get("cross_campaign_dedup_days") or 60)
        cutoff_iso = (
            datetime.now(timezone.utc) - timedelta(days=lookback_days)
        ).isoformat()
        previous_set = _fetch_previous_emails(
            user_id=user["id"],
            exclude_campaign_id=campaign_id,
            sent_cutoff_iso=cutoff_iso,
        )
        if previous_set:
            filtered: list[dict] = []
            for c in contacts:
                em = (c.get("email") or "").strip().lower()
                if em and em in previous_set:
                    skipped_previous += 1
                else:
                    filtered.append(c)
            contacts = filtered

    result = contact_model.bulk_insert(campaign_id, contacts, suppressed=suppressed_set)

    total = contact_model.get_campaign_contacts_count(campaign_id)
    campaign_model.update_campaign(campaign_id, {"total_contacts": total})

    # Audit: evidence that the user — not us — supplied the recipient
    # list. Store counts + an upload-source fingerprint; never the raw
    # addresses (those live in contacts and cascade-delete with user).
    audit_source = "csv" if body.csv_string else "json"
    audit_csv_hash = (
        audit.hash_bytes(body.csv_string) if body.csv_string else None
    )
    audit.emit(
        audit.EVENT_CONTACTS_UPLOADED,
        user_id=user["id"],
        email=user["email"],
        metadata={
            "campaign_id": campaign_id,
            "source": audit_source,
            "csv_hash": audit_csv_hash,
            "inserted": result["inserted"],
            "skipped_invalid": result["skipped_invalid"],
            "skipped_duplicate": result["skipped_duplicate"],
            "skipped_suppressed": result["skipped_suppressed"],
            "skipped_previous": skipped_previous,
            "total_after_upload": total,
        },
        request=request,
    )

    preview = []
    for c in contacts[:3]:
        merged_subject = _merge_template(campaign["subject"], c)
        preview.append({"email": c.get("email", ""), "subject": merged_subject})

    return {
        "count": result["inserted"],
        "skipped_invalid": result["skipped_invalid"],
        "skipped_duplicate": result["skipped_duplicate"],
        "skipped_suppressed": result["skipped_suppressed"],
        "skipped_previous": skipped_previous,
        "warn_role": result.get("warn_role", 0),
        "warn_disposable": result.get("warn_disposable", 0),
        "preview": preview,
    }


@router.post("/{campaign_id}/send")
async def send_campaign(
    campaign_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
    authorization: str = Header(...),
):
    """
    Start sending emails for a campaign.
    Uses stored refresh_token (Web flow) to get fresh MS access token.
    MVP: synchronous send (no Celery).
    """
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign["status"] == "sending":
        raise HTTPException(status_code=409, detail="Campaign already sending")
    if campaign["status"] == "sent":
        raise HTTPException(status_code=409, detail="Campaign already sent")

    # Audit: the exact click-Send moment, before we even touch Microsoft.
    # This is the "user initiated the send" evidence row.
    pending_count = contact_model.get_campaign_contacts_count(campaign_id)
    audit.emit(
        audit.EVENT_SEND_TRIGGERED,
        user_id=user["id"],
        email=user["email"],
        metadata={
            "campaign_id": campaign_id,
            "pending_contacts": pending_count,
            "plan": user.get("plan", "free"),
        },
        request=request,
    )

    # ── Get fresh access token via refresh_token (Web flow) ──
    from models.ms_token import get_fresh_access_token

    x_ms_token = get_fresh_access_token(user["id"])
    if not x_ms_token:
        raise HTTPException(
            status_code=401,
            detail="Could not refresh Microsoft token. Please log out and log in again.",
        )

    # ── Freemium check ──
    sent_this_month = user.get("emails_sent_this_month", 0)
    plan = user.get("plan", "free")

    pending = contact_model.get_pending_contacts(campaign_id)
    if not pending:
        raise HTTPException(status_code=400, detail="No pending contacts")

    # ── C.2: Merge-tag validation ──
    for field_name, content in (
        ("subject", campaign["subject"]),
        ("body", campaign["body"]),
    ):
        malformed = find_malformed_tags(content or "")
        if malformed:
            raise HTTPException(
                status_code=400,
                detail=f"Malformed merge tag in {field_name}: {malformed[0]}",
            )
    # Collect contact keys actually present in the pending set (first row is enough)
    first_contact = pending[0]
    contact_keys: set[str] = set()
    key_remap = {"first_name": "firstName", "last_name": "lastName"}
    for k, v in first_contact.items():
        if v not in (None, ""):
            contact_keys.add(key_remap.get(k, k))
    for k in (first_contact.get("custom_fields") or {}).keys():
        contact_keys.add(k)
    unknown_subj = find_unknown_tags(campaign["subject"] or "", contact_keys)
    unknown_body = find_unknown_tags(campaign["body"] or "", contact_keys)
    unknowns = sorted(set(unknown_subj + unknown_body))
    if unknowns:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown merge tags (not in CSV): {', '.join(unknowns)}",
        )

    if plan == "free":
        limit = FREE_PLAN_MONTHLY_LIMIT
    elif plan == "starter":
        limit = STARTER_PLAN_MONTHLY_LIMIT
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
                    unsubscribe_text=user.get("unsubscribe_text", "Unsubscribe"),
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


# ── C.3: Test Send ──
#
# Two variants, same behavior:
#   POST /campaigns/test-send           — stateless, subject+body in body (preferred)
#   POST /campaigns/{campaign_id}/test-send — legacy, reads subject+body from a
#       persisted campaign row (kept for backwards compat with older extensions)
#
# Neither variant consumes monthly quota nor writes any contact/campaign row.


class TestSendRequest(BaseModel):
    sample: dict | None = None  # optional merge-tag values (first CSV row)
    # Stateless path uses these; legacy path ignores them.
    subject: str | None = None
    body: str | None = None


async def _run_test_send(
    subject: str, email_body: str, sample: dict | None, user: dict
) -> dict:
    """Shared implementation: validate + send one preview email to the user."""
    subject = subject or ""
    email_body = email_body or ""
    if not subject.strip() or not email_body.strip():
        raise HTTPException(
            status_code=400, detail="Subject and body are required"
        )

    for field_name, content in (("subject", subject), ("body", email_body)):
        malformed = find_malformed_tags(content)
        if malformed:
            raise HTTPException(
                status_code=400,
                detail=f"Malformed merge tag in {field_name}: {malformed[0]}",
            )

    from models.ms_token import get_fresh_access_token

    access_token = get_fresh_access_token(user["id"])
    if not access_token:
        raise HTTPException(
            status_code=401,
            detail="Could not refresh Microsoft token. Please log in again.",
        )

    sample = sample or {}
    synthetic_campaign = {"subject": subject, "body": email_body}
    synthetic_contact = {
        "id": "test-stateless",
        "email": user["email"],
        "first_name": sample.get("firstName", "Test"),
        "last_name": sample.get("lastName", "User"),
        "company": sample.get("company", ""),
        "position": sample.get("position", ""),
        "custom_fields": {
            k: v
            for k, v in sample.items()
            if k
            not in ("firstName", "lastName", "company", "position", "email")
        },
    }

    async with httpx.AsyncClient() as client:
        result = await _send_single_email(
            client=client,
            access_token=access_token,
            campaign=synthetic_campaign,
            contact=synthetic_contact,
            track_opens=False,
            track_clicks=False,
            unsubscribe_text=user.get("unsubscribe_text", "Unsubscribe"),
            sender_info=user,
        )

    if not result.get("success"):
        raise HTTPException(
            status_code=502, detail=result.get("error", "Test send failed")
        )

    return {"success": True, "sent_to": user["email"]}


@router.post("/test-send")
async def test_send_stateless(
    body: TestSendRequest,
    user: dict = Depends(get_current_user),
):
    """Preferred: send one test email using subject+body from request.

    Does NOT create a campaign row, so test sends never pollute the
    Reports tab. This is what the extension uses.
    """
    return await _run_test_send(
        subject=body.subject or "",
        email_body=body.body or "",
        sample=body.sample,
        user=user,
    )


@router.post("/{campaign_id}/test-send")
async def test_send(
    campaign_id: str,
    body: TestSendRequest,
    user: dict = Depends(get_current_user),
):
    """Legacy: read subject+body from an existing campaign row.

    Kept so older extension versions still work while Chrome auto-updates
    users to the new stateless flow. Can be removed after v0.2.x.
    """
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")
    # Treat as before, share impl.
    result_payload = await _run_test_send(
        subject=campaign["subject"] or "",
        email_body=campaign["body"] or "",
        sample=body.sample,
        user=user,
    )
    return result_payload


# ── D.2: Archive Endpoints ──


@router.post("/{campaign_id}/archive")
async def archive_campaign(
    campaign_id: str,
    user: dict = Depends(get_current_user),
):
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign_model.set_archived(campaign_id, True)
    return {"campaign_id": campaign_id, "archived": True}


@router.post("/{campaign_id}/unarchive")
async def unarchive_campaign(
    campaign_id: str,
    user: dict = Depends(get_current_user),
):
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign_model.set_archived(campaign_id, False)
    return {"campaign_id": campaign_id, "archived": False}


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
    unsubscribe_text: str = "Unsubscribe",
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
    # Plain-text input needs newline→<br> conversion since Graph sends HTML.
    merged_body = _text_to_html(merged_body)

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
        # Audit: one row per successfully dispatched email. Graph sometimes
        # surfaces a message_id via a Location header on 202; capture it
        # when present so the audit trail links back to Microsoft's own
        # mailbox records.
        try:
            graph_msg_id = resp.headers.get("Location") or resp.headers.get("x-ms-message-id")
        except Exception:  # noqa: BLE001
            graph_msg_id = None
        audit.emit_email_sent(
            user_id=campaign.get("user_id"),
            campaign_id=campaign.get("id"),
            recipient_email=contact.get("email", ""),
            graph_message_id=graph_msg_id,
            status_code=resp.status_code,
        )
        return {"success": True}

    error_detail = ""
    try:
        error_detail = resp.json().get("error", {}).get("message", "")
    except Exception:
        error_detail = f"HTTP {resp.status_code}"

    return {"success": False, "error": error_detail}


def _fetch_previous_emails(
    user_id: str, exclude_campaign_id: str, sent_cutoff_iso: str
) -> set[str]:
    """Return lowercase emails the user has already contacted (sent or pending).

    - Limited to campaigns owned by user_id.
    - The current campaign (exclude_campaign_id) is excluded.
    - sent contacts are filtered by sent_at >= cutoff; pending contacts
      are always included regardless of age (they're an active outbox).
    """
    db = get_db()
    camps = (
        db.table("campaigns")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )
    camp_ids = [
        c["id"]
        for c in (camps.data or [])
        if c.get("id") != exclude_campaign_id
    ]
    if not camp_ids:
        return set()

    emails: set[str] = set()
    for cid in camp_ids:
        sent = (
            db.table("contacts")
            .select("email")
            .eq("campaign_id", cid)
            .eq("status", "sent")
            .gte("sent_at", sent_cutoff_iso)
            .execute()
        )
        pending = (
            db.table("contacts")
            .select("email")
            .eq("campaign_id", cid)
            .eq("status", "pending")
            .execute()
        )
        for r in (sent.data or []):
            if r.get("email"):
                emails.add(r["email"].lower())
        for r in (pending.data or []):
            if r.get("email"):
                emails.add(r["email"].lower())
    return emails


_HTML_TAG_RE = re.compile(r"<[a-z!/][^>]*>", re.IGNORECASE)


def _text_to_html(body: str) -> str:
    """Convert plain-text body to simple HTML when no markup is present.

    Graph API sends with `contentType: HTML`, so newlines in plain-text
    input disappear unless we convert them. If the user already pasted
    HTML tags (any `<tag>` form), pass through unchanged so their
    formatting survives.
    """
    if not body:
        return body
    if _HTML_TAG_RE.search(body):
        return body
    escaped = (
        body.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
    # Double newline → paragraph break; single → line break.
    # Normalize CRLF first so Windows-authored templates behave the same.
    escaped = escaped.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.replace("\n", "<br>") for p in escaped.split("\n\n")]
    return "<p>" + "</p><p>".join(paragraphs) + "</p>"


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
