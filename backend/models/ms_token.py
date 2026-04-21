"""
OutMass — MS Graph Token Helper
Refreshes access tokens using stored refresh_token + client_secret (Web flow).
"""

import logging
from datetime import datetime, timezone

import httpx

from config import (
    AZURE_CLIENT_ID,
    AZURE_CLIENT_SECRET,
    BACKEND_URL,
    MAILERSEND_API_KEY,
    MAILERSEND_FROM_EMAIL,
    MAILERSEND_FROM_NAME,
    MS_GRAPH_SCOPES,
    MS_TOKEN_ENDPOINT,
)
from database import get_db

logger = logging.getLogger(__name__)


def _send_reauth_email(user_email: str, user_name: str | None, reason: str) -> None:
    """Best-effort MailerSend email telling the user to reconnect Outlook.

    Fires only once per flagging transition (caller gates on False→True).
    Silent on any failure — token flagging must not depend on email delivery.
    """
    if not MAILERSEND_API_KEY or not user_email:
        return
    greeting = f"Hi {user_name}," if user_name else "Hi,"
    reconnect_url = f"{BACKEND_URL.rstrip('/')}/"
    html = (
        "<div style='font-family:sans-serif;max-width:520px;margin:auto;color:#323130;'>"
        "<h2 style='color:#0078d4;'>Action needed: reconnect Outlook</h2>"
        f"<p>{greeting}</p>"
        "<p>Your OutMass connection to Microsoft Outlook has expired. "
        "Until you reconnect, any scheduled campaigns and follow-ups will "
        "pause instead of sending.</p>"
        "<p style='margin:28px 0;'>"
        "<b>How to fix it:</b> open the OutMass sidebar in Outlook Web, "
        "click the <em>Reconnect to Outlook</em> banner, and sign in again. "
        "Takes about 10 seconds.</p>"
        "<p style='color:#888;font-size:12px;'>"
        f"Reason: {reason}. If you keep seeing this, reply to this email "
        "and we'll look into it.</p>"
        "<p style='color:#888;font-size:12px;'>— The OutMass team</p>"
        "</div>"
    )
    payload = {
        "from": {"email": MAILERSEND_FROM_EMAIL, "name": MAILERSEND_FROM_NAME},
        "to": [{"email": user_email}],
        "subject": "Reconnect OutMass to Outlook",
        "html": html,
    }
    try:
        httpx.post(
            "https://api.mailersend.com/v1/email",
            headers={
                "Authorization": f"Bearer {MAILERSEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Reauth MailerSend dispatch failed: %s", e)


def _mark_requires_reauth(user_id: str, reason: str) -> None:
    """Flag the user as needing to re-authorize with Microsoft.

    Called when the refresh_token exchange fails irrecoverably (typically
    401 invalid_grant). The sidebar reads this flag from /settings and
    shows a 'Reconnect to Outlook' banner so the user knows to sign in
    again — instead of silently watching scheduled campaigns no-op.

    Idempotent: if the user is already flagged, we do not re-send the
    email notification. That way a busted refresh_token hit by every
    scheduled task doesn't generate a mail storm.
    """
    try:
        db = get_db()
        existing = (
            db.table("users")
            .select("requires_reauth, email, name")
            .eq("id", user_id)
            .execute()
        )
        previously_flagged = False
        email = None
        name = None
        if existing.data:
            row = existing.data[0]
            previously_flagged = bool(row.get("requires_reauth"))
            email = row.get("email")
            name = row.get("name")

        db.table("users").update({
            "requires_reauth": True,
            "reauth_reason": reason,
            "reauth_flagged_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", user_id).execute()
        logger.warning("Flagged user %s as requires_reauth (%s)", user_id, reason)

        if not previously_flagged and email:
            _send_reauth_email(email, name, reason)
    except Exception:  # noqa: BLE001 — never let token-refresh logging kill the caller
        logger.exception("Failed to mark user %s as requires_reauth", user_id)


def get_fresh_access_token(user_id: str) -> str | None:
    """
    Return a valid Microsoft access token for the given user.

    Strategy:
    1. Return stored access_token if it's still valid (verified via /me call)
    2. Otherwise refresh using stored refresh_token + client_secret
    3. Return None if neither works (user needs to re-login)
    """
    db = get_db()
    result = (
        db.table("user_tokens")
        .select("access_token, refresh_token")
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        return None

    row = result.data[0]

    # Strategy 1: Stored access token may still be valid
    access_token = row.get("access_token")
    if access_token:
        try:
            check = httpx.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=5.0,
            )
            if check.status_code == 200:
                return access_token
        except httpx.HTTPError:
            pass

    # Strategy 2: Use refresh token to get new access token
    refresh_token = row.get("refresh_token")
    if not refresh_token:
        return None

    data = {
        "client_id": AZURE_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": MS_GRAPH_SCOPES,
    }
    if AZURE_CLIENT_SECRET:
        data["client_secret"] = AZURE_CLIENT_SECRET

    try:
        resp = httpx.post(
            MS_TOKEN_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            tokens = resp.json()
            new_access = tokens.get("access_token")
            new_refresh = tokens.get("refresh_token", refresh_token)
            db.table("user_tokens").update(
                {"access_token": new_access, "refresh_token": new_refresh}
            ).eq("user_id", user_id).execute()
            return new_access
        # 4xx from Microsoft (especially 400/401 invalid_grant) means the
        # refresh_token is dead. Flag the user so the sidebar can prompt
        # re-auth instead of silently no-op'ing forever.
        if 400 <= resp.status_code < 500:
            body_snippet = resp.text[:200]
            reason = "refresh_failed"
            if "invalid_grant" in body_snippet:
                reason = "invalid_grant"
            elif "invalid_client" in body_snippet:
                reason = "invalid_client"
            _mark_requires_reauth(user_id, reason)
        logger.warning(
            "Refresh token exchange failed for user %s: %s %s",
            user_id,
            resp.status_code,
            resp.text[:200],
        )
    except httpx.HTTPError as e:
        logger.error("Refresh token network error: %s", e)

    return None
