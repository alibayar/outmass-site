"""
OutMass — MS Graph Token Helper
Refreshes access tokens using stored refresh_token + client_secret (Web flow).
"""

import logging

import httpx

from config import (
    AZURE_CLIENT_ID,
    AZURE_CLIENT_SECRET,
    MS_GRAPH_SCOPES,
    MS_TOKEN_ENDPOINT,
)
from database import get_db

logger = logging.getLogger(__name__)


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
        logger.warning(
            "Refresh token exchange failed for user %s: %s %s",
            user_id,
            resp.status_code,
            resp.text[:200],
        )
    except httpx.HTTPError as e:
        logger.error("Refresh token network error: %s", e)

    return None
