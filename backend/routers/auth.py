"""
OutMass — Auth Router
GET  /auth/callback    → OAuth callback, code exchange, redirect to extension with JWT
POST /auth/microsoft   → legacy SPA flow (kept for backward compat)
GET  /auth/me          → current user info
"""

import base64
import json
import logging
import re
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
import posthog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
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
    MS_GRAPH_ONEDRIVE_SCOPES,
    MS_GRAPH_SCOPES,
    MS_TOKEN_ENDPOINT,
    POSTHOG_API_KEY,
)
from models import audit
from models import user as user_model
from utils import welcome_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# Extension store IDs — used to tag each login's install source (chrome vs edge
# store) WITHOUT an extension update, since every /auth/login already carries
# ?ext=<id>. Anything else (legacy/sideload/unknown) is "other".
_CHROME_EXT_ID = "adcfddainnkjomddlappnnbeomhlcbmm"
_EDGE_EXT_ID = "nfgnhhdeninjmnpfbhnggknimhejbelc"


def _install_source(ext_id: str | None) -> str:
    if ext_id == _CHROME_EXT_ID:
        return "chrome"
    if ext_id == _EDGE_EXT_ID:
        return "edge"
    return "other"


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
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        # iat powers the sliding refresh in get_current_user: tokens past
        # half their life get silently reissued via X-Refresh-JWT.
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user(
    response: Response,
    authorization: str = Header(...),
    x_extension_version: Annotated[str | None, Header()] = None,
) -> dict:
    """Dependency: extract and verify JWT from Authorization header.

    Also records the calling extension's version (sent via X-Extension-Version
    header). Both the activity timestamp and the version write are gated by
    a 15-minute rate-limiter inside maybe_touch_activity, so this is cheap.

    Sliding refresh: a VALID token past half its 24h life gets a fresh
    replacement in the X-Refresh-JWT response header. Active users
    therefore never hit the daily "sign in again" wall (hrcargo lost a
    send to it on 2026-07-17); a client idle past the full TTL still
    expires normally, so the security posture is unchanged. Old
    extensions simply ignore the header.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")
    token = authorization[7:]
    payload = decode_jwt(token)
    user_id = payload.get("sub")
    user = user_model.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    user_model.maybe_touch_activity(user, extension_version=x_extension_version)

    iat = payload.get("iat")
    half_life_seconds = JWT_EXPIRATION_HOURS * 3600 / 2
    now_ts = datetime.now(timezone.utc).timestamp()
    # Tokens minted before the iat claim existed refresh unconditionally —
    # they're at most one TTL old anyway.
    if iat is None or (now_ts - float(iat)) > half_life_seconds:
        response.headers["X-Refresh-JWT"] = create_jwt(
            user_id, payload.get("email") or user.get("email") or ""
        )
    return user


# ── Endpoints ──


def _encode_state(
    ext_id: str,
    include_onedrive: bool = False,
    attempt_id: str | None = None,
) -> str:
    """Pack extension_id + CSRF nonce + onedrive flag into an opaque
    OAuth `state` param.

    URL-safe base64 of JSON — Microsoft echoes `state` verbatim on the
    callback, so we can recover which extension initiated the flow,
    whether OneDrive scopes were requested at the authorize step (so we
    can match them in the token-exchange step), and have an unguessable
    nonce for CSRF protection.

    `attempt_id` is an opaque random id minted by the extension. It rides
    along so a sign-in that dies at Microsoft can be tied back to the
    `oauth_started` event that began it. Deliberately NOT the user's
    identity: nothing here may carry an email, because state travels
    through URLs and lands in access logs.
    """
    payload = {
        "ext": ext_id,
        "n": secrets.token_urlsafe(12),  # CSRF nonce — presence alone is enough
    }
    if include_onedrive:
        payload["od"] = True
    if attempt_id:
        payload["aid"] = attempt_id[:40]
    payload_str = json.dumps(payload, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload_str.encode("utf-8")).decode("ascii").rstrip("=")


# AADSTS codes worth naming in a report. Everything else is reported by
# its raw code — the point is to stop guessing, not to pre-judge.
_AADSTS_MEANINGS = {
    "AADSTS65004": "user_declined_consent",
    "AADSTS65001": "consent_required",
    "AADSTS90094": "admin_consent_required",
    "AADSTS50105": "user_not_assigned_to_app",
    "AADSTS50020": "account_from_other_tenant",
    "AADSTS53003": "blocked_by_conditional_access",
    "AADSTS50076": "mfa_required",
    "AADSTS700016": "app_not_found_in_tenant",
    "AADSTS900561": "bad_request_method",
    "AADSTS7000218": "client_secret_missing",
}

_AADSTS_RE = re.compile(r"AADSTS\d+")


def _classify_ms_error(error: str | None, description: str | None) -> dict:
    """Turn Microsoft's error redirect into reportable, PII-free fields.

    `error_description` is free text that can name the user, their tenant
    and their app registration, so it is never forwarded as-is — only the
    AADSTS code is extracted.
    """
    desc = description or ""
    match = _AADSTS_RE.search(desc)
    code = match.group(0) if match else None
    return {
        "error": (error or "unknown")[:64],
        "aadsts": code,
        "meaning": _AADSTS_MEANINGS.get(code or "", "unclassified"),
    }


def _track_ms_auth_failed(state: str | None, stage: str, fields: dict) -> None:
    """Report a sign-in that died on Microsoft's side.

    This used to be invisible. The callback rendered an error page and
    returned, so a tenant that blocks unverified apps (AADSTS90094) looked
    exactly like a user who changed their mind: the window sat on our
    error page until the user closed it, and Chrome then reported "the
    user did not approve access". 24 of 26 sign-in failures in the 30 days
    to 2026-07-31 carried that one label, with in-window times up to 18
    minutes — nobody deliberates that long over a consent screen.
    """
    if not POSTHOG_API_KEY:
        return
    try:
        data = _decode_state(state) or {}
        attempt_id = data.get("aid")
        posthog.capture(
            # No identity exists at this point — the user never got a token.
            # The attempt id (when the client sent one) stitches this back to
            # the extension's own oauth_started event.
            distinct_id=attempt_id or "anonymous_auth_failure",
            event="ms_auth_failed",
            properties={
                "stage": stage,
                "attempt_id": attempt_id,
                "install_source": _install_source(data.get("ext")),
                "wants_onedrive": bool(data.get("od")),
                **fields,
            },
        )
    except Exception:
        logger.warning("ms_auth_failed capture failed", exc_info=True)


def _decode_state(state: str | None) -> dict | None:
    """Decode the JSON payload from a state param. Returns None on any
    parse failure. Caller is responsible for validating fields like
    ext_id against the allowlist."""
    if not state:
        return None
    try:
        padded = state + "=" * (-len(state) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        if isinstance(data, dict):
            return data
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return None


def _decode_state_ext(state: str | None) -> str | None:
    """Extract extension_id from a state param. Returns None if invalid
    OR not in the allowlist (prevents OAuth open-redirect to attacker)."""
    data = _decode_state(state)
    if not data:
        return None
    ext = data.get("ext")
    if ext and ext in ALLOWED_EXTENSION_IDS:
        return ext
    return None


def _state_includes_onedrive(state: str | None) -> bool:
    """True if the state was minted with include_onedrive=true. Lets
    /auth/callback know whether to ask for OneDrive scopes during the
    token exchange. Defaults to False for safety — a corrupt/missing
    state never accidentally requests scopes the user didn't consent to.
    """
    data = _decode_state(state)
    return bool(data and data.get("od"))


def _persist_ms_tokens(
    user_id: str,
    access_token: str,
    refresh_token: str | None,
    wants_onedrive: bool,
) -> None:
    """Store the freshest Microsoft tokens for the user.

    Microsoft omits the refresh_token on some repeat consents — notably
    the incremental OneDrive flow. Gating the whole write on refresh_token
    (the pre-2026-07-16 behaviour) also threw away the NEW wider-scope
    access token and the has_onedrive_scope flag, so /api/onedrive/*
    kept being served the stale Mail-only token and the sidebar
    re-launched consent in a loop.

    Rules:
      - access_token: always overwrite — it's the freshest, widest-scope one.
      - refresh_token: only overwrite when Microsoft returned one; never
        clobber a still-good stored token with nothing.
      - has_onedrive_scope: sticky True once any OneDrive consent
        completes (the consent record outlives individual tokens).
    """
    from database import get_db

    db = get_db()
    existing = (
        db.table("user_tokens")
        .select("id, has_onedrive_scope")
        .eq("user_id", user_id)
        .execute()
    )
    previously_had_onedrive = bool(
        existing.data and existing.data[0].get("has_onedrive_scope")
    )
    token_row = {
        "access_token": access_token,
        "has_onedrive_scope": previously_had_onedrive or wants_onedrive,
    }
    if refresh_token:
        token_row["refresh_token"] = refresh_token

    if existing.data:
        db.table("user_tokens").update(token_row).eq("user_id", user_id).execute()
    elif refresh_token:
        token_row["user_id"] = user_id
        db.table("user_tokens").insert(token_row).execute()
    else:
        # No stored row AND no refresh_token: shouldn't happen on a first
        # consent (offline_access always yields one), and a row that can
        # never refresh is useless — log loudly instead of half-inserting.
        logger.warning(
            "Token exchange for user %s returned no refresh_token on first "
            "sign-in; tokens not persisted",
            user_id,
        )


@router.get("/login")
async def login_redirect(
    ext: str | None = Query(None),
    include_onedrive: bool = Query(False),
    aid: str | None = Query(None),
):
    """Redirect user to Microsoft login. Used by extension launchWebAuthFlow.

    `ext` is the calling extension's chrome.runtime.id. It's echoed to
    Microsoft via the OAuth `state` parameter, validated against
    ALLOWED_EXTENSION_IDS on the callback, and used to route the final
    chromiumapp.org redirect back to the originating extension. An
    unrecognized or missing `ext` falls back to AZURE_EXTENSION_ID so
    legacy (pre-multi-ext) clients still work.

    `include_onedrive=true` adds Files.Read.All + Files.ReadWrite scopes
    on top of the default Mail scopes. Used by the OneDrive-link feature
    for incremental consent: the user only sees the OneDrive permission
    on the Microsoft screen when they actually opt into the feature.
    Microsoft re-issues a token covering all previously-granted scopes
    plus the new ones, so a successful callback gives us a single
    refresh_token usable for both Mail and OneDrive operations.
    """
    chosen_ext = ext if ext in ALLOWED_EXTENSION_IDS else AZURE_EXTENSION_ID
    # `aid` is the extension's opaque attempt id (0.1.27+). Older clients
    # simply don't send one — the failure is still reported, just without
    # the link back to their oauth_started event.
    safe_aid = aid if aid and re.fullmatch(r"[A-Za-z0-9_-]{6,40}", aid) else None
    state = _encode_state(
        chosen_ext, include_onedrive=include_onedrive, attempt_id=safe_aid
    )

    scope = MS_GRAPH_SCOPES
    if include_onedrive:
        scope = f"{scope} {MS_GRAPH_ONEDRIVE_SCOPES}"

    params = {
        "client_id": AZURE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": AZURE_REDIRECT_URI,
        "response_mode": "query",
        "scope": scope,
        # `select_account` lets the user pick if they're signed into
        # multiple Microsoft accounts. Doesn't force re-consent for
        # already-granted scopes — Microsoft skips the consent step
        # automatically when scopes are already authorized.
        "prompt": "select_account",
        "state": state,
    }
    auth_url = f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}"

    # Funnel midpoint. oauth_started (client) proves the flow was REQUESTED;
    # this proves the auth window actually loaded and left for Microsoft.
    # A sign-in that has this event but neither ms_auth_failed nor a login
    # is a user parked ON Microsoft's own pages (password/MFA/account
    # picker) — the window most likely lost behind another window. That is
    # the one state we previously could not distinguish from "window never
    # opened", and it is what the 2026-08-03 rage-uninstall came down to.
    if POSTHOG_API_KEY:
        try:
            posthog.capture(
                distinct_id=safe_aid or "anonymous_auth_window",
                event="ms_auth_window_opened",
                properties={
                    "attempt_id": safe_aid,
                    "install_source": _install_source(chosen_ext),
                    "wants_onedrive": include_onedrive,
                },
            )
        except Exception:
            logger.warning("ms_auth_window_opened capture failed", exc_info=True)

    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def auth_callback(
    request: Request,
    background_tasks: BackgroundTasks,
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
        _track_ms_auth_failed(
            state, "authorize", _classify_ms_error(error, error_description)
        )
        return _error_page(error_description or error)

    if not code:
        _track_ms_auth_failed(state, "authorize", {"error": "no_code"})
        return _error_page("No authorization code received")

    if not AZURE_CLIENT_SECRET:
        return _error_page("Server misconfigured: AZURE_CLIENT_SECRET not set")

    # Exchange code for tokens using Web platform (client_secret)
    async with httpx.AsyncClient() as client:
        try:
            # IMPORTANT: token-exchange scope MUST match (or be a subset
            # of) what was requested at /authorize. Adding scopes the
            # user never consented to triggers AADSTS65001 and breaks
            # the entire sign-in. We use the state param (decoded
            # below) to know whether the original /auth/login asked
            # for OneDrive scopes — the include_onedrive=true path —
            # and only then request them here. The legacy state shape
            # (no `od` flag) defaults to Mail-only.
            wants_onedrive = _state_includes_onedrive(state)
            exchange_scope = (
                f"{MS_GRAPH_SCOPES} {MS_GRAPH_ONEDRIVE_SCOPES}"
                if wants_onedrive
                else MS_GRAPH_SCOPES
            )
            token_resp = await client.post(
                MS_TOKEN_ENDPOINT,
                data={
                    "client_id": AZURE_CLIENT_ID,
                    "client_secret": AZURE_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": AZURE_REDIRECT_URI,
                    "scope": exchange_scope,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as e:
            logger.error("Token exchange network error: %s", e)
            return _error_page("Could not reach Microsoft")

    if token_resp.status_code != 200:
        err = token_resp.json() if token_resp.content else {}
        logger.error("Token exchange failed: %s %s", token_resp.status_code, err)
        _track_ms_auth_failed(
            state,
            "token_exchange",
            {
                "status": token_resp.status_code,
                **_classify_ms_error(
                    err.get("error"), err.get("error_description")
                ),
            },
        )
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
    user, created = user_model.upsert_user(
        microsoft_id=ms_id,
        email=email,
        name=name,
    )

    # First-ever sign-in → one-time welcome email (best-effort, after the
    # response; a mail hiccup must never break the OAuth redirect).
    if created:
        background_tasks.add_task(
            welcome_email.send_welcome_email, user["email"], user.get("name")
        )

    # Persist tokens for server-side refresh (worker, scheduled sending).
    # The access_token is ALWAYS updated (repeat consents can omit the
    # refresh_token, but the access token they return carries the newly
    # consented scopes — discarding it trapped OneDrive users in a
    # consent loop, 2026-07-16). See _persist_ms_tokens for the rules.
    _persist_ms_tokens(
        user_id=user["id"],
        access_token=access_token,
        refresh_token=refresh_token,
        wants_onedrive=wants_onedrive,
    )

    # Clear any prior requires_reauth flag on ANY successful interactive
    # sign-in — not only when a refresh_token came back. Nesting this inside
    # the `if refresh_token:` block above meant a repeat consent that omitted
    # the refresh_token left the flag set, so the reconnect banner reappeared
    # on the next poll and the user was trapped in a reconnect loop. If the
    # stored token is genuinely still dead, the daily token-health beat / next
    # send re-flags it.
    from database import get_db

    get_db().table("users").update({
        "requires_reauth": False,
        "reauth_reason": None,
        "reauth_flagged_at": None,
    }).eq("id", user["id"]).execute()

    # Monthly reset check
    _check_monthly_reset(user)

    # Bump last_login_at + last_activity_at now that we're certain the
    # login is going through. Phase 5's inactivity beat reads this.
    user_model.touch_login(user["id"])

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

    # Tag this person's install source (chrome vs edge store) in PostHog so any
    # metric can be broken down by store — no extension change needed, the ext id
    # rides along with every login. Best-effort; must never block the redirect.
    if POSTHOG_API_KEY:
        try:
            _src = _install_source(ext_from_state)
            posthog.capture(
                distinct_id=user["email"],
                event="login",
                properties={
                    "install_source": _src,
                    "ext_id": ext_from_state or "",
                    "plan": user.get("plan", "free"),
                    "$set": {"install_source": _src},
                },
            )
        except Exception:
            logger.warning("install_source capture failed", exc_info=True)

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
async def microsoft_auth(
    body: MicrosoftAuthRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
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
    user, created = user_model.upsert_user(
        microsoft_id=ms_id,
        email=email,
        name=name,
    )

    # First-ever sign-in → one-time welcome email (mirrors the web callback).
    if created:
        background_tasks.add_task(
            welcome_email.send_welcome_email, user["email"], user.get("name")
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

    # Bump last_login_at + last_activity_at (mirrors web callback).
    user_model.touch_login(user["id"])

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
    """Reset quota counters when the billing-anchored month rolls over.

    Delegates to user_model.check_monthly_reset — a ROLLING month from
    month_reset_date, not the calendar month, so paid users' quota period
    matches their Stripe billing period. Kept as a wrapper so the three
    auth call sites stay unchanged."""
    user_model.check_monthly_reset(user)
