"""
OutMass — Scheduled Campaign Worker + A/B Test Winner Sender
Celery beat tasks:
- processes due scheduled campaigns every 5 minutes
- evaluates A/B test winners and sends remaining contacts every 10 minutes
- proactively checks user token health once per day
"""

import logging
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import httpx

from config import (
    BACKEND_URL,
    FREE_PLAN_MONTHLY_LIMIT,
    GRAPH_API_BASE,
    OUTBOUND_HTTP_TIMEOUT,
    PRO_PLAN_MONTHLY_LIMIT,
    QUOTA_CHARGE_BATCH,
    RATE_LIMIT_WAIT_SECONDS,
    SEND_DELAY_SECONDS,
    STARTER_PLAN_MONTHLY_LIMIT,
)

logger = logging.getLogger(__name__)
from models.ms_token import get_fresh_access_token
from utils.send_classify import _classify_failure
from workers.celery_app import celery


@celery.task
def process_scheduled_campaigns():
    """
    Find scheduled campaigns that are due and send them.
    """
    from database import get_db
    from models import campaign as campaign_model
    from models import contact as contact_model
    from models import user as user_model

    due = campaign_model.get_due_scheduled_campaigns()
    if not due:
        return {"processed": 0}

    db = get_db()
    total_sent = 0

    for campaign in due:
        user = user_model.get_by_id(campaign["user_id"])
        if not user:
            # A deleted user's campaigns are FK-cascaded away, so a missing
            # user here is a transient DB read blip — not a real deletion.
            # Leave the campaign 'scheduled' so the next beat retries instead
            # of permanently 'failed' (which would silently drop it).
            continue

        # Freemium check BEFORE the token refresh: an over-quota campaign would
        # otherwise burn a token refresh every beat. Over-quota is transient —
        # the monthly counter resets — so we keep the campaign 'scheduled' to
        # send after the reset, never permanently 'failed'.
        # Roll the quota period over first: the reset used to run only at
        # login, so a user who scheduled sends and never logged back in would
        # stay blocked on LAST period's counter forever.
        user_model.check_monthly_reset(user)
        sent_this_month = user.get("emails_sent_this_month", 0)
        plan = user.get("plan", "free")
        if plan == "free":
            limit = FREE_PLAN_MONTHLY_LIMIT
        elif plan == "starter":
            limit = STARTER_PLAN_MONTHLY_LIMIT
        else:
            limit = PRO_PLAN_MONTHLY_LIMIT

        remaining = limit - sent_this_month
        if remaining <= 0:
            # Over quota now, but the counter resets monthly — stay scheduled
            # and retry after the reset rather than dropping the campaign.
            continue

        # Get fresh access token (auto-flags user as requires_reauth on permanent failure)
        access_token = get_fresh_access_token(user["id"])
        if not access_token:
            # If the user was flagged requires_reauth by the refresh attempt,
            # the failure is permanent until they re-authorize. Mark the
            # campaign failed_auth so the sidebar surfaces a clear error
            # instead of the scheduled campaign silently looping forever.
            refreshed_user = user_model.get_by_id(user["id"])
            if refreshed_user and refreshed_user.get("requires_reauth"):
                campaign_model.update_campaign(
                    campaign["id"], {"status": "failed_auth"}
                )
            # Transient failures keep the campaign scheduled for retry.
            continue

        pending = contact_model.get_resumable_contacts(campaign["id"])
        if not pending:
            campaign_model.update_campaign(campaign["id"], {"status": "sent"})
            continue

        # Daily cap (multi-day spread): today's batch is at most
        # daily_send_cap contacts; the leftover rolls to tomorrow below.
        daily_cap = campaign.get("daily_send_cap") or 0
        if daily_cap > 0:
            pending = pending[:daily_cap]

        # Quota slice. Remember whether it actually truncated the list: a
        # clean quota-capped batch must NOT close as 'sent' below, or the
        # leftover contacts stay 'pending' inside a campaign that looks
        # finished — invisible to the Resume endpoint AND to the
        # auto-resume beat (which only queries status='partial'). The
        # send-now path had exactly this bug (c1705f2, the 2026-07-20
        # incident); the scheduled path kept it, and here it is worse
        # because no alert is shown at all.
        quota_capped = len(pending) > remaining
        pending = pending[:remaining]

        # Filter suppressed
        suppressed_result = (
            db.table("suppression_list")
            .select("email")
            .eq("user_id", user["id"])
            .execute()
        )
        suppressed_emails = {r["email"].lower() for r in suppressed_result.data}

        # Mark as sending
        campaign_model.update_campaign(campaign["id"], {"status": "sending"})

        sent_count = 0
        quota_charged = 0
        errors = []

        with httpx.Client(timeout=OUTBOUND_HTTP_TIMEOUT) as client:
            for contact in pending:
                if contact.get("unsubscribed"):
                    # The unsubscribed flag already excludes them everywhere.
                    continue
                if contact.get("email", "").lower() in suppressed_emails:
                    # Record the skip, or they stay 'pending' forever and keep
                    # reappearing in resumable sets (see mark_suppressed).
                    # Guarded: this sits outside the per-contact try below, so
                    # an unguarded raise would escape the Celery task, leave
                    # the campaign 'sending', and skip every other campaign due
                    # in this beat. Failing to record is harmless by itself.
                    try:
                        contact_model.mark_suppressed(contact["id"])
                    except Exception:  # noqa: BLE001
                        import logging
                        logging.getLogger(__name__).warning(
                            "Could not mark contact %s suppressed", contact.get("id"),
                            exc_info=True,
                        )
                    continue

                try:
                    result = _send_email(
                        client=client,
                        access_token=access_token,
                        campaign=campaign,
                        contact=contact,
                        unsubscribe_text=user.get("unsubscribe_text") or "Unsubscribe",
                    )
                    if result["success"]:
                        contact_model.mark_sent(contact["id"])
                        campaign_model.increment_stat(campaign["id"], "sent_count")
                        sent_count += 1
                        # Charge the quota in batches as we go, not once
                        # at the end. The end is not guaranteed to arrive: a
                        # Railway deploy or an OOM kills this task mid-loop,
                        # and every recipient already marked 'sent' was then
                        # free — the durable per-contact state said they went
                        # out while the counter said they never did. A
                        # SIGKILL runs no handler, so no except block can fix
                        # it; only having already written the number can.
                        # Same reasoning, and the same constant, as the
                        # send-now path in routers/campaigns.py.
                        if sent_count - quota_charged >= QUOTA_CHARGE_BATCH:
                            # Its own try. This sits inside the per-contact
                            # try whose except marks the contact 'deferred' —
                            # and mark_sent has ALREADY committed by now, so
                            # letting a quota-write failure reach that except
                            # would rewind a delivered recipient and get them
                            # emailed twice. Leaving quota_charged unadvanced
                            # is correct: the end-of-loop flush recharges it.
                            try:
                                user_model.increment_sent_count(
                                    user["id"], sent_count - quota_charged
                                )
                                quota_charged = sent_count
                            except Exception:  # noqa: BLE001
                                logger.warning(
                                    "batch quota charge failed; deferring to "
                                    "the end-of-loop flush",
                                    exc_info=True,
                                )
                    else:
                        contact_model.mark_failed(
                            contact["id"], _classify_failure(result.get("status_code"))
                        )
                        errors.append(contact["email"])
                except Exception:
                    # Network/timeout: transient, retryable on next run.
                    contact_model.mark_failed(contact["id"], "deferred")
                    errors.append(contact["email"])

                time.sleep(SEND_DELAY_SECONDS)

        # Whatever the batches have not covered yet.
        # Wrapped for the same reason as the in-loop batches, one level up:
        # this runs per campaign inside the beat's for-loop, so an unhandled
        # error here would abort every remaining campaign in the run, not
        # just lose one charge.
        if sent_count > quota_charged:
            try:
                user_model.increment_sent_count(
                    user["id"], sent_count - quota_charged
                )
                quota_charged = sent_count
            except Exception:  # noqa: BLE001
                logger.warning(
                    "final quota flush failed for user %s (%s uncharged sends)",
                    user["id"], sent_count - quota_charged, exc_info=True,
                )

        # Daily-cap campaigns: if resumable contacts remain after today's
        # batch, advance the schedule 24h and go back to 'scheduled' — the
        # same beat loop continues tomorrow until the list is exhausted.
        # (Re-query rather than arithmetic: suppression/unsubscribe skips
        # above mean len(pending) isn't a reliable "what's left" signal.)
        if daily_cap > 0:
            still_pending = contact_model.get_resumable_contacts(campaign["id"])
            if still_pending:
                next_run = (
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat()
                campaign_model.update_campaign(
                    campaign["id"],
                    {"status": "scheduled", "scheduled_for": next_run},
                )
                total_sent += sent_count
                continue

        final_status = "sent" if not errors and not quota_capped else "partial"
        campaign_model.update_campaign(campaign["id"], {"status": final_status})
        total_sent += sent_count

    return {"processed": len(due), "sent": total_sent}


def _send_email(
    client: httpx.Client,
    access_token: str,
    campaign: dict,
    contact: dict,
    unsubscribe_text: str = "Unsubscribe",
) -> dict:
    """Send a single email via Graph API.

    `unsubscribe_text` must be the user's configured label (from the
    Settings tab). Defaulting to the English "Unsubscribe" means callers
    that forget to pass it no longer silently ship the Turkish default
    to every recipient.
    """
    merge_ctx = {
        "firstName": contact.get("first_name", ""),
        "lastName": contact.get("last_name", ""),
        "email": contact.get("email", ""),
        "company": contact.get("company", ""),
        "position": contact.get("position", ""),
    }
    custom = contact.get("custom_fields") or {}
    merge_ctx.update(custom)

    merged_subject = _merge(campaign["subject"], merge_ctx)
    merged_body = _merge(campaign["body"], merge_ctx)

    tracking_pixel = (
        f'<img src="{BACKEND_URL}/t/{contact["id"]}" '
        f'width="1" height="1" style="display:none" alt="" />'
    )
    tracked_body = _wrap_links(merged_body, contact["id"])

    # OneDrive attachment chips (rendered above unsubscribe). Shared
    # helper so all send paths produce identical markup.
    from utils.email_attachments import render_attachments_footer
    attachments_html = render_attachments_footer(campaign.get("attachments"))

    unsub_url = f"{BACKEND_URL}/unsubscribe/{contact['id']}"
    # Escape user-controlled label so a malicious value can't break out
    # of the <a> tag context. Escape ampersands, angle brackets, quotes.
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

    # Bounded retries on 5xx + transient network errors (and 429,
    # honouring Retry-After). 3 attempts total before giving up.
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

    if resp.status_code in (200, 202):
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
        return {"success": True}

    error_detail = ""
    try:
        error_detail = resp.json().get("error", {}).get("message", "")
    except Exception:
        error_detail = f"HTTP {resp.status_code}"

    return {"success": False, "error": error_detail, "status_code": resp.status_code}


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
        encoded = urllib.parse.quote(original_url, safe="")
        tracked = f"{BACKEND_URL}/c/{contact_id}?url={encoded}"
        return f'href="{tracked}"'
    return re.sub(r'href="(https?://[^"]+)"', replacer, html)


# ── A/B Test Winner Evaluation ──

MIN_AB_WAIT_HOURS = 4  # Wait at least 4 hours before evaluating


@celery.task
def evaluate_ab_tests():
    """
    Evaluate A/B tests that are awaiting a winner.
    Compare opens_a vs opens_b, pick the winner, send remaining contacts.
    """
    from datetime import datetime, timedelta, timezone

    from database import get_db
    from models import ab_test as ab_test_model
    from models import campaign as campaign_model
    from models import contact as contact_model
    from models import user as user_model

    db = get_db()

    # Find AB tests awaiting winner
    result = (
        db.table("ab_tests")
        .select("*")
        .eq("status", "awaiting_winner")
        .execute()
    )
    if not result.data:
        return {"evaluated": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=MIN_AB_WAIT_HOURS)
    total_sent = 0

    for ab_test in result.data:
        # Only evaluate if enough time has passed. Parse defensively — a single
        # malformed created_at must not raise out of the loop and abort the
        # whole beat (which would freeze EVERY awaiting A/B test indefinitely).
        # Treat an unparseable value as old-enough so the test still evaluates.
        created_at = ab_test.get("created_at", "")
        if created_at:
            try:
                created_dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                created_dt = None
            if created_dt is not None and created_dt > cutoff:
                continue

        # Determine winner
        opens_a = ab_test.get("opens_a", 0)
        opens_b = ab_test.get("opens_b", 0)
        winner = "A" if opens_a >= opens_b else "B"
        winning_subject = ab_test["subject_a"] if winner == "A" else ab_test["subject_b"]

        ab_test_model.update_ab_test(ab_test["id"], {
            "winner": winner,
            "status": "sending_winner",
        })

        campaign = campaign_model.get_campaign(ab_test["campaign_id"])
        if not campaign:
            ab_test_model.update_ab_test(ab_test["id"], {"status": "evaluated"})
            continue

        user = user_model.get_by_id(ab_test["user_id"])
        if not user:
            ab_test_model.update_ab_test(ab_test["id"], {"status": "evaluated"})
            continue

        access_token = get_fresh_access_token(user["id"])
        if not access_token:
            refreshed_user = user_model.get_by_id(user["id"])
            if refreshed_user and refreshed_user.get("requires_reauth"):
                ab_test_model.update_ab_test(ab_test["id"], {"status": "failed_auth"})
                campaign_model.update_campaign(
                    ab_test["campaign_id"], {"status": "failed_auth"}
                )
            continue

        # Get remaining pending contacts (those without ab_variant)
        remaining = contact_model.get_pending_contacts(ab_test["campaign_id"])
        if not remaining:
            ab_test_model.update_ab_test(ab_test["id"], {"status": "evaluated"})
            campaign_model.update_campaign(ab_test["campaign_id"], {"status": "sent"})
            continue

        # Suppression list
        suppressed_result = (
            db.table("suppression_list")
            .select("email")
            .eq("user_id", user["id"])
            .execute()
        )
        suppressed_emails = {r["email"].lower() for r in suppressed_result.data}

        sent_count = 0
        quota_charged = 0
        errors = []
        with httpx.Client(timeout=OUTBOUND_HTTP_TIMEOUT) as client:
            for contact in remaining:
                if contact.get("unsubscribed"):
                    continue
                if contact.get("email", "").lower() in suppressed_emails:
                    # Guarded — see process_scheduled_campaigns. This loop is
                    # the worst place to raise: the ab_test row was already
                    # flipped to 'sending_winner' above, and evaluate_ab_tests
                    # only ever re-queries 'awaiting_winner', so an escape here
                    # leaves the pair in a state no beat or sweep picks up.
                    try:
                        contact_model.mark_suppressed(contact["id"])
                    except Exception:  # noqa: BLE001
                        import logging
                        logging.getLogger(__name__).warning(
                            "Could not mark contact %s suppressed", contact.get("id"),
                            exc_info=True,
                        )
                    continue

                try:
                    # Override campaign subject with winning subject
                    campaign_copy = dict(campaign)
                    campaign_copy["subject"] = winning_subject
                    result = _send_email(
                        client=client,
                        access_token=access_token,
                        campaign=campaign_copy,
                        contact=contact,
                        unsubscribe_text=user.get("unsubscribe_text") or "Unsubscribe",
                    )
                    if result["success"]:
                        contact_model.mark_sent(contact["id"])
                        campaign_model.increment_stat(ab_test["campaign_id"], "sent_count")
                        sent_count += 1
                        # Batched for the same reason as the campaign loop
                        # above: a mid-loop SIGKILL would otherwise leave
                        # every already-'sent' contact uncharged.
                        if sent_count - quota_charged >= QUOTA_CHARGE_BATCH:
                            # Its own try. This sits inside the per-contact
                            # try whose except marks the contact 'deferred' —
                            # and mark_sent has ALREADY committed by now, so
                            # letting a quota-write failure reach that except
                            # would rewind a delivered recipient and get them
                            # emailed twice. Leaving quota_charged unadvanced
                            # is correct: the end-of-loop flush recharges it.
                            try:
                                user_model.increment_sent_count(
                                    user["id"], sent_count - quota_charged
                                )
                                quota_charged = sent_count
                            except Exception:  # noqa: BLE001
                                logger.warning(
                                    "batch quota charge failed; deferring to "
                                    "the end-of-loop flush",
                                    exc_info=True,
                                )
                    else:
                        # A failed send must mark the contact (so Resume can
                        # retry it) and flip the campaign to 'partial' — never
                        # silently drop most of the list while reporting 'sent'.
                        contact_model.mark_failed(
                            contact["id"], _classify_failure(result.get("status_code"))
                        )
                        errors.append(contact.get("email"))
                except Exception:
                    # Network/timeout: transient, retryable via Resume.
                    contact_model.mark_failed(contact["id"], "deferred")
                    errors.append(contact.get("email"))

                time.sleep(SEND_DELAY_SECONDS)

        # Wrapped for the same reason as the in-loop batches, one level up:
        # this runs per campaign inside the beat's for-loop, so an unhandled
        # error here would abort every remaining campaign in the run, not
        # just lose one charge.
        if sent_count > quota_charged:
            try:
                user_model.increment_sent_count(
                    user["id"], sent_count - quota_charged
                )
                quota_charged = sent_count
            except Exception:  # noqa: BLE001
                logger.warning(
                    "final quota flush failed for user %s (%s uncharged sends)",
                    user["id"], sent_count - quota_charged, exc_info=True,
                )
        ab_test_model.update_ab_test(ab_test["id"], {"status": "evaluated"})
        # 'partial' (not 'sent') when any send failed, so the Resume button
        # surfaces and the still-pending/deferred contacts can be retried.
        final_status = "sent" if not errors else "partial"
        campaign_model.update_campaign(ab_test["campaign_id"], {"status": final_status})
        total_sent += sent_count

    return {"evaluated": len(result.data), "sent": total_sent}


# ── Proactive token health check ──
#
# Microsoft refresh_tokens typically live 14-90 days depending on tenant
# policy. If the user doesn't trigger a scheduled send or follow-up in
# that window, we won't notice the token died until the next send attempt
# — by which time the user has already missed a send window.
#
# This task runs daily, attempts a silent refresh for every user who
# still has a stored refresh_token and isn't already flagged. If the
# refresh fails with a permanent error, `get_fresh_access_token` flags
# the user + fires the reconnect email via `_mark_requires_reauth`.


@celery.task
def _mark_partial(db, campaign_id) -> bool:
    """Move a stuck campaign to 'partial'. Never to 'scheduled'.

    'scheduled' with a NULL scheduled_for is a state no recovery path can
    see: get_due_scheduled_campaigns filters `.lte("scheduled_for", now)`,
    Resume 409s unless 'partial', auto-resume queries 'partial' only, and the
    sweep itself queries 'sending'. Its recipients were reachable by nothing.
    """
    try:
        (
            db.table("campaigns")
            .update({"status": "partial"})
            .eq("id", campaign_id)
            .eq("status", "sending")  # double-check to avoid races
            .execute()
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def reset_stuck_sending_campaigns():
    """Recover campaigns stuck in 'sending' status.

    The send loop marks a campaign 'sending' before iterating its
    contacts and 'sent' / 'partial' afterwards. If the worker crashes
    mid-loop (Railway restart, OOM, network blip), the campaign is
    left in 'sending' forever — the scheduled-campaign beat picks up
    only 'scheduled' rows, so it never retries on its own.

    Strategy:
      - Find campaigns in 'sending' whose LAST ACTUAL SEND is 30+
        minutes old (or, before the first send lands, whose row is
        30+ minutes old).
      - Mark them 'partial' so the user sees them and both resume
        paths can pick them up.

    Freshness is measured from contacts.sent_at, not from
    scheduled_for. That used to be the proxy, and it was a
    correctness bug rather than an approximation: `scheduled_for` is
    NULL for every campaign started with Send now (only the scheduler
    writes it), so `if scheduled_for and scheduled_for > cutoff`
    short-circuited and the 30-minute guard was skipped ENTIRELY for
    exactly those campaigns. A send-now run is one Graph call plus
    SEND_DELAY_SECONDS per recipient, so any list big enough to still
    be running when the hourly beat fired was flipped to 'partial'
    mid-flight — after which Resume (or auto_resume_partial_campaigns,
    whose eligibility check is only a date window) could start a
    SECOND loop over contacts the first loop had not reached yet, and
    email those people twice.

    contacts.sent_at is written per recipient as the loop runs, so
    "the newest sent_at is recent" means the loop is alive. It needs
    no migration and it cannot be NULL for a campaign that is
    genuinely progressing — which is the property scheduled_for never
    had.

    Nothing is ever parked on 'scheduled' any more either. A send-now
    campaign has scheduled_for NULL, and get_due_scheduled_campaigns
    filters `.lte("scheduled_for", now)`, which NULL never satisfies —
    so 'scheduled' made the campaign invisible to the send beat, to
    Resume (409s unless 'partial'), to auto-resume ('partial' only)
    and to this sweep ('sending' only). Its recipients were reachable
    by nothing. _run_campaign_send's own failure handler already
    refuses to write 'scheduled' for this reason; this sweep was the
    remaining way in.

    Idempotent — running this twice in a row is a no-op the second
    time because the status no longer matches. Hourly schedule keeps
    recovery latency < 1 hour without putting load on the DB.
    """
    from datetime import datetime, timedelta, timezone

    from database import get_db
    from models import contact as contact_model

    db = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()

    # updated_at is maintained by the trigger in migration 025 and is the only
    # signal here that is right for BOTH a first run and a resumed one. It is
    # selected optimistically: PostgREST rejects an unknown column at the
    # QUERY level (42703), so an unrun migration raises rather than returning
    # rows without the key, and the fallback below is the 2026-08-08
    # behaviour. Retry the wide select on every beat — one wasted round trip
    # per hour is nothing, and it means the sweep starts using the column the
    # moment the migration is applied, with no deploy.
    stuck = None
    have_updated_at = True
    for columns in (
        "id, scheduled_for, sent_count, status, created_at, updated_at",
        "id, scheduled_for, sent_count, status, created_at",
    ):
        try:
            stuck = (
                db.table("campaigns").select(columns).eq("status", "sending").execute()
            )
            break
        except Exception as e:  # noqa: BLE001
            have_updated_at = False
            last_error = e
    if stuck is None:
        import logging
        logging.getLogger(__name__).warning(
            "stuck-sending lookup failed: %s", last_error
        )
        return {"reset": 0}

    rows = stuck.data or []
    reset_to_partial = 0
    reset_to_scheduled = 0
    for row in rows:
        # Migration 025 present: the database has been stamping this row on
        # every write, including the per-recipient increment_stat that IS the
        # progress signal. Right for a first run and a resumed one alike,
        # which is what the two proxies below never managed.
        if have_updated_at:
            updated_at = row.get("updated_at")
            if not updated_at:
                continue  # no basis to judge — never flip on a guess
            if updated_at > cutoff:
                continue  # touched recently — still working
            _mark_partial(db, row["id"])
            reset_to_partial += 1
            continue

        # The newest recipient that actually went out. Present => the send
        # loop reached it, so its age is the age of the campaign's last
        # observable progress.
        try:
            latest = (
                db.table("contacts")
                .select("sent_at")
                .eq("campaign_id", row["id"])
                .eq("status", "sent")
                .order("sent_at", desc=True)
                .limit(1)
                .execute()
            )
            newest = (latest.data or [{}])[0].get("sent_at")
        except Exception:  # noqa: BLE001
            # Cannot measure progress => cannot prove it is stuck. Leaving a
            # dead campaign in 'sending' costs one hour until the next beat;
            # flipping a live one costs the recipients a duplicate email.
            continue

        if newest:
            if newest > cutoff:
                continue  # still delivering — leave it alone
        else:
            # No send has landed yet. Before the first Graph call returns
            # that is completely normal, so fall back to the row's own age.
            # A missing created_at means no basis to judge — skip.
            created_at = row.get("created_at")
            if not created_at or created_at > cutoff:
                continue

        if _mark_partial(db, row["id"]):
            reset_to_partial += 1

    return {
        "reset_to_partial": reset_to_partial,
        # Always 0 now — kept so the beat's result shape does not change
        # under anything reading it. See the docstring: 'scheduled' with a
        # NULL scheduled_for is a state no recovery path can see.
        "reset_to_scheduled": reset_to_scheduled,
    }


@celery.task
def anonymize_audit_log_ips():
    """Daily: anonymize IP addresses in audit_log rows older than 1 year.

    Calls the Postgres function defined in migration 011
    (`anonymize_old_audit_ips()`) which masks IPv4 to /24 and IPv6 to
    /48. Keeps us GDPR-compliant (data minimization) without losing
    the rough forensic value of the logs — a /24 is still useful for
    spotting geographic patterns during fraud investigations.

    The function is idempotent — already-anonymized rows are skipped
    by the `NOT LIKE '%.0'` predicate.
    """
    from database import get_db

    try:
        result = get_db().rpc("anonymize_old_audit_ips", {}).execute()
        if result.data:
            row = result.data[0] if isinstance(result.data, list) else result.data
            v4 = row.get("v4_updated", 0) if isinstance(row, dict) else 0
            v6 = row.get("v6_updated", 0) if isinstance(row, dict) else 0
            return {"v4_updated": v4, "v6_updated": v6}
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("audit IP anonymization failed: %s", e)
    return {"v4_updated": 0, "v6_updated": 0}


@celery.task
def check_user_tokens():
    """Proactively verify every connected user's MS refresh token."""
    from database import get_db

    db = get_db()

    # Only users who have a token row AND aren't already flagged. Users
    # flagged already will re-send a new refresh_token on their next OAuth
    # callback, which clears the flag — no point hammering a known-dead
    # token for them daily.
    tokens = (
        db.table("user_tokens")
        .select("user_id")
        .execute()
    )
    user_ids = [t["user_id"] for t in (tokens.data or []) if t.get("user_id")]
    if not user_ids:
        return {"checked": 0, "flagged": 0}

    flagged_before = set()
    healthy = 0
    newly_flagged = 0

    # Get current requires_reauth state in one query so we can tell which
    # users transitioned during this run (for metrics — the email is
    # handled inside _mark_requires_reauth).
    users_rows = (
        db.table("users")
        .select("id, requires_reauth")
        .in_("id", user_ids)
        .execute()
    )
    for row in users_rows.data or []:
        if row.get("requires_reauth"):
            flagged_before.add(row["id"])

    targets = [uid for uid in user_ids if uid not in flagged_before]

    for user_id in targets:
        token = get_fresh_access_token(user_id)
        if token:
            healthy += 1
            continue
        # get_fresh_access_token flags via _mark_requires_reauth on
        # permanent failure. Count the transition for reporting.
        check = (
            db.table("users")
            .select("requires_reauth")
            .eq("id", user_id)
            .execute()
        )
        if check.data and check.data[0].get("requires_reauth"):
            newly_flagged += 1

    return {
        "checked": len(targets),
        "healthy": healthy,
        "newly_flagged": newly_flagged,
        "already_flagged": len(flagged_before),
    }


# ── Manual promo expiry ──
#
# When we hand a user a free promo (e.g. a 60-day Starter as an apology) we
# set users.manual_promo_until. This daily task ends an expired promo so we
# don't have to keep a manual calendar reminder — UNLESS the user became a
# real Stripe subscriber in the meantime (never downgrade a paying customer).
# Idempotent: ending a promo clears manual_promo_until, so the row drops out
# of the candidate set on subsequent runs and never re-fires.
#
# Since migration 026 the grant is recorded in manual_promo_grants, and that
# record is what tells us how to undo it. This matters because granting a
# promo is DESTRUCTIVE to users.stripe_subscription_id: the guard below
# skips anyone carrying one, so the column has to be cleared for the promo
# to be expirable at all. The original value lives in the grant row and is
# put back here.
#
# Rows granted before 026 have no grant record. They still work — they fall
# back to the old behaviour (revert to 'free', leave the subscription id
# alone), which is exactly what they were granted under.


def _load_active_grant(db, user_id):
    """The user's live promo record, or None.

    Never raises: a promo must still expire even if the grants lookup
    fails, and the fallback (revert to 'free') is the pre-026 behaviour.
    """
    import logging

    logger = logging.getLogger(__name__)
    try:
        res = (
            db.table("manual_promo_grants")
            .select(
                "id, user_id, granted_plan, previous_plan, "
                "previous_stripe_subscription_id, expires_at, status"
            )
            .eq("user_id", user_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
    except Exception:  # noqa: BLE001
        logger.warning("promo grant lookup failed for user %s", user_id, exc_info=True)
        return None
    rows = res.data or []
    return rows[0] if rows else None


def _reread_user(db, user_id):
    """Fetch the user row fresh, immediately before writing to it.

    Returns None if the row cannot be read — in which case the caller skips
    it and the next daily run tries again, which is the safe direction.
    """
    import logging

    logger = logging.getLogger(__name__)
    try:
        res = (
            db.table("users")
            .select("id, email, plan, manual_promo_until, stripe_subscription_id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    except Exception:  # noqa: BLE001
        logger.warning("promo re-read failed for user %s", user_id, exc_info=True)
        return None
    rows = res.data or []
    return rows[0] if rows else None


def _reconcile_orphaned_grants(db, now):
    """Close grants whose user row no longer shows a promo.

    The expiry of one promo is two writes — the users row, then the grant
    record — and they cannot be made atomic through the REST client. If the
    second one fails, users.manual_promo_until is already NULL, so that user
    never appears in the candidate query again and the grant sits at
    'active' forever. That is not a cosmetic leak: the partial unique index
    allows one active grant per user, so the next time we try to gift that
    same customer anything, the INSERT fails on a row nobody remembers.

    This sweep is the retry the candidate query cannot provide. It is
    deliberately narrow — only grants already past their own expiry whose
    user shows no promo — so it can never close a grant that is still doing
    its job.
    """
    import logging

    logger = logging.getLogger(__name__)
    closed = 0

    try:
        res = (
            db.table("manual_promo_grants")
            .select("id, user_id, expires_at, status")
            .eq("status", "active")
            .limit(500)
            .execute()
        )
    except Exception:  # noqa: BLE001
        logger.warning("orphaned-grant sweep lookup failed", exc_info=True)
        return 0

    for grant in res.data or []:
        expires = grant.get("expires_at")
        if not expires:
            continue
        try:
            expires_dt = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            logger.warning(
                "orphaned-grant sweep: unparseable expires_at %r on grant %s",
                expires,
                grant.get("id"),
            )
            continue
        if expires_dt >= now:
            continue

        user = _reread_user(db, grant.get("user_id"))
        if user is None or user.get("manual_promo_until"):
            # Either unreadable, or the promo is still marked on the user
            # row — in which case the main loop owns it, not this sweep.
            continue

        # Record what actually happened rather than a convenient default:
        # a user carrying a subscription id went the supersede route.
        outcome = "superseded" if user.get("stripe_subscription_id") else "restored"
        _resolve_grant(db, grant["id"], outcome)
        logger.info(
            "orphaned-grant sweep closed grant %s for user %s",
            grant.get("id"),
            grant.get("user_id"),
        )
        closed += 1

    return closed


def _resolve_grant(db, grant_id, status):
    """Close out a grant record. Best-effort: the user row is the source of
    truth for what the user gets, so a bookkeeping failure here must not
    make the caller think the expiry itself failed."""
    import logging
    from datetime import datetime, timezone

    logger = logging.getLogger(__name__)
    try:
        (
            db.table("manual_promo_grants")
            .update(
                {
                    "status": status,
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", grant_id)
            .execute()
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to mark promo grant %s as %s", grant_id, status)


@celery.task
def expire_manual_promos():
    """End expired manual plan promos, restoring what the grant replaced.

    Targets rows where manual_promo_until is set and in the past, the plan
    is not already free, and there's no Stripe subscription. The
    stripe_subscription_id guard is the load-bearing safety check — a manual
    promo recipient who later subscribed for real must keep their paid plan.
    Since 026 that guard reads correctly rather than by luck: a grant clears
    the column, so anything found there was set AFTER the grant, i.e. by a
    real new subscription.

    The DB-side filters (date, plan, stripe) are re-applied in Python so the
    task is correct even against a client that doesn't push every predicate
    down, and so a single broad fetch can be evaluated row-by-row. Each
    revert is wrapped in try/except — one bad row never aborts the batch.
    """
    import logging
    from datetime import datetime, timezone

    from database import get_db
    from models import audit

    logger = logging.getLogger(__name__)
    db = get_db()

    now = datetime.now(timezone.utc)

    try:
        result = (
            db.table("users")
            .select("id, email, plan, manual_promo_until, stripe_subscription_id")
            .not_.is_("manual_promo_until", "null")
            .limit(500)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("expire_manual_promos lookup failed: %s", e)
        return {"reverted": 0, "considered": 0}

    rows = result.data or []
    reverted = 0
    superseded = 0

    for user in rows:
        until = user.get("manual_promo_until")
        if not until:
            continue

        # Only act once the promo window has actually passed. This check
        # comes FIRST so that nothing below — including closing out a grant
        # record — can touch a promo that is still running.
        try:
            until_dt = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
            if until_dt.tzinfo is None:
                until_dt = until_dt.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            logger.warning(
                "expire_manual_promos: unparseable manual_promo_until %r for user %s",
                until,
                user.get("id"),
            )
            continue
        if until_dt >= now:
            continue

        # Re-read the row we are about to overwrite.
        #
        # The candidate SELECT above takes one snapshot of up to 500 rows and
        # the loop then makes several round-trips per row, so by the time we
        # reach row #300 the snapshot can be minutes old. The dangerous case
        # is small but real: a user whose promo expires today completes a
        # Stripe checkout while the beat is mid-batch. The snapshot still
        # says stripe_subscription_id=NULL, so we would take the restore
        # branch and overwrite the plan the checkout webhook had just
        # written — downgrading someone moments after they paid.
        fresh = _reread_user(db, user["id"])
        if fresh is None:
            continue
        if not fresh.get("manual_promo_until"):
            # Someone (a concurrent run, a manual fix) already ended it.
            continue
        user = fresh

        grant = _load_active_grant(db, user["id"])

        # Never touch a real paying customer. A grant CLEARS
        # stripe_subscription_id, and grant_manual_promo refuses to run
        # while a live one is present, so a value here was written after the
        # grant — by a genuine new subscription. There is nothing to undo:
        # they are paying, and the plan they are paying for is theirs.
        if user.get("stripe_subscription_id"):
            if grant:
                # Clear the marker BEFORE closing the grant, not after.
                #
                # These two writes cannot be one transaction through the
                # REST client, so one of them can land alone — and the order
                # decides whether the leftover state can heal. Marker first:
                # if it fails, the grant stays 'active' and the row stays a
                # candidate, so tomorrow's run simply tries again. Grant
                # first: the grant is closed, `grant` is None on every later
                # run, and the retry the old comment promised silently never
                # happens.
                try:
                    (
                        db.table("users")
                        .update({"manual_promo_until": None})
                        .eq("id", user["id"])
                        .execute()
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "expire_manual_promos: failed to clear promo marker for %s",
                        user.get("id"),
                    )
                    continue
                _resolve_grant(db, grant["id"], "superseded")
                superseded += 1
            continue

        if grant:
            # Undo exactly what the grant did. previous_plan rather than a
            # hardcoded 'free': the user may have been on a paid plan when
            # the promo was granted, and the billing webhook retargets this
            # field to 'free' if their subscription dies mid-promo.
            payload = {
                "plan": grant.get("previous_plan") or "free",
                "manual_promo_until": None,
            }
            # users.stripe_subscription_id is deliberately NOT written back.
            #
            # The stash exists so the id is never lost — it lives in the
            # grant record permanently, and stripe_customer_id is never
            # cleared, so Stripe itself stays one query away. But the column
            # means "this user's CURRENT subscription", and since
            # grant_manual_promo refuses to run over a live one, every
            # stashed id is one an operator confirmed DEAD. Restoring it
            # would put a false value into a live field, and six readers
            # believe that field:
            #
            #   * account.py:122 blocks account deletion on (paid plan AND
            #     a subscription id) — a restored dead id can lock a user
            #     out of deleting their own account, telling them to cancel
            #     a subscription that does not exist;
            #   * daily_report counts a real payer as paid plan AND a
            #     subscription id, so it would report revenue nobody pays;
            #   * daily_report's gift count keys off the same column being
            #     NULL, so both halves of the split go wrong at once;
            #   * create_checkout treats it as "existing subscriber" and
            #     burns a Stripe retrieve on every future upgrade;
            #   * inactivity_nudge targets on it;
            #   * grant_manual_promo refuses when it is set, so the next
            #     gift to this customer would need the confirmation dance
            #     again for a subscription already known to be dead.
        else:
            # Granted before migration 026, so there is no record of what to
            # restore. Fall back to the behaviour it was granted under.
            if user.get("plan") in (None, "free"):
                continue
            payload = {"plan": "free", "manual_promo_until": None}

        try:
            (
                db.table("users")
                .update(payload)
                .eq("id", user["id"])
                .execute()
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "expire_manual_promos: failed to revert user %s", user.get("id")
            )
            continue

        if grant:
            _resolve_grant(db, grant["id"], "restored")

        audit.emit(
            audit.EVENT_MANUAL_PROMO_EXPIRED,
            user_id=user["id"],
            email=user.get("email"),
            metadata={
                # The plan they were ON during the promo (the granted one),
                # named "previous_plan" since 019 because from the audit
                # entry's point of view the promo is what just ended.
                "previous_plan": user.get("plan"),
                "manual_promo_until": str(until),
                "restored_to": payload.get("plan"),
                # The stashed id stays in the grant record rather than going
                # back on the user row; carry it here so the audit trail can
                # answer "which subscription did this account once have?"
                # without a second lookup.
                "stashed_subscription_id": (
                    grant.get("previous_stripe_subscription_id") if grant else None
                ),
                "grant_id": grant.get("id") if grant else None,
            },
        )
        reverted += 1

    # Catch grants whose user row was updated but whose own close-out write
    # failed on some earlier run. Nothing else revisits those, and each one
    # blocks that customer from ever being granted another promo.
    orphans_closed = _reconcile_orphaned_grants(db, now)

    return {
        "reverted": reverted,
        "superseded": superseded,
        "orphans_closed": orphans_closed,
        "considered": len(rows),
    }


# ── Auto-resume quota-capped partial campaigns ──
#
# A send that hits the monthly quota leaves the rest of the list 'pending'
# and the campaign 'partial'. Until 2026-07-20 the ONLY way those went out
# was the user remembering to click Resume after their reset — a Starter
# hit 2,500 exactly with 250 recipients parked behind that click. This
# beat removes the click: once the owner has headroom again (rolling reset
# or an upgrade), the campaign flips back to 'scheduled' and the regular
# process_scheduled_campaigns beat finishes it with ALL its existing
# guards (quota slice, daily cap, token refresh, suppression). No new send
# path is introduced here — this task only changes campaign status.

# Outer bound for the candidate QUERY only — the real age rule is per-user
# and lives in _capped_in_last_quota_cycle() below. A fixed 14-day window was
# wrong: the quota period is a rolling month anchored on the user's own
# month_reset_date, so the gap between hitting the cap and the next reset is
# anywhere from 0 to 31 days. Anyone who burned their quota early in their
# cycle was already outside a 14-day window on reset day — and stayed
# outside it forever, while the in-app text promised an automatic send.
AUTO_RESUME_MAX_AGE_DAYS = 70


def _capped_in_last_quota_cycle(created_at, user) -> bool:
    """Was this campaign created within the user's current or previous quota
    cycle?

    Call AFTER check_monthly_reset, so month_reset_date is the current
    anchor. "Previous cycle" is what makes the promise true: a campaign
    capped anywhere inside the cycle that just ended gets resumed at the
    reset that follows it, whether that was 2 days later or 30.

    Anything older is left alone on purpose — that is the original guard's
    intent (a months-old abandoned partial must never resurrect itself and
    surprise-send a stale list). Those campaigns still show the Resume
    button in Reports.
    """
    from models import user as user_model

    if not created_at:
        return False
    anchor = user.get("month_reset_date")
    if not anchor:
        # No anchor to reason about (legacy row): fall back to a plain
        # 31-day window rather than resuming something arbitrarily old.
        cutoff = datetime.now(timezone.utc) - timedelta(days=31)
    else:
        if isinstance(anchor, str):
            anchor = date.fromisoformat(anchor)
        prev_cycle_start = user_model._add_months(anchor, -1)
        cutoff = datetime(
            prev_cycle_start.year,
            prev_cycle_start.month,
            prev_cycle_start.day,
            tzinfo=timezone.utc,
        )
    if isinstance(created_at, str):
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return False
    else:
        created = created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created >= cutoff


@celery.task
def auto_resume_partial_campaigns():
    """Flip recent 'partial' campaigns to 'scheduled' when the owner has
    quota headroom again.

    Guards:
      - only campaigns created in the last AUTO_RESUME_MAX_AGE_DAYS days —
        an old abandoned partial must never resurrect itself and
        surprise-send
      - check_monthly_reset runs first, so the reset happens even if the
        user never logs in on their anniversary day
      - requires_reauth owners are skipped (retried on later runs once
        they reconnect)
      - campaigns with nothing resumable left are closed out as 'sent'
        (mirrors the manual Resume endpoint)
      - quota is NOT consumed here; the send beat re-enforces it and
        keeps over-quota campaigns scheduled for the next window
    """
    from models import campaign as campaign_model
    from models import contact as contact_model
    from models import user as user_model

    campaigns = campaign_model.get_recent_partial_campaigns(
        AUTO_RESUME_MAX_AGE_DAYS
    )
    resumed = 0
    closed = 0
    users_cache: dict = {}

    for campaign in campaigns:
        uid = campaign.get("user_id")
        if uid not in users_cache:
            users_cache[uid] = user_model.get_by_id(uid)
        user = users_cache[uid]
        if not user or user.get("requires_reauth"):
            continue

        user_model.check_monthly_reset(user)

        # Age rule runs AFTER the reset so it compares against the fresh
        # anchor (see _capped_in_last_quota_cycle).
        if not _capped_in_last_quota_cycle(campaign.get("created_at"), user):
            continue

        plan = user.get("plan", "free")
        if plan == "free":
            limit = FREE_PLAN_MONTHLY_LIMIT
        elif plan == "starter":
            limit = STARTER_PLAN_MONTHLY_LIMIT
        else:
            limit = PRO_PLAN_MONTHLY_LIMIT
        if limit - user.get("emails_sent_this_month", 0) <= 0:
            continue

        pending = contact_model.get_resumable_contacts(campaign["id"])
        if not pending:
            campaign_model.update_campaign(campaign["id"], {"status": "sent"})
            closed += 1
            continue

        campaign_model.update_campaign(
            campaign["id"],
            {
                "status": "scheduled",
                "scheduled_for": datetime.now(timezone.utc).isoformat(),
            },
        )
        resumed += 1

    return {
        "checked": len(campaigns),
        "resumed": resumed,
        "closed_as_sent": closed,
    }
