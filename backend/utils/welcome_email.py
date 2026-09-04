"""
OutMass — onboarding and billing transactional emails (MailerSend, best-effort).

Five senders, six messages. Each is fired exactly once by a guarded trigger:
- send_welcome_email      — user row CREATED (first-ever sign-in, never later
  logins; auth callbacks pass the upsert's `created` flag).
- send_upgrade_email      — first processing of a Stripe checkout (rides the
  webhook's replay guard, so redeliveries can't send it twice).
- send_quota_capped_email — a send that hit the monthly ceiling.
- send_campaign_stalled_email — a campaign silent too long to resume on its
  own (rides campaigns.stalled_notice_at, written before the call).
- send_plan_dropped_email — a paid plan ended, in two variants.

All are dispatched via BackgroundTasks and never raise — a failed email must
never break or slow the OAuth flow or the Stripe webhook.

Why they exist: users got total silence from us after signup AND after paying
(only Stripe's bare receipt). A paying customer literally asked "will I
receive any other confirmation?" — and an anonymous prospect reinstalled 9
times without ever finding the sign-in.

The copy is no longer here. Every word lives in emails/strings/<lang>.json and
is rendered into both parts by emails.render; this module is now the wiring
between a trigger and a message. See emails/catalog.py.
"""

import logging

import httpx

from config import (
    MAILERSEND_API_KEY,
    MAILERSEND_FROM_EMAIL,
    MAILERSEND_PERSON_FROM_NAME,
    monthly_limit_for_plan,
)
from emails import (
    SUPPORT_EMAIL,
    fill,
    format_number,
    month_name,
    render,
    strings_for,
)

logger = logging.getLogger("outmass.welcome")

__all__ = [
    "SUPPORT_EMAIL",
    "send_welcome_email",
    "send_quota_capped_email",
    "send_campaign_stalled_email",
    "send_upgrade_email",
    "send_plan_dropped_email",
]


def _dispatch(email: str, subject: str, text: str, html: str) -> bool:
    """POST one email to MailerSend. Never raises. True = accepted."""
    if not MAILERSEND_API_KEY or not email:
        return False
    payload = {
        "from": {"email": MAILERSEND_FROM_EMAIL, "name": MAILERSEND_PERSON_FROM_NAME},
        "to": [{"email": email}],
        "reply_to": {"email": SUPPORT_EMAIL, "name": "OutMass Support"},
        "subject": subject,
        "text": text,
        "html": html,
    }
    try:
        resp = httpx.post(
            "https://api.mailersend.com/v1/email",
            headers={"Authorization": f"Bearer {MAILERSEND_API_KEY}"},
            json=payload,
            timeout=10.0,
        )
        if resp.status_code in (200, 201, 202):
            logger.info("Email %r dispatched to %s", subject, email)
            return True
        logger.warning(
            "Email dispatch failed (%s): %s", resp.status_code, resp.text[:300]
        )
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("Email dispatch failed: %s", e)
        return False


def _send(template: str, email: str, name: str | None, lang: str | None, **vars) -> bool:
    msg = render(template, lang=lang, name=name, **vars)
    return _dispatch(email, msg.subject, msg.text, msg.html)


def send_welcome_email(
    email: str, name: str | None = None, lang: str | None = None
) -> bool:
    """Best-effort welcome email. Never raises. True = accepted by MailerSend."""
    # Read, not typed. This said "250 emails/month" in two places until
    # 2026-08-13 — the same drift that left docs/terms.html promising a
    # 50-email free tier for months after the code moved to 250.
    return _send(
        "welcome",
        email,
        name,
        lang,
        free_quota=format_number(monthly_limit_for_plan("free"), lang),
    )


def send_quota_capped_email(
    email: str,
    name: str | None,
    skipped: int,
    limit: int,
    next_reset_iso: str | None,
    lang: str | None = None,
) -> bool:
    """Best-effort 'your remaining recipients are saved' email. Never raises.

    Fired when a send gets quota-capped (quota_skipped > 0): the capped
    recipients stay pending and the auto_resume_partial_campaigns beat
    sends them automatically once the quota resets — this email tells the
    user exactly that, so nobody has to remember a Resume button
    (2026-07-20: a Starter capped at exactly 2,500 with 250 parked).
    """
    strings = strings_for(lang)
    reset_phrase = strings["quota_capped.reset_generic"]
    if next_reset_iso:
        try:
            from datetime import date

            d = date.fromisoformat(next_reset_iso)
            reset_phrase = fill(
                strings["quota_capped.reset_on_date"],
                month=month_name(d.month, lang),
                # Not zero-padded. "on September 05" is written by no
                # language on earth, and %d had been padding it since the
                # first version of this email.
                day=str(d.day),
            )
        except ValueError:
            pass

    return _send(
        "quota_capped",
        email,
        name,
        lang,
        skipped=skipped,
        limit=format_number(limit, lang),
        reset_phrase=reset_phrase,
    )


def send_campaign_stalled_email(
    email: str,
    name: str | None,
    campaign: str,
    pending: int,
    days: int,
    lang: str | None = None,
) -> bool:
    """Best-effort 'this campaign is too old to resume by itself'. Never raises.

    Fired once per stall by auto_resume_partial_campaigns, which writes
    campaigns.stalled_notice_at BEFORE calling this — the beat runs every two
    hours, and a notification without a persistent marker is a notification
    twelve times a day.

    The opposite message to send_quota_capped_email, and the pair has to stay
    consistent: that one promises the rest goes out on its own, this one says
    it will not. What keeps both true is the threshold
    (AUTO_RESUME_MAX_IDLE_DAYS, 35 days), which no quota wait can reach.

    `campaign` is a name the user typed. It reaches the template as a variable
    and every variable is escaped at render time, so a name containing markup,
    angle brackets or a stray ${ cannot alter the message.
    """
    return _send(
        "campaign_stalled",
        email,
        name,
        lang,
        campaign=campaign or "—",
        pending=format_number(pending, lang),
        days=days,
    )


def send_upgrade_email(
    email: str, name: str | None, plan: str, lang: str | None = None
) -> bool:
    """Best-effort upgrade thank-you. Never raises. True = accepted.

    Fired once per new paid subscription (the Stripe webhook's replay guard
    gates the call) — the user's only confirmation used to be Stripe's bare
    receipt, which a paying customer explicitly found insufficient.
    """
    return _send(
        "upgrade",
        email,
        name,
        lang,
        plan_label="Pro" if plan == "pro" else "Starter",
        quota=format_number(monthly_limit_for_plan(plan), lang),
    )


def send_plan_dropped_email(
    email: str, name: str | None, reason: str, lang: str | None = None
) -> bool:
    """Tell someone their plan went back to Free. Never raises.

    Two ways to arrive here, and they are not the same message:

      * ``payment_failed`` — Stripe spent about two weeks retrying the card
        and gave up. They have already had Stripe's dunning emails (all five
        customer-email toggles were switched on 2026-08-10), so this is the
        END of a chain they know about, not news. Writing it as a surprise
        would be strange.
      * ``promo_ended`` — a plan we granted ran out. Nothing failed, and
        saying anything about payment here would be wrong.

    Deliberately NOT sent when the customer asked to cancel: they know, and
    a second message minutes after their confirmation is noise. The webhook
    reads Stripe's cancellation_details.reason to tell those apart.

    The quota comes from monthly_limit_for_plan, never typed here.
    docs/terms.html spent months promising a 50-email free tier because
    somebody wrote a number into copy.
    """
    template = (
        "plan_dropped_promo_ended"
        if reason == "promo_ended"
        else "plan_dropped_payment_failed"
    )
    return _send(
        template,
        email,
        name,
        lang,
        free_quota=format_number(monthly_limit_for_plan("free"), lang),
    )
