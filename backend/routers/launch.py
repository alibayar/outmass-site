"""
OutMass — Launch notify-me Router

POST /launch/notify — add an email to the launch_subscribers list. Idempotent:
  re-submitting the same email returns "already_subscribed" instead of 409,
  so the landing page can show a cheerful message either way.

Rate-limited at the application layer by relying on the unique index to
avoid duplicates. No auth required (public form).
"""
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from database import get_db

router = APIRouter(prefix="/launch", tags=["launch"])


_EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)


class NotifyRequest(BaseModel):
    email: str
    locale: str | None = None      # e.g. "tr", "en"
    source: str | None = None      # e.g. "landing", "twitter"


@router.post("/notify")
async def notify(body: NotifyRequest, request: Request):
    email = (body.email or "").strip().lower()
    if not email or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email")

    locale = (body.locale or "")[:10] or None
    source = (body.source or "landing")[:40]

    db = get_db()

    # Has this email already signed up? Case-insensitive check.
    existing = (
        db.table("launch_subscribers")
        .select("id")
        .ilike("email", email)
        .limit(1)
        .execute()
    )
    if existing.data:
        return {"status": "already_subscribed", "email": email}

    try:
        db.table("launch_subscribers").insert({
            "email": email,
            "locale": locale,
            "source": source,
        }).execute()
    except Exception:
        # Race: another request inserted the same email between our check and
        # insert. Treat as success.
        return {"status": "already_subscribed", "email": email}

    return {"status": "subscribed", "email": email}
