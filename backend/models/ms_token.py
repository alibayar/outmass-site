"""
OutMass — MS Graph Token Helper
Refreshes access tokens using stored refresh_token + client_secret (Web flow).
"""

import logging
import time
from datetime import datetime, timezone

import httpx
from postgrest.exceptions import APIError

from config import (
    AZURE_CLIENT_ID,
    AZURE_CLIENT_SECRET,
    BACKEND_URL,
    MAILERSEND_API_KEY,
    MAILERSEND_FROM_EMAIL,
    MAILERSEND_PERSON_FROM_NAME,
    MS_GRAPH_FIRST_SIGNIN_SCOPES,
    MS_GRAPH_ONEDRIVE_SCOPES,
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
        "from": {"email": MAILERSEND_FROM_EMAIL, "name": MAILERSEND_PERSON_FROM_NAME},
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


# ── migration-024 column guard ──────────────────────────────────────────────
#
# has_mail_read_scope is added by migration 024, which is run BY HAND on
# Supabase. This code must deploy safely BEFORE that happens, and PostgREST
# does not shrug at unknown columns — it raises:
#
#   SELECT ...,has_mail_read_scope → APIError code 42703
#       ("column user_tokens.has_mail_read_scope does not exist")
#   INSERT/UPDATE with the key      → APIError code PGRST204
#       ("Could not find the 'has_mail_read_scope' column ... in the schema
#        cache" — PostgREST rejects it before any SQL runs, so a retry
#        without the key never half-writes)
#
# supabase-py surfaces both as postgrest.exceptions.APIError; it NEVER
# returns a row that is merely missing the key. So "a missing column reads
# as a missing dict key" — the assumption the first version of this feature
# leaned on — is false, and without this guard an unrun migration 024 would
# 500 every sign-in (via _persist_ms_tokens) and kill every token refresh,
# including the worker beats that stop at the first failing user.
#
# Strategy: optimistic single query, with a process-cached fallback.
#   * Steady state (migration run, i.e. forever after one weekend): the
#     optimistic query simply succeeds — exactly ONE query, zero overhead.
#     This is why the guard is not a catch-per-call double query.
#   * Migration unrun: the first query fails once, we cache "column
#     missing", and every later query goes straight to the column-free
#     shape — again one query per call.
#   * SELF-HEALING: while cached as missing we re-probe at most once per
#     _MAIL_READ_COLUMN_RETRY_SECONDS. When migration 024 lands, every
#     process (API + each Celery worker independently) starts reading the
#     column again within that window — no redeploy, no restart.
#
# A row WITHOUT the key is semantically safe everywhere by design: all
# readers use `.get("has_mail_read_scope") is not False`, i.e. absent ⇒
# True ⇒ "user has Mail.Read" — correct for every pre-024 row, because the
# column can only be missing before the split is allowed to be flipped on.
#
# Concurrency note: the state dict is shared across threads without a lock
# on purpose — a race costs at worst one redundant probe query, never a
# wrong answer.

_MAIL_READ_COLUMN = "has_mail_read_scope"
_MAIL_READ_COLUMN_RETRY_SECONDS = 300.0

_mail_read_column_state = {
    "missing": False,  # believed absent (migration 024 not run yet)
    "retry_at": 0.0,   # monotonic deadline after which we probe again
}


def is_missing_mail_read_column(err: APIError) -> bool:
    """True only for THE error that means migration 024 has not run.

    Deliberately narrow — code AND column name must both match. Any other
    APIError (RLS denial, some other missing column, malformed query) is a
    real bug and must keep propagating exactly as it does today.
    """
    code = getattr(err, "code", None)
    message = getattr(err, "message", None) or ""
    return code in ("42703", "PGRST204") and _MAIL_READ_COLUMN in message


def mail_read_column_attemptable() -> bool:
    """Should the next user_tokens query include has_mail_read_scope?"""
    if not _mail_read_column_state["missing"]:
        return True
    return time.monotonic() >= _mail_read_column_state["retry_at"]


def mark_mail_read_column_missing() -> None:
    _mail_read_column_state["missing"] = True
    _mail_read_column_state["retry_at"] = (
        time.monotonic() + _MAIL_READ_COLUMN_RETRY_SECONDS
    )
    logger.warning(
        "user_tokens.%s does not exist yet (migration 024 unrun) — querying "
        "without it and re-probing in %ss",
        _MAIL_READ_COLUMN,
        int(_MAIL_READ_COLUMN_RETRY_SECONDS),
    )


def mark_mail_read_column_present() -> None:
    if _mail_read_column_state["missing"]:
        # WARNING, not INFO, deliberately: the backend configures no root
        # logger, so the default level is WARNING and every logger.info in
        # this codebase is silently dropped. On 2026-08-06 Ali ran migration
        # 024, the "unrun" warnings correctly stopped, and this confirmation
        # never appeared — leaving the absence of a message as the only
        # evidence the fix had healed. A once-per-process state transition is
        # not noise; make it visible.
        logger.warning(
            "user_tokens.%s is now queryable — migration 024 has run",
            _MAIL_READ_COLUMN,
        )
    _mail_read_column_state["missing"] = False
    _mail_read_column_state["retry_at"] = 0.0


def reset_mail_read_column_state() -> None:
    """Test hook: forget everything learned about the column."""
    _mail_read_column_state["missing"] = False
    _mail_read_column_state["retry_at"] = 0.0


def select_user_tokens(db, user_id: str, base_columns: str):
    """SELECT one user's user_tokens row, adding has_mail_read_scope only
    when the column is believed to exist.

    On the fallback path the returned row simply lacks the key, which every
    reader already treats as True ("has Mail.Read") — the correct value for
    any row that can exist before migration 024.
    """
    if mail_read_column_attemptable():
        try:
            result = (
                db.table("user_tokens")
                .select(f"{base_columns}, {_MAIL_READ_COLUMN}")
                .eq("user_id", user_id)
                .execute()
            )
            mark_mail_read_column_present()
            return result
        except APIError as err:
            if not is_missing_mail_read_column(err):
                raise
            mark_mail_read_column_missing()
    return (
        db.table("user_tokens")
        .select(base_columns)
        .eq("user_id", user_id)
        .execute()
    )


def user_has_mail_read_scope(user_id: str) -> bool:
    """Has this user consented to Mail.Read?

    True for everyone who signed in while it was part of the first-sign-in
    ask, and for anyone who has since opted into reply detection. False only
    for users created after the split who have not upgraded.

    Every failure mode returns True — no row, no column (migration 024
    unrun), a DB hiccup. That is the safe direction: a wrong True merely
    means we don't offer an upgrade prompt, while a wrong False would nag
    established users to re-consent to something they already granted.
    """
    try:
        # Routed through the column guard: with migration 024 unrun this
        # returns rows without the key (⇒ True below) instead of leaning on
        # the except-arm — the fallback is a decision, not an accident.
        result = select_user_tokens(get_db(), user_id, "user_id")
        if not result.data:
            return True
        return result.data[0].get("has_mail_read_scope") is not False
    except Exception:  # noqa: BLE001
        logger.warning("mail-read scope lookup failed for %s", user_id, exc_info=True)
        return True


def get_fresh_access_token(user_id: str) -> str | None:
    """
    Return a valid Microsoft access token for the given user.

    Strategy:
    1. Return stored access_token if it's still valid (verified via /me call)
    2. Otherwise refresh using stored refresh_token + client_secret
    3. Return None if neither works (user needs to re-login)
    """
    db = get_db()
    # Column-guarded select: with migration 024 unrun the row comes back
    # WITHOUT has_mail_read_scope instead of the query raising 42703 —
    # which used to kill this function for every caller, including the
    # worker beats that die at the first failing user. The missing key
    # then reads as True below, which is correct for every pre-024 row.
    result = select_user_tokens(
        db, user_id, "access_token, refresh_token, has_onedrive_scope"
    )
    if not result.data:
        return None

    row = result.data[0]
    # Refresh-token requests must scope-match the user's prior consent.
    # `has_onedrive_scope` is set on the user_tokens row whenever the
    # user successfully completes an /auth/login?include_onedrive=true
    # flow. If we ask for OneDrive scopes but the user only granted
    # Mail, Microsoft returns AADSTS65001 and the entire refresh fails
    # — knocking the user out of all background sends.
    #
    # Mail.Read now works the same way, and the direction of the default
    # matters: `.get(...) is not False` treats BOTH a True flag and a
    # MISSING key as "has it". Missing happens in exactly two harmless
    # cases — the column not yet added (migration 024 unrun) and any row
    # predating it — and in both, the user really does have Mail.Read from
    # the old first-sign-in ask. Defaulting the other way would silently
    # narrow every established user's token and kill reply detection for
    # the entire base the moment this deploys.
    refresh_scopes = (
        MS_GRAPH_SCOPES
        if row.get("has_mail_read_scope") is not False
        else MS_GRAPH_FIRST_SIGNIN_SCOPES
    )
    if row.get("has_onedrive_scope"):
        refresh_scopes = f"{refresh_scopes} {MS_GRAPH_ONEDRIVE_SCOPES}"

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
        "scope": refresh_scopes,
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
