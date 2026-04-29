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


@router.get("/browse")
async def browse_drive(
    folder_id: str = "root",
    user: dict = Depends(get_current_user),
):
    """List the user's OneDrive contents at a given folder.

    Replaces the Microsoft File Picker iframe (which Microsoft serves
    with X-Frame-Options: DENY for personal accounts) with a custom
    browser the extension can render natively. Returns items sorted
    folders-first then files-alphabetical, plus the current folder's
    name + parent_id so the frontend can render breadcrumbs without
    a second round trip.

    `folder_id` defaults to "root" — Microsoft Graph treats the literal
    string "root" as a special alias for the user's drive root. Subfolders
    use the opaque drive item ID returned in each child's `id` field.
    """
    access_token = get_fresh_access_token(user["id"])
    if not access_token:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "needs_reauth",
                "message": "Microsoft connection expired. Please sign in again.",
            },
        )

    if folder_id == "root":
        list_url = "https://graph.microsoft.com/v1.0/me/drive/root/children"
        item_url = "https://graph.microsoft.com/v1.0/me/drive/root"
    else:
        list_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}/children"
        item_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{folder_id}"

    # We restrict the field set with $select to keep payloads small —
    # the picker UI doesn't need thumbnails, sharing settings, etc.
    list_params = {
        "$select": "id,name,size,lastModifiedDateTime,folder,file,parentReference",
        "$top": "200",
        "$orderby": "name asc",
    }
    item_params = {"$select": "id,name,parentReference"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            list_resp = await client.get(
                list_url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=list_params,
            )
            item_resp = await client.get(
                item_url,
                headers={"Authorization": f"Bearer {access_token}"},
                params=item_params,
            )
    except httpx.HTTPError as e:
        logger.error("OneDrive browse network error: %s", e)
        raise HTTPException(
            status_code=502,
            detail={"error": "network", "message": "Could not reach Microsoft."},
        )

    if list_resp.status_code in (401, 403):
        # Microsoft Graph returns 401 (InvalidAuthenticationToken) or
        # 403 (insufficient_scope) when the access token is valid but
        # missing the OneDrive scopes. Both map to the same recovery
        # path on the frontend — launch incremental consent — so we
        # collapse them into a single error code here.
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
    if list_resp.status_code in (400, 404):
        # Two sub-cases:
        #   a) The Microsoft account has no OneDrive at all (some old
        #      Outlook.com accounts, work accounts without an SPO
        #      license). Microsoft signals this with various status
        #      codes + error bodies — most reliable heuristic is "we
        #      asked for the root drive and got 404", or a 400/404
        #      whose error text mentions tenant/license/provisioned.
        #   b) For a non-root browse, 404 just means that subfolder
        #      no longer exists.
        body_text = (list_resp.text or "").lower()
        no_drive_markers = (
            "tenant does not have",
            "spo license",
            "user has no drives",
            "not provisioned",
            "mysite",
            "drive not found",
            "doesn't exist",
            "doesn't have a onedrive",
        )
        looks_like_no_drive = any(m in body_text for m in no_drive_markers)
        if folder_id == "root" or looks_like_no_drive:
            logger.info(
                "OneDrive browse: account has no OneDrive (status=%s body=%s)",
                list_resp.status_code,
                list_resp.text[:200],
            )
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "no_onedrive",
                    "message": (
                        "This Microsoft account doesn't have OneDrive. "
                        "Sign in with an account that has OneDrive enabled, "
                        "or skip OneDrive attachments for this campaign."
                    ),
                },
            )
        # Genuine "subfolder gone" case — keep the prior error code
        # so the frontend can still render a meaningful message.
        raise HTTPException(
            status_code=404,
            detail={
                "error": "folder_not_found",
                "message": "OneDrive folder not found.",
            },
        )
    if list_resp.status_code >= 400:
        logger.warning(
            "OneDrive browse failed: %s %s",
            list_resp.status_code,
            list_resp.text[:300],
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": "graph_error",
                "message": f"Microsoft Graph error (HTTP {list_resp.status_code}).",
            },
        )

    list_data = list_resp.json()
    raw_items = list_data.get("value", []) or []

    folders = []
    files = []
    for it in raw_items:
        if it.get("folder"):
            folders.append({
                "id": it.get("id"),
                "name": it.get("name") or "untitled",
                "type": "folder",
                "child_count": (it.get("folder") or {}).get("childCount", 0),
                "last_modified": it.get("lastModifiedDateTime"),
            })
        elif it.get("file"):
            mime = (it.get("file") or {}).get("mimeType")
            files.append({
                "id": it.get("id"),
                "name": it.get("name") or "untitled",
                "type": "file",
                "size": it.get("size", 0),
                "mime": mime,
                "last_modified": it.get("lastModifiedDateTime"),
            })
        # Items that are neither file nor folder (e.g. notebooks,
        # bundles) are dropped — we can't generate a share link for
        # them anyway, no point cluttering the picker.

    # Folders first (sorted by name, case-insensitive), then files.
    folders.sort(key=lambda x: x["name"].lower())
    files.sort(key=lambda x: x["name"].lower())

    # Breadcrumb data: name of current folder + ID of its parent so the
    # frontend can build a back button. Microsoft returns the root item
    # without a parentReference, which we treat as the top of the tree.
    item_data = item_resp.json() if item_resp.status_code == 200 else {}
    parent_ref = item_data.get("parentReference") or {}
    parent_id = parent_ref.get("id")
    # The root drive item's parent is the drive itself, not a folder
    # we can browse — surface as None so the frontend hides the back
    # button.
    if parent_ref.get("path") in (None, "") or folder_id == "root":
        parent_id = None

    return {
        "folder_id": folder_id,
        "folder_name": item_data.get("name") if folder_id != "root" else None,
        "parent_id": parent_id,
        "items": folders + files,
    }


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
    # Microsoft Graph sometimes returns 403 (insufficient_scope) and
    # sometimes 401 (InvalidAuthenticationToken) when the access token
    # is valid for some scopes but not the OneDrive ones. We collapse
    # both into needs_files_scope so the frontend can launch the
    # incremental consent flow regardless of which one Microsoft picked.
    if resp.status_code in (401, 403):
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
