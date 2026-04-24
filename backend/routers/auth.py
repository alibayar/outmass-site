"""
OutMass — Auth Router
GET  /auth/callback    → OAuth callback, code exchange, redirect to extension with JWT
POST /auth/microsoft   → legacy SPA flow (kept for backward compat)
GET  /auth/me          → current user info
"""

import base64
import json
import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from jose import jwt
from pydantic import BaseModel

from config import (
    ALLOWED_EXTENSION_IDS,
    AZURE_CLIENT_ID,
    AZURE_CLIENT_SECRET,
    AZURE_EXTENSION_ID,
    AZURE_REDIRECT_URI,
    GRAPH_API_BASE,
    JWT_ALGORITHM,
    JWT_EXPIRATION_HOURS,
    JWT_SECRET,
    MS_GRAPH_SCOPES,
    MS_TOKEN_ENDPOINT,
)
from models import audit
from models import user as user_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Schemas ──


class MicrosoftAuthRequest(BaseModel):
    access_token: str
    microsoft_id: str
    email: str
    name: str
    refresh_token: str | None = None


class AuthResponse(BaseModel):
    jwt: str
    user: dict


# ── JWT Helpers ──


def create_jwt(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc)
        + timedelta(hours=JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user(authorization: str = Header(...)) -> dict:
    """Dependency: extract and verify JWT from Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")
    token = authorization[7:]
    payload = decode_jwt(token)
    user = user_model.get_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ── Endpoints ──


def _encode_state(ext_id: str) -> str:
    """Pack extension_id + CSRF nonce into an opaque OAuth `state` param.

    URL-safe base64 of JSON — Microsoft echoes `state` verbatim on the
    callback, so we can recover which extension initiated the flow and
    redirect the JWT back to the right chromiumapp.org subdomain.
    """
    payload = json.dumps({
        "ext": ext_id,
        "n": secrets.token_urlsafe(12),  # CSRF nonce — presence alone is enough
    }, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_state_ext(state: str | None) -> str | None:
    """Extract extension_id from a state param. Returns None if invalid
    OR not in the allowlist (prevents OAuth open-redirect to attacker)."""
    if not state:
        return None
    try:
        padded = state + "=" * (-len(state) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        ext = data.get("ext")
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if ext and ext in ALLOWED_EXTENSION_IDS:
        return ext
    return None


@router.get("/login")
async def login_redirect(ext: str | None = Query(None)):
    """Redirect user to Microsoft login. Used by extension launchWebAuthFlow.

    `ext` is the calling extension's chrome.runtime.id. It's echoed to
    Microsoft via the OAuth `state` parameter, validated against
    ALLOWED_EXTENSION_IDS on the callback, and used to route the final
    chromiumapp.org redirect back to the originating extension. An
    unrecognized or missing `ext` falls back to AZURE_EXTENSION_ID so
    legacy (pre-multi-ext) clients still work.
    """
    chosen_ext = ext if ext in ALLOWED_EXTENSION_IDS else AZURE_EXTENSION_ID
    state = _encode_state(chosen_ext)

    params = {
        "client_id": AZURE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": AZURE_REDIRECT_URI,
        "response_mode": "query",
        "scope": MS_GRAPH_SCOPES,
        "prompt": "select_account",
        "state": state,
    }
    auth_url = f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def auth_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
):
    """
    OAuth redirect endpoint. Microsoft redirects here after user login.
    Exchanges code for tokens (using client_secret), stores refresh_token,
    then redirects to extension with OutMass JWT in URL fragment.
    """
    if error:
        return _error_page(error_description or error)

    if not code:
        return _error_page("No authorization code received")

    if not AZURE_CLIENT_SECRET:
        return _error_page("Server misconfigured: AZURE_CLIENT_SECRET not set")

    # Exchange code for tokens using Web platform (client_secret)
    async with httpx.AsyncClient() as client:
        try:
            token_resp = await client.post(
                MS_TOKEN_ENDPOINT,
                data={
                    "client_id": AZURE_CLIENT_ID,
                    "client_secret": AZURE_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": AZURE_REDIRECT_URI,
                    "scope": MS_GRAPH_SCOPES,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as e:
            logger.error("Token exchange network error: %s", e)
            return _error_page("Could not reach Microsoft")

    if token_resp.status_code != 200:
        err = token_resp.json() if token_resp.content else {}
        logger.error("Token exchange failed: %s %s", token_resp.status_code, err)
        return _error_page(err.get("error_description", "Token exchange failed"))

    tokens = token_resp.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    if not access_token:
        return _error_page("No access token received")

    # Fetch user profile
    async with httpx.AsyncClient() as client:
        profile_resp = await client.get(
            f"{GRAPH_API_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if profile_resp.status_code != 200:
        logger.error("Profile fetch failed: %s", profile_resp.text)
        return _error_page("Could not fetch user profile")

    profile = profile_resp.json()
    ms_id = profile.get("id", "")
    email = profile.get("mail") or profile.get("userPrincipalName") or ""
    name = profile.get("displayName", "")

    if not ms_id or not email:
        return _error_page("Incomplete user profile from Microsoft")

    # Upsert user in DB
    user = user_model.upsert_user(
        microsoft_id=ms_id,
        email=email,
        name=name,
    )

    # Save refresh_token for server-side token refresh (worker, scheduled sending)
    if refresh_token:
        from database import get_db

        db = get_db()
        existing = (
            db.table("user_tokens")
            .select("id")
            .eq("user_id", user["id"])
            .execute()
        )
        if existing.data:
            db.table("user_tokens").update(
                {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                }
            ).eq("user_id", user["id"]).execute()
        else:
            db.table("user_tokens").insert(
                {
                    "user_id": user["id"],
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                }
            ).execute()

        # Fresh OAuth succeeded → clear any prior requires_reauth flag so the
        # sidebar banner disappears immediately. Idempotent if the flag was
        # already false.
        db.table("users").update({
            "requires_reauth": False,
            "reauth_reason": None,
            "reauth_flagged_at": None,
        }).eq("id", user["id"]).execute()

    # Monthly reset check
    _check_monthly_reset(user)

    # Issue OutMass JWT
    outmass_jwt = create_jwt(user["id"], user["email"])

    # Audit trail: OAuth consent + login. These two events separately
    # cover the legal-defense needs — oauth_granted captures "user
    # authorized Mail.Send scope" (survives chargeback disputes), and
    # login ties that authorization to a specific session that may
    # later click Send.
    audit.emit(
        audit.EVENT_OAUTH_GRANTED,
        user_id=user["id"],
        email=user["email"],
        metadata={"scopes": MS_GRAPH_SCOPES, "microsoft_id": ms_id},
        request=request,
    )
    audit.emit(
        audit.EVENT_LOGIN,
        user_id=user["id"],
        email=user["email"],
        metadata={"plan": user.get("plan", "free"), "flow": "web_callback"},
        request=request,
    )

    # Build redirect URL to extension with JWT in URL fragment (hash)
    # Fragment is not sent to server, only visible to extension.
    # Pick the chromiumapp.org subdomain from the state param if it
    # validated against the allowlist; fall back to the legacy single-ID
    # env var for old clients that don't pass ?ext=.
    ext_from_state = _decode_state_ext(state)
    target_ext_id = ext_from_state or AZURE_EXTENSION_ID
    ext_redirect = f"https://{target_ext_id}.chromiumapp.org/auth"
    params = {
        "jwt": outmass_jwt,
        "email": user["email"],
        "name": user.get("name", ""),
        "plan": user.get("plan", "free"),
    }
    fragment = urllib.parse.urlencode(params)
    return RedirectResponse(url=f"{ext_redirect}#{fragment}")


def _error_page(message: str) -> HTMLResponse:
    """Minimal HTML error page shown when auth fails."""
    safe_message = (
        message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    html = f"""<!DOCTYPE html>
<html><head><title>OutMass Auth Error</title>
<style>body{{font-family:sans-serif;padding:40px;max-width:500px;margin:auto;text-align:center;color:#323130}}
h1{{color:#a4262c}}.msg{{background:#fde7e9;padding:12px;border-radius:4px;margin:20px 0}}</style>
</head><body>
<h1>Authentication Failed</h1>
<div class="msg">{safe_message}</div>
<p>Please close this window and try again.</p>
</body></html>"""
    return HTMLResponse(content=html, status_code=400)


@router.post("/microsoft", response_model=AuthResponse)
async def microsoft_auth(body: MicrosoftAuthRequest, request: Request):
    """
    Verify Microsoft access token via Graph API /me,
    upsert user, return OutMass JWT.
    """
    # Verify the MS token by calling Graph API
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH_API_BASE}/me",
            headers={"Authorization": f"Bearer {body.access_token}"},
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail="Microsoft token verification failed",
        )

    ms_profile = resp.json()
    ms_id = ms_profile.get("id", body.microsoft_id)
    email = ms_profile.get("mail") or ms_profile.get("userPrincipalName") or body.email
    name = ms_profile.get("displayName", body.name)

    # Upsert user
    user = user_model.upsert_user(
        microsoft_id=ms_id,
        email=email,
        name=name,
    )

    # Save refresh token for follow-up worker (async email sending)
    if body.refresh_token:
        from database import get_db

        db = get_db()
        existing_token = (
            db.table("user_tokens")
            .select("id")
            .eq("user_id", user["id"])
            .execute()
        )
        if existing_token.data and len(existing_token.data) > 0:
            db.table("user_tokens").update(
                {"refresh_token": body.refresh_token}
            ).eq("user_id", user["id"]).execute()
        else:
            db.table("user_tokens").insert(
                {"user_id": user["id"], "refresh_token": body.refresh_token}
            ).execute()

        # Clear any prior requires_reauth flag — the user just re-authed.
        db.table("users").update({
            "requires_reauth": False,
            "reauth_reason": None,
            "reauth_flagged_at": None,
        }).eq("id", user["id"]).execute()

    # Check monthly reset
    _check_monthly_reset(user)

    # Audit trail — mirrors the web callback path so SPA and web flows
    # both leave evidence.
    audit.emit(
        audit.EVENT_LOGIN,
        user_id=user["id"],
        email=user["email"],
        metadata={"plan": user.get("plan", "free"), "flow": "spa_token"},
        request=request,
    )

    # Issue JWT
    token = create_jwt(user["id"], user["email"])

    return AuthResponse(
        jwt=token,
        user={
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "plan": user["plan"],
            "emailsSentThisMonth": user["emails_sent_this_month"],
        },
    )


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    _check_monthly_reset(user)
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "plan": user["plan"],
        "emailsSentThisMonth": user["emails_sent_this_month"],
    }


def _check_monthly_reset(user: dict):
    """Reset monthly counter if we've crossed into a new month."""
    reset_date = user.get("month_reset_date")
    if reset_date:
        from datetime import date, datetime, timezone

        if isinstance(reset_date, str):
            reset_date = date.fromisoformat(reset_date)
        today = datetime.now(timezone.utc).date()
        if today.month != reset_date.month or today.year != reset_date.year:
            from database import get_db

            get_db().table("users").update(
                {
                    "emails_sent_this_month": 0,
                    "ai_generations_this_month": 0,
                    "month_reset_date": today.isoformat(),
                }
            ).eq("id", user["id"]).execute()
            user["emails_sent_this_month"] = 0
            user["ai_generations_this_month"] = 0
