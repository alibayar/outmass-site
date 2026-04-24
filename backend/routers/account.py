"""
OutMass — Account Router

Currently a single endpoint: POST /account/delete. Lives separately
from auth (which is about sessions) and billing (which is about Stripe)
because account lifecycle is its own concern — more endpoints may land
here later (export, rename, etc.).
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from config import (
    BACKEND_URL,
    MAILERSEND_API_KEY,
    MAILERSEND_FROM_EMAIL,
    MAILERSEND_FROM_NAME,
)
from models import audit
from models import user_archive
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account", tags=["account"])


class DeleteAccountRequest(BaseModel):
    # Required literal "DELETE" typed by the user in the confirmation
    # modal — guards against accidental clicks.
    confirm_text: str
    # Required checkbox — "I understand this is irreversible".
    understand_irreversible: bool


def _send_deletion_confirmation_email(
    email: str,
    name: str | None,
    archive_id: str,
) -> None:
    """Best-effort confirmation email. Fires AFTER the DB transaction,
    so a mail-delivery failure can't undo a successful deletion.
    """
    if not MAILERSEND_API_KEY or not email:
        return
    greeting = f"Hi {name}," if name else "Hi,"
    html = (
        "<div style='font-family:sans-serif;max-width:540px;margin:auto;color:#323130;'>"
        "<h2 style='color:#0078d4;'>Your OutMass account has been deleted</h2>"
        f"<p>{greeting}</p>"
        "<p>As you requested, your OutMass account and all associated "
        "data (campaigns, contacts, templates, Microsoft authorization, "
        "and settings) have been permanently removed.</p>"
        "<p>Per our Privacy Policy, we retain an anonymised audit "
        "record for 5 years to comply with fraud prevention and legal "
        "obligations. This record contains only a hash of your email "
        "address and aggregate counters &mdash; no content.</p>"
        "<p><b>If you had an active paid subscription</b>, it is "
        "managed separately through Stripe. If you need help cancelling "
        "or getting a refund, reply to this email.</p>"
        f"<p style='color:#888;font-size:11px;'>Archive reference: {archive_id}</p>"
        "<p style='color:#888;font-size:12px;'>&mdash; The OutMass team</p>"
        "</div>"
    )
    payload = {
        "from": {"email": MAILERSEND_FROM_EMAIL, "name": MAILERSEND_FROM_NAME},
        "to": [{"email": email}],
        "subject": "Your OutMass account has been deleted",
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
        logger.warning("Deletion confirmation email failed: %s", e)


@router.post("/delete")
async def delete_account(
    body: DeleteAccountRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Permanently delete the authenticated user's account.

    Three hard guards before the archive+delete transaction:
      1. The typed confirmation text must be exactly "DELETE".
      2. The irreversibility checkbox must be true.
      3. Any paid subscription must already be cancelled — we won't
         silently leave a Stripe charge running after the user and
         their JWT are gone.

    Emits an `account_deleted` audit event BEFORE the cascade delete,
    so the evidence survives (audit_log doesn't cascade).
    """
    if body.confirm_text != "DELETE":
        raise HTTPException(
            status_code=400,
            detail="Please type DELETE to confirm.",
        )
    if not body.understand_irreversible:
        raise HTTPException(
            status_code=400,
            detail="You must acknowledge this action is irreversible.",
        )

    # Guard: active subscription must be cancelled first. We trust the
    # DB flag — we update it on every Stripe webhook, so it's the source
    # of truth for our side. Edge case of a missed webhook manifests as
    # a mildly annoying 409 with a clear fix in the message.
    plan = user.get("plan", "free")
    has_subscription = bool(user.get("stripe_subscription_id"))
    if plan != "free" and has_subscription:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "active_subscription",
                "message": (
                    "Your subscription is still active. Please cancel it "
                    "from Manage Subscription before deleting your account."
                ),
            },
        )

    # Capture what we need for the confirmation email BEFORE delete —
    # the user row is gone once archive_and_delete returns.
    user_email = user.get("email")
    user_name = user.get("name")
    user_id = user["id"]

    # Emit the audit event BEFORE the delete. If the delete transaction
    # fails, we'll still have an "account_deleted attempted" row and
    # can investigate. If it succeeds, the row stays as permanent proof.
    audit.emit(
        audit.EVENT_ACCOUNT_DELETED,
        user_id=user_id,
        email=user_email,
        metadata={
            "reason": user_archive.REASON_USER_REQUESTED,
            "plan_at_deletion": plan,
            "had_subscription": has_subscription,
        },
        request=request,
    )

    try:
        archive_id = user_archive.archive_and_delete(
            user_id=user_id,
            reason=user_archive.REASON_USER_REQUESTED,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Account deletion failed for user %s", user_id)
        raise HTTPException(
            status_code=500,
            detail="Deletion failed. Please email support@getoutmass.com.",
        ) from e

    # Deletion already committed above. Belt-and-braces try/except in
    # case anything inside the email helper somehow escapes its own
    # internal try/except — we never want a mailer failure to surface
    # a 500 AFTER the user's data is already gone.
    try:
        _send_deletion_confirmation_email(user_email, user_name, archive_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("Post-deletion email dispatch bubbled an exception: %s", e)

    logger.info("User %s deleted their account (archive=%s)", user_id, archive_id)
    return {"status": "deleted", "archive_id": archive_id}
