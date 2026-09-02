"""
OutMass — Campaigns Router
POST /campaigns                   → create campaign
GET  /campaigns                   → list campaigns
GET  /campaigns/{id}/stats        → campaign statistics
POST /campaigns/{id}/contacts     → upload contacts
POST /campaigns/{id}/send         → start sending
"""

import asyncio
import base64
import csv
import io
import logging
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from config import (
    BACKEND_URL,
    CANCEL_CHECK_EVERY,
    FREE_PLAN_MONTHLY_LIMIT,
    STARTER_PLAN_MONTHLY_LIMIT,
    PRO_PLAN_MONTHLY_LIMIT,
    GRAPH_API_BASE,
    OUTBOUND_HTTP_TIMEOUT,
    RATE_LIMIT_WAIT_SECONDS,
    QUOTA_CHARGE_BATCH,
    SEND_DELAY_SECONDS,
    SUPABASE_MAX_ROWS,
    FOLLOWUP_LOCKED_MIN_CLIENT,
    upload_limit_for_plan,
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
from utils import welcome_email
from utils.client_version import client_at_least
from utils.email_body import render_body
from utils.merge_tags import (
    CONTACT_TAGS,
    build_merge_context,
    find_malformed_tags,
    find_unknown_tags,
)
from utils.send_classify import _classify_failure  # re-exported for the send loop

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


# ── Schemas ──


class AttachmentRequest(BaseModel):
    name: str
    url: str


class CreateCampaignRequest(BaseModel):
    name: str
    subject: str
    body: str
    scheduled_for: str | None = None  # ISO datetime string, e.g. "2026-03-30T09:00:00Z"
    # Multi-day spread: send at most this many contacts per day; the
    # scheduled worker rolls the schedule forward daily until done.
    # Requires scheduled_for (the sidebar auto-schedules "now" when the
    # user sets a cap without picking a date). 0/None = no cap.
    daily_send_cap: int | None = None
    send_days: list[int] | None = None
    # OneDrive sharing links the user added in the sidebar's
    # Attachments section. Stored as JSON on the campaign row and
    # rendered as a footer block on every outgoing email by the
    # shared utils.email_attachments helper.
    attachments: list[AttachmentRequest] = []


class UploadContactsRequest(BaseModel):
    csv_string: str | None = None
    contacts: list[dict] | None = None


class CreateFollowupRequest(BaseModel):
    # Bounded. The panel sends parseInt(value, 10) || 3, which passes a typed
    # -1 straight through the input's min="1" — and a negative delay puts the
    # follow-up's due moment BEFORE the campaign, so it goes out on the next
    # beat instead of days later. 365 is well past any real cadence.
    delay_days: int = Field(3, ge=1, le=365)
    subject: str
    body: str
    condition: str = "not_opened"


class CreateAbTestRequest(BaseModel):
    subject_a: str
    subject_b: str
    test_percentage: int = 20  # % of contacts for testing


class ValidateTagsRequest(BaseModel):
    subject: str | None = None
    body: str | None = None
    sample: dict | None = None  # CSV first row (column→value), for available tags


# ── Merge-tag validation (shared by send, test-send, validate-tags) ──


def _raise_if_bad_merge_tags(
    subject: str | None,
    body: str | None,
    allowed_keys: set[str],
    available_tags: list[str],
) -> None:
    """Validate merge tags in subject+body. Raise a structured HTTPException
    (matching the feature_locked pattern background.js parses via detail.error)
    on the first malformed or unknown tag; otherwise return None.

    Shared by send_campaign, _run_test_send, and the validate-tags endpoint so
    all three surface IDENTICAL errors. `allowed_keys` is the set of resolvable
    column names; `available_tags` is the user-facing list shown in the unknown
    error (the columns the user can actually use).
    """
    for field_name, content in (("subject", subject or ""), ("body", body or "")):
        malformed = find_malformed_tags(content)
        if malformed:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "malformed_merge_tag",
                    "tag": malformed[0],
                    "field": field_name,
                    "message": f"Malformed merge tag in {field_name}: {malformed[0]}",
                },
            )
    unknown_subj = find_unknown_tags(subject or "", allowed_keys)
    unknown_body = find_unknown_tags(body or "", allowed_keys)
    unknowns = sorted(set(unknown_subj + unknown_body))
    if unknowns:
        field = "subject" if unknown_subj else "body"
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unknown_merge_tags",
                "tags": unknowns,
                "field": field,
                "available_tags": available_tags,
                "message": (
                    f"Unknown merge tags (not in CSV): {', '.join(unknowns)}. "
                    f"Available: {', '.join(available_tags)}"
                ),
            },
        )


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

    # Daily cap rides the scheduled-send machinery, so it inherits the
    # same plan gate below. Clamp to a sane range; 0/negative = no cap.
    if body.send_days is not None:
        # ISO weekdays, deduplicated and ordered so the stored value reads the
        # way a person would write it. An empty list means "never send", which
        # nobody wants and the column's CHECK constraint refuses - treat it as
        # "no restriction" rather than bouncing the whole campaign over a
        # checkbox nobody ticked.
        days = sorted({int(d) for d in body.send_days if 1 <= int(d) <= 7})
        body.send_days = days or None
    if body.daily_send_cap is not None:
        if body.daily_send_cap <= 0:
            body.daily_send_cap = None
        else:
            body.daily_send_cap = min(body.daily_send_cap, 5000)
            if not body.scheduled_for:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "cap_requires_schedule",
                        "message": "A daily send limit needs a scheduled start time.",
                    },
                )

    # Scheduled sending requires Starter+ plan
    if body.scheduled_for:
        plan = user_model.effective_plan(user)
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

    # Cap attachment count + reject malformed URLs as a defense-in-depth
    # check; the picker SDK already restricts what users can submit.
    safe_attachments = []
    for att in (body.attachments or [])[:10]:
        if att.url and att.name:
            safe_attachments.append({"name": att.name[:200], "url": att.url[:1000]})

    campaign = campaign_model.create_campaign(
        user_id=user["id"],
        name=body.name,
        subject=body.subject,
        body=body.body,
        scheduled_for=body.scheduled_for,
        attachments=safe_attachments,
        daily_send_cap=body.daily_send_cap,
        send_days=body.send_days,
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
            "attachment_count": len(safe_attachments),
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

    # sent_count is EMAILS SENT. It is not the denominator of an engagement
    # rate, and using it as one was wrong in two ways at once:
    #
    #   - a follow-up adds to sent_count without adding a recipient, so the
    #     first campaign to actually receive a follow-up would have shown
    #     "180 sent" for a list of 100 and four rates at roughly half their
    #     true value;
    #   - it counts recipients this campaign could not reach, and there is no
    #     sense in which someone who was never emailed failed to open.
    #
    # The denominator is how many people actually received it. Kept separate
    # from the displayed count on purpose: both numbers are true, they just
    # answer different questions.
    sent = campaign["sent_count"] or 0
    delivered = contact_model.count_delivered_contacts(campaign_id)
    open_rate = round((campaign["open_count"] / delivered) * 100, 1) if delivered > 0 else 0.0
    click_rate = round((campaign["click_count"] / delivered) * 100, 1) if delivered > 0 else 0.0

    # ── Engaged + reply metrics ──
    # open_count and click_count are atomically incremented stat counters
    # on the campaigns row. They aren't unique per contact (a recipient
    # who opens five times bumps open_count five times), and they don't
    # tell us whether opens and clicks come from the SAME recipient.
    #
    # We pull the contact rows ONCE and derive three distinct-recipient
    # metrics in Python:
    #   - opened_unique: distinct contacts with opened_at set
    #   - replied_count: distinct contacts whose Inbox reply was matched
    #     by the daily reply-detector beat
    #   - engaged_count: distinct contacts who opened OR clicked OR replied
    #
    # Replied is the strongest signal — replies arrive even when pixels
    # don't load and even when the recipient never clicks a link.
    db = get_db()
    engaged_count = 0
    replied_count = 0
    try:
        engaged_rows = (
            db.table("contacts")
            .select("id, opened_at, clicked_at, replied_at")
            .eq("campaign_id", campaign_id)
            .limit(SUPABASE_MAX_ROWS)
            .execute()
        )
        rows = engaged_rows.data or []
        if len(rows) >= SUPABASE_MAX_ROWS and delivered > SUPABASE_MAX_ROWS:
            # The page is at its ceiling and there are more recipients than
            # it can hold, so any number derived from it is short by an
            # unknown amount. A number that is quietly too low is worse than
            # no number: it is read as a result.
            raise RuntimeError("engagement page truncated")
        for row in rows:
            opened = bool(row.get("opened_at"))
            clicked = bool(row.get("clicked_at"))
            replied = bool(row.get("replied_at"))
            if opened or clicked or replied:
                engaged_count += 1
            if replied:
                replied_count += 1
    except Exception:  # noqa: BLE001 — never break stats response on a count failure
        # None, not 0. Zero is an answer, and it is the answer the user is
        # most afraid of: "nobody replied". Saying nothing is the honest
        # outcome of a read that did not happen, and the panel renders it as
        # a dash, which needs no translation.
        logging.getLogger(__name__).warning(
            "engagement stats unavailable for campaign %s", campaign_id,
            exc_info=True,
        )
        engaged_count = None
        replied_count = None
    engaged_rate = (
        round((engaged_count / delivered) * 100, 1)
        if engaged_count is not None and delivered > 0
        else None
    )
    reply_rate = (
        round((replied_count / delivered) * 100, 1)
        if replied_count is not None and delivered > 0
        else None
    )

    followups = followup_model.get_campaign_followups(campaign_id)
    pending_followups = sum(1 for f in followups if f["status"] == "scheduled")

    return {
        "campaign_id": campaign_id,
        "name": campaign["name"],
        "status": campaign["status"],
        "total_contacts": campaign["total_contacts"],
        # What the campaign actually says. There was no way to see this after
        # a campaign was created — Reports carried the numbers and never the
        # message. Hélène Carpentier, 2026-09-02: "I can't seem to see what
        # the campaign is anymore on the extension… It would be really good if
        # we could see the detail of campaign too once it is set up."
        #
        # She asked in the same message whether we had added a second
        # signature to her email. We had not, but she had no way to check, and
        # a person who cannot read their own campaign has to ask us instead.
        "subject": campaign.get("subject") or "",
        "body": campaign.get("body") or "",
        "sent_count": sent,
        # Recipients who actually received it, which is what every rate above
        # is divided by. Reported so the panel can show the two numbers apart
        # instead of implying they are the same one.
        "delivered_count": delivered,
        "open_count": campaign["open_count"],
        "click_count": campaign["click_count"],
        "engaged_count": engaged_count,
        "replied_count": replied_count,
        "open_rate": open_rate,
        "click_rate": click_rate,
        "engaged_rate": engaged_rate,
        "reply_rate": reply_rate,
        "pending_followups": pending_followups,
        # How long after each recipient receives the campaign their follow-up
        # goes out. The panel had a bare count, which cannot tell a bump due
        # tonight from one due next week — and since follow-ups now trail a
        # paced campaign rather than firing together at the end, "pending"
        # is a state a user can sit in for days without being able to see
        # why. The first scheduled one is enough: the panel creates one per
        # send, and a campaign carrying several would still be described
        # correctly by the soonest.
        "followup_delay_days": next(
            (f.get("delay_days") for f in followups if f["status"] == "scheduled"),
            None,
        ),
        # A follow-up written for this campaign that the plan could not run.
        # Inert until activated; surfaced so the panel can say it is there
        # rather than leaving the user to remember writing it.
        "locked_followup": next(
            (
                {"id": f["id"], "delay_days": f.get("delay_days"),
                 "subject": f.get("subject")}
                for f in followups
                if f["status"] == "locked"
            ),
            None,
        ),
    }


@router.get("/{campaign_id}/export")
async def export_campaign_csv(
    campaign_id: str,
    user: dict = Depends(get_current_user),
):
    """Export campaign contacts as CSV. Requires Standard+ plan."""
    plan = user_model.effective_plan(user)
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


# ── CSV encoding detection ──
#
# The extension decodes CSVs itself and refuses anything it cannot place from
# the user's own language — deliberately, because the legacy single-byte
# tables cannot fail on wrong input, so a wrong guess is undetectable and
# ends up as a mangled name in a sent email. That refusal is safe but it is
# still a dead end, and it is not rare: Turkish, Polish, Baltic, Vietnamese
# and Western European lists all land there.
#
# This endpoint is the second opinion for exactly that population. Measured
# 2026-08-08 on a 51-file corpus (12 languages, real and short sizes):
#
#   on the files the extension refuses   charset-normalizer  8 of 9 correct
#                                        jschardet (bundled) 3 of 9 correct
#
# jschardet was rejected on three independent grounds — that accuracy, 334 KB
# minified against a 243 KB extension, and LGPL-2.1+ on a closed-source
# product. Server-side detection costs a round trip and no bundle at all.
#
# What this endpoint must NOT become: an authority. charset-normalizer's own
# confidence does not separate its right answers from its wrong ones (chaos
# 0.0 appears in both sets, measured), so the result is a SUGGESTION the user
# confirms against a preview, never a silent decision. Ship it that way.

# Python codec names are not WHATWG labels — TextDecoder rejects "utf_8" and
# "cp932" outright. Only names in this table are ever returned, and the
# mapping is the safety feature rather than a convenience: a detection the
# browser cannot use (cp775, cp850, mac_latin2) becomes null, which the
# client already knows how to handle because null is what it does today.
_WHATWG_LABELS = {
    "utf_8": "utf-8", "utf_8_sig": "utf-8", "ascii": "utf-8",
    "cp1250": "windows-1250", "cp1251": "windows-1251",
    "cp1252": "windows-1252", "cp1253": "windows-1253",
    "cp1254": "windows-1254", "cp1255": "windows-1255",
    "cp1256": "windows-1256", "cp1257": "windows-1257",
    "cp1258": "windows-1258", "cp874": "windows-874", "cp866": "ibm866",
    "koi8_r": "koi8-r", "koi8_u": "koi8-u", "mac_cyrillic": "x-mac-cyrillic",
    "iso8859_2": "iso-8859-2", "iso8859_3": "iso-8859-3",
    "iso8859_4": "iso-8859-4", "iso8859_5": "iso-8859-5",
    "iso8859_6": "iso-8859-6", "iso8859_7": "iso-8859-7",
    "iso8859_8": "iso-8859-8", "iso8859_9": "windows-1254",
    "iso8859_10": "iso-8859-10", "iso8859_13": "iso-8859-13",
    "iso8859_14": "iso-8859-14", "iso8859_15": "iso-8859-15",
    "iso8859_16": "iso-8859-16", "latin_1": "windows-1252",
    "cp932": "shift_jis", "shift_jis": "shift_jis", "euc_jp": "euc-jp",
    "cp936": "gbk", "gbk": "gbk", "gb18030": "gb18030",
    "cp950": "big5", "big5": "big5", "big5hkscs": "big5",
    "cp949": "euc-kr", "euc_kr": "euc-kr",
    "utf_16": "utf-16le", "utf_16_le": "utf-16le", "utf_16_be": "utf-16be",
}

# 64 KB decides it. Measured on a 5 MB list: the whole file takes 2521 ms and
# 64 KB takes 19 ms, for the same answer — and the whole-file version is a
# denial-of-service invitation on an authenticated endpoint that accepts
# arbitrary bytes.
_DETECT_SAMPLE_BYTES = 64 * 1024


class DetectEncodingRequest(BaseModel):
    # base64 of the FIRST 64 KB, not the file. The client slices before it
    # sends because the server samples anyway, so there is no reason for a
    # customer's whole contact list to cross the wire for a question a slice
    # answers identically (measured: 19 ms vs 2521 ms on 5 MB, same answer).
    #
    # base64 rather than a raw body because backendFetch — the extension's
    # single authenticated request path, with the sticky host failover, the
    # 20s timeout and the sliding-JWT refresh — JSON-stringifies every body.
    # Bending that one function for this one caller would be the wrong trade.
    sample_b64: str


@router.post("/detect-encoding")
async def detect_encoding(
    body: DetectEncodingRequest,
    user: dict = Depends(get_current_user),
):
    """Second opinion on a CSV the extension could not decode.

    Returns a WHATWG label the browser can hand straight to TextDecoder, or
    null.

    The bytes are a customer's contact list — real names, real addresses.
    They are decoded into memory, sampled, and dropped. Nothing here logs,
    stores, hashes or forwards them, and the response carries the label and a
    byte count and nothing else. Anything added later must keep that true.
    """
    try:
        raw = base64.b64decode(body.sample_b64 or "", validate=True)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="sample_b64 is not valid base64")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty sample")
    if len(raw) > _DETECT_SAMPLE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Sample exceeds {_DETECT_SAMPLE_BYTES // 1024} KB",
        )

    sample = raw
    # Cut back to the last line break so a half-read multi-byte character at
    # the boundary cannot skew the verdict.
    nl = sample.rfind(b"\n")
    if nl > 0:
        sample = sample[:nl]

    try:
        from charset_normalizer import from_bytes

        best = from_bytes(sample).best()
    except Exception:  # noqa: BLE001
        # Never let a detector fault break an upload. The client's own chain
        # already handled the common cases; this is the extra mile.
        logging.getLogger(__name__).warning("encoding detection failed", exc_info=True)
        return {"encoding": None, "sampled_bytes": len(sample)}

    label = _WHATWG_LABELS.get(best.encoding) if best else None
    logging.getLogger(__name__).info(
        "encoding detection: sampled=%s guess=%s label=%s",
        len(sample),
        best.encoding if best else None,
        label,
    )
    return {"encoding": label, "sampled_bytes": len(sample)}


@router.post("/{campaign_id}/contacts")
async def upload_contacts(
    campaign_id: str,
    body: UploadContactsRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    # Sent by backendFetch on every authenticated call since 0.1.x
    # (extension/background.js:910). Absent means a build we cannot vouch
    # for, which reads as old.
    x_extension_version: Annotated[str | None, Header()] = None,
):
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    plan = user_model.effective_plan(user)
    # Same number for every plan; the helper stays the single source so this
    # cannot drift from /settings the way the inline copy of this dict could.
    row_limit = upload_limit_for_plan(plan, x_extension_version)

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
        # Header names are stripped: hand-made CSVs often have spaces after
        # commas ("email, Company"), which used to key custom_fields by
        # " Company" — a column the {{tag}} syntax (\w+) could never
        # reference, and a padded " email" even failed the mandatory-column
        # check. The sidebar's merge-tag chips are built from trimmed
        # headers, so storage must agree with them (0.1.26 review finding).
        # A.2: Mandatory 'email' column (case-insensitive)
        headers = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
        if "email" not in headers:
            raise HTTPException(
                status_code=400,
                detail="Column 'email' is required in the CSV header",
            )
        for row in reader:
            normalized: dict = {}
            for k, v in row.items():
                key = (k or "").strip()
                if not key:
                    continue
                if key.lower() == "email":
                    normalized["email"] = v
                else:
                    normalized[key] = v
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
    background_tasks: BackgroundTasks,
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
    # Roll the quota period over first if it elapsed — the reset otherwise
    # only ran at login, so a long-lived session (or a user who never
    # re-authed) could be wrongly blocked by LAST period's counter.
    user_model.check_monthly_reset(user)
    sent_this_month = user.get("emails_sent_this_month", 0)
    plan = user_model.effective_plan(user)

    pending = contact_model.get_resumable_contacts(campaign_id)
    if not pending:
        raise HTTPException(status_code=400, detail="No pending contacts")

    # ── C.2: Merge-tag validation ──
    # Collect contact keys actually present in the pending set (first row is
    # enough). available_tags = the CSV columns the user can actually use:
    # filled standard contact fields + custom columns (e.g. "adSoyad"), with
    # internal row fields (id, status, ...) excluded by intersecting with
    # CONTACT_TAGS. Falls back to the standard contact tags if empty.
    first_contact = pending[0]
    contact_keys: set[str] = set()
    key_remap = {"first_name": "firstName", "last_name": "lastName"}
    for k, v in first_contact.items():
        if v not in (None, ""):
            contact_keys.add(key_remap.get(k, k))
    custom_keys = set((first_contact.get("custom_fields") or {}).keys())
    contact_keys |= custom_keys
    available_tags = sorted((contact_keys & CONTACT_TAGS) | custom_keys) or sorted(CONTACT_TAGS)
    _raise_if_bad_merge_tags(
        campaign["subject"], campaign["body"], contact_keys, available_tags
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
                "message": f"You've reached your monthly limit of {limit} emails",
                "emails_sent": sent_this_month,
                "limit": limit,
            },
        )
    # Cap to remaining quota — and REPORT it. This cap used to be silent: the
    # response said queued=N and nothing told the user the rest of their list
    # was skipped for quota, so they believed the whole list went out. The
    # skipped recipients stay 'pending' (resumable after upgrade/monthly reset).
    total_pending = len(pending)
    pending = pending[:remaining]
    quota_skipped = total_pending - len(pending)

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
    half = 0
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

    # ── Hand the actual send to a background task ──
    # The recipient loop runs one Graph call + a delay PER recipient, so a large
    # list takes minutes — far longer than the platform's HTTP request timeout,
    # which used to 502 a big "Send now" even though the send itself was fine.
    # All the synchronous prep above (token, quota, merge-tag validation, dedup,
    # suppression, A/B split) already gave the user immediate feedback; the send
    # itself now runs after the response returns, so the request never times out.
    send_list = pending if not ab_test else ab_group_a + ab_group_b
    background_tasks.add_task(
        _run_campaign_send,
        campaign_id,
        campaign,
        send_list,
        ab_test,
        half,
        ab_remaining,
        x_ms_token,
        user,
        suppressed_emails,
        quota_skipped > 0,
    )

    # Quota-capped: the skipped recipients stay 'pending' and the
    # auto_resume_partial_campaigns beat sends them automatically once the
    # rolling reset (or an upgrade) restores headroom. Tell the user by
    # email so nobody has to remember a Resume click (2026-07-20: a
    # Starter capped at exactly 2,500 with 250 recipients parked).
    if quota_skipped > 0:
        next_reset = user_model.next_reset_date(user)
        background_tasks.add_task(
            welcome_email.send_quota_capped_email,
            user.get("email"),
            user.get("name"),
            quota_skipped,
            limit,
            next_reset.isoformat() if next_reset else None,
            user.get("preferred_language"),
        )

    return {
        "queued": len(send_list),
        "campaign_id": campaign_id,
        "status": "sending",
        "errors": [],
        "ab_test": bool(ab_test),
        # Explicit quota-cap signal so the client can tell the user exactly
        # how many recipients were left out of this batch (never silently).
        "quota_capped": quota_skipped > 0,
        "quota_skipped": quota_skipped,
    }


async def _run_campaign_send(
    campaign_id: str,
    campaign: dict,
    send_list: list,
    ab_test: dict | None,
    half: int,
    ab_remaining: list,
    access_token: str,
    user: dict,
    suppressed_emails: set,
    quota_capped: bool = False,
):
    """Send a campaign's recipients off the request path (FastAPI BackgroundTask).

    A large list (one Graph call + SEND_DELAY per recipient) can run for minutes —
    longer than the platform's HTTP request timeout — so doing it inside the
    request 502'd big "Send now" campaigns even though the send was fine. The
    caller has already validated everything and marked the campaign 'sending';
    this drives it to 'sent' / 'partial' / 'ab_testing'. A process restart
    mid-send leaves it 'sending', which the hourly stuck-sending sweep recovers
    to 'partial' for Resume — so no recipients are silently lost.
    """
    sent_count = 0
    errors = []
    # Renamed from token_expired_midbatch on 2026-08-30. The old name
    # asserted a diagnosis the code cannot make: 401 and 403 arrive on the
    # same branch, and a 403 from sendMail is usually not the token at all
    # — it is Microsoft refusing to send from that mailbox. Two campaigns
    # stopped this way that day, 17 and 9 minutes after a fresh sign-in,
    # and the name sent the first reading of the logs down the wrong path.
    auth_stopped_midbatch = False
    # What Graph actually said, kept for the end-of-send log. Until this was
    # added the one branch that halts a whole campaign recorded the least:
    # `errors` is never appended to here, so the summary printed
    # "failed=0 first_error=[]" and the status code was lost.
    abort_status = None
    abort_error = ""
    # The quota counter is bumped once on the happy path and once more in the
    # failure handler, so recipients sent before a mid-batch crash still count.
    # Without this flag ANY exception raised after the first bump charges the
    # user twice — which is what the `import logging` shadowing did to every
    # send between 2026-08-04 and 08-06. Fixing that shadowing removed the
    # trigger; this removes the whole failure mode.
    quota_counted = False
    # How much of sent_count has already been charged to the monthly quota.
    # Every path that charges must move this with it, or a recovery handler
    # bills the same recipients twice.
    quota_charged = 0
    # Set when the owner stops the campaign while this loop is running. Every
    # close-out below is conditional anyway, but the A/B branch also writes to
    # a second table, and that write has no status to be conditional on.
    cancelled_midbatch = False
    try:
        async with httpx.AsyncClient(timeout=OUTBOUND_HTTP_TIMEOUT) as client:
            for idx, contact in enumerate(send_list):
                # Ask whether we are still wanted. The scheduled path does the
                # same thing at the same interval; this one was the gap that
                # made the Stop button's own message untrue — "$1 reached, $2
                # will not be contacted" while the loop kept going through all
                # $2 of them.
                if idx and idx % CANCEL_CHECK_EVERY == 0:
                    # A read that fails must not halt the send. The durable
                    # protection is the conditional close-out below, which
                    # cannot write over a cancellation whatever happens here;
                    # this only shortens the overshoot. Trading a bounded
                    # overshoot for an outage on one flaky select is the worse
                    # bargain.
                    try:
                        still_ours = campaign_model.get_status(campaign_id)
                    except Exception:  # noqa: BLE001
                        logging.getLogger(__name__).warning(
                            "campaign %s: cancellation check failed, continuing",
                            campaign_id, exc_info=True,
                        )
                        still_ours = "sending"
                    if still_ours != "sending":
                        cancelled_midbatch = True
                        logging.getLogger(__name__).info(
                            "campaign %s stopped by its owner mid-batch after "
                            "%s sent", campaign_id, sent_count,
                        )
                        break
                if contact.get("unsubscribed"):
                    # Already excluded from every resumable set by the
                    # unsubscribed flag itself — nothing to record.
                    continue
                if contact.get("email", "").lower() in suppressed_emails:
                    # Record the skip. A bare `continue` left these 'pending'
                    # forever, so they stayed in every resumable set and made
                    # Resume/auto-resume think work remained.
                    #
                    # GUARDED ON PURPOSE. This sits ABOVE the per-contact
                    # try (below), so an unguarded raise here is caught by
                    # the function-level handler and aborts the ENTIRE
                    # campaign — a bookkeeping write killing delivery. Worse,
                    # with sent_count still 0 the campaign lands on
                    # 'scheduled' with scheduled_for NULL, which no recovery
                    # path queries. Failing to record only restores the old
                    # benign behaviour (row stays 'pending'), so swallow it.
                    try:
                        contact_model.mark_suppressed(contact["id"])
                    except Exception:  # noqa: BLE001
                        logging.getLogger(__name__).warning(
                            "Could not mark contact %s suppressed; skipping anyway",
                            contact.get("id"),
                            exc_info=True,
                        )
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
                        access_token=access_token,
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
                        # Charge the quota in batches as we go, not once at
                        # the end. The end is not guaranteed to arrive: a
                        # Railway deploy or an OOM kills this task mid-loop,
                        # and every recipient already emailed and marked
                        # 'sent' was then free — the durable per-contact
                        # state said they went out while the counter said
                        # they never did. A SIGKILL runs no handler at all,
                        # so no except block can fix that; only having
                        # already written the number can.
                        #
                        # 25 bounds the loss to at most 24 emails however the
                        # process dies, at one extra write per 25 sends.
                        if sent_count - quota_charged >= QUOTA_CHARGE_BATCH:
                            # Its own try, for the reason the three worker
                            # loops already have one (scheduled_worker.py:189):
                            # mark_sent committed twelve lines up, so letting a
                            # quota-write failure reach the per-contact except
                            # below would run mark_failed(..., "deferred") on a
                            # recipient who HAS the email, and Resume would
                            # send it to them a second time. Leaving
                            # quota_charged unadvanced is correct — the
                            # end-of-loop flush recharges it.
                            try:
                                user_model.increment_sent_count(
                                    user["id"], sent_count - quota_charged,
                                    reason="send_now", email=user.get("email"),
                                )
                                quota_charged = sent_count
                            except Exception:  # noqa: BLE001
                                logging.getLogger(__name__).warning(
                                    "batch quota charge failed; deferring to "
                                    "the end-of-loop flush",
                                    exc_info=True,
                                )
                    else:
                        sc = result.get("status_code")
                        if sc in (401, 403):
                            # Not this RECIPIENT being refused — the mailbox or
                            # the token. Either way it hits every remaining
                            # send, so stop and leave the rest 'pending'
                            # (resumable) rather than burning the list one
                            # doomed request at a time.
                            #
                            # 401 and 403 mean different things and we cannot
                            # tell them apart afterwards without this log line.
                            # 401: the access token is dead, and Resume gets a
                            # fresh one. 403: Microsoft is refusing the send —
                            # a new consumer mailbox under an anti-abuse limit,
                            # SendAs denied, a blocked account — and Resume
                            # will hit exactly the same wall until whatever it
                            # is clears.
                            auth_stopped_midbatch = True
                            abort_status = sc
                            abort_error = str(result.get("error") or "")[:200]
                            break
                        contact_model.mark_failed(contact["id"], _classify_failure(sc))
                        errors.append(contact.get("email"))
                except Exception:  # noqa: BLE001
                    contact_model.mark_failed(contact["id"], "deferred")
                    errors.append(contact.get("email"))

                if sent_count < len(send_list):
                    await asyncio.sleep(SEND_DELAY_SECONDS)

        # Whatever the batches have not covered yet.
        #
        # Deliberately NOT wrapped, unlike the in-loop batch above. A failure
        # here escapes to this function's own handler, which recharges (it
        # checks `not quota_counted`) and parks the campaign as 'partial'.
        # Catching it instead would keep the status honest and lose the charge
        # — free emails, silently. The status is recoverable (Resume finds
        # nothing pending and closes the campaign as 'sent'); an uncounted
        # send is not. Nothing was marked failed at this point either, so no
        # recipient can be emailed twice by it.
        if sent_count > quota_charged:
            user_model.increment_sent_count(
                user["id"], sent_count - quota_charged,
                reason="send_now", email=user.get("email"),
            )
            quota_charged = sent_count
        quota_counted = True

        # One line per finished send. The `errors` list was built through the
        # whole loop and then died with the function: a batch where every
        # single recipient was rejected 4xx by Graph produced no Railway line
        # at any level, so "I sent a campaign and nobody got it" was
        # unanswerable from the server side. Cheap and permanent.
        #
        # `logging` here is the MODULE-level import. Never add a local
        # `import logging` anywhere in this function: it makes the name local
        # to the whole scope, so this line raises UnboundLocalError before it
        # ever binds, every send lands in the handler below as 'partial', and
        # the quota gets charged twice.
        logging.getLogger(__name__).warning(
            "campaign %s finished: sent=%s failed=%s quota_capped=%s "
            "auth_stopped=%s abort_status=%s abort_error=%s first_error=%s",
            campaign_id,
            sent_count,
            len(errors),
            quota_capped,
            auth_stopped_midbatch,
            abort_status,
            abort_error,
            errors[:1],
        )

        if auth_stopped_midbatch:
            # Conditional like the rest: a mailbox Microsoft refused is still
            # not a reason to overwrite a cancellation the owner asked for.
            campaign_model.update_if_status(
                campaign_id, {"status": "partial"}, expected="sending"
            )
        elif ab_test and ab_remaining and not cancelled_midbatch:
            # Order matters. The campaign row is the one with a status to
            # guard, so move it first and only arm the A/B test if it applied
            # — otherwise a stopped campaign leaves an experiment waiting for
            # a winner that will never be sent.
            if campaign_model.update_if_status(
                campaign_id, {"status": "ab_testing"}, expected="sending"
            ):
                try:
                    ab_test_model.update_ab_test(
                        ab_test["id"], {"status": "awaiting_winner"}
                    )
                except Exception:  # noqa: BLE001
                    # Put the campaign back before letting this reach the
                    # handler below. That handler closes out conditionally on
                    # 'sending', so against a row already moved to
                    # 'ab_testing' it would silently no-op — leaving the
                    # campaign 'ab_testing' with its experiment still
                    # 'testing', a pair evaluate_ab_tests never selects (it
                    # queries 'awaiting_winner') and no sweep or resume path
                    # reaches either. Rolling back is what keeps the
                    # ordering-for-cancellation safe from costing us the
                    # recovery the old ordering gave for free.
                    campaign_model.update_if_status(
                        campaign_id, {"status": "sending"}, expected="ab_testing"
                    )
                    raise
        else:
            # A quota-capped batch that itself sends cleanly must still land
            # on 'partial': the recipients skipped for quota stay 'pending',
            # and BOTH resume paths (the Resume endpoint and the auto-resume
            # beat) only look at 'partial' campaigns. Closing as 'sent' here
            # stranded a Starter's 250 capped recipients invisibly —
            # discovered 2026-07-25 when their promised auto-resume never
            # fired (the campaign had closed as 'sent' on 07-20).
            # `errors` and `quota_capped` describe the ONE list fetched at
            # the top of this function, and that list is capped at
            # SUPABASE_MAX_ROWS. On 2026-06-30 a 1,020-recipient campaign
            # therefore sent a clean 1,000, saw no errors and no quota cap,
            # and closed itself 'sent' with twenty people who had never been
            # read out of the table at all. Nothing reopens 'sent', so they
            # were simply gone.
            #
            # The count is not paged, and it runs only when the answer would
            # otherwise be 'sent'.
            # Conditional on the campaign still being 'sending': if the
            # owner pressed Stop while this loop ran, the row says
            # 'cancelled' and this write must not undo that.
            campaign_model.update_if_status(
                campaign_id,
                {
                    "status": "sent"
                    if not errors
                    and not quota_capped
                    and not contact_model.has_resumable_contacts(campaign_id)
                    else "partial"
                },
                expected="sending",
            )
    except asyncio.CancelledError:
        # NOT covered by `except Exception`. CancelledError has derived from
        # BaseException since Python 3.8, and uvicorn raises it into the
        # awaits above when it cancels in-flight background tasks on
        # SIGTERM — i.e. on every deploy, which for this project is often.
        #
        # What that cost: each recipient is marked 'sent' and counted into
        # campaigns.sent_count as it goes, but the user's monthly quota is
        # charged ONCE after the whole loop. Cancelled mid-loop, the
        # per-contact state was durable and the quota charge simply
        # vanished, so a deploy during a 1,500-recipient send let ~600 real
        # emails go out uncounted — and the resumed remainder then charged
        # against a quota that had never seen them.
        #
        # Charge what actually went out, park the campaign where the
        # recovery paths can see it, then re-raise: swallowing cancellation
        # would leave the event loop shutting down while this task claims
        # to still be running.
        try:
            if not quota_counted and sent_count > quota_charged:
                user_model.increment_sent_count(
                    user["id"], sent_count - quota_charged,
                    reason="send_now", email=user.get("email"),
                )
                quota_charged = sent_count
        except Exception:  # noqa: BLE001
            pass
        try:
            # Conditional: if the owner pressed Stop and a deploy then killed
            # the task, the row already says 'cancelled' and parking it on
            # 'partial' would offer them a Resume button for a campaign they
            # ended.
            campaign_model.update_if_status(
                campaign_id, {"status": "partial"}, expected="sending"
            )
        except Exception:  # noqa: BLE001
            pass
        logging.getLogger(__name__).warning(
            "campaign %s cancelled mid-send: charged %s sent recipients",
            campaign_id,
            sent_count,
        )
        raise
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception(
            "Background campaign send failed: campaign=%s", campaign_id
        )
        try:
            if not quota_counted and sent_count > quota_charged:
                user_model.increment_sent_count(
                    user["id"], sent_count - quota_charged,
                    reason="send_now", email=user.get("email"),
                )
                quota_charged = sent_count
            # ALWAYS 'partial', never 'scheduled'. This function only ever runs
            # the send-NOW path (queued as a background task from /send), so
            # the campaign has scheduled_for NULL — and the due-campaign query
            # filters `.lte("scheduled_for", now)`, which never matches NULL.
            # A campaign parked on 'scheduled' here was therefore invisible to
            # the send beat, to Resume (409s unless 'partial'), to auto-resume
            # ('partial' only) and to the stuck sweep ('sending' only): its
            # recipients were unreachable by every path. 'partial' is the one
            # status the recovery machinery actually looks at.
            # Conditional for the same reason as every other close-out here:
            # a campaign whose owner stopped it has nothing to recover.
            campaign_model.update_if_status(
                campaign_id, {"status": "partial"}, expected="sending"
            )
        except Exception:  # noqa: BLE001
            pass


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

    # Merge-tag validation. The user's onboarding path is "try Test Send
    # first", so catch malformed AND unknown tags here too (not just in the
    # real send), using the sample row's columns (the CSV's first row, if any).
    sample_keys = set((sample or {}).keys())
    available_tags = sorted(sample_keys) or sorted(CONTACT_TAGS)
    _raise_if_bad_merge_tags(subject, email_body, sample_keys, available_tags)

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

    async with httpx.AsyncClient(timeout=OUTBOUND_HTTP_TIMEOUT) as client:
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


@router.post("/validate-tags")
async def validate_tags(
    body: ValidateTagsRequest,
    user: dict = Depends(get_current_user),
):
    """Validate merge tags without sending — used by the sidebar Preview so
    the user sees the SAME structured error as Send/Test Send before the
    preview modal opens. No email, no Graph token, no DB write."""
    sample_keys = set((body.sample or {}).keys())
    available_tags = sorted(sample_keys) or sorted(CONTACT_TAGS)
    _raise_if_bad_merge_tags(body.subject, body.body, sample_keys, available_tags)
    return {"valid": True}


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


# Statuses a campaign can still be stopped FROM. Everything else has already
# finished or already been stopped, and offering to stop it would promise
# something that does not happen.
STOPPABLE_STATUSES = {
    "scheduled", "sending", "partial", "pending",
    "ab_testing", "awaiting_winner", "sending_winner",
    "testing", "active", "failed_auth",
}


@router.post("/{campaign_id}/stop")
async def stop_campaign(
    campaign_id: str,
    user: dict = Depends(get_current_user),
):
    """Stop a campaign that is running, scheduled, or part-way through.

    There was no way to do this until 2026-09-01. A customer discovered that
    five recipients into a 66-person send and told us her only remaining
    option was to close her account — which was accurate.

    Two writes, and both are needed. `status='cancelled'` takes it out of
    `get_due_scheduled_campaigns`, which selects `status='scheduled'`.
    `archived=true` takes it out of `get_resumable_partial_campaigns`, so the
    auto-resume beat cannot pick it back up — and it is also what makes the
    follow-up worker cancel any pending follow-up for this campaign
    (`followup_worker.py:85`), because a bump for a campaign someone has
    stopped is the same mistake in slow motion.

    What this cannot do is un-send. The response says how many were already
    reached so the panel can say it plainly rather than implying a clean undo.
    """
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    status = campaign.get("status")
    if status not in STOPPABLE_STATUSES:
        # 409 rather than a quiet 200: the caller believes something is
        # running, and it is not. Saying "stopped" would be a lie about a
        # thing they care about.
        raise HTTPException(
            status_code=409,
            detail={"error": "not_stoppable", "status": status},
        )

    already_sent = campaign.get("sent_count") or 0
    remaining = contact_model.count_resumable_contacts(campaign_id)

    campaign_model.update_campaign(
        campaign_id, {"status": "cancelled", "archived": True}
    )
    logging.getLogger(__name__).warning(
        "campaign %s stopped by its owner: %s already sent, %s not contacted",
        campaign_id, already_sent, remaining,
    )
    return {
        "campaign_id": campaign_id,
        "stopped": True,
        "already_sent": already_sent,
        "not_contacted": remaining,
    }


@router.post("/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: str,
    user: dict = Depends(get_current_user),
):
    """Resume sending the still-pending contacts of a partial / stuck
    campaign.

    A campaign reaches `partial` status when some recipients failed
    during a send loop (network blip, Microsoft 5xx, worker crash).
    Pre-this endpoint, the only recovery was manual SQL — change the
    campaign status back to `scheduled` and wait for the beat task.
    Now the user can hit Resume from the Reports detail view.

    Behaviour:
      - 404 unless the campaign belongs to the caller.
      - 409 if status isn't `partial` (a `sent` campaign has nothing
        left, a `draft` was never sent).
      - Otherwise: flip status to `scheduled` with scheduled_for=now
        so the next process_scheduled_campaigns beat picks it up
        and sends the contacts that are still resumable
        (`pending` or transiently-`deferred`).
    """
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.get("status") != "partial":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "not_resumable",
                "message": (
                    "Only campaigns in 'partial' status can be resumed."
                ),
            },
        )

    # Confirm there are resumable contacts to send before flipping the
    # status. Resumable = still pending OR transiently failed (deferred);
    # permanently failed contacts are skipped (retry is futile). If
    # everything recoverable has gone out, mark it sent and return.
    pending = contact_model.get_resumable_contacts(campaign_id)
    if not pending:
        campaign_model.update_campaign(campaign_id, {"status": "sent"})
        return {"campaign_id": campaign_id, "status": "sent", "queued": 0}

    now_iso = datetime.now(timezone.utc).isoformat()
    # archived=False is not decoration. get_due_scheduled_campaigns began
    # filtering archived on 2026-09-01 so a stopped campaign could not come
    # back; an archived campaign resumed from the Archived tab would otherwise
    # land on 'scheduled' AND archived, which that query skips, auto-resume
    # skips ('partial' only), the sweep skips ('sending' only) and this
    # endpoint then 409s on — while the response above cheerfully reports N
    # recipients queued. Resume is an explicit un-stop, so it clears the stop
    # switch it is fighting.
    campaign_model.update_campaign(
        campaign_id,
        {"status": "scheduled", "scheduled_for": now_iso, "archived": False},
    )

    return {
        "campaign_id": campaign_id,
        "status": "scheduled",
        "queued": len(pending),
    }


# ── Follow-up Endpoints ──


@router.post("/{campaign_id}/followups")
async def create_followup(
    campaign_id: str,
    body: CreateFollowupRequest,
    user: dict = Depends(get_current_user),
    x_extension_version: Annotated[str | None, Header()] = None,
):
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if user_model.effective_plan(user) not in ("pro",):
        # The only moment a follow-up could ever be attached was the instant
        # Send was pressed. Refusing here threw away a subject line and a body
        # the user had just written, and left that campaign with no second
        # chance on any plan — including after they upgraded. Save it instead,
        # inert, and let them press activate when they can run it.
        #
        # Only for clients that know what the answer means. An older panel
        # reads any 200 as "your follow-up is scheduled", which is the silent
        # failure this replaces, so it keeps the 402 and its alert.
        if client_at_least(x_extension_version, FOLLOWUP_LOCKED_MIN_CLIENT):
            locked = followup_model.create_followup(
                campaign_id=campaign_id,
                user_id=user["id"],
                delay_days=body.delay_days,
                subject=body.subject,
                body=body.body,
                condition=body.condition,
                status="locked",
            )
            return {
                "followup_id": locked["id"],
                "locked": True,
                "required_plan": "pro",
            }
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
        # Explicit, not the model default. The locked path a few lines up
        # passes its status too, and one of the two relying on a default is
        # how the wrong one quietly inherits a change to it.
        status="scheduled",
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


@router.post("/{campaign_id}/followups/{followup_id}/activate")
async def activate_followup(
    campaign_id: str,
    followup_id: str,
    confirm_immediate: bool = False,
    user: dict = Depends(get_current_user),
):
    """Turn a saved-but-locked follow-up into a running one.

    Never automatic. A follow-up written weeks ago and forgotten, firing
    because the account changed plan, would be our mistake sent under the
    user's name — so activation is always a deliberate press, and this is the
    endpoint behind it.

    The one hazard is timing. A follow-up is due per recipient at their own
    sent_at + delay_days, so on a campaign that finished a while ago every one
    of those moments has already passed and activating does not schedule
    anything: it sends, at once, to everyone still eligible. That is a
    legitimate thing to want and an unacceptable thing to discover, so it
    needs `confirm_immediate` and the caller is told the number first.
    """
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if user_model.effective_plan(user) not in ("pro",):
        raise HTTPException(
            status_code=402,
            detail={
                "error": "feature_locked",
                "message": "Follow-up ozelligi sadece Pro planda kullanilabilir",
                "required_plan": "pro",
            },
        )

    if campaign.get("archived"):
        # The worker cancels an archived campaign's follow-up before anything
        # else (followup_worker.py:83). Activating here would return 200, say
        # "Follow-up started", and be silently undone on the next beat —
        # nothing sent, and the user told something untrue.
        raise HTTPException(
            status_code=409,
            detail={"error": "campaign_archived"},
        )

    followups = followup_model.get_campaign_followups(campaign_id)
    followup = next((f for f in followups if f["id"] == followup_id), None)
    if not followup:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    if followup["status"] != "locked":
        # Already running, already sent, or cancelled. Activating any of those
        # again would duplicate a send, so this is a 409 rather than a no-op.
        raise HTTPException(
            status_code=409,
            detail={"error": "not_locked", "status": followup["status"]},
        )

    # `or 0`, matching followup_worker.py:91 exactly. Both sides must read a
    # falsy delay_days the same way: 0 is falsy, so `or 3` would have this
    # guard count against a three-day cutoff while the worker sends against
    # a zero-day one. That is the one direction the warning can UNDERSTATE
    # — it would report nobody due, skip the confirmation, and let a whole
    # finished list go out with nothing asked.
    delay_days = followup.get("delay_days") or 0
    due_now = followup_model.count_due_immediately(campaign_id, delay_days)
    if due_now > 0 and not confirm_immediate:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "would_send_immediately",
                "count": due_now,
                "delay_days": delay_days,
            },
        )

    followup_model.update_followup_status(followup_id, "scheduled")
    return {"followup_id": followup_id, "status": "scheduled",
            "sending_immediately_to": due_now}


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
    if user_model.effective_plan(user) != "pro":
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
    merge_ctx = build_merge_context(contact, sender_info)

    subject_text = subject_override or campaign["subject"]
    merged_subject = _merge_template(subject_text, merge_ctx)
    merged_body = _merge_template(campaign["body"], merge_ctx)
    # Plain-text input needs newline→<br> conversion since Graph sends HTML.
    #
    # The TEMPLATE decides whether the author wrote markup; the merged text is
    # what gets converted. Passing only the merged text — which this line did
    # until 2026-09-01 — lets a single CSV value containing something like
    # <info@example.com> flip the whole message into "author wrote HTML" and
    # collapse that one recipient's line breaks, while the preview (first row)
    # showed the other answer.
    merged_body = render_body(campaign["body"], merged_body)

    # Add tracking pixel (if enabled)
    tracking_pixel = ""
    if track_opens:
        tracking_pixel = (
            f'<img src="{BACKEND_URL}/t/{contact["id"]}" '
            f'width="1" height="1" style="display:none" alt="" />'
        )

    # Wrap links for click tracking (if enabled)
    tracked_body = _wrap_links(merged_body, contact["id"]) if track_clicks else merged_body

    # OneDrive attachment links (chips). Rendered above the unsubscribe
    # footer so they read as part of the message rather than mixed into
    # the legal/footer territory.
    from utils.email_attachments import render_attachments_footer
    attachments_html = render_attachments_footer(campaign.get("attachments"))

    # Add unsubscribe footer
    unsubscribe_url = f"{BACKEND_URL}/unsubscribe/{contact['id']}"
    footer = (
        f'<br/><p style="font-size:11px;color:#999;">'
        f'<a href="{unsubscribe_url}">{unsubscribe_text}</a></p>'
    )

    final_html = tracked_body + attachments_html + footer + tracking_pixel

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

    from utils.graph_retry import async_post_with_retry
    resp = await async_post_with_retry(
        client,
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

    return {"success": False, "error": error_detail, "status_code": resp.status_code}


def _fetch_previous_emails(
    user_id: str, exclude_campaign_id: str, sent_cutoff_iso: str
) -> set[str]:
    """Return lowercase emails the user has already contacted.

    - `sent` contacts (actually delivered) with sent_at >= cutoff, from any of
      the user's other campaigns.
    - `pending` contacts ONLY from campaigns still on track to deliver them
      (scheduled / sending / ab_testing) — the live outbox. Pending contacts in
      a failed / partial / cancelled campaign never reached the recipient, so
      they are NOT deduped — otherwise one failed/timed-out send would lock the
      user out of re-mailing their own list (a real complaint we hit).
    - The current campaign (exclude_campaign_id) is excluded.
    """
    db = get_db()
    camps = (
        db.table("campaigns")
        .select("id, status")
        .eq("user_id", user_id)
        .execute()
    )
    camps_to_scan = [
        c for c in (camps.data or []) if c.get("id") != exclude_campaign_id
    ]
    if not camps_to_scan:
        return set()

    # A 'pending' contact only counts as "already contacted" while its campaign
    # is still going to deliver it; a done/dead campaign's pending never arrives.
    ACTIVE_OUTBOX = {"scheduled", "sending", "ab_testing"}
    emails: set[str] = set()
    for c in camps_to_scan:
        cid = c["id"]
        sent = (
            db.table("contacts")
            .select("email")
            .eq("campaign_id", cid)
            .eq("status", "sent")
            .gte("sent_at", sent_cutoff_iso)
            .execute()
        )
        for r in (sent.data or []):
            if r.get("email"):
                emails.add(r["email"].lower())
        if c.get("status") in ACTIVE_OUTBOX:
            pending = (
                db.table("contacts")
                .select("email")
                .eq("campaign_id", cid)
                .eq("status", "pending")
                .execute()
            )
            for r in (pending.data or []):
                if r.get("email"):
                    emails.add(r["email"].lower())
    return emails


_HTML_TAG_RE = re.compile(r"<[a-z!/][^>]*>", re.IGNORECASE)


def _text_to_html(body: str) -> str:
    """DEPRECATED — use utils.email_body.render_body.

    Kept only because removing it in the same commit as the incident fix would
    mix a behaviour change with a cleanup. It decides from the text it is
    given, which is the bug: by the time the send path had it, the merge had
    already run and user data could flip the mode.

    Convert plain-text body to simple HTML when no markup is present.

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
