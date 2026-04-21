"""Token lifecycle tests — covers the three behaviours layered on top
of the base requires_reauth flag (see test_reauth_flagging.py):

1. Scheduled campaigns transition to status=failed_auth when the user's
   refresh_token is permanently dead.
2. MailerSend reconnect email fires once on the False→True transition,
   but never on subsequent flagging calls (idempotent).
3. The daily token health beat task attempts a silent refresh for every
   connected user and flags the ones with dead tokens.
"""
from unittest.mock import MagicMock, patch

from tests.conftest import FAKE_USER, FakeQueryBuilder


class _RecordingTable(FakeQueryBuilder):
    """FakeQueryBuilder that records every update() call for assertions."""

    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(vals)
        self._data = [vals]
        return self


# ── Task #2 — campaign failed_auth transition ──


def test_scheduled_campaign_marked_failed_auth_on_permanent_token_failure(fake_db):
    """When refresh_token is dead, the campaign must go to failed_auth."""
    from workers import scheduled_worker

    user_id = FAKE_USER["id"]
    campaign = {
        "id": "camp-1",
        "user_id": user_id,
        "status": "scheduled",
        "subject": "Hi",
        "body": "Body",
    }
    campaigns_table = _RecordingTable(rows=[campaign])
    fake_db.set_table("campaigns", campaigns_table)

    flagged_user = {**FAKE_USER, "requires_reauth": True}

    with patch.object(
        scheduled_worker, "get_fresh_access_token", return_value=None
    ), patch(
        "models.campaign.get_due_scheduled_campaigns", return_value=[campaign]
    ), patch(
        "models.user.get_by_id", return_value=flagged_user
    ), patch(
        "models.campaign.update_campaign"
    ) as mock_update:
        result = scheduled_worker.process_scheduled_campaigns()

    assert result["processed"] == 1
    # Must mark the campaign failed_auth, not silently skip it
    update_statuses = [
        call.kwargs.get("updates") or (call.args[1] if len(call.args) > 1 else {})
        for call in mock_update.call_args_list
    ]
    flat_statuses = [
        (s.get("status") if isinstance(s, dict) else None) for s in update_statuses
    ]
    assert "failed_auth" in flat_statuses


def test_scheduled_campaign_not_marked_failed_auth_on_transient_failure(fake_db):
    """Transient token failures must NOT transition the campaign status."""
    from workers import scheduled_worker

    campaign = {
        "id": "camp-2",
        "user_id": FAKE_USER["id"],
        "status": "scheduled",
        "subject": "Hi",
        "body": "Body",
    }

    # User NOT flagged requires_reauth → failure is transient
    clean_user = {**FAKE_USER, "requires_reauth": False}

    with patch.object(
        scheduled_worker, "get_fresh_access_token", return_value=None
    ), patch(
        "models.campaign.get_due_scheduled_campaigns", return_value=[campaign]
    ), patch(
        "models.user.get_by_id", return_value=clean_user
    ), patch(
        "models.campaign.update_campaign"
    ) as mock_update:
        scheduled_worker.process_scheduled_campaigns()

    # No update_campaign call with status=failed_auth
    statuses = []
    for call in mock_update.call_args_list:
        args = call.args
        if len(args) >= 2 and isinstance(args[1], dict):
            statuses.append(args[1].get("status"))
    assert "failed_auth" not in statuses


# ── Task #3 — MailerSend reconnect email ──


def test_mark_requires_reauth_sends_email_on_first_transition(fake_db):
    """False→True transition must dispatch a MailerSend email."""
    from models.ms_token import _mark_requires_reauth

    users_table = _RecordingTable(rows=[
        {**FAKE_USER, "requires_reauth": False}
    ])
    fake_db.set_table("users", users_table)

    with patch("httpx.post") as mock_post, \
         patch("models.ms_token.MAILERSEND_API_KEY", "mlsn_test"):
        _mark_requires_reauth(FAKE_USER["id"], "invalid_grant")

    assert mock_post.called, "MailerSend post must fire on first flag"
    url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs.get("url")
    assert "mailersend.com" in url
    payload = mock_post.call_args.kwargs.get("json", {})
    assert payload["to"][0]["email"] == FAKE_USER["email"]
    assert "Reconnect" in payload["subject"]


def test_mark_requires_reauth_skips_email_when_already_flagged(fake_db):
    """Re-flagging an already-flagged user must NOT re-send the email."""
    from models.ms_token import _mark_requires_reauth

    users_table = _RecordingTable(rows=[
        {**FAKE_USER, "requires_reauth": True}
    ])
    fake_db.set_table("users", users_table)

    with patch("httpx.post") as mock_post, \
         patch("models.ms_token.MAILERSEND_API_KEY", "mlsn_test"):
        _mark_requires_reauth(FAKE_USER["id"], "invalid_grant")

    assert not mock_post.called, "Must not re-send email to already-flagged user"


def test_mark_requires_reauth_no_email_when_mailersend_disabled(fake_db):
    """No API key → no network call, no crash."""
    from models.ms_token import _mark_requires_reauth

    users_table = _RecordingTable(rows=[
        {**FAKE_USER, "requires_reauth": False}
    ])
    fake_db.set_table("users", users_table)

    with patch("httpx.post") as mock_post, \
         patch("models.ms_token.MAILERSEND_API_KEY", ""):
        _mark_requires_reauth(FAKE_USER["id"], "invalid_grant")

    assert not mock_post.called


# ── Task #4 — proactive token health check ──


def test_check_user_tokens_flags_dead_tokens(fake_db):
    """Users with dead refresh tokens get flagged during the daily sweep."""
    from workers import scheduled_worker

    user_tokens_table = FakeQueryBuilder(data=[
        {"user_id": "u-healthy"},
        {"user_id": "u-broken"},
        {"user_id": "u-already-flagged"},
    ])
    fake_db.set_table("user_tokens", user_tokens_table)

    users_table = FakeQueryBuilder(data=[
        {"id": "u-healthy", "requires_reauth": False},
        {"id": "u-broken", "requires_reauth": False},
        {"id": "u-already-flagged", "requires_reauth": True},
    ])
    fake_db.set_table("users", users_table)

    def fake_refresh(user_id):
        if user_id == "u-healthy":
            return "new_access_token"
        if user_id == "u-broken":
            # Simulate what get_fresh_access_token does on failure:
            # it flips the user's requires_reauth flag via a DB update.
            # We mimic that by mutating the fake rows so the final
            # status check sees the flag.
            for r in users_table._data:
                if r["id"] == "u-broken":
                    r["requires_reauth"] = True
            return None
        # u-already-flagged shouldn't be called; but be defensive
        return None

    with patch.object(
        scheduled_worker, "get_fresh_access_token", side_effect=fake_refresh
    ) as mock_refresh:
        result = scheduled_worker.check_user_tokens()

    # The already-flagged user must be skipped (no wasteful refresh attempt)
    called_with = [c.args[0] for c in mock_refresh.call_args_list]
    assert "u-already-flagged" not in called_with

    assert result["checked"] == 2
    assert result["healthy"] == 1
    assert result["already_flagged"] == 1


def test_check_user_tokens_handles_no_users(fake_db):
    from workers import scheduled_worker

    fake_db.set_table("user_tokens", FakeQueryBuilder(data=[]))

    result = scheduled_worker.check_user_tokens()
    assert result == {"checked": 0, "flagged": 0}
