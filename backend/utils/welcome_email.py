"""
OutMass — Welcome email (first sign-in).

One transactional email, sent exactly once: when the user's account row is
CREATED (first-ever sign-in), never on later logins. Dispatched from the
auth callbacks via BackgroundTasks as best-effort — a failed email must
never break or slow the OAuth flow, so this function never raises.

Why it exists: new users got total silence from us after install/signup
(only Stripe's receipt if they paid). A paying customer literally asked
"will I receive any other confirmation?" — and an anonymous prospect
reinstalled 9 times without ever finding the sign-in. This mail is the
"you're in — here's the 3-step path to your first campaign" answer.
"""

import logging

import httpx

from config import MAILERSEND_API_KEY, MAILERSEND_FROM_EMAIL

logger = logging.getLogger("outmass.welcome")

SUPPORT_EMAIL = "support@getoutmass.com"


def _first_name(name: str | None) -> str:
    if not name or not name.strip():
        return "there"
    return name.strip().split(" ")[0]


def send_welcome_email(email: str, name: str | None = None) -> bool:
    """Best-effort welcome email. Never raises. True = accepted by MailerSend."""
    if not MAILERSEND_API_KEY or not email:
        return False

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
        "You're on the Free plan (250 emails/month) — you can upgrade anytime\n"
        "from the panel when you need more.\n"
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
        '<p style="font-size:14px;line-height:1.6;">You\'re on the <strong>Free '
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
            logger.info("Welcome email dispatched to %s", email)
            return True
        logger.warning(
            "Welcome email dispatch failed (%s): %s",
            resp.status_code,
            resp.text[:300],
        )
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("Welcome email dispatch failed: %s", e)
        return False
