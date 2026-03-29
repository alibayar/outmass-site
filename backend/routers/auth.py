"""
OutMass — Auth Router
POST /auth/microsoft  → verify MS token, upsert user, return JWT
GET  /auth/me          → current user info
"""

from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from jose import jwt
from pydantic import BaseModel

from config import (
    GRAPH_API_BASE,
    JWT_ALGORITHM,
    JWT_EXPIRATION_HOURS,
    JWT_SECRET,
)
from models import user as user_model

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


@router.post("/microsoft", response_model=AuthResponse)
async def microsoft_auth(body: MicrosoftAuthRequest):
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

    # Check monthly reset
    _check_monthly_reset(user)

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
                    "month_reset_date": today.isoformat(),
                }
            ).eq("id", user["id"]).execute()
            user["emails_sent_this_month"] = 0
