"""
OutMass — Templates Router
POST   /templates           → save template
GET    /templates           → list templates
DELETE /templates/{id}      → delete template
Requires Standard+ plan.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from models import template as template_model
from routers.auth import get_current_user

router = APIRouter(prefix="/templates", tags=["templates"])


class CreateTemplateRequest(BaseModel):
    name: str
    subject: str
    body: str


def _require_standard_plus(user: dict):
    plan = user.get("plan", "free")
    if plan == "free":
        raise HTTPException(
            status_code=402,
            detail={
                "error": "feature_locked",
                "message": "Email sablonlari Standard ve Pro planlarda kullanilabilir",
                "required_plan": "standard",
            },
        )


@router.post("")
async def create_template(
    body: CreateTemplateRequest,
    user: dict = Depends(get_current_user),
):
    _require_standard_plus(user)

    template = template_model.create_template(
        user_id=user["id"],
        name=body.name,
        subject=body.subject,
        body=body.body,
    )
    return {"template_id": template["id"]}


@router.get("")
async def list_templates(user: dict = Depends(get_current_user)):
    _require_standard_plus(user)
    templates = template_model.list_templates(user["id"])
    return {"templates": templates}


@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    user: dict = Depends(get_current_user),
):
    _require_standard_plus(user)
    template_model.delete_template(template_id, user["id"])
    return {"status": "deleted"}
