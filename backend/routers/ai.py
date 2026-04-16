"""
OutMass — AI Router
POST /ai/generate-email   → Generate email content using Claude Haiku
Pro plan only.
"""

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import ANTHROPIC_API_KEY, AI_GENERATION_MONTHLY_LIMIT
from database import get_db
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


class GenerateEmailRequest(BaseModel):
    prompt: str  # e.g. "Write a cold outreach email for a SaaS product"
    tone: str = "professional"  # professional, friendly, formal, casual
    language: str = "en"  # en, tr, de, fr, es, ru, ar, hi, zh, ja
    sender_name: str = ""
    sender_position: str = ""
    sender_company: str = ""


_LANG_NAMES = {
    "en": "English",
    "tr": "Turkish",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "ru": "Russian",
    "ar": "Arabic",
    "hi": "Hindi",
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
}


SYSTEM_PROMPT = """You are an expert email copywriter. Generate a marketing/outreach email based on the user's description.

Rules:
- Return ONLY valid JSON: {"subject": "...", "body": "..."}
- The body should be HTML-formatted (use <p>, <br/>, <strong> tags)
- Include merge placeholders where appropriate: {{firstName}}, {{lastName}}, {{company}}, {{position}} for recipients and {{senderName}}, {{senderPosition}}, {{senderCompany}} for the sender
- Keep the email concise and engaging
- Match the requested tone and language
- Do NOT include greetings like "Dear" - start with the actual content after a simple "Merhaba {{firstName}}," or "Hi {{firstName}},"
- End with a clear call-to-action
- Do NOT wrap the JSON in markdown code blocks
"""


@router.post("/generate-email")
async def generate_email(
    body: GenerateEmailRequest,
    user: dict = Depends(get_current_user),
):
    """Generate email content using AI. Pro plan only, rate-limited per month."""
    if user.get("plan", "free") != "pro":
        raise HTTPException(
            status_code=402,
            detail={
                "error": "feature_locked",
                "message": "AI email writer is only available on the Pro plan",
                "required_plan": "pro",
            },
        )

    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="AI service not configured")

    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")

    # ── Monthly AI generation limit check ──
    ai_used = user.get("ai_generations_this_month", 0) or 0
    if ai_used >= AI_GENERATION_MONTHLY_LIMIT:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "ai_limit_reached",
                "message": f"Monthly AI generation limit reached ({AI_GENERATION_MONTHLY_LIMIT}). Resets next month.",
                "used": ai_used,
                "limit": AI_GENERATION_MONTHLY_LIMIT,
            },
        )

    lang_name = _LANG_NAMES.get(body.language, "English")
    lang_hint = f"Write in {lang_name}."
    tone_hint = f"Tone: {body.tone}."

    sender_hint = ""
    if body.sender_name or body.sender_company or body.sender_position:
        parts = []
        if body.sender_name:
            parts.append(f"Name: {body.sender_name}")
        if body.sender_position:
            parts.append(f"Position: {body.sender_position}")
        if body.sender_company:
            parts.append(f"Company: {body.sender_company}")
        sender_hint = "\nSender info: " + ", ".join(parts) + ". Use {{senderName}}, {{senderPosition}}, {{senderCompany}} placeholders for sender fields in the signature."

    user_message = f"{body.prompt}\n\n{lang_hint} {tone_hint}{sender_hint}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 1000,
                    "system": SYSTEM_PROMPT,
                    "messages": [
                        {"role": "user", "content": user_message}
                    ],
                },
            )

        if resp.status_code != 200:
            logger.error("Claude API error: %s %s", resp.status_code, resp.text)
            raise HTTPException(status_code=502, detail="AI service error")

        data = resp.json()
        content = data["content"][0]["text"]

        try:
            result = json.loads(content, strict=False)
        except (json.JSONDecodeError, ValueError):
            result = {"subject": "", "body": content}

        # Increment AI generation counter (best-effort)
        try:
            get_db().table("users").update(
                {"ai_generations_this_month": ai_used + 1}
            ).eq("id", user["id"]).execute()
        except Exception as e:
            logger.warning("Failed to increment ai_generations_this_month: %s", e)

        return {
            "subject": result.get("subject", ""),
            "body": result.get("body", ""),
            "ai_used": ai_used + 1,
            "ai_limit": AI_GENERATION_MONTHLY_LIMIT,
        }

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="AI service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI generation error: %s", e)
        raise HTTPException(status_code=500, detail="AI generation failed")
