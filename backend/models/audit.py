"""
OutMass — Audit Log Helper

Append-only evidence trail for every user-initiated action. Powers three
things:

1. Legal defense — when a user disputes a send ("I didn't click that"),
   we show them the timestamped audit trail of their actions.
2. Fraud prevention — cross-check signup patterns, catch abuse (same
   email_hash creating multiple accounts).
3. Chargeback dispute — prove the user actually consented + acted.

Design rules:

* **Best-effort.** Audit writes must NEVER break the business action.
  If the DB is down, log a warning and continue. The email still sends.
* **Immutable.** We only INSERT; never UPDATE or DELETE the content
  field. Row-level retention is enforced by a separate cleanup job
  (IP anonymization after 1 year, see migration 011).
* **Minimize PII.** We store the user's email *hash*, never their
  recipients' raw emails — only `recipient_hash` in metadata. This
  survives account deletion without re-introducing personal data.
* **Event-type vocabulary.** Keep the enum tight; new event types
  should be added to `EVENT_*` constants below and documented.
"""

import hashlib
import logging
from typing import Any

from fastapi import Request

from database import get_db

logger = logging.getLogger(__name__)


# ── Event type vocabulary ──
# Adding one? Update the audit_log docs section in migration 011 too.

EVENT_OAUTH_GRANTED = "oauth_granted"
EVENT_LOGIN = "login"
EVENT_CAMPAIGN_CREATED = "campaign_created"
EVENT_CONTACTS_UPLOADED = "contacts_uploaded"
EVENT_SEND_TRIGGERED = "send_triggered"
EVENT_EMAIL_SENT = "email_sent"
EVENT_SCHEDULED_SEND_FIRED = "scheduled_send_fired"
EVENT_FOLLOWUP_CREATED = "followup_created"
EVENT_SETTINGS_CHANGED = "settings_changed"
EVENT_SUBSCRIPTION_STARTED = "subscription_started"
EVENT_SUBSCRIPTION_CANCELED = "subscription_canceled"
EVENT_ACCOUNT_DELETED = "account_deleted"
EVENT_TOKEN_REFRESH_FAILED = "token_refresh_failed"
EVENT_REQUIRES_REAUTH_FLAGGED = "requires_reauth_flagged"


def hash_email(email: str | None) -> str | None:
    """SHA256 of the lowercased, stripped email.

    Used as a stable identifier for audit continuity across account
    deletion. The hash is NOT personal data under GDPR — one-way, no
    practical way to reverse without already knowing the email.
    """
    if not email:
        return None
    normalized = email.lower().strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_bytes(data: bytes | str) -> str:
    """SHA256 of arbitrary content — used for CSV file fingerprints,
    email-body integrity checks, etc."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _extract_request_context(request: Request | None) -> dict[str, Any]:
    """Pull IP + User-Agent from a FastAPI request, if present.

    Railway sits behind a proxy, so `request.client.host` may be the
    proxy's address. Prefer X-Forwarded-For (first hop = real client).
    """
    if request is None:
        return {"ip_address": None, "user_agent": None}

    ip = None
    try:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            # First entry is the original client; subsequent entries are proxies.
            ip = fwd.split(",")[0].strip()
        if not ip and request.client:
            ip = request.client.host
    except Exception:  # noqa: BLE001
        ip = None

    ua = None
    try:
        ua = request.headers.get("user-agent", "")[:500] or None
    except Exception:  # noqa: BLE001
        ua = None

    return {"ip_address": ip, "user_agent": ua}


def emit(
    event_type: str,
    *,
    user_id: str | None = None,
    email: str | None = None,
    metadata: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Insert one audit row. Never raises.

    Call sites:
      >>> from models import audit
      >>> audit.emit(audit.EVENT_LOGIN, user_id=user["id"], email=user["email"], request=req)

    `user_id` can be None (e.g. failed login before we know the user).
    `email` is used to compute email_hash; pass whichever you have.
    `metadata` is a dict of event-specific fields. Keep it small and
    free of raw PII — prefer hashes and counts.
    """
    try:
        ctx = _extract_request_context(request)
        row: dict[str, Any] = {
            "event_type": event_type,
            "metadata": metadata or {},
            "ip_address": ctx["ip_address"],
            "user_agent": ctx["user_agent"],
        }
        if user_id:
            row["user_id"] = user_id
        h = hash_email(email)
        if h:
            row["email_hash"] = h

        get_db().table("audit_log").insert(row).execute()
    except Exception:  # noqa: BLE001 — audit must not kill business logic
        logger.exception(
            "Audit emit failed for event=%s user_id=%s",
            event_type,
            user_id,
        )


def emit_email_sent(
    *,
    user_id: str,
    campaign_id: str,
    recipient_email: str,
    graph_message_id: str | None = None,
    status_code: int | None = None,
) -> None:
    """Specialized helper for per-email send events.

    Called from workers inside the send loop, so it's the hottest audit
    path. Stores recipient_hash (not raw email) so we can answer
    "did OutMass ever send to this address?" without persisting more
    PII than necessary.
    """
    emit(
        EVENT_EMAIL_SENT,
        user_id=user_id,
        metadata={
            "campaign_id": campaign_id,
            "recipient_hash": hash_email(recipient_email),
            "graph_message_id": graph_message_id,
            "status_code": status_code,
        },
    )
