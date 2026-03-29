"""
OutMass — Celery Email Worker
Async email queue for production use.
MVP uses synchronous send in campaigns.py — this is for future scaling.
"""

import re
import time
import urllib.parse
from datetime import datetime, timezone

import httpx

from config import (
    BACKEND_URL,
    GRAPH_API_BASE,
    RATE_LIMIT_WAIT_SECONDS,
    SEND_DELAY_SECONDS,
)
from workers.celery_app import celery


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_task(self, contact_id: str, campaign_id: str, access_token: str):
    """
    Send a single email via Graph API.
    Called from campaign send endpoint when Celery is available.
    """
    from database import get_db

    db = get_db()

    # Fetch contact
    contact_result = (
        db.table("contacts")
        .select("*")
        .eq("id", contact_id)
        .execute()
    )
    if not contact_result.data or len(contact_result.data) == 0:
        return {"error": "Contact not found"}
    contact = contact_result.data[0]

    # Fetch campaign
    campaign_result = (
        db.table("campaigns")
        .select("*")
        .eq("id", campaign_id)
        .execute()
    )
    if not campaign_result.data or len(campaign_result.data) == 0:
        return {"error": "Campaign not found"}
    campaign = campaign_result.data[0]

    # Skip unsubscribed
    if contact.get("unsubscribed"):
        return {"skipped": True, "reason": "unsubscribed"}

    # Build merge context
    merge_ctx = {
        "firstName": contact.get("first_name", ""),
        "lastName": contact.get("last_name", ""),
        "email": contact.get("email", ""),
        "company": contact.get("company", ""),
        "position": contact.get("position", ""),
    }
    custom = contact.get("custom_fields") or {}
    merge_ctx.update(custom)

    # Merge templates
    merged_subject = _merge(campaign["subject"], merge_ctx)
    merged_body = _merge(campaign["body"], merge_ctx)

    # Add tracking
    tracking_pixel = (
        f'<img src="{BACKEND_URL}/t/{contact_id}" '
        f'width="1" height="1" style="display:none" alt="" />'
    )

    # Wrap links
    tracked_body = _wrap_links(merged_body, contact_id)

    # Unsubscribe footer
    unsub_url = f"{BACKEND_URL}/unsubscribe/{contact_id}"
    footer = (
        f'<br/><p style="font-size:11px;color:#999;">'
        f'<a href="{unsub_url}">Abonelikten cik</a></p>'
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

    # Send via Graph API
    with httpx.Client() as client:
        resp = client.post(
            f"{GRAPH_API_BASE}/me/sendMail",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

        # Rate limited
        if resp.status_code == 429:
            retry_after = int(
                resp.headers.get("Retry-After", RATE_LIMIT_WAIT_SECONDS)
            )
            raise self.retry(countdown=retry_after)

        if resp.status_code not in (200, 202):
            error = ""
            try:
                error = resp.json().get("error", {}).get("message", "")
            except Exception:
                error = f"HTTP {resp.status_code}"
            raise self.retry(exc=Exception(error))

    # Mark as sent
    db.table("contacts").update(
        {"status": "sent", "sent_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", contact_id).execute()

    # Increment campaign sent count
    campaign_data = (
        db.table("campaigns")
        .select("sent_count")
        .eq("id", campaign_id)
        .execute()
    )
    if campaign_data.data and len(campaign_data.data) > 0:
        db.table("campaigns").update(
            {"sent_count": campaign_data.data[0]["sent_count"] + 1}
        ).eq("id", campaign_id).execute()

    # Rate limiting delay
    time.sleep(SEND_DELAY_SECONDS)

    return {"success": True, "email": contact["email"]}


def _merge(template_str: str, context: dict) -> str:
    def replacer(match):
        key = match.group(1)
        return str(context.get(key, match.group(0)))

    return re.sub(r"\{\{(\w+)\}\}", replacer, template_str)


def _wrap_links(html: str, contact_id: str) -> str:
    def replacer(match):
        original_url = match.group(1)
        if BACKEND_URL in original_url:
            return match.group(0)
        encoded = urllib.parse.quote(original_url, safe="")
        tracked = f"{BACKEND_URL}/c/{contact_id}?url={encoded}"
        return f'href="{tracked}"'

    return re.sub(r'href="(https?://[^"]+)"', replacer, html)
