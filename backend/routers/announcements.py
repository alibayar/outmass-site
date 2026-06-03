"""
OutMass — Announcements Router
GET  /announcements              → list announcements visible to the user
POST /announcements/{id}/read    → mark read
POST /announcements/{id}/dismiss → dismiss (hide permanently for this user)
"""

from fastapi import APIRouter, Depends, HTTPException

from models import announcement as ann
from routers.auth import get_current_user

router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("")
async def list_announcements(user: dict = Depends(get_current_user)):
    items = ann.get_user_announcements(user["id"])
    return {"announcements": items, "count": len(items)}


@router.post("/{announcement_id}/read")
async def mark_read(announcement_id: str, user: dict = Depends(get_current_user)):
    if not ann.mark_read(announcement_id, user["id"]):
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"status": "read"}


@router.post("/{announcement_id}/dismiss")
async def dismiss(announcement_id: str, user: dict = Depends(get_current_user)):
    if not ann.mark_dismissed(announcement_id, user["id"]):
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"status": "dismissed"}
