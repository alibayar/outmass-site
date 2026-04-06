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

from config import ANTHROPIC_API_KEY
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


class GenerateEmailRequest(BaseModel):
    prompt: str  # e.g. "Write a cold outreach email for a SaaS product"
    tone: str = "professional"  # professional, friendly, formal, casual
    language: str = "tr"  # tr or en


SYSTEM_PROMPT = """You are an expert email copywriter. Generate a marketing/outreach email based on the user's description.

Rules:
- Return ONLY valid JSON: {"subject": "...", "body": "..."}
- The body should be HTML-formatted (use <p>, <br/>, <strong> tags)
- Include merge placeholders where appropriate: {{firstName}}, {{lastName}}, {{company}}, {{position}}
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
    """Generate email content using AI. Pro plan only."""
    if user.get("plan", "free") != "pro":
        raise HTTPException(
            status_code=402,
            detail={
                "error": "feature_locked",
                "message": "AI email yazici sadece Pro planda kullanilabilir",
                "required_plan": "pro",
            },
        )

    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="AI service not configured")

    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")

    lang_hint = "Write in Turkish." if body.language == "tr" else "Write in English."
    tone_hint = f"Tone: {body.tone}."

    user_message = f"{body.prompt}\n\n{lang_hint} {tone_hint}"

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

        return {
            "subject": result.get("subject", ""),
            "body": result.get("body", ""),
        }

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="AI service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("AI generation error: %s", e)
        raise HTTPException(status_code=500, detail="AI generation failed")
