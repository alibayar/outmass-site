"""Mail a customer receives must come from a person, not the feedback desk.

MAILERSEND_FROM_NAME defaults to "OutMass Feedback" and belongs to the
feedback form in main.py, which mails US. Two customer-facing senders were
still reading it on 2026-08-11 — the Outlook reconnect email and the
account-deletion confirmation — and both ask the customer to reply:

    "If you keep seeing this, reply to this email and we'll look into it."
    "If you need help cancelling or getting a refund, reply to this email."

An ask for a reply is not credible over a name shaped like a no-reply box.
Found the same day a real user got both a welcome email and a reconnect
email within fifteen hours, which is exactly the moment the sender name
decides whether they answer or shrug.

Two layers here on purpose. The source scan catches a new mailer picking
the wrong constant. The dispatch tests catch what a scan cannot: whether
the value actually reaches MailerSend. Three guards written the day before
passed their unit tests and were dead at the call site, which is the whole
argument for driving the real function.
"""
from unittest.mock import patch

import pytest

from config import MAILERSEND_FROM_NAME, MAILERSEND_PERSON_FROM_NAME


class _Captured:
    """Stands in for httpx.post and keeps the payload."""

    def __init__(self):
        self.payload = {}

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.payload = json or {}

        class _R:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {}

        return _R()


def test_the_two_names_are_actually_different():
    """If someone 'simplifies' by pointing the person constant at the shared
    one, every test below still passes while the bug returns. This is the
    assertion that stops that."""
    assert MAILERSEND_PERSON_FROM_NAME != MAILERSEND_FROM_NAME
    assert "Feedback" not in MAILERSEND_PERSON_FROM_NAME


# ── Layer 1: no customer-facing mailer may read the feedback name ──

# main.py is deliberately absent: its email goes TO us, so the feedback
# name is correct there. Adding a new customer mailer means adding it here.
_CUSTOMER_MAILERS = (
    "models/ms_token.py",
    "routers/account.py",
    "utils/welcome_email.py",
    "workers/inactivity_nudge.py",
)


@pytest.mark.parametrize("module_path", _CUSTOMER_MAILERS)
def test_customer_mailer_does_not_use_the_feedback_name(module_path):
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / module_path).read_text(
        encoding="utf-8"
    )
    offending = [
        line.strip()
        for line in src.splitlines()
        if '"name": MAILERSEND_FROM_NAME' in line
    ]
    assert not offending, (
        f"{module_path} sends to customers as the feedback desk: {offending}. "
        "Use MAILERSEND_PERSON_FROM_NAME."
    )


def test_the_feedback_form_keeps_the_feedback_name():
    """The mirror of the rule. This email arrives in our own inbox and
    'OutMass Feedback' is the useful label there — a sweep that renamed
    every sender would take that away."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8"
    )
    assert "MAILERSEND_FROM_NAME" in src


# ── Layer 2: the value reaches the wire ──


def test_reauth_email_is_sent_by_a_person():
    from models import ms_token

    post = _Captured()
    with patch.object(ms_token, "MAILERSEND_API_KEY", "k"), \
         patch.object(ms_token.httpx, "post", post):
        ms_token._send_reauth_email("u@example.com", "Sam", "invalid_grant")

    assert post.payload["from"]["name"] == MAILERSEND_PERSON_FROM_NAME


def test_deletion_confirmation_is_sent_by_a_person():
    from routers import account

    post = _Captured()
    with patch.object(account, "MAILERSEND_API_KEY", "k"), \
         patch.object(account.httpx, "post", post):
        account._send_deletion_confirmation_email(
            "u@example.com", "Sam", "arch-1"
        )

    assert post.payload["from"]["name"] == MAILERSEND_PERSON_FROM_NAME


def test_welcome_email_is_sent_by_a_person():
    from utils import welcome_email

    post = _Captured()
    with patch.object(welcome_email, "MAILERSEND_API_KEY", "k"), \
         patch.object(welcome_email.httpx, "post", post):
        welcome_email._dispatch("u@example.com", "s", "t", "<p>h</p>")

    assert post.payload["from"]["name"] == MAILERSEND_PERSON_FROM_NAME


def test_inactivity_email_is_sent_by_a_person():
    from workers import inactivity_nudge

    post = _Captured()
    with patch.object(inactivity_nudge, "MAILERSEND_API_KEY", "k"), \
         patch.object(inactivity_nudge.httpx, "post", post):
        inactivity_nudge._send_email("u@example.com", "s", "<p>h</p>")

    assert post.payload["from"]["name"] == MAILERSEND_PERSON_FROM_NAME


# ── The reason the rule exists ──


def test_the_emails_that_ask_for_a_reply_still_ask_for_one():
    """The sender-name fix is only worth anything because these emails
    invite a reply. If that invitation is ever edited out, the constant
    stops mattering and this test should be revisited rather than silently
    left passing."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for module_path in ("models/ms_token.py", "routers/account.py"):
        src = (root / module_path).read_text(encoding="utf-8")
        assert "reply to this email" in src, (
            f"{module_path} no longer asks the customer to reply"
        )
