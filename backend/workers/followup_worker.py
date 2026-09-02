"""
OutMass — Follow-up Worker
Celery beat task: processes due follow-ups every hour.
Uses stored refresh tokens to get fresh MS access tokens.
"""

import logging
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx

from config import (
    BACKEND_URL,
    SUPABASE_MAX_ROWS,
    GRAPH_API_BASE,
    OUTBOUND_HTTP_TIMEOUT,
    QUOTA_CHARGE_BATCH,
    RATE_LIMIT_WAIT_SECONDS,
    SEND_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)
from models.ms_token import get_fresh_access_token
from utils.email_body import render_body, unescape_href
from utils.merge_tags import build_merge_context
from workers.celery_app import celery


@celery.task
def process_followups():
    """
    Find scheduled follow-ups that are due, filter contacts by condition,
    and send follow-up emails.
    """
    from database import get_db
    from models import campaign as campaign_model
    from models import contact as contact_model
    from models import followup as followup_model
    from models import user as user_model

    pending = followup_model.get_pending_followups()
    if not pending:
        return {"processed": 0}

    db = get_db()
    total_sent = 0
    # Counted rather than silently skipped: "no follow-ups were due" and
    # "three are waiting for their campaigns to finish" are different states.
    waiting_on_campaign = 0
    waiting_on_delay = 0

    for followup in pending:
        campaign = campaign_model.get_campaign(followup["campaign_id"])
        if not campaign:
            followup_model.update_followup_status(followup["id"], "cancelled")
            continue

        user = user_model.get_by_id(followup["user_id"])
        if not user:
            followup_model.update_followup_status(followup["id"], "cancelled")
            continue

        # ── Is the campaign this follows even finished? ──
        #
        # follow_ups.scheduled_for is stamped now + delay_days at CREATION
        # (models/followup.py), which silently assumed the campaign goes out
        # at once. Scheduled sends and daily caps break that assumption, and
        # the old code then closed the follow-up over the gap: no contact was
        # 'sent' yet, `contacts` came back empty, and the branch below marked
        # the follow-up 'sent' — permanently, having emailed nobody.
        #
        # A live example, 2026-08-28. A customer scheduled 66 recipients for
        # four days later, paced at 5 a day — a fortnight of sending — and
        # turned on a follow-up. Had it been created (a plan gate refused it,
        # which is the only reason this was not the outcome), it would have
        # come due on day three, found zero sent recipients, and closed
        # itself. She would have been told nothing, and the toggle would have
        # read as on.
        #
        # So: wait for the campaign, and measure the delay from when the LAST
        # recipient actually received it. For an ordinary instant send that is
        # the send itself, to the second — this changes nothing there.
        if campaign.get("archived"):
            # Archiving is the user's stop switch everywhere else; a bump for
            # a campaign they have put away is not something to keep waiting
            # to send.
            followup_model.update_followup_status(followup["id"], "cancelled")
            continue

        delay_days = followup.get("delay_days") or 0
        already = followup_model.get_bumped_contact_ids(followup["id"])

        # Everyone whose own delay has elapsed and who has not been bumped.
        contacts = [
            c
            for c in _get_filtered_contacts(
                db, followup["campaign_id"], followup["condition"], delay_days
            )
            if c["id"] not in already
        ]

        if not contacts:
            # Nobody due right now. That is not the same as being finished:
            # the campaign may still be sending, or the people it has already
            # reached may still be inside their delay. Closing over either
            # would end the follow-up for everyone who had not had their turn
            # yet — the exact failure this whole design replaced.
            if _work_remains(db, followup, already):
                waiting_on_campaign += 1
                continue
            followup_model.update_followup_status(followup["id"], "sent")
            continue

        # Get fresh access token (auto-flags user as requires_reauth on permanent failure)
        access_token = get_fresh_access_token(user["id"])
        if not access_token:
            # Permanent failure → cancel the follow-up so it doesn't retry
            # forever. Transient failures leave it pending.
            refreshed_user = user_model.get_by_id(user["id"])
            if refreshed_user and refreshed_user.get("requires_reauth"):
                followup_model.update_followup_status(followup["id"], "failed_auth")
            continue

        # Filter out suppressed emails
        suppressed_result = (
            db.table("suppression_list")
            .select("email")
            .eq("user_id", user["id"])
            .execute()
        )
        suppressed_emails = {r["email"].lower() for r in suppressed_result.data}

        sent_count = 0
        quota_charged = 0
        failed_count = 0
        bumped: set = set()
        skipped: set = set()
        with httpx.Client(timeout=OUTBOUND_HTTP_TIMEOUT) as client:
            for contact in contacts:
                if contact.get("unsubscribed"):
                    skipped.add(contact["id"])
                    continue
                if contact.get("email", "").lower() in suppressed_emails:
                    skipped.add(contact["id"])
                    continue

                try:
                    _send_followup_email(
                        client=client,
                        access_token=access_token,
                        campaign=campaign,
                        followup=followup,
                        contact=contact,
                        sender_info=user,
                        unsubscribe_text=user.get("unsubscribe_text") or "Unsubscribe",
                    )
                    sent_count += 1
                    # Written down before anything else that can fail. The
                    # primary key on (follow_up_id, contact_id) makes a
                    # second bump impossible, but only for a row that got
                    # written — and the cost of losing one is emailing a
                    # person twice from their own mailbox.
                    bumped.add(contact["id"])
                    try:
                        followup_model.record_bump(followup["id"], contact["id"])
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "follow-up %s: bump to contact %s delivered but "
                            "NOT recorded — they may be emailed again",
                            followup["id"], contact["id"],
                        )
                    # Batched: a follow-up run can cover a whole campaign's
                    # list, and a deploy mid-loop would otherwise leave every
                    # delivered follow-up uncharged.
                    if sent_count - quota_charged >= QUOTA_CHARGE_BATCH:
                        # Own try — see scheduled_worker. The enclosing
                        # except counts a failure, and a quota-write error
                        # must not make a delivered follow-up look failed.
                        try:
                            user_model.increment_sent_count(
                                user["id"], sent_count - quota_charged,
                                reason="followup", email=user.get("email"),
                            )
                            quota_charged = sent_count
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "batch quota charge failed; deferring to the "
                                "end-of-loop flush",
                                exc_info=True,
                            )
                except Exception:
                    failed_count += 1

                time.sleep(SEND_DELAY_SECONDS)

        campaign_model.increment_stat(
            followup["campaign_id"], "sent_count", sent_count
        )
        # Wrapped for the same reason as the in-loop batches, one level up:
        # this runs per campaign inside the beat's for-loop, so an unhandled
        # error here would abort every remaining campaign in the run, not
        # just lose one charge.
        if sent_count > quota_charged:
            try:
                user_model.increment_sent_count(
                    user["id"], sent_count - quota_charged,
                    reason="followup", email=user.get("email"),
                )
                quota_charged = sent_count
            except Exception:  # noqa: BLE001
                logger.warning(
                    "final quota flush failed for user %s (%s uncharged sends)",
                    user["id"], sent_count - quota_charged, exc_info=True,
                )
        # Only mark 'sent' if something actually went out (or there was nothing
        # to fail). If EVERY send failed, leave the follow-up pending so the
        # next hourly run retries it instead of falsely reporting 'sent' while
        # the bump reached no one — these recipients already received the
        # original campaign, so their addresses are valid and the failures are
        # transient. A genuinely dead token is caught before this loop
        # (failed_auth), so this cannot retry forever.
        # Closed only when nothing is coming. A run that bumped today's
        # batch of a fortnight-long campaign has done its job and must stay
        # open for the rest; the old unconditional close is what made the
        # first five recipients the only ones ever followed up.
        if sent_count > 0 or failed_count == 0:
            # Only what was actually handled. The first version folded in
            # every candidate, including the ones whose send raised and the
            # ones skipped as unsubscribed or suppressed — so a run that
            # delivered nine and failed one could close the follow-up and
            # drop that tenth person for good, contradicting the comment
            # directly above about retrying transient failures next hour.
            #
            # Deliberate skips DO belong here: a suppressed contact still
            # matches the filtered query, so leaving them out would make
            # _work_remains answer True forever and the follow-up would
            # never close.
            already |= bumped | skipped
            if not _work_remains(db, followup, already):
                followup_model.update_followup_status(followup["id"], "sent")
        total_sent += sent_count

    return {
        "processed": len(pending),
        "sent": total_sent,
        "waiting_on_campaign": waiting_on_campaign,
        "waiting_on_delay": waiting_on_delay,
    }


def _work_remains(db, followup: dict, already: set) -> bool:
    """Is anyone still owed a follow-up, now or later?

    Two ways to be owed one. The campaign may still be sending, so people who
    have not received the original yet cannot possibly be due. And of those
    who have received it, some may still be inside their delay.

    A follow-up is closed only when neither is true, because closing is
    permanent: `status` leaves 'scheduled' and get_pending_followups never
    returns the row again.

    Errs toward staying open. A query that fails here returns True, so the
    next hourly run asks again — an extra pass costs two selects, and a
    wrong close costs every recipient who had not had their turn.
    """
    from models import contact as contact_model

    try:
        if contact_model.get_resumable_contacts(followup["campaign_id"]):
            return True
        pending = _get_filtered_contacts(
            db, followup["campaign_id"], followup["condition"]
        )
        return any(c["id"] not in already for c in pending)
    except Exception:  # noqa: BLE001
        logger.exception(
            "follow-up %s: could not tell whether work remains — staying open",
            followup.get("id"),
        )
        return True


def _get_filtered_contacts(
    db,
    campaign_id: str,
    condition: str,
    delay_days: int | None = None,
) -> list[dict]:
    """Get contacts matching the follow-up condition.

    With `delay_days`, only those whose OWN delay has elapsed — measured from
    contacts.sent_at, the moment that recipient received the original. That
    is what "follow up 3 days later" means to the person who set it, and for
    a campaign paced over a fortnight it is the only reading that is true for
    more than the last batch.

    A recipient who REPLIED is always excluded, regardless of condition:
    bumping someone mid-conversation reads as spam and is the #1 thing
    users expect follow-ups to never do (the site briefly promised it
    before the feature existed — 2026-07-15 claims audit, backlog item
    shipped 2026-07-18). reply_detector stamps contacts.replied_at.
    """
    query = (
        db.table("contacts")
        .select("*")
        .eq("campaign_id", campaign_id)
        .eq("status", "sent")
        .eq("unsubscribed", False)
        .is_("replied_at", "null")
    )

    if condition == "not_opened":
        query = query.is_("opened_at", "null")
    elif condition == "not_clicked":
        query = query.is_("clicked_at", "null")

    if delay_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=delay_days)
        query = query.lte("sent_at", cutoff.isoformat())

    # Same ceiling and the same reason as get_bumped_contact_ids: a short
    # read here means part of the list is never followed up, and nothing
    # would say so.
    result = query.limit(SUPABASE_MAX_ROWS).execute()
    rows = result.data or []
    if len(rows) >= SUPABASE_MAX_ROWS:
        logger.error(
            "campaign %s matched at least %s follow-up candidates — the read "
            "is at its ceiling and may be truncated",
            campaign_id, SUPABASE_MAX_ROWS,
        )
    return rows


def _send_followup_email(
    client: httpx.Client,
    access_token: str,
    campaign: dict,
    followup: dict,
    contact: dict,
    sender_info: dict,
    unsubscribe_text: str = "Unsubscribe",
):
    """Send a single follow-up email via Graph API."""
    merge_ctx = build_merge_context(contact, sender_info)

    merged_subject = _merge(followup["subject"], merge_ctx)
    merged_body = _merge(followup["body"], merge_ctx)
    # Same omission as the scheduled worker had: a follow-up is always sent by
    # a worker, so every follow-up would have arrived as one block.
    merged_body = render_body(followup["body"], merged_body)

    # Tracking pixel
    tracking_pixel = (
        f'<img src="{BACKEND_URL}/t/{contact["id"]}" '
        f'width="1" height="1" style="display:none" alt="" />'
    )

    # Wrap links
    tracked_body = _wrap_links(merged_body, contact["id"])

    # OneDrive attachment chips (use the parent campaign's attachments;
    # follow-ups inherit them so a recipient who didn't open the first
    # email still gets the file references in the bump).
    from utils.email_attachments import render_attachments_footer
    attachments_html = render_attachments_footer(campaign.get("attachments"))

    # Unsubscribe footer — honours the user's Settings → unsubscribe_text
    # override. Escape to prevent HTML injection via a crafted label.
    unsub_url = f"{BACKEND_URL}/unsubscribe/{contact['id']}"
    safe_label = (
        unsubscribe_text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    footer = (
        f'<br/><p style="font-size:11px;color:#999;">'
        f'<a href="{unsub_url}">{safe_label}</a></p>'
    )

    final_html = tracked_body + attachments_html + footer + tracking_pixel

    payload = {
        "message": {
            "subject": merged_subject,
            "body": {"contentType": "HTML", "content": final_html},
            "toRecipients": [
                {"emailAddress": {"address": contact["email"]}}
            ],
        },
        "saveToSentItems": True,
    }

    from utils.graph_retry import post_with_retry
    resp = post_with_retry(
        client,
        f"{GRAPH_API_BASE}/me/sendMail",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
    )

    if resp.status_code not in (200, 202):
        raise Exception(f"Graph API error: HTTP {resp.status_code}")

    try:
        from models import audit
        graph_msg_id = resp.headers.get("Location") or resp.headers.get("x-ms-message-id")
        audit.emit_email_sent(
            user_id=campaign.get("user_id"),
            campaign_id=campaign.get("id"),
            recipient_email=contact.get("email", ""),
            graph_message_id=graph_msg_id,
            status_code=resp.status_code,
        )
    except Exception:  # noqa: BLE001
        pass


def _merge(template_str: str, context: dict) -> str:
    def replacer(match):
        key = match.group(1)
        return str(context.get(key, match.group(0)))

    return re.sub(r"\{\{(\w+)\}\}", replacer, template_str)


def _wrap_links(html: str, contact_id: str) -> str:
    def replacer(match):
        original_url = match.group(1)
        if BACKEND_URL in original_url:
            return match.group(0)
        # html.unescape first: the href sits in HTML, so a two-parameter
        # link is written "?a=1&amp;b=2". Encoding that as-is sends the
        # click to a parameter literally named "amp;b". Plain-text bodies
        # reach this too since autolink started escaping ampersands.
        encoded = urllib.parse.quote(unescape_href(original_url), safe="")
        tracked = f"{BACKEND_URL}/c/{contact_id}?url={encoded}"
        return f'href="{tracked}"'

    return re.sub(r'href="(https?://[^"]+)"', replacer, html)
