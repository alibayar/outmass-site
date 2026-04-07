"""
OutMass — Follow-up Worker
Celery beat task: processes due follow-ups every hour.
Uses stored refresh tokens to get fresh MS access tokens.
"""

import re
import time
import urllib.parse

import httpx

from config import (
    AZURE_CLIENT_ID,
    BACKEND_URL,
    GRAPH_API_BASE,
    MS_GRAPH_SCOPES,
    MS_TOKEN_ENDPOINT,
    RATE_LIMIT_WAIT_SECONDS,
    SEND_DELAY_SECONDS,
)
from workers.celery_app import celery


@celery.task
def process_followups():
    """
    Find scheduled follow-ups that are due, filter contacts by condition,
    and send follow-up emails.
    """
    from database import get_db
    from models import campaign as campaign_model
    from models import contact as contact_model
    from models import followup as followup_model
    from models import user as user_model

    pending = followup_model.get_pending_followups()
    if not pending:
        return {"processed": 0}

    db = get_db()
    total_sent = 0

    for followup in pending:
        campaign = campaign_model.get_campaign(followup["campaign_id"])
        if not campaign:
            followup_model.update_followup_status(followup["id"], "cancelled")
            continue

        user = user_model.get_by_id(followup["user_id"])
        if not user:
            followup_model.update_followup_status(followup["id"], "cancelled")
            continue

        # Get contacts filtered by condition
        contacts = _get_filtered_contacts(
            db, followup["campaign_id"], followup["condition"]
        )

        if not contacts:
            followup_model.update_followup_status(followup["id"], "sent")
            continue

        # Get fresh access token using stored refresh token
        access_token = _get_fresh_access_token(db, user["id"])
        if not access_token:
            # Can't send without token — skip but keep scheduled for retry
            continue

        # Filter out suppressed emails
        suppressed_result = (
            db.table("suppression_list")
            .select("email")
            .eq("user_id", user["id"])
            .execute()
        )
        suppressed_emails = {r["email"].lower() for r in suppressed_result.data}

        sent_count = 0
        with httpx.Client() as client:
            for contact in contacts:
                if contact.get("unsubscribed"):
                    continue
                if contact.get("email", "").lower() in suppressed_emails:
                    continue

                try:
                    _send_followup_email(
                        client=client,
                        access_token=access_token,
                        campaign=campaign,
                        followup=followup,
                        contact=contact,
                    )
                    sent_count += 1
                except Exception:
                    pass

                time.sleep(SEND_DELAY_SECONDS)

        campaign_model.increment_stat(
            followup["campaign_id"], "sent_count", sent_count
        )
        user_model.increment_sent_count(user["id"], sent_count)
        followup_model.update_followup_status(followup["id"], "sent")
        total_sent += sent_count

    return {"processed": len(pending), "sent": total_sent}


def _get_filtered_contacts(db, campaign_id: str, condition: str) -> list[dict]:
    """Get contacts matching the follow-up condition."""
    query = (
        db.table("contacts")
        .select("*")
        .eq("campaign_id", campaign_id)
        .eq("status", "sent")
        .eq("unsubscribed", False)
    )

    if condition == "not_opened":
        query = query.is_("opened_at", "null")
    elif condition == "not_clicked":
        query = query.is_("clicked_at", "null")

    result = query.execute()
    return result.data


def _get_fresh_access_token(db, user_id: str) -> str | None:
    """
    Get a valid MS access token.
    Strategy:
    1. Try stored access_token first (saved during campaign send, valid ~1 hour)
    2. Try refresh_token to get a new access_token
    """
    result = (
        db.table("user_tokens")
        .select("access_token, refresh_token")
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data or len(result.data) == 0:
        return None

    row = result.data[0]

    # Strategy 1: Try stored access token (may still be valid)
    access_token = row.get("access_token")
    if access_token:
        # Verify it's still valid with a quick Graph API call
        try:
            check = httpx.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if check.status_code == 200:
                return access_token
        except Exception:
            pass

    # Strategy 2: Try refresh token
    refresh_token = row.get("refresh_token")
    if refresh_token:
        try:
            resp = httpx.post(
                MS_TOKEN_ENDPOINT,
                data={
                    "client_id": AZURE_CLIENT_ID,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": MS_GRAPH_SCOPES,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if resp.status_code == 200:
                tokens = resp.json()
                new_access = tokens.get("access_token")
                new_refresh = tokens.get("refresh_token", refresh_token)
                db.table("user_tokens").update(
                    {"access_token": new_access, "refresh_token": new_refresh}
                ).eq("user_id", user_id).execute()
                return new_access
        except Exception:
            pass

    return None


def _send_followup_email(
    client: httpx.Client,
    access_token: str,
    campaign: dict,
    followup: dict,
    contact: dict,
):
    """Send a single follow-up email via Graph API."""
    merge_ctx = {
        "firstName": contact.get("first_name", ""),
        "lastName": contact.get("last_name", ""),
        "email": contact.get("email", ""),
        "company": contact.get("company", ""),
        "position": contact.get("position", ""),
    }
    custom = contact.get("custom_fields") or {}
    merge_ctx.update(custom)

    merged_subject = _merge(followup["subject"], merge_ctx)
    merged_body = _merge(followup["body"], merge_ctx)

    # Tracking pixel
    tracking_pixel = (
        f'<img src="{BACKEND_URL}/t/{contact["id"]}" '
        f'width="1" height="1" style="display:none" alt="" />'
    )

    # Wrap links
    tracked_body = _wrap_links(merged_body, contact["id"])

    # Unsubscribe footer
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
        retry_after = int(
            resp.headers.get("Retry-After", RATE_LIMIT_WAIT_SECONDS)
        )
        time.sleep(retry_after)
        resp = client.post(
            f"{GRAPH_API_BASE}/me/sendMail",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if resp.status_code not in (200, 202):
        raise Exception(f"Graph API error: HTTP {resp.status_code}")


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
