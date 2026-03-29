"""
OutMass — Tracking Router
GET  /t/{contact_id}          → open tracking pixel
GET  /c/{contact_id}          → click tracking redirect
POST /unsubscribe/{contact_id} → unsubscribe
"""

import base64

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import RedirectResponse, Response

from database import get_db
from models import campaign as campaign_model
from models import contact as contact_model

router = APIRouter(tags=["tracking"])

# 1x1 transparent GIF (43 bytes)
TRANSPARENT_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


def _record_event(contact_id: str, campaign_id: str, event_type: str):
    """Insert an event row in background."""
    get_db().table("events").insert(
        {
            "contact_id": contact_id,
            "campaign_id": campaign_id,
            "event_type": event_type,
            "metadata": {},
        }
    ).execute()


@router.get("/t/{contact_id}")
async def track_open(contact_id: str, background_tasks: BackgroundTasks):
    """Return 1x1 transparent GIF and record open event."""
    contact = contact_model.get_contact(contact_id)

    if contact:
        background_tasks.add_task(contact_model.mark_opened, contact_id)
        background_tasks.add_task(
            campaign_model.increment_stat,
            contact["campaign_id"],
            "open_count",
        )
        background_tasks.add_task(
            _record_event,
            contact_id,
            contact["campaign_id"],
            "open",
        )

    return Response(
        content=TRANSPARENT_GIF,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@router.get("/c/{contact_id}")
async def track_click(
    contact_id: str,
    background_tasks: BackgroundTasks,
    url: str = Query(..., description="Original URL to redirect to"),
):
    """Record click event and 302 redirect to original URL."""
    # C-03: Validate URL scheme to prevent open redirect
    if not url.startswith("https://") and not url.startswith("http://"):
        raise HTTPException(status_code=400, detail="Invalid redirect URL")

    contact = contact_model.get_contact(contact_id)

    if contact:
        background_tasks.add_task(contact_model.mark_clicked, contact_id)
        background_tasks.add_task(
            campaign_model.increment_stat,
            contact["campaign_id"],
            "click_count",
        )
        background_tasks.add_task(
            _record_event,
            contact_id,
            contact["campaign_id"],
            "click",
        )

    return RedirectResponse(url=url, status_code=302)


@router.post("/unsubscribe/{contact_id}")
async def unsubscribe(contact_id: str):
    """Mark contact as unsubscribed and add to suppression list."""
    contact = contact_model.get_contact(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact_model.mark_unsubscribed(contact_id)

    # Get campaign to find user_id
    campaign = campaign_model.get_campaign(contact["campaign_id"])
    if campaign:
        get_db().table("suppression_list").insert(
            {
                "user_id": campaign["user_id"],
                "email": contact["email"],
                "reason": "user_unsubscribed",
            }
        ).execute()

    return Response(
        content="""<!DOCTYPE html>
<html>
<head><title>OutMass — Abonelikten Cikildi</title></head>
<body style="font-family:'Segoe UI',sans-serif;text-align:center;padding:60px;background:#faf9f8;">
  <div style="max-width:400px;margin:0 auto;background:#fff;padding:40px;border-radius:8px;
              box-shadow:0 2px 8px rgba(0,0,0,0.1);">
    <div style="width:48px;height:48px;border-radius:50%;background:#107c10;color:#fff;
                font-size:24px;line-height:48px;margin:0 auto 16px;">&#10003;</div>
    <h2 style="color:#323130;margin-bottom:8px;">Basariyla Cikildi</h2>
    <p style="color:#605e5c;">Bu listeden aboneliginiz iptal edildi. Artik email almayacaksiniz.</p>
  </div>
  <p style="margin-top:24px;font-size:12px;color:#a19f9d;">OutMass</p>
</body>
</html>""",
        media_type="text/html",
    )


@router.get("/unsubscribe/{contact_id}")
async def unsubscribe_page(contact_id: str):
    """Simple HTML unsubscribe confirmation page."""
    return Response(
        content="""<!DOCTYPE html>
<html>
<head><title>OutMass — Abonelikten Cik</title></head>
<body style="font-family:'Segoe UI',sans-serif;text-align:center;padding:60px;background:#faf9f8;">
  <div style="max-width:400px;margin:0 auto;background:#fff;padding:40px;border-radius:8px;
              box-shadow:0 2px 8px rgba(0,0,0,0.1);">
    <h2 style="color:#323130;margin-bottom:12px;">Abonelikten Cik</h2>
    <p style="color:#605e5c;margin-bottom:24px;">
      Bu listeden cikmak istediginizi onayliyor musunuz?
    </p>
    <form method="POST">
      <button type="submit"
        style="background:#d13438;color:#fff;border:none;padding:12px 24px;
               font-size:14px;border-radius:4px;cursor:pointer;font-family:inherit;">
        Evet, Abonelikten Cik
      </button>
    </form>
  </div>
  <p style="margin-top:24px;font-size:12px;color:#a19f9d;">OutMass</p>
</body>
</html>""",
        media_type="text/html",
    )
