"""
OutMass — onboarding transactional emails (MailerSend, best-effort).

Two one-time emails, each fired exactly once by a guarded trigger:
- send_welcome_email  — user row CREATED (first-ever sign-in, never later
  logins; auth callbacks pass the upsert's `created` flag).
- send_upgrade_email  — first processing of a Stripe checkout (rides the
  webhook's replay guard, so redeliveries can't send it twice).

Both are dispatched via BackgroundTasks and never raise — a failed email
must never break or slow the OAuth flow or the Stripe webhook.

Why they exist: users got total silence from us after signup AND after
paying (only Stripe's bare receipt). A paying customer literally asked
"will I receive any other confirmation?" — and an anonymous prospect
reinstalled 9 times without ever finding the sign-in.
"""

import logging

import httpx

from config import MAILERSEND_API_KEY, MAILERSEND_FROM_EMAIL, monthly_limit_for_plan

logger = logging.getLogger("outmass.welcome")

SUPPORT_EMAIL = "support@getoutmass.com"


def _dispatch(email: str, subject: str, text: str, html: str) -> bool:
    """POST one email to MailerSend. Never raises. True = accepted."""
    if not MAILERSEND_API_KEY or not email:
        return False
    payload = {
        "from": {"email": MAILERSEND_FROM_EMAIL, "name": "Ali from OutMass"},
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


def _first_name(name: str | None) -> str:
    if not name or not name.strip():
        return "there"
    return name.strip().split(" ")[0]


def send_welcome_email(email: str, name: str | None = None) -> bool:
    """Best-effort welcome email. Never raises. True = accepted by MailerSend."""
    first = _first_name(name)

    subject = "Welcome to OutMass — your first campaign in 3 steps"

    text = (
        "Hi " + first + ",\n"
        "\n"
        "Thanks for signing in to OutMass! You're set up to send personalized\n"
        "mail-merge campaigns straight from your own Outlook account.\n"
        "\n"
        "Your first campaign in 3 steps:\n"
        "\n"
        "1. Open Outlook on the web and click the round OM button in the\n"
        "   bottom-right corner — it opens the OutMass panel.\n"
        "2. In the panel, upload your recipients as a CSV (there's a template\n"
        "   inside), write your email, and drop {{firstName}} anywhere to\n"
        "   personalize each message.\n"
        "3. Click Preview or send yourself a Test Send, then hit Send.\n"
        "   OutMass paces delivery and tracks opens, clicks and replies.\n"
        "\n"
        "You start on the Free plan (250 emails/month) — you can upgrade\n"
        "anytime from the panel when you need more.\n"
        "\n"
        "Hit a snag or have a question? Just reply to this email — it comes\n"
        "straight to me and I usually answer within a few hours.\n"
        "\n"
        "Ali\n"
        "Founder, OutMass\n"
        "https://getoutmass.com\n"
        "\n"
        "P.S. The panel lives in Outlook ON THE WEB (outlook.office.com or\n"
        "outlook.live.com) — the Windows/Mac desktop app isn't supported. If\n"
        "you don't see the round button, refresh your Outlook tab once.\n"
    )

    steps_html = (
        '<ol style="color:#323130;font-size:14px;line-height:1.7;padding-left:20px;">'
        "<li>Open <strong>Outlook on the web</strong> and click the round "
        "<strong>OM button</strong> in the bottom-right corner — it opens the "
        "OutMass panel.</li>"
        "<li>Upload your recipients as a <strong>CSV</strong> (there's a template "
        "inside), write your email, and drop <code>{{firstName}}</code> anywhere "
        "to personalize each message.</li>"
        "<li>Click <strong>Preview</strong> or send yourself a <strong>Test "
        "Send</strong>, then hit <strong>Send</strong>. OutMass paces delivery and "
        "tracks opens, clicks and replies.</li>"
        "</ol>"
    )

    html = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,'
        'sans-serif;max-width:560px;margin:0 auto;color:#323130;">'
        '<h2 style="font-size:20px;margin:0 0 14px;">Welcome to OutMass 👋</h2>'
        '<p style="font-size:14px;line-height:1.6;">Hi ' + first + ",</p>"
        '<p style="font-size:14px;line-height:1.6;">Thanks for signing in! '
        "You're set up to send personalized mail-merge campaigns straight from "
        "your own Outlook account. Here's your first campaign in 3 steps:</p>"
        + steps_html +
        '<p style="font-size:14px;line-height:1.6;">You start on the <strong>Free '
        "plan</strong> (250 emails/month) — upgrade anytime from the panel when "
        "you need more.</p>"
        '<p style="font-size:14px;line-height:1.6;">Hit a snag or have a '
        "question? <strong>Just reply to this email</strong> — it comes straight "
        "to me and I usually answer within a few hours.</p>"
        '<p style="font-size:14px;line-height:1.6;">Ali<br>'
        'Founder, OutMass<br>'
        '<a href="https://getoutmass.com" style="color:#0078d4;">getoutmass.com</a></p>'
        '<p style="font-size:12px;color:#797775;line-height:1.5;margin-top:18px;">'
        "P.S. The panel lives in Outlook <em>on the web</em> (outlook.office.com "
        "or outlook.live.com) — the Windows/Mac desktop app isn't supported. If "
        "you don't see the round button, refresh your Outlook tab once.</p>"
        "</div>"
    )

    return _dispatch(email, subject, text, html)


def send_quota_capped_email(
    email: str,
    name: str | None,
    skipped: int,
    limit: int,
    next_reset_iso: str | None,
) -> bool:
    """Best-effort 'your remaining recipients are saved' email. Never raises.

    Fired when a send gets quota-capped (quota_skipped > 0): the capped
    recipients stay pending and the auto_resume_partial_campaigns beat
    sends them automatically once the quota resets — this email tells the
    user exactly that, so nobody has to remember a Resume button
    (2026-07-20: a Starter capped at exactly 2,500 with 250 parked).
    """
    first = _first_name(name)

    reset_phrase = "when your monthly quota resets"
    if next_reset_iso:
        try:
            from datetime import date

            d = date.fromisoformat(next_reset_iso)
            reset_phrase = f"on {d.strftime('%B %d')}, when your monthly quota resets"
        except ValueError:
            pass

    subject = (
        f"{skipped} recipients saved — they'll be sent automatically"
    )

    text = (
        "Hi " + first + ",\n"
        "\n"
        f"Your campaign just reached your monthly limit of {limit:,} emails.\n"
        f"The remaining {skipped} recipients are safely saved — nothing was\n"
        "lost, and there's nothing you need to do.\n"
        "\n"
        f"OutMass will send them automatically {reset_phrase}.\n"
        "\n"
        "Want them out sooner? Upgrading raises your limit immediately and\n"
        "the saved recipients go out on the next sending run — open the\n"
        "OutMass panel and click Upgrade.\n"
        "\n"
        "Questions? Just reply — it comes straight to me.\n"
        "\n"
        "Ali\n"
        "Founder, OutMass\n"
        "https://getoutmass.com\n"
    )

    html = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,'
        'sans-serif;max-width:560px;margin:0 auto;color:#323130;">'
        f'<h2 style="font-size:20px;margin:0 0 14px;">{skipped} recipients saved 📬</h2>'
        '<p style="font-size:14px;line-height:1.6;">Hi ' + first + ",</p>"
        '<p style="font-size:14px;line-height:1.6;">Your campaign just reached '
        f"your monthly limit of <strong>{limit:,} emails</strong>. The remaining "
        f"<strong>{skipped} recipients are safely saved</strong> — nothing was "
        "lost, and there's nothing you need to do.</p>"
        '<p style="font-size:14px;line-height:1.6;">OutMass will send them '
        f"<strong>automatically</strong> {reset_phrase}.</p>"
        '<p style="font-size:14px;line-height:1.6;">Want them out sooner? '
        "Upgrading raises your limit immediately and the saved recipients go "
        "out on the next sending run — open the OutMass panel and click "
        "<strong>Upgrade</strong>.</p>"
        '<p style="font-size:14px;line-height:1.6;">Questions? Just reply — it '
        "comes straight to me.</p>"
        '<p style="font-size:14px;line-height:1.6;">Ali<br>'
        "Founder, OutMass<br>"
        '<a href="https://getoutmass.com" style="color:#0078d4;">getoutmass.com</a></p>'
        "</div>"
    )

    return _dispatch(email, subject, text, html)


def send_upgrade_email(email: str, name: str | None, plan: str) -> bool:
    """Best-effort upgrade thank-you. Never raises. True = accepted.

    Fired once per new paid subscription (the Stripe webhook's replay guard
    gates the call) — the user's only confirmation used to be Stripe's bare
    receipt, which a paying customer explicitly found insufficient.
    """
    first = _first_name(name)
    label = "Pro" if plan == "pro" else "Starter"
    quota = f"{monthly_limit_for_plan(plan):,}"

    subject = f"Your OutMass {label} plan is active — thank you!"

    text = (
        "Hi " + first + ",\n"
        "\n"
        "Thank you for upgrading — your " + label + " plan is active as of now.\n"
        "\n"
        "What that means:\n"
        "\n"
        "- You can send up to " + quota + " emails per month.\n"
        "- Your billing month starts today and renews monthly from this date\n"
        "  (your quota resets on the same day, not on the 1st).\n"
        "- You can see your usage anytime in the OutMass panel under Account,\n"
        "  and manage or cancel the subscription via Manage Subscription.\n"
        "\n"
        "If anything at all comes up — a question, a snag, a feature you're\n"
        "missing — just reply to this email. It comes straight to me.\n"
        "\n"
        "Thanks for backing a small product early. It means a lot.\n"
        "\n"
        "Ali\n"
        "Founder, OutMass\n"
        "https://getoutmass.com\n"
    )

    html = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,'
        'sans-serif;max-width:560px;margin:0 auto;color:#323130;">'
        '<h2 style="font-size:20px;margin:0 0 14px;">Your ' + label +
        " plan is active 🎉</h2>"
        '<p style="font-size:14px;line-height:1.6;">Hi ' + first + ",</p>"
        '<p style="font-size:14px;line-height:1.6;">Thank you for upgrading — '
        "your <strong>" + label + "</strong> plan is active as of now. What that "
        "means:</p>"
        '<ul style="color:#323130;font-size:14px;line-height:1.7;padding-left:20px;">'
        "<li>You can send up to <strong>" + quota + " emails per month</strong>.</li>"
        "<li>Your billing month <strong>starts today</strong> and renews monthly "
        "from this date — your quota resets on the same day, not on the 1st.</li>"
        "<li>See your usage anytime in the OutMass panel under "
        "<strong>Account</strong>, and manage or cancel via <strong>Manage "
        "Subscription</strong>.</li>"
        "</ul>"
        '<p style="font-size:14px;line-height:1.6;">If anything at all comes up — '
        "a question, a snag, a feature you're missing — <strong>just reply to "
        "this email</strong>. It comes straight to me.</p>"
        '<p style="font-size:14px;line-height:1.6;">Thanks for backing a small '
        "product early. It means a lot.</p>"
        '<p style="font-size:14px;line-height:1.6;">Ali<br>'
        "Founder, OutMass<br>"
        '<a href="https://getoutmass.com" style="color:#0078d4;">getoutmass.com</a></p>'
        "</div>"
    )

    return _dispatch(email, subject, text, html)
