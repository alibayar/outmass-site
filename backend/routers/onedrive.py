"""
OutMass — OneDrive integration

Single endpoint: POST /api/onedrive/share-link

Why this exists: when a user wants to share a file via OutMass, we
build sharing links inside their OWN OneDrive — the file never lives
on our servers. Less storage cost, less malware/DMCA liability, and
better email deliverability than a base64 attachment.

Flow per request:
  1. Authenticate user via JWT (existing dependency).
  2. Pull a fresh MS access token (uses refresh_token if needed).
  3. Call Microsoft Graph: POST /me/drive/items/{id}/createLink with
     type=view scope=anonymous → "anyone with the link can view".
  4. Return the public web URL plus the file's display name.

If the user hasn't granted Files.Read.All / Files.ReadWrite (default
sign-in scopes don't include them — incremental consent), Graph
returns 403 InvalidAuthenticationToken with insufficient_scope. We
surface that as a structured `needs_files_scope` error so the
extension can prompt for re-consent without throwing the user a raw
500.
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from models import audit
from models.ms_token import get_fresh_access_token
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onedrive", tags=["onedrive"])


class ShareLinkRequest(BaseModel):
    item_id: str = Field(..., min_length=1, max_length=200)


# Microsoft drive-item IDs are opaque — typically 30-50 chars of
# uppercase hex / base64. We don't need to enforce a strict format
# here; Graph itself rejects bad IDs. Length cap above is just a
# sanity guard.


@router.post("/share-link")
async def create_share_link(
    body: ShareLinkRequest,
    user: dict = Depends(get_current_user),
):
    access_token = get_fresh_access_token(user["id"])
    if not access_token:
        # User's MS connection is gone entirely — same path the rest of
        # the app uses (the requires_reauth banner will appear on next
        # /settings poll).
        raise HTTPException(
            status_code=401,
            detail={
                "error": "needs_reauth",
                "message": "Microsoft connection expired. Please sign in again.",
            },
        )

    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{body.item_id}/createLink"
    payload = {"type": "view", "scope": "anonymous"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as e:
        logger.error("OneDrive share-link network error: %s", e)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "network",
                "message": "Could not reach Microsoft.",
            },
        )

    # ── Insufficient-scope (incremental consent gate) ──
    # Microsoft returns 403 when the access token is valid but missing
    # the required scope. We return a structured error so the extension
    # can launch a fresh OAuth flow with include_onedrive=true and retry.
    if resp.status_code == 403:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "needs_files_scope",
                "message": (
                    "OneDrive access not yet granted. Please authorize "
                    "OneDrive integration."
                ),
            },
        )

    # ── Item not found / no permission to share ──
    if resp.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "file_not_found",
                "message": "OneDrive file not found or not accessible.",
            },
        )

    if resp.status_code >= 400:
        body_snippet = resp.text[:500]
        logger.warning(
            "OneDrive share-link failed: %s %s",
            resp.status_code,
            body_snippet,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": "graph_error",
                "message": f"Microsoft Graph error (HTTP {resp.status_code}).",
            },
        )

    data = resp.json()
    link = data.get("link", {})
    share_url = link.get("webUrl")
    if not share_url:
        logger.error("OneDrive share-link response missing webUrl: %s", data)
        raise HTTPException(
            status_code=502,
            detail={
                "error": "graph_malformed",
                "message": "Microsoft Graph returned an unexpected response.",
            },
        )

    # We don't get the filename back from createLink directly. Fetch the
    # item separately so the chip in the sidebar can show the real
    # filename instead of the opaque item_id.
    file_name = await _fetch_item_name(access_token, body.item_id)

    audit.emit(
        "onedrive_link_created",
        user_id=user["id"],
        email=user.get("email"),
        metadata={
            "item_id": body.item_id,
            "file_name": file_name,
        },
    )

    return {
        "share_url": share_url,
        "name": file_name or body.item_id,
    }


async def _fetch_item_name(access_token: str, item_id: str) -> str | None:
    """Best-effort GET /me/drive/items/{id}?select=name. Returns None on
    any failure — caller falls back to the item_id."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"$select": "name"},
            )
        if resp.status_code == 200:
            return resp.json().get("name")
    except Exception:  # noqa: BLE001
        pass
    return None
