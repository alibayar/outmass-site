"""
OutMass — FastAPI Application
"""

import logging
import traceback

import httpx
import posthog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import (
    CORS_ORIGINS,
    MAILERSEND_API_KEY,
    MAILERSEND_FROM_EMAIL,
    MAILERSEND_FROM_NAME,
    MAILERSEND_TO_EMAIL,
    POSTHOG_API_KEY,
    POSTHOG_HOST,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from routers import account, ai, auth, billing, campaigns, launch, onedrive, settings, templates, tracking

logger = logging.getLogger(__name__)

# ── PostHog Error Tracking ──
if POSTHOG_API_KEY:
    posthog.api_key = POSTHOG_API_KEY
    posthog.host = POSTHOG_HOST

app = FastAPI(
    title="OutMass API",
    version="0.1.0",
    description="Mass email campaign backend for OutMass Chrome Extension",
)


# ── Global Exception Handler → PostHog ──
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and send to PostHog."""
    if POSTHOG_API_KEY:
        posthog.capture(
            distinct_id="backend-server",
            event="$exception",
            properties={
                "$exception_message": str(exc),
                "$exception_type": type(exc).__name__,
                "$exception_stack_trace_raw": traceback.format_exc(),
                "endpoint": str(request.url.path),
                "method": request.method,
            },
        )
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Security Headers ──
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

# ── Routers ──
app.include_router(auth.router)
app.include_router(campaigns.router)
app.include_router(tracking.router)
app.include_router(billing.router)
app.include_router(templates.router)
app.include_router(ai.router)
app.include_router(settings.router)
app.include_router(launch.router)
app.include_router(account.router)
app.include_router(onedrive.router)


# ── Extension Error Reporting ──
class ClientErrorReport(BaseModel):
    message: str
    source: str = "extension"
    stack: str = ""
    context: dict = {}


@app.post("/api/error-report")
async def report_client_error(body: ClientErrorReport):
    """Receive error reports from the Chrome extension."""
    if POSTHOG_API_KEY:
        posthog.capture(
            distinct_id="extension-client",
            event="$exception",
            properties={
                "$exception_message": body.message,
                "$exception_type": "ClientError",
                "$exception_stack_trace_raw": body.stack,
                "source": body.source,
                "context": body.context,
            },
        )
    return {"status": "received"}


# ── User Feedback ──
class UserFeedback(BaseModel):
    message: str
    email: str = ""
    context: dict = {}


def _send_feedback_telegram(message: str, email: str) -> None:
    """Best-effort Telegram alert. Never raises."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    text = (
        "💬 OutMass Feedback\n\n"
        f"From: {email or 'anonymous'}\n\n"
        f"{message[:1500]}"
    )
    try:
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": "true",
            },
            timeout=5.0,
        )
    except Exception as e:
        logger.warning("Feedback Telegram dispatch failed: %s", e)


def _send_feedback_email(message: str, email: str, context: dict) -> None:
    """Best-effort MailerSend email. Never raises. Sets Reply-To to user's email."""
    if not MAILERSEND_API_KEY:
        return
    subject = f"[Feedback] {(email or 'Anonymous user')[:60]}"
    safe_msg = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_email = (email or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = (
        "<h2 style='font-family:sans-serif;'>OutMass Feedback</h2>"
        f"<p><b>From:</b> {safe_email or 'anonymous'}</p>"
        f"<p style='white-space:pre-wrap;background:#f5f5f5;padding:12px;border-radius:6px;'>"
        f"{safe_msg[:2000]}</p>"
        f"<p style='color:#888;font-size:12px;'>Source: extension &middot; "
        f"UA: {str(context.get('userAgent', 'n/a'))[:120]}</p>"
    )
    payload = {
        "from": {
            "email": MAILERSEND_FROM_EMAIL,
            "name": MAILERSEND_FROM_NAME,
        },
        "to": [{"email": MAILERSEND_TO_EMAIL}],
        "subject": subject,
        "html": html,
    }
    if email:
        payload["reply_to"] = {"email": email}
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
    except Exception as e:
        logger.warning("Feedback MailerSend dispatch failed: %s", e)


@app.post("/api/feedback")
async def submit_feedback(body: UserFeedback):
    """Receive user feedback/bug reports from the extension.
    Dispatches to PostHog (archive), Telegram (instant alert), and Resend (email)."""
    if not body.message.strip():
        return {"status": "empty"}

    # 1. PostHog archive
    if POSTHOG_API_KEY:
        posthog.capture(
            distinct_id=body.email or "anonymous-user",
            event="user_feedback",
            properties={
                "message": body.message[:1000],
                "email": body.email,
                "source": "extension",
                **body.context,
            },
        )

    # 2. Telegram (instant)
    _send_feedback_telegram(body.message, body.email)

    # 3. Email via Resend (with Reply-To = user's email so we can reply directly)
    _send_feedback_email(body.message, body.email, body.context or {})

    logger.info("User feedback from %s: %s", body.email or "anonymous", body.message[:200])
    return {"status": "received"}


# ── Uninstall Feedback ──
#
# Chrome opens docs/uninstall.html after the user removes the extension.
# That page lets them submit an optional reason + free-form note. We want
# this data to (a) learn why people churn and (b) flag them in analytics
# so we can correlate paid-but-uninstalled → chargeback risk later.
#
# Anonymous by design — the uninstalled extension can no longer send a
# JWT, so we can't identify the user. That's OK; reason distribution is
# valuable on its own.


class UninstallFeedback(BaseModel):
    reason: str | None = None
    details: str | None = None
    user_agent: str | None = None


@app.post("/api/uninstall-feedback")
async def uninstall_feedback(body: UninstallFeedback):
    reason = (body.reason or "").strip()[:40]
    details = (body.details or "").strip()[:1000]
    ua = (body.user_agent or "").strip()[:200]

    # Silently accept empty submissions — the UI already blocks totally
    # blank ones, but we'd rather log a no-op than 400 a churning user.
    if not reason and not details:
        return {"status": "empty"}

    if POSTHOG_API_KEY:
        posthog.capture(
            distinct_id="uninstalled-anonymous",
            event="extension_uninstall",
            properties={
                "reason": reason,
                "details": details[:500],
                "user_agent": ua,
            },
        )

    # Telegram ping so we see churn in real time during early days.
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        text = (
            "👋 OutMass uninstall feedback\n\n"
            f"Reason: {reason or '(none)'}\n"
            f"Details: {details or '(none)'}"
        )
        try:
            httpx.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": text},
                timeout=5.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Uninstall Telegram dispatch failed: %s", e)

    logger.info("Uninstall feedback: reason=%s details=%s", reason, details[:200])
    return {"status": "received"}


# ── Health Check ──
@app.get("/")
async def health_check():
    return {"status": "ok", "version": "0.1.0", "service": "outmass-api"}
