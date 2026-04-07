"""
OutMass — FastAPI Application
"""

import logging
import traceback

import posthog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import CORS_ORIGINS, POSTHOG_API_KEY, POSTHOG_HOST
from routers import ai, auth, billing, campaigns, settings, templates, tracking

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


# ── Health Check ──
@app.get("/")
async def health_check():
    return {"status": "ok", "version": "0.1.0", "service": "outmass-api"}
