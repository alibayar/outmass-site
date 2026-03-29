"""
OutMass — Scheduled Campaign Worker
Celery beat task: processes due scheduled campaigns every 5 minutes.
Uses stored access tokens to send emails via Graph API.
"""

import re
import time
import urllib.parse

import httpx

from config import (
    BACKEND_URL,
    FREE_PLAN_MONTHLY_LIMIT,
    GRAPH_API_BASE,
    PRO_PLAN_MONTHLY_LIMIT,
    RATE_LIMIT_WAIT_SECONDS,
    SEND_DELAY_SECONDS,
    STANDARD_PLAN_MONTHLY_LIMIT,
)
from workers.celery_app import celery
from workers.followup_worker import _get_fresh_access_token


@celery.task
def process_scheduled_campaigns():
    """
    Find scheduled campaigns that are due and send them.
    """
    from database import get_db
    from models import campaign as campaign_model
    from models import contact as contact_model
    from models import user as user_model

    due = campaign_model.get_due_scheduled_campaigns()
    if not due:
        return {"processed": 0}

    db = get_db()
    total_sent = 0

    for campaign in due:
        user = user_model.get_by_id(campaign["user_id"])
        if not user:
            campaign_model.update_campaign(campaign["id"], {"status": "failed"})
            continue

        # Get fresh access token
        access_token = _get_fresh_access_token(db, user["id"])
        if not access_token:
            # Can't send without token — keep scheduled for retry
            continue

        # Freemium check
        sent_this_month = user.get("emails_sent_this_month", 0)
        plan = user.get("plan", "free")
        if plan == "free":
            limit = FREE_PLAN_MONTHLY_LIMIT
        elif plan == "standard":
            limit = STANDARD_PLAN_MONTHLY_LIMIT
        else:
            limit = PRO_PLAN_MONTHLY_LIMIT

        remaining = limit - sent_this_month
        if remaining <= 0:
            campaign_model.update_campaign(campaign["id"], {"status": "failed"})
            continue

        pending = contact_model.get_pending_contacts(campaign["id"])
        if not pending:
            campaign_model.update_campaign(campaign["id"], {"status": "sent"})
            continue

        pending = pending[:remaining]

        # Filter suppressed
        suppressed_result = (
            db.table("suppression_list")
            .select("email")
            .eq("user_id", user["id"])
            .execute()
        )
        suppressed_emails = {r["email"].lower() for r in suppressed_result.data}

        # Mark as sending
        campaign_model.update_campaign(campaign["id"], {"status": "sending"})

        sent_count = 0
        errors = []

        with httpx.Client() as client:
            for contact in pending:
                if contact.get("unsubscribed"):
                    continue
                if contact.get("email", "").lower() in suppressed_emails:
                    continue

                try:
                    result = _send_email(
                        client=client,
                        access_token=access_token,
                        campaign=campaign,
                        contact=contact,
                    )
                    if result["success"]:
                        contact_model.mark_sent(contact["id"])
                        campaign_model.increment_stat(campaign["id"], "sent_count")
                        sent_count += 1
                    else:
                        errors.append(contact["email"])
                except Exception:
                    errors.append(contact["email"])

                time.sleep(SEND_DELAY_SECONDS)

        user_model.increment_sent_count(user["id"], sent_count)
        final_status = "sent" if not errors else "partial"
        campaign_model.update_campaign(campaign["id"], {"status": final_status})
        total_sent += sent_count

    return {"processed": len(due), "sent": total_sent}


def _send_email(
    client: httpx.Client,
    access_token: str,
    campaign: dict,
    contact: dict,
) -> dict:
    """Send a single email via Graph API."""
    merge_ctx = {
        "firstName": contact.get("first_name", ""),
        "lastName": contact.get("last_name", ""),
        "email": contact.get("email", ""),
        "company": contact.get("company", ""),
        "position": contact.get("position", ""),
    }
    custom = contact.get("custom_fields") or {}
    merge_ctx.update(custom)

    merged_subject = _merge(campaign["subject"], merge_ctx)
    merged_body = _merge(campaign["body"], merge_ctx)

    tracking_pixel = (
        f'<img src="{BACKEND_URL}/t/{contact["id"]}" '
        f'width="1" height="1" style="display:none" alt="" />'
    )
    tracked_body = _wrap_links(merged_body, contact["id"])

    unsub_url = f"{BACKEND_URL}/unsubscribe/{contact['id']}"
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

    resp = client.post(
        f"{GRAPH_API_BASE}/me/sendMail",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
    )

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", RATE_LIMIT_WAIT_SECONDS))
        time.sleep(retry_after)
        resp = client.post(
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
