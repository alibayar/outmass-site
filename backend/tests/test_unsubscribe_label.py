"""Regression test for the user's configurable unsubscribe label.

Before this test existed, scheduled_worker / followup_worker / email_worker
each had hardcoded "Abonelikten cik" in the email footer, ignoring the
user's Settings → Interface → Unsubscribe text override. A user who
typed "Unsubscribe" in Settings still got Turkish text in their
actual sent emails.

The fix: every _send_email / _send_followup_email takes an
`unsubscribe_text` kwarg sourced from the user row. These tests lock
that behaviour in so the hardcoded string doesn't silently regress.
"""
from unittest.mock import MagicMock, patch

from workers.followup_worker import _send_followup_email
from workers.scheduled_worker import _send_email


def _capturing_client(captured: list) -> MagicMock:
    """Stub httpx.Client that captures the last sendMail payload."""
    client = MagicMock()
    resp = MagicMock(status_code=202)
    resp.json.return_value = {}
    client.post = MagicMock(
        side_effect=lambda *a, **kw: (captured.append(kw.get("json")), resp)[1]
    )
    return client


_CAMPAIGN = {"id": "c1", "user_id": "u1", "subject": "Hi", "body": "Hello"}
_CONTACT = {"id": "co1", "email": "to@example.com", "first_name": "Jane"}


def test_scheduled_send_uses_user_unsubscribe_label():
    captured = []
    client = _capturing_client(captured)

    _send_email(
        client=client,
        access_token="tok",
        campaign=_CAMPAIGN,
        contact=_CONTACT,
        unsubscribe_text="Unsubscribe",
    )

    html = captured[-1]["message"]["body"]["content"]
    assert ">Unsubscribe</a>" in html
    assert "Abonelikten" not in html


def test_scheduled_send_default_is_english_not_turkish():
    """Callers that forget to pass the kwarg must not regress to Turkish.

    The default was explicitly changed from the old hardcoded
    "Abonelikten cik" to English "Unsubscribe" — if a future refactor
    drops the kwarg at the callsite, we want English, not Turkish.
    """
    captured = []
    client = _capturing_client(captured)

    _send_email(
        client=client,
        access_token="tok",
        campaign=_CAMPAIGN,
        contact=_CONTACT,
    )

    html = captured[-1]["message"]["body"]["content"]
    assert ">Unsubscribe</a>" in html
    assert "Abonelikten" not in html


def test_scheduled_send_escapes_html_in_label():
    """A malicious label must not break out of the <a> tag context."""
    captured = []
    client = _capturing_client(captured)

    _send_email(
        client=client,
        access_token="tok",
        campaign=_CAMPAIGN,
        contact=_CONTACT,
        unsubscribe_text='"><script>alert(1)</script>',
    )

    html = captured[-1]["message"]["body"]["content"]
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_followup_send_uses_user_unsubscribe_label():
    captured = []
    client = _capturing_client(captured)

    _send_followup_email(
        client=client,
        access_token="tok",
        campaign=_CAMPAIGN,
        followup={"subject": "Bump", "body": "Hey"},
        contact=_CONTACT,
        unsubscribe_text="Remove me",
    )

    html = captured[-1]["message"]["body"]["content"]
    assert ">Remove me</a>" in html
    assert "Abonelikten" not in html


def test_followup_send_default_is_english():
    captured = []
    client = _capturing_client(captured)

    _send_followup_email(
        client=client,
        access_token="tok",
        campaign=_CAMPAIGN,
        followup={"subject": "Bump", "body": "Hey"},
        contact=_CONTACT,
    )

    html = captured[-1]["message"]["body"]["content"]
    assert ">Unsubscribe</a>" in html
    assert "Abonelikten" not in html
