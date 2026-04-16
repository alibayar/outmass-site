"""
OutMass — Tracking Router
GET  /t/{contact_id}          → open tracking pixel
GET  /c/{contact_id}          → click tracking redirect
POST /unsubscribe/{contact_id} → unsubscribe
"""

import base64

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

from database import get_db
from models import ab_test as ab_test_model
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
        # Only increment stats on first open (mark_opened checks opened_at is null)
        if not contact.get("opened_at"):
            background_tasks.add_task(contact_model.mark_opened, contact_id)
            background_tasks.add_task(
                campaign_model.increment_stat,
                contact["campaign_id"],
                "open_count",
            )
            # Track A/B variant opens
            if contact.get("ab_variant"):
                ab_test = ab_test_model.get_ab_test(contact["campaign_id"])
                if ab_test:
                    background_tasks.add_task(
                        ab_test_model.increment_opens,
                        ab_test["id"],
                        contact["ab_variant"],
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
    # C-03: Validate URL scheme to prevent open redirect (case-insensitive)
    if not url.lower().startswith(("https://", "http://")):
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


# ── Unsubscribe i18n translations (inline — no frontend JS) ──
# Keys: title, confirmQ, yesBtn, cancelBtn, successTitle, successMsg, undoBtn,
#       undoTitle, undoMsg, restoreBtn, notFound, fromSender
_UNSUB_STRINGS = {
    "en": {
        "title": "Unsubscribe",
        "confirmQ": "Are you sure you want to unsubscribe <b>{email}</b>?",
        "fromSender": "You will no longer receive emails from <b>{sender}</b>.",
        "yesBtn": "Yes, Unsubscribe",
        "cancelBtn": "Cancel",
        "successTitle": "Successfully Unsubscribed",
        "successMsg": "<b>{email}</b> has been removed from <b>{sender}</b>'s mailing list.",
        "undoBtn": "Undo",
        "undoTitle": "Subscription Restored",
        "undoMsg": "Your email <b>{email}</b> has been restored to <b>{sender}</b>'s mailing list.",
        "notFound": "This link is invalid or has expired.",
    },
    "tr": {
        "title": "Abonelikten Cik",
        "confirmQ": "<b>{email}</b> adresinin aboneligini iptal etmek istediginize emin misiniz?",
        "fromSender": "Artik <b>{sender}</b> tarafindan email almayacaksiniz.",
        "yesBtn": "Evet, Abonelikten Cik",
        "cancelBtn": "Vazgec",
        "successTitle": "Abonelik Iptal Edildi",
        "successMsg": "<b>{email}</b> adresi <b>{sender}</b> posta listesinden cikarildi.",
        "undoBtn": "Geri Al",
        "undoTitle": "Abonelik Yeniden Aktif",
        "undoMsg": "<b>{email}</b> adresi <b>{sender}</b> posta listesine geri eklendi.",
        "notFound": "Bu link gecersiz veya suresi dolmus.",
    },
    "de": {
        "title": "Abmelden",
        "confirmQ": "Moechten Sie <b>{email}</b> wirklich abmelden?",
        "fromSender": "Sie erhalten keine E-Mails mehr von <b>{sender}</b>.",
        "yesBtn": "Ja, abmelden",
        "cancelBtn": "Abbrechen",
        "successTitle": "Erfolgreich abgemeldet",
        "successMsg": "<b>{email}</b> wurde aus der Verteilerliste von <b>{sender}</b> entfernt.",
        "undoBtn": "Rueckgaengig",
        "undoTitle": "Abonnement wiederhergestellt",
        "undoMsg": "<b>{email}</b> wurde zur Verteilerliste von <b>{sender}</b> hinzugefuegt.",
        "notFound": "Dieser Link ist ungueltig oder abgelaufen.",
    },
    "fr": {
        "title": "Se desabonner",
        "confirmQ": "Voulez-vous vraiment desabonner <b>{email}</b>?",
        "fromSender": "Vous ne recevrez plus d'e-mails de <b>{sender}</b>.",
        "yesBtn": "Oui, me desabonner",
        "cancelBtn": "Annuler",
        "successTitle": "Desabonnement reussi",
        "successMsg": "<b>{email}</b> a ete retire de la liste de diffusion de <b>{sender}</b>.",
        "undoBtn": "Annuler",
        "undoTitle": "Abonnement retabli",
        "undoMsg": "<b>{email}</b> a ete reajoute a la liste de diffusion de <b>{sender}</b>.",
        "notFound": "Ce lien est invalide ou a expire.",
    },
    "es": {
        "title": "Darse de baja",
        "confirmQ": "Estas seguro de que quieres dar de baja <b>{email}</b>?",
        "fromSender": "Ya no recibiras correos de <b>{sender}</b>.",
        "yesBtn": "Si, darme de baja",
        "cancelBtn": "Cancelar",
        "successTitle": "Baja exitosa",
        "successMsg": "<b>{email}</b> ha sido eliminado de la lista de <b>{sender}</b>.",
        "undoBtn": "Deshacer",
        "undoTitle": "Suscripcion restaurada",
        "undoMsg": "<b>{email}</b> ha sido restaurado en la lista de <b>{sender}</b>.",
        "notFound": "Este enlace no es valido o ha expirado.",
    },
    "ru": {
        "title": "Отписаться",
        "confirmQ": "Вы уверены, что хотите отписаться <b>{email}</b>?",
        "fromSender": "Вы больше не будете получать письма от <b>{sender}</b>.",
        "yesBtn": "Да, отписаться",
        "cancelBtn": "Отмена",
        "successTitle": "Успешно отписались",
        "successMsg": "<b>{email}</b> удален из списка рассылки <b>{sender}</b>.",
        "undoBtn": "Отменить",
        "undoTitle": "Подписка восстановлена",
        "undoMsg": "<b>{email}</b> восстановлен в списке рассылки <b>{sender}</b>.",
        "notFound": "Эта ссылка недействительна или срок ее действия истек.",
    },
    "ar": {
        "title": "إلغاء الاشتراك",
        "confirmQ": "هل أنت متأكد من أنك تريد إلغاء اشتراك <b>{email}</b>؟",
        "fromSender": "لن تتلقى المزيد من رسائل البريد الإلكتروني من <b>{sender}</b>.",
        "yesBtn": "نعم، إلغاء الاشتراك",
        "cancelBtn": "إلغاء",
        "successTitle": "تم إلغاء الاشتراك بنجاح",
        "successMsg": "تمت إزالة <b>{email}</b> من قائمة <b>{sender}</b>.",
        "undoBtn": "تراجع",
        "undoTitle": "تم استعادة الاشتراك",
        "undoMsg": "تمت استعادة <b>{email}</b> إلى قائمة <b>{sender}</b>.",
        "notFound": "هذا الرابط غير صالح أو انتهت صلاحيته.",
    },
    "hi": {
        "title": "सदस्यता रद्द करें",
        "confirmQ": "क्या आप वाकई <b>{email}</b> की सदस्यता रद्द करना चाहते हैं?",
        "fromSender": "अब आपको <b>{sender}</b> से ईमेल नहीं मिलेंगे।",
        "yesBtn": "हाँ, सदस्यता रद्द करें",
        "cancelBtn": "रद्द करें",
        "successTitle": "सदस्यता सफलतापूर्वक रद्द की गई",
        "successMsg": "<b>{email}</b> को <b>{sender}</b> की मेलिंग सूची से हटा दिया गया है।",
        "undoBtn": "पूर्ववत करें",
        "undoTitle": "सदस्यता बहाल",
        "undoMsg": "<b>{email}</b> को <b>{sender}</b> की मेलिंग सूची में बहाल कर दिया गया है।",
        "notFound": "यह लिंक अमान्य है या समाप्त हो गया है।",
    },
    "zh": {
        "title": "取消订阅",
        "confirmQ": "您确定要取消订阅 <b>{email}</b> 吗？",
        "fromSender": "您将不再收到 <b>{sender}</b> 的邮件。",
        "yesBtn": "是的，取消订阅",
        "cancelBtn": "取消",
        "successTitle": "已成功取消订阅",
        "successMsg": "<b>{email}</b> 已从 <b>{sender}</b> 的邮件列表中删除。",
        "undoBtn": "撤消",
        "undoTitle": "订阅已恢复",
        "undoMsg": "<b>{email}</b> 已恢复到 <b>{sender}</b> 的邮件列表中。",
        "notFound": "此链接无效或已过期。",
    },
    "ja": {
        "title": "配信停止",
        "confirmQ": "<b>{email}</b> の配信を停止しますか？",
        "fromSender": "今後 <b>{sender}</b> からメールは届きません。",
        "yesBtn": "はい、配信停止します",
        "cancelBtn": "キャンセル",
        "successTitle": "配信停止が完了しました",
        "successMsg": "<b>{email}</b> は <b>{sender}</b> のメーリングリストから削除されました。",
        "undoBtn": "元に戻す",
        "undoTitle": "配信が復元されました",
        "undoMsg": "<b>{email}</b> は <b>{sender}</b> のメーリングリストに復元されました。",
        "notFound": "このリンクは無効または期限切れです。",
    },
}


def _detect_lang(accept_language: str | None) -> str:
    """Detect language from Accept-Language header, fallback to en."""
    if not accept_language:
        return "en"
    # Parse primary language (e.g. "tr-TR,tr;q=0.9,en;q=0.8" -> "tr")
    first = accept_language.split(",")[0].strip().split("-")[0].lower()
    if first in _UNSUB_STRINGS:
        return first
    return "en"


def _unsub_page(
    title: str,
    body_html: str,
    lang: str = "en",
    is_rtl: bool = False,
) -> Response:
    """Render a standalone unsubscribe page (no JS, self-contained HTML)."""
    dir_attr = 'dir="rtl"' if is_rtl else ""
    html = f"""<!DOCTYPE html>
<html lang="{lang}" {dir_attr}>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OutMass — {title}</title>
<style>
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         margin:0;padding:60px 20px;background:#faf9f8;color:#323130; }}
  .card {{ max-width:460px;margin:0 auto;background:#fff;padding:40px 32px;
           border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,0.08); }}
  h2 {{ margin:0 0 16px;font-size:22px;font-weight:600; }}
  p {{ color:#605e5c;line-height:1.5;margin:0 0 12px; }}
  b {{ color:#323130; }}
  .actions {{ display:flex;gap:10px;margin-top:24px;justify-content:center;flex-wrap:wrap; }}
  button, a.btn {{ display:inline-block;padding:10px 20px;font-size:14px;
                    border-radius:4px;cursor:pointer;font-family:inherit;
                    text-decoration:none;border:none;font-weight:500; }}
  .btn-danger {{ background:#d13438;color:#fff; }}
  .btn-danger:hover {{ background:#a4262c; }}
  .btn-secondary {{ background:#f3f2f1;color:#323130;border:1px solid #c8c6c4; }}
  .btn-secondary:hover {{ background:#edebe9; }}
  .btn-link {{ background:none;color:#0078d4;text-decoration:underline;padding:4px 8px; }}
  .icon {{ width:48px;height:48px;border-radius:50%;margin:0 auto 16px;
           display:flex;align-items:center;justify-content:center;
           font-size:24px;color:#fff; }}
  .icon-success {{ background:#107c10; }}
  .icon-info {{ background:#0078d4; }}
  .footer {{ margin-top:20px;font-size:12px;color:#a19f9d;text-align:center; }}
  .center {{ text-align:center; }}
</style>
</head>
<body>
<div class="card">{body_html}</div>
<p class="footer">OutMass</p>
</body>
</html>"""
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get("/unsubscribe/{contact_id}")
async def unsubscribe_page(
    contact_id: str,
    request: Request,
):
    """Show unsubscribe confirmation page with user's email and sender name."""
    lang = _detect_lang(request.headers.get("accept-language"))
    s = _UNSUB_STRINGS.get(lang, _UNSUB_STRINGS["en"])
    is_rtl = lang == "ar"

    contact = contact_model.get_contact(contact_id)
    if not contact:
        body = f'<h2 class="center">{s["title"]}</h2><p class="center">{s["notFound"]}</p>'
        return _unsub_page(s["title"], body, lang, is_rtl)

    email = contact.get("email", "")
    sender_name = "OutMass"
    campaign = campaign_model.get_campaign(contact.get("campaign_id", ""))
    if campaign:
        user_result = (
            get_db().table("users").select("sender_name, sender_company, name, email")
            .eq("id", campaign["user_id"]).execute()
        )
        if user_result.data:
            u = user_result.data[0]
            sender_name = (
                u.get("sender_company")
                or u.get("sender_name")
                or u.get("name")
                or u.get("email", "OutMass")
            )

    # Already unsubscribed?
    if contact.get("unsubscribed"):
        body = f"""
        <div class="icon icon-info">i</div>
        <h2 class="center">{s["successTitle"]}</h2>
        <p class="center">{s["successMsg"].format(email=email, sender=sender_name)}</p>
        <div class="actions">
          <form method="POST" action="/unsubscribe/{contact_id}/undo" style="margin:0;">
            <button type="submit" class="btn-secondary">{s["undoBtn"]}</button>
          </form>
        </div>
        """
        return _unsub_page(s["title"], body, lang, is_rtl)

    body = f"""
    <h2 class="center">{s["title"]}</h2>
    <p class="center">{s["confirmQ"].format(email=email)}</p>
    <p class="center">{s["fromSender"].format(sender=sender_name)}</p>
    <div class="actions">
      <form method="POST" style="margin:0;">
        <button type="submit" class="btn-danger">{s["yesBtn"]}</button>
      </form>
      <button type="button" class="btn-secondary" onclick="window.close();history.back();">{s["cancelBtn"]}</button>
    </div>
    """
    return _unsub_page(s["title"], body, lang, is_rtl)


@router.post("/unsubscribe/{contact_id}")
async def unsubscribe(contact_id: str, request: Request):
    """Mark contact as unsubscribed, add to suppression list, show success page."""
    lang = _detect_lang(request.headers.get("accept-language"))
    s = _UNSUB_STRINGS.get(lang, _UNSUB_STRINGS["en"])
    is_rtl = lang == "ar"

    contact = contact_model.get_contact(contact_id)
    if not contact:
        body = f'<h2 class="center">{s["title"]}</h2><p class="center">{s["notFound"]}</p>'
        return _unsub_page(s["title"], body, lang, is_rtl)

    contact_model.mark_unsubscribed(contact_id)

    email = contact.get("email", "")
    sender_name = "OutMass"
    campaign = campaign_model.get_campaign(contact["campaign_id"])
    if campaign:
        user_result = (
            get_db().table("users").select("sender_name, sender_company, name, email")
            .eq("id", campaign["user_id"]).execute()
        )
        if user_result.data:
            u = user_result.data[0]
            sender_name = (
                u.get("sender_company")
                or u.get("sender_name")
                or u.get("name")
                or u.get("email", "OutMass")
            )

        # Add to suppression list (skip duplicates)
        existing = (
            get_db()
            .table("suppression_list")
            .select("id")
            .eq("user_id", campaign["user_id"])
            .eq("email", email)
            .execute()
        )
        if not existing.data:
            get_db().table("suppression_list").insert({
                "user_id": campaign["user_id"],
                "email": email,
                "reason": "user_unsubscribed",
            }).execute()

    body = f"""
    <div class="icon icon-success">&#10003;</div>
    <h2 class="center">{s["successTitle"]}</h2>
    <p class="center">{s["successMsg"].format(email=email, sender=sender_name)}</p>
    <div class="actions">
      <form method="POST" action="/unsubscribe/{contact_id}/undo" style="margin:0;">
        <button type="submit" class="btn-link">{s["undoBtn"]}</button>
      </form>
    </div>
    """
    return _unsub_page(s["title"], body, lang, is_rtl)


@router.post("/unsubscribe/{contact_id}/undo")
async def unsubscribe_undo(contact_id: str, request: Request):
    """Reverse an unsubscribe: mark contact as subscribed, remove from suppression list."""
    lang = _detect_lang(request.headers.get("accept-language"))
    s = _UNSUB_STRINGS.get(lang, _UNSUB_STRINGS["en"])
    is_rtl = lang == "ar"

    contact = contact_model.get_contact(contact_id)
    if not contact:
        body = f'<h2 class="center">{s["title"]}</h2><p class="center">{s["notFound"]}</p>'
        return _unsub_page(s["title"], body, lang, is_rtl)

    # Mark as subscribed again
    get_db().table("contacts").update({"unsubscribed": False}).eq("id", contact_id).execute()

    email = contact.get("email", "")
    sender_name = "OutMass"
    campaign = campaign_model.get_campaign(contact["campaign_id"])
    if campaign:
        user_result = (
            get_db().table("users").select("sender_name, sender_company, name, email")
            .eq("id", campaign["user_id"]).execute()
        )
        if user_result.data:
            u = user_result.data[0]
            sender_name = (
                u.get("sender_company")
                or u.get("sender_name")
                or u.get("name")
                or u.get("email", "OutMass")
            )
        # Remove from suppression list (only if entry was from user_unsubscribed reason)
        get_db().table("suppression_list").delete().eq(
            "user_id", campaign["user_id"]
        ).eq("email", email).eq("reason", "user_unsubscribed").execute()

    body = f"""
    <div class="icon icon-info">&#8634;</div>
    <h2 class="center">{s["undoTitle"]}</h2>
    <p class="center">{s["undoMsg"].format(email=email, sender=sender_name)}</p>
    """
    return _unsub_page(s["undoTitle"], body, lang, is_rtl)
