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
from postgrest.exceptions import APIError
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
    FIRST_SIGNIN_INCLUDE_MAIL_READ,
    MS_GRAPH_FIRST_SIGNIN_SCOPES,
    MS_GRAPH_MAIL_READ_SCOPE,
    MS_GRAPH_ONEDRIVE_SCOPES,
    MS_GRAPH_SCOPES,
    MS_TOKEN_ENDPOINT,
    POSTHOG_API_KEY,
)
from models import audit
from models import ms_token as ms_token_model
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
    include_mail_read: bool = False,
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
    # ALWAYS written, both True and False — unlike `od`, whose absence
    # unambiguously means "not requested". Absence of `mr` means "minted
    # before the split", which the decoder reads as True. So omitting it
    # when narrow would make the token exchange request Mail.Read that
    # /authorize never asked for: scope mismatch, AADSTS65001, and a dead
    # sign-in for every new user the moment the flag is flipped.
    payload["mr"] = bool(include_mail_read)
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
    # Fires on the token-EXCHANGE leg only: an unregistered redirect_uri at
    # the authorize leg errors on Microsoft's own page and never reaches us.
    "AADSTS50011": "redirect_uri_not_registered",
}


def _request_host(request: Request) -> str:
    """Which public hostname served this request.

    We run one backend behind two domains (api.getoutmass.com primary,
    the railway.app domain as the extension's fallback), and some networks
    filter one but not the other — Saudi ISPs blocked railway.app outright in
    the 0.1.18 era. The 2026-08-05 Vietnam investigation burned an evening of
    Ali reading Railway log screenshots to learn which door one user came
    through; this property answers it from PostHog for every future attempt.
    """
    raw = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    # X-Forwarded-Host may be a comma-joined chain; the first entry is the
    # client-facing one. Port and case are noise for a breakdown.
    return raw.split(",")[0].strip().split(":")[0].lower()[:80]

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


def _track_ms_auth_failed(
    state: str | None, stage: str, fields: dict, host: str = ""
) -> None:
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
                # The domain Microsoft redirected the user's browser to. If a
                # network blocks one of our two domains, failures cluster on
                # the OTHER one's absence — measurable without server logs.
                "host": host,
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
    # Deliberately broad. The narrow tuple that used to sit here
    # ((ValueError, json.JSONDecodeError, UnicodeDecodeError)) missed
    # RecursionError — json.loads on deeply nested arrays raises it, and it
    # inherits from RuntimeError, not ValueError. A ~45KB crafted `state` on
    # an UNAUTHENTICATED GET therefore escaped this function, escaped
    # _error_page, and became a 500 with no settle script: the popup hang
    # this whole feature exists to eliminate, triggerable by anyone.
    # Verified end-to-end against real uvicorn+h11 by the 2026-08-06 review.
    # This function's contract is "a bad state is no state" — nothing a
    # parser can throw should ever be louder than that.
    except Exception:
        return None
    return None


def _decode_state_ext(state: str | None) -> str | None:
    """Extract extension_id from a state param. Returns None if invalid
    OR not in the allowlist (prevents OAuth open-redirect to attacker)."""
    data = _decode_state(state)
    if not data:
        return None
    ext = data.get("ext")
    # isinstance BEFORE the membership test: `ext` is attacker-minted JSON
    # and can be a list or dict. Harmless against today's list allowlist
    # (`in` falls back to ==), but the day someone tidies
    # ALLOWED_EXTENSION_IDS into a set — the natural change for a
    # membership-only lookup — an unhashable value raises TypeError on this
    # same unguarded path. 67 bytes of crafted state would then be a 500.
    if isinstance(ext, str) and ext in ALLOWED_EXTENSION_IDS:
        return ext
    return None


def _state_includes_mail_read(state: str | None) -> bool:
    """True if the state was minted with include_mail_read=true.

    Note the default is the OPPOSITE of the OneDrive helper below, and that
    is deliberate. A state with no `mr` key was minted before this split
    existed, i.e. by a build that always asked for Mail.Read — so absence
    means "yes, it was requested". Any sign-in already in flight when this
    deploys carries exactly that shape; defaulting to False would make the
    token exchange under-request and drop Mail.Read from their token.
    """
    data = _decode_state(state)
    if data is None:
        return True
    return bool(data.get("mr", True))


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
    wants_mail_read: bool = True,
) -> None:
    """Store the freshest Microsoft tokens for the user.

    Microsoft omits the refresh_token on some repeat consents — notably
    the incremental OneDrive flow. Gating the whole write on refresh_token
    (the pre-2026-07-16 behaviour) also threw away the NEW wider-scope
    access token and the has_onedrive_scope flag, so /api/onedrive/*
    kept being served the stale Mail-only token and the sidebar
    re-launched consent in a loop.

    Rules:
      - access_token: overwrite with the freshest one — EXCEPT when this
        exchange requested a narrower scope set than the user's recorded
        consent (a plain re-sign-in after the Mail.Read split flips on).
        Storing that token would make get_fresh_access_token's Strategy 1
        serve it for up to ~1h (the /me validity probe cannot see scopes)
        and reply detection would 403 silently the whole time. Instead we
        store NULL: Strategy 1 is skipped and the very next token use goes
        straight to the refresh, which requests the full recorded consent
        (wide Mail + OneDrive if granted) — one extra token round-trip,
        never a wrong-scope window, and it also covers the combined case
        where the same sign-in ADDS OneDrive while narrowing Mail.
      - refresh_token: only overwrite when Microsoft returned one; never
        clobber a still-good stored token with nothing.
      - has_onedrive_scope: sticky True once any OneDrive consent
        completes (the consent record outlives individual tokens).
      - has_mail_read_scope: same stickiness; written only when migration
        024's column exists (see the guarded write below).
    """
    from database import get_db

    db = get_db()
    # Column-guarded select (models.ms_token): with migration 024 unrun this
    # returns the row WITHOUT has_mail_read_scope instead of raising 42703 —
    # which used to escape to main.py's global handler and 500 every OAuth
    # callback, bypassing _error_page and its settle redirect (hung popups).
    existing = ms_token_model.select_user_tokens(
        db, user_id, "id, has_onedrive_scope"
    )
    previously_had_onedrive = bool(
        existing.data and existing.data[0].get("has_onedrive_scope")
    )
    # Sticky like OneDrive: consent outlives individual tokens. For an
    # EXISTING row a missing key reads as True — the column may not exist
    # yet (migration 024 unrun) and every pre-024 row belongs to someone who
    # granted Mail.Read at sign-in. A brand-new user has granted nothing, so
    # only this flow's own request counts.
    if existing.data:
        previously_had_mail_read = (
            existing.data[0].get("has_mail_read_scope") is not False
        )
    else:
        previously_had_mail_read = False

    has_mail_read = previously_had_mail_read or wants_mail_read
    # This exchange asked Microsoft for LESS than the user's recorded
    # consent — see the access_token rule in the docstring.
    narrower_than_consent = previously_had_mail_read and not wants_mail_read

    token_row = {
        "access_token": None if narrower_than_consent else access_token,
        "has_onedrive_scope": previously_had_onedrive or wants_onedrive,
    }
    if refresh_token:
        token_row["refresh_token"] = refresh_token

    def _write(payload: dict) -> None:
        if existing.data:
            db.table("user_tokens").update(payload).eq(
                "user_id", user_id
            ).execute()
        elif refresh_token:
            db.table("user_tokens").insert(
                {**payload, "user_id": user_id}
            ).execute()
        else:
            # No stored row AND no refresh_token: shouldn't happen on a first
            # consent (offline_access always yields one), and a row that can
            # never refresh is useless — log loudly instead of half-inserting.
            logger.warning(
                "Token exchange for user %s returned no refresh_token on "
                "first sign-in; tokens not persisted",
                user_id,
            )

    # Guarded write. With migration 024 unrun, an update/insert payload
    # containing has_mail_read_scope is rejected by PostgREST with PGRST204
    # BEFORE any SQL runs (so the retry below never double-writes). The
    # guard also covers the brief post-migration window where PostgREST's
    # schema cache hasn't reloaded: the select above may already succeed
    # while the write still bounces.
    if ms_token_model.mail_read_column_attemptable():
        try:
            _write({**token_row, "has_mail_read_scope": has_mail_read})
            return
        except APIError as err:
            if not ms_token_model.is_missing_mail_read_column(err):
                raise
            ms_token_model.mark_mail_read_column_missing()
    _write(token_row)
    if not has_mail_read:
        # Only reachable when FIRST_SIGNIN_INCLUDE_MAIL_READ was flipped
        # BEFORE migration 024 ran — an operator-order violation. The narrow
        # consent cannot be recorded, migration 024 will backfill this row
        # to TRUE, and this user's refresh will then over-request Mail.Read
        # and fail with AADSTS65001. Loud on purpose.
        logger.error(
            "user %s consented WITHOUT Mail.Read but user_tokens.has_mail_"
            "read_scope does not exist (migration 024 unrun) — the narrow "
            "consent is NOT recorded and will be backfilled wrongly to TRUE. "
            "Run migration 024 before flipping FIRST_SIGNIN_INCLUDE_MAIL_READ.",
            user_id,
        )


@router.get("/login")
async def login_redirect(
    request: Request,
    ext: str | None = Query(None),
    include_onedrive: bool = Query(False),
    aid: str | None = Query(None),
    include_mail_read: bool = Query(False),
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

    `include_mail_read=true` does the same for Mail.Read, which is leaving
    the first-sign-in ask (see MS_GRAPH_FIRST_SIGNIN_SCOPES). Reply
    detection is the only thing that needs it, and it cannot matter before
    the user's first campaign — whereas "Read your mail" on a consent
    screen shown to someone who has sent nothing yet is the most alarming
    line there. Gated by FIRST_SIGNIN_INCLUDE_MAIL_READ so the narrow ask
    only starts when that variable is flipped; until then this endpoint
    behaves exactly as it did.
    """
    chosen_ext = ext if ext in ALLOWED_EXTENSION_IDS else AZURE_EXTENSION_ID
    # `aid` is the extension's opaque attempt id (0.1.27+). Older clients
    # simply don't send one — the failure is still reported, just without
    # the link back to their oauth_started event.
    safe_aid = aid if aid and re.fullmatch(r"[A-Za-z0-9_-]{6,40}", aid) else None
    # Ask for Mail.Read when the flag says to (today's behaviour) OR when the
    # client is explicitly upgrading for reply detection. Both cases must be
    # recorded in `state`, because the token exchange has to request exactly
    # what /authorize did — a mismatch is AADSTS65001 and a dead sign-in.
    wants_mail_read = FIRST_SIGNIN_INCLUDE_MAIL_READ or include_mail_read
    state = _encode_state(
        chosen_ext,
        include_onedrive=include_onedrive,
        attempt_id=safe_aid,
        include_mail_read=wants_mail_read,
    )

    scope = MS_GRAPH_SCOPES if wants_mail_read else MS_GRAPH_FIRST_SIGNIN_SCOPES
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
                    # Which of our two domains the extension's sticky base
                    # actually picked. Distinguishes "user on the primary"
                    # from "user riding the railway fallback because their
                    # network filters the primary" — the fork the 2026-08-05
                    # investigation could only close with Railway screenshots.
                    "host": _request_host(request),
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
        classified = _classify_ms_error(error, error_description)
        _track_ms_auth_failed(
            state, "authorize", classified, host=_request_host(request)
        )
        # The PAGE may show Microsoft's full description — it renders only in
        # the user's own window. The FRAGMENT may not: it becomes a PostHog
        # property and a client-side string, and descriptions embed the
        # user's address and tenant name ("User account 'x@y.com' from...").
        return _error_page(
            error_description or error,
            state=state,
            fragment=_ms_settle_code(classified, fallback=error),
        )

    if not code:
        _track_ms_auth_failed(
            state, "authorize", {"error": "no_code"}, host=_request_host(request)
        )
        return _error_page(
            "No authorization code received",
            state=state,
            fragment="Sign-in did not complete, please try again",
        )

    if not AZURE_CLIENT_SECRET:
        # The env-var name belongs on the operator-facing page, not in every
        # client's telemetry.
        return _error_page(
            "Server misconfigured: AZURE_CLIENT_SECRET not set",
            state=state,
            fragment="Sign-in failed on our server, please retry",
        )

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
            # Legacy state (no `mr` key) means the flow started before the
            # split existed, when Mail.Read was always requested — so the
            # absence of the flag must read as True, not False. Getting this
            # backwards would under-request on every in-flight sign-in the
            # moment this deploys.
            wants_mail_read = _state_includes_mail_read(state)
            exchange_scope = (
                MS_GRAPH_SCOPES if wants_mail_read else MS_GRAPH_FIRST_SIGNIN_SCOPES
            )
            if wants_onedrive:
                exchange_scope = f"{exchange_scope} {MS_GRAPH_ONEDRIVE_SCOPES}"
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
            return _error_page(
                "Could not reach Microsoft",
                state=state,
                fragment="Could not reach Microsoft, please retry",
            )

    if token_resp.status_code != 200:
        # NOT assumed to be JSON. A successful HTTP response carrying an ISP
        # or captive-portal block page — precisely the network-filtering
        # scenario this feature line exists to diagnose — used to raise here,
        # OUTSIDE the httpx.HTTPError guard above (which only covers
        # transport errors). FastAPI then returned 500 with no HTML at all,
        # so no settle script ran and the popup hung: the exact chain the
        # settle redirect was built to break.
        try:
            err = token_resp.json() if token_resp.content else {}
            if not isinstance(err, dict):
                err = {}
        except ValueError:
            logger.error(
                "Token exchange returned non-JSON (%s): %r",
                token_resp.status_code,
                token_resp.text[:200],
            )
            err = {}
        logger.error("Token exchange failed: %s %s", token_resp.status_code, err)
        classified = _classify_ms_error(
            err.get("error"), err.get("error_description")
        )
        _track_ms_auth_failed(
            state,
            "token_exchange",
            host=_request_host(request),
            fields={"status": token_resp.status_code, **classified},
        )
        return _error_page(
            err.get("error_description") or "Token exchange failed",
            state=state,
            fragment=_ms_settle_code(classified, fallback="server_error"),
        )

    tokens = token_resp.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    if not access_token:
        return _error_page(
            "No access token received",
            state=state,
            fragment="Microsoft sent no token, please try again",
        )

    # Fetch user profile
    async with httpx.AsyncClient() as client:
        profile_resp = await client.get(
            f"{GRAPH_API_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if profile_resp.status_code != 200:
        logger.error("Profile fetch failed: %s", profile_resp.text)
        return _error_page(
            "Could not fetch user profile",
            state=state,
            fragment="Could not read your Microsoft profile, please retry",
        )

    profile = profile_resp.json()
    ms_id = profile.get("id", "")
    email = profile.get("mail") or profile.get("userPrincipalName") or ""
    name = profile.get("displayName", "")

    if not ms_id or not email:
        return _error_page(
            "Incomplete user profile from Microsoft",
            state=state,
            fragment="Your Microsoft profile has no email address",
        )

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
        wants_mail_read=wants_mail_read,
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
    #
    # `exchange_scope`, NOT the MS_GRAPH_SCOPES constant: once the
    # Mail.Read split flips on, narrow users never consent to Mail.Read,
    # and an audit record asserting they did is worse than none — this
    # trail exists precisely to be believed in a dispute.
    audit.emit(
        audit.EVENT_OAUTH_GRANTED,
        user_id=user["id"],
        email=user["email"],
        metadata={"scopes": exchange_scope, "microsoft_id": ms_id},
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
                    "host": _request_host(request),
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


# How long the error page shows before it redirects itself and closes.
#
# 9s while the page returned 400 — where it never actually ran, because
# Chromium tore the popup down first. Serving it as 200 made the dwell real,
# and a real dwell has a cost the 400 hid: a user who closes the window
# manually makes launchWebAuthFlow report "user did not approve", which every
# shipped client maps to consent_declined. A network blip then gets filed as
# a refused permission, in the user's face and in our telemetry.
#
# 5s, because the dwell is a bridge and not the destination — the same reason
# is shown again, persistently, by the extension once the flight settles
# (popup error section, sidebar reauth banner). Long enough not to read as a
# flash, short enough to halve the window in which a manual close can lie
# about what happened.
_SETTLE_DELAY_MS = 5000


# RFC 6749 §4.1.2.1 + OpenID Connect: the complete set of `error` codes an
# authorization server may return. The fragment reaches PostHog and every
# client, so only a value FROM THIS LIST is ever echoed — everything else
# collapses to the generic sentence.
_OAUTH_ERROR_CODES = frozenset(
    {
        "invalid_request",
        "unauthorized_client",
        "access_denied",
        "unsupported_response_type",
        "invalid_scope",
        "server_error",
        "temporarily_unavailable",
        "interaction_required",
        "login_required",
        "account_selection_required",
        "consent_required",
        "invalid_request_uri",
        "invalid_request_object",
        "request_not_supported",
        "request_uri_not_supported",
        "registration_not_supported",
    }
)


# What the user should DO, one sentence per failure class.
#
# Constraints, all enforced by test_settle_messages_are_deliverable:
#   * <= 64 chars — every shipped client truncates the fragment there;
#   * only characters that survive _settle_fragment's sanitizer, so no
#     apostrophes (they are stripped, turning "organization's" into
#     "organizations" mid-word);
#   * no '$' — the sidebar's i18n substitution reads it as a placeholder;
#   * one stable sentence per class, because this doubles as the PostHog
#     grouping key.
#
# English only. The server does not know the user's panel language, and
# guessing from Accept-Language would be the same mistake the CSV decoder
# just made. An English sentence naming the next step beats a localized
# nothing; localizing properly needs the client to read errorCode, which no
# shipped version does.
_SETTLE_MESSAGES = {
    "user_declined_consent":
        "Permission was declined on the Microsoft screen",
    "consent_required":
        "OutMass needs your permission from Microsoft",
    "admin_consent_required":
        "Your IT admin must approve OutMass first",
    "user_not_assigned_to_app":
        "Your IT admin has not given you access",
    "account_from_other_tenant":
        "Use the account you use for Outlook",
    "blocked_by_conditional_access":
        "Your organization blocked this sign-in",
    "mfa_required":
        "Finish your extra sign-in check, then retry",
    "app_not_found_in_tenant":
        "Your IT admin must add OutMass to your org",
    "client_secret_missing":
        "Sign-in is misconfigured. Please contact us",
    "redirect_uri_not_registered":
        "Sign-in is misconfigured. Please contact us",
}


def _ms_settle_code(classified: dict, fallback: str | None = None) -> str:
    """A class-stable, PII-free settle fragment for a Microsoft-side error.

    The raw error_description must NEVER feed the fragment: it embeds the
    user's address and tenant ("User account 'x@y.com' from identity
    provider..."), and the character sanitizer downstream deletes the '@'
    but keeps the parts — 'xy.com' inside the 64-char cap. That is a PII
    leak into PostHog and every client, and it also shatters the grouping
    the fragment exists for (one distinct code per user).

    So this helper is built from CLOSED VOCABULARIES only: the AADSTS number
    and our own meaning table, or an `error` value that appears in the
    RFC 6749 list above. The first version of this function claimed exactly
    that in prose while its last line echoed the caller's free text — the
    2026-08-06 review proved PII straight through it via the `error` query
    param. An allowlist keeps the docstring and the code the same shape.

    Underscores become spaces — '_' is deliberately outside the sanitizer
    alphabet, so no fragment can ever collide with the sidebar's exact-match
    "session_expired" handling.
    """
    aadsts = classified.get("aadsts") or ""
    raw_meaning = classified.get("meaning") or ""
    meaning = raw_meaning.replace("_", " ")
    if aadsts:
        # Every client in the field renders this string verbatim: 0.1.26 and
        # 0.1.27 both resolve the flight with `{ error: errorMsg }` and no
        # errorCode, so nothing downstream can turn it into localized
        # guidance. Until the 200 fix the point was moot — Chromium threw the
        # fragment away — but now it IS the message, and "AADSTS90094: admin
        # consent required" tells a user nothing they can act on.
        #
        # So say what to do. The diagnostic code is not lost: ms_auth_failed
        # carries the AADSTS number and meaning server-side, correlated by
        # attempt_id, which is where support should read it from anyway.
        if raw_meaning in _SETTLE_MESSAGES:
            # Sentence first, code in parentheses. The user reads an
            # instruction; support still greps the AADSTS number, which two
            # earlier tests pin as the telemetry grouping key. Messages are
            # capped at 48 so the longest code still fits inside 64.
            composed = f"{_SETTLE_MESSAGES[raw_meaning]} ({aadsts})"
            if len(composed) <= 64:
                return composed
            return _SETTLE_MESSAGES[raw_meaning]
        if meaning and meaning != "unclassified":
            return f"{aadsts}: {meaning}"[:64]
        return f"Sign-in failed ({aadsts}), please try again"[:64]
    code = (fallback or "").strip().lower()
    if code in _OAUTH_ERROR_CODES:
        return f"Sign-in failed ({code.replace('_', ' ')}), please try again"[:64]
    return "Sign-in failed, please try again"


def _settle_fragment(message: str) -> str:
    """The error string carried back to the extension in the URL fragment.

    The frozen 0.1.26 client parses the fragment with URLSearchParams and, on
    `error=`, resolves the flight and reports oauth_failed with
    reason=backend_error, code=value[:64] — a path that shipped and works. The
    value doubles as BOTH the user-visible error text (popup, sidebar reauth
    banner, OneDrive picker) and the telemetry code, so: one short plain
    sentence, stable per failure class so PostHog can group it, ASCII only
    (no `$` — the sidebar's i18n substitution treats it as a placeholder
    marker), and hard-capped at 64 chars because that is where the client
    truncates the code anyway.
    """
    clean = re.sub(r"[^A-Za-z0-9 .,:()\-]", "", message or "")
    clean = re.sub(r"\s+", " ", clean).strip()
    return (clean or "Sign-in failed, please try again")[:64]


def _error_page(
    message: str, state: str | None = None, fragment: str | None = None
) -> HTMLResponse:
    """HTML error page shown in the auth popup when sign-in fails.

    Until 2026-08-05 this page simply sat there. That had a nasty side
    effect: launchWebAuthFlow only settles when the window reaches the
    chromiumapp.org redirect or closes, so this page HELD the popup open —
    the user parked it behind other windows, the extension's single-flight
    guard then made every later Sign-in click silently join the dead flight
    (the 2026-08-03 rage-uninstall), and Chrome filed the eventual close as
    "user did not approve", burying the real AADSTS reason this page was
    displaying all along.

    Now, when the state identifies an allowlisted extension, the page shows
    the message for _SETTLE_DELAY_MS (9s) and then redirects itself to that
    extension's chromiumapp.org URL with the error in the FRAGMENT. The
    browser closes the popup, the flight settles, the frozen 0.1.26 client
    reports the real reason through its existing backend_error path, and the
    Sign-in button is immediately usable again.

    The redirect is gated on _decode_state_ext, which validates against
    ALLOWED_EXTENSION_IDS — state is attacker-mintable (unsigned base64
    JSON), and redirecting to an arbitrary <id>.chromiumapp.org would hang
    a foreign browser's popup on an unresolvable address. No valid state →
    no redirect → exactly the old behaviour.

    `message` and `fragment` are STRUCTURALLY separate on purpose. The page
    message renders only in the user's own window and may carry Microsoft's
    full description; the fragment becomes a PostHog property and a string
    inside every client, so it must be class-stable and PII-free. The
    pre-deploy adversarial review (2026-08-06) caught the first version of
    this function deriving the fragment FROM the message — which walked
    "User account 'x@y.com'..." straight into telemetry with only the '@'
    removed. `message` must never feed the fragment again; a call site that
    forgets to pass one gets a generic sentence, not a leak.
    """
    # str() first: a JSON `error_description: null` reached this as None and
    # crashed on .replace — a 500 with no settle script, i.e. the hung popup
    # again, from a field we do not control.
    safe_message = (
        str(message or "Sign-in failed")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    settle_ext = _decode_state_ext(state)
    if settle_ext:
        settle_url = (
            f"https://{settle_ext}.chromiumapp.org/auth#"
            + urllib.parse.urlencode(
                {"error": _settle_fragment(fragment or "")}
            )
        )
        footer = "<p>This window will return to OutMass in a few seconds.</p>"
        settle_script = (
            f'<script>setTimeout(function(){{location.replace({json.dumps(settle_url)})}},'
            f"{_SETTLE_DELAY_MS});</script>"
        )
    else:
        footer = "<p>Please close this window and try again.</p>"
        settle_script = ""
    html = f"""<!DOCTYPE html>
<html><head><title>OutMass Auth Error</title>
<style>body{{font-family:sans-serif;padding:40px;max-width:500px;margin:auto;text-align:center;color:#323130}}
h1{{color:#a4262c}}.msg{{background:#fde7e9;padding:12px;border-radius:4px;margin:20px 0}}</style>
</head><body>
<h1>Authentication Failed</h1>
<div class="msg">{safe_message}</div>
{footer}{settle_script}
</body></html>"""
    # 200, not 400 — and that is the whole point of this line.
    #
    # Chromium fails a launchWebAuthFlow navigation whose response code is
    # >= 400 and reports it as "Authorization page could not be loaded".
    # So a 400 here destroyed everything this page does: the browser tore
    # the popup down before the settle script above could run, the real
    # AADSTS reason never reached the client, and — worse — the generic
    # load-failure message matched the extension's `auth_page_failed`
    # branch, which fires a one-shot auto-retry. A user who had just
    # DECLINED consent was handed a fresh consent screen 3 seconds later.
    # The comment guarding that retry says consent declines must never be
    # retried; it was correct and simply never engaged, because the decline
    # arrived disguised as a page-load failure.
    #
    # Measured 2026-08-07: a US user clicked sign-in 48s after installing,
    # then fought that loop six times over 75 minutes and left.
    #
    # Nothing reads this status code. The page is only ever loaded inside
    # the auth popup, and both the message and the settle fragment are the
    # actual channel. Serving it as a successful response is what lets the
    # browser render it and then follow the redirect we chose.
    return HTMLResponse(content=html, status_code=200)


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
