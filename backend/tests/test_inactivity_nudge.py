"""Tests for the 3-tier inactivity notification beat tasks."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from tests.conftest import FakeQueryBuilder


# ── Feature flag gate ──


def test_tier_disabled_by_default(fake_db):
    from workers import inactivity_nudge

    with patch("workers.inactivity_nudge.INACTIVITY_NUDGE_ENABLED", False):
        r1 = inactivity_nudge.send_inactivity_nudges()
        r2 = inactivity_nudge.send_inactivity_warnings_60d()
        r3 = inactivity_nudge.send_inactivity_warnings_90d()

    for r in (r1, r2, r3):
        assert r["skipped"] == "disabled"
        assert r["notified"] == 0


# ── No-target cases ──


def test_tier_noop_when_no_targets(fake_db):
    from workers import inactivity_nudge

    fake_db.set_table("users", FakeQueryBuilder(data=[]))
    with patch("workers.inactivity_nudge.INACTIVITY_NUDGE_ENABLED", True), \
         patch("workers.inactivity_nudge._find_inactive_paid_users", return_value=[]):
        r = inactivity_nudge.send_inactivity_nudges()

    assert r == {"tier": "30d_nudge", "notified": 0, "considered": 0}


# ── Happy paths — one per tier ──


def _inactive_user(days: int, stamp_col: str | None = None):
    now = datetime.now(timezone.utc)
    row = {
        "id": f"u-{days}d",
        "email": f"u{days}@example.com",
        "name": f"User{days}",
        "last_activity_at": (now - timedelta(days=days)).isoformat(),
    }
    if stamp_col:
        row[stamp_col] = None
    return row


class _RecordingUsers(FakeQueryBuilder):
    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(vals)
        return super().update(vals)


def test_30d_tier_sends_email_and_stamps(fake_db):
    from workers import inactivity_nudge

    user = _inactive_user(45, "inactivity_nudge_sent_at")
    users = _RecordingUsers(rows=[user])
    fake_db.set_table("users", users)

    with patch("workers.inactivity_nudge.INACTIVITY_NUDGE_ENABLED", True), \
         patch("workers.inactivity_nudge._find_inactive_paid_users",
               return_value=[user]), \
         patch("workers.inactivity_nudge._send_email", return_value=True):
        r = inactivity_nudge.send_inactivity_nudges()

    assert r["notified"] == 1
    # 30d tier stamps inactivity_nudge_sent_at
    stamped = [u for u in users.update_calls if "inactivity_nudge_sent_at" in u]
    assert len(stamped) == 1


def test_60d_tier_stamps_correct_column(fake_db):
    from workers import inactivity_nudge

    user = _inactive_user(65, "inactivity_warning_60d_sent_at")
    users = _RecordingUsers(rows=[user])
    fake_db.set_table("users", users)

    with patch("workers.inactivity_nudge.INACTIVITY_NUDGE_ENABLED", True), \
         patch("workers.inactivity_nudge._find_inactive_paid_users",
               return_value=[user]), \
         patch("workers.inactivity_nudge._send_email", return_value=True):
        inactivity_nudge.send_inactivity_warnings_60d()

    stamped = [u for u in users.update_calls if "inactivity_warning_60d_sent_at" in u]
    assert len(stamped) == 1
    # Must NOT touch the other tiers' stamp columns
    assert not any("inactivity_nudge_sent_at" in u for u in users.update_calls)
    assert not any("inactivity_warning_90d_sent_at" in u for u in users.update_calls)


def test_90d_tier_stamps_correct_column(fake_db):
    from workers import inactivity_nudge

    user = _inactive_user(95, "inactivity_warning_90d_sent_at")
    users = _RecordingUsers(rows=[user])
    fake_db.set_table("users", users)

    with patch("workers.inactivity_nudge.INACTIVITY_NUDGE_ENABLED", True), \
         patch("workers.inactivity_nudge._find_inactive_paid_users",
               return_value=[user]), \
         patch("workers.inactivity_nudge._send_email", return_value=True):
        inactivity_nudge.send_inactivity_warnings_90d()

    stamped = [u for u in users.update_calls if "inactivity_warning_90d_sent_at" in u]
    assert len(stamped) == 1


# ── Failure modes ──


def test_tier_skips_stamp_when_email_fails(fake_db):
    from workers import inactivity_nudge

    user = _inactive_user(45)
    users = _RecordingUsers(rows=[user])
    fake_db.set_table("users", users)

    with patch("workers.inactivity_nudge.INACTIVITY_NUDGE_ENABLED", True), \
         patch("workers.inactivity_nudge._find_inactive_paid_users",
               return_value=[user]), \
         patch("workers.inactivity_nudge._send_email", return_value=False):
        r = inactivity_nudge.send_inactivity_nudges()

    assert r["notified"] == 0
    # No stamp written — next run retries
    assert not any("inactivity_nudge_sent_at" in u for u in users.update_calls)


# ── Finder idempotency ──


def test_find_skips_when_stamp_is_current(fake_db):
    """Already-notified user in the current streak is filtered out."""
    from workers.inactivity_nudge import TIERS, _find_inactive_paid_users

    now = datetime.now(timezone.utc)
    tier60 = TIERS[1]  # 60d tier
    already = {
        "id": "u-seen",
        "last_activity_at": (now - timedelta(days=65)).isoformat(),
        # Stamp is AFTER last_activity_at → current streak, skip
        tier60.stamp_column: (now - timedelta(days=3)).isoformat(),
    }
    came_back = {
        "id": "u-returning",
        "last_activity_at": (now - timedelta(days=62)).isoformat(),
        # Stamp predates last_activity → they came back then went idle
        tier60.stamp_column: (now - timedelta(days=120)).isoformat(),
    }
    never_nudged = {
        "id": "u-new-inactive",
        "last_activity_at": (now - timedelta(days=70)).isoformat(),
        tier60.stamp_column: None,
    }

    mock_db = MagicMock()
    mock_db.table.return_value = FakeQueryBuilder(
        data=[already, came_back, never_nudged]
    )

    result = _find_inactive_paid_users(mock_db, tier60)
    ids = [u["id"] for u in result]
    assert "u-seen" not in ids
    assert "u-returning" in ids
    assert "u-new-inactive" in ids


# ── Tone locks ──
#
# The copy moved to emails/strings/<lang>.json on 2026-08-14, so these render
# through the catalog now. They are the same assertions: what the three tiers
# must and must not say, in a product where the person receiving them is
# paying us and has done nothing wrong.


def _tier_texts(name="Alice", days=45, lang=None):
    """Every tier's rendered words, subject included, lowercased."""
    from emails import render
    from workers.inactivity_nudge import TIERS

    out = {}
    for tier in TIERS:
        msg = render(tier.template, lang=lang, name=name, days=days)
        out[tier.name] = f"{msg.subject}\n{msg.text}\n{msg.html}".lower()
    return out


def test_email_tone_is_warm_not_dunning():
    """All three tiers must keep a warm, non-threatening tone.
    These go to paying customers who did nothing wrong — a future
    edit making them aggressive would break the trust compact."""
    for tier_name, body in _tier_texts().items():
        for bad in ["you owe", "overdue", "final notice", "last chance",
                    "delinquent", "collection"]:
            assert bad not in body, \
                f"{tier_name} contains dunning language: {bad}"


def test_sender_name_is_a_person_not_the_feedback_desk():
    """These emails ask the customer to reply and say a person reads every
    one. MAILERSEND_FROM_NAME defaults to "OutMass Feedback" — correct for
    the feedback form, which mails US, and corrosive here: the ask is not
    credible over an automation-desk name."""
    import re

    from unittest.mock import patch

    from workers import inactivity_nudge

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(json or {})
        class _R:
            status_code = 200
        return _R()

    with patch.object(inactivity_nudge, "MAILERSEND_API_KEY", "key"), \
         patch.object(inactivity_nudge.httpx, "post", fake_post):
        inactivity_nudge._send_email("x@y.com", "s", "t", "<p>h</p>")

    assert captured["from"]["name"] == "Ali from OutMass"
    src = open(inactivity_nudge.__file__, encoding="utf-8").read()
    assert not re.search(r'"name":\s*MAILERSEND_FROM_NAME', src), (
        "the sender name is back on the shared config value, which the "
        "feedback path owns"
    )


def test_tier1_does_not_assume_they_uninstalled():
    """Inverted 2026-08-10. The trigger is INACTIVITY, not uninstalling, and
    telling someone to reinstall describes something that did not happen —
    the one customer this would have reached had been silent 33 days and had
    auto-updated through four releases to 0.2.0 in the meantime. The 30-day
    note points at the panel they already have."""
    body = _tier_texts(name="X", days=30)["30d_nudge"]
    assert "reinstall" not in body
    assert "outlook" in body, "it must say where to find the panel instead"


def test_no_tier_hardcodes_a_browser_store():
    """install_source is captured for PostHog but never stored on the user
    row, so the worker cannot tell a Chrome install from an Edge one. A
    hardcoded Chrome link would send Edge customers to the wrong store —
    and Edge is a live channel.

    Checked in EVERY language, unlike the wording locks around it: a URL is
    the one thing a translator can add without knowing they have made a
    decision, and the one thing nobody reviewing an unfamiliar script spots.
    """
    from emails import available_languages

    for lang in available_languages():
        for tier_name, body in _tier_texts(name="X", lang=lang).items():
            assert "chromewebstore" not in body, (
                f"{tier_name}/{lang} hardcodes Chrome"
            )
            assert "microsoftedge" not in body, (
                f"{tier_name}/{lang} hardcodes Edge"
            )


def test_every_tier_asks_what_went_wrong():
    """The first version offered keep-or-cancel and never asked why they
    stopped. With a handful of paying customers that answer is worth more
    than the subscription, and only they have it."""
    for tier_name, body in _tier_texts(name="X").items():
        assert "reply" in body, f"{tier_name} gives them no way to answer"
        asks = any(p in body for p in
                   ("got in the way", "went wrong", "stopped you"))
        assert asks, f"{tier_name} never asks what stopped them"


def test_tier3_promises_no_follow_up_it_cannot_keep():
    """Inverted 2026-08-10. It used to commit to a person contacting them.
    There is one person here, and 90 days is the LAST tier — so both "we
    will call you" and "we will write once more" are promises with nothing
    behind them. It now says the emails stop, which is true."""
    body = _tier_texts(name="Bob", days=90)["90d_warning"]
    assert "contact you personally" not in body
    assert "last automatic email" in body
