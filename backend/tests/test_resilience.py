"""Tests for the v0.1.6 resilience features:
  - utils.graph_retry: bounded retry on 5xx + transient network errors
  - workers.scheduled_worker.reset_stuck_sending_campaigns
  - routers.campaigns: POST /campaigns/{id}/resume
  - routers.campaigns: /stats includes engaged_count + replied_count
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from tests.conftest import FAKE_USER, FakeQueryBuilder


# ── utils.graph_retry ──


def test_retry_returns_success_immediately():
    from utils.graph_retry import post_with_retry

    client = MagicMock()
    success_resp = MagicMock(status_code=202, headers={})
    client.post.return_value = success_resp

    resp = post_with_retry(client, "https://x", headers={}, json={})
    assert resp.status_code == 202
    assert client.post.call_count == 1


def test_retry_does_not_retry_4xx_other_than_429():
    """400/401/403/404 are permanent — retrying won't fix them."""
    from utils.graph_retry import post_with_retry

    client = MagicMock()
    fail_resp = MagicMock(status_code=400, headers={})
    client.post.return_value = fail_resp

    resp = post_with_retry(client, "https://x", headers={}, json={})
    assert resp.status_code == 400
    assert client.post.call_count == 1


def test_retry_retries_5xx_up_to_max_attempts():
    from utils.graph_retry import post_with_retry, MAX_ATTEMPTS

    client = MagicMock()
    fail_resp = MagicMock(status_code=503, headers={})
    client.post.return_value = fail_resp

    with patch("utils.graph_retry.time.sleep"):  # don't actually sleep
        resp = post_with_retry(client, "https://x", headers={}, json={})

    assert resp.status_code == 503
    assert client.post.call_count == MAX_ATTEMPTS


def test_retry_succeeds_after_5xx_then_200():
    from utils.graph_retry import post_with_retry

    client = MagicMock()
    fail_resp = MagicMock(status_code=502, headers={})
    success_resp = MagicMock(status_code=202, headers={})
    client.post.side_effect = [fail_resp, success_resp]

    with patch("utils.graph_retry.time.sleep"):
        resp = post_with_retry(client, "https://x", headers={}, json={})

    assert resp.status_code == 202
    assert client.post.call_count == 2


def test_retry_429_honours_retry_after_header():
    from utils.graph_retry import post_with_retry

    client = MagicMock()
    rate_limited = MagicMock(status_code=429, headers={"Retry-After": "7"})
    success = MagicMock(status_code=202, headers={})
    client.post.side_effect = [rate_limited, success]

    with patch("utils.graph_retry.time.sleep") as mock_sleep:
        post_with_retry(client, "https://x", headers={}, json={})

    # First sleep call should be the Retry-After value
    mock_sleep.assert_called_once_with(7)


def test_retry_on_network_error_then_success():
    from utils.graph_retry import post_with_retry

    client = MagicMock()
    success = MagicMock(status_code=202, headers={})
    client.post.side_effect = [
        httpx.ConnectError("network down"),
        success,
    ]

    with patch("utils.graph_retry.time.sleep"):
        resp = post_with_retry(client, "https://x", headers={}, json={})

    assert resp.status_code == 202
    assert client.post.call_count == 2


def test_retry_raises_network_error_after_max_attempts():
    from utils.graph_retry import post_with_retry, MAX_ATTEMPTS

    client = MagicMock()
    client.post.side_effect = httpx.ConnectError("persistent network failure")

    with patch("utils.graph_retry.time.sleep"):
        with pytest.raises(httpx.ConnectError):
            post_with_retry(client, "https://x", headers={}, json={})

    assert client.post.call_count == MAX_ATTEMPTS


# ── reset_stuck_sending_campaigns ──


def test_stuck_reset_does_nothing_when_no_stuck_campaigns(fake_db):
    from workers import scheduled_worker

    fake_db.set_table("campaigns", FakeQueryBuilder(data=[]))
    result = scheduled_worker.reset_stuck_sending_campaigns()
    assert result == {"reset_to_partial": 0, "reset_to_scheduled": 0}


def test_stuck_reset_marks_partial_when_some_sent(fake_db):
    """A stuck 'sending' campaign whose last send is old gets reset to
    'partial' so the user — and both resume paths — can see it."""
    from workers import scheduled_worker

    old_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    stuck = {
        "id": "c-stuck-progress",
        "scheduled_for": old_iso,
        "created_at": old_iso,
        "updated_at": old_iso,
        "sent_count": 5,
        "status": "sending",
    }

    class _CampaignsTable(FakeQueryBuilder):
        def __init__(self, rows):
            super().__init__(data=rows)
            self.update_calls = []

        def update(self, vals):
            self.update_calls.append(vals)
            return super().update(vals)

    campaigns = _CampaignsTable(rows=[stuck])
    contacts = FakeQueryBuilder(data=[{"sent_at": old_iso}])
    fake_db.set_table("campaigns", campaigns)
    fake_db.set_table("contacts", contacts)

    result = scheduled_worker.reset_stuck_sending_campaigns()
    assert result["reset_to_partial"] == 1
    assert result["reset_to_scheduled"] == 0
    assert any(u.get("status") == "partial" for u in campaigns.update_calls)


def test_stuck_reset_never_parks_a_campaign_on_scheduled(fake_db):
    """A campaign that made no progress must still become 'partial'.

    It used to be written back to 'scheduled'. For a Send-now campaign
    scheduled_for is NULL, and get_due_scheduled_campaigns filters
    `.lte("scheduled_for", now)`, which NULL never satisfies — so
    'scheduled' hid the campaign from the send beat, from Resume (409s
    unless 'partial'), from auto-resume ('partial' only) and from this
    sweep ('sending' only). Its recipients were reachable by nothing at
    all, and nobody was told.
    """
    from workers import scheduled_worker

    old_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    stuck = {
        "id": "c-stuck-fresh",
        "scheduled_for": None,
        "created_at": old_iso,
        "updated_at": old_iso,
        "sent_count": 0,
        "status": "sending",
    }

    class _CampaignsTable(FakeQueryBuilder):
        def __init__(self, rows):
            super().__init__(data=rows)
            self.update_calls = []

        def update(self, vals):
            self.update_calls.append(vals)
            return super().update(vals)

    campaigns = _CampaignsTable(rows=[stuck])
    fake_db.set_table("campaigns", campaigns)
    fake_db.set_table("contacts", FakeQueryBuilder(data=[]))  # nothing sent

    result = scheduled_worker.reset_stuck_sending_campaigns()
    assert result["reset_to_scheduled"] == 0
    assert campaigns.update_calls, "the campaign must still be recovered"
    assert all(u.get("status") == "partial" for u in campaigns.update_calls)


def test_stuck_reset_leaves_a_running_send_now_campaign_alone(fake_db):
    """THE duplicate-email bug.

    Send now leaves campaigns.scheduled_for NULL — only the scheduler
    ever writes it. The old freshness guard was
    `if scheduled_for and scheduled_for > cutoff`, so for every send-now
    campaign it short-circuited on the falsy NULL and the 30-minute
    window was skipped entirely. A campaign still delivering when the
    hourly beat fired was flipped to 'partial' mid-flight, and Resume or
    auto_resume_partial_campaigns could then start a SECOND loop over
    the contacts the first loop had not reached — emailing those people
    twice.

    Freshness now comes from the newest contacts.sent_at, which is
    written per recipient as the loop runs and cannot be NULL for a
    campaign that is genuinely progressing.
    """
    from workers import scheduled_worker

    running = {
        "id": "c-send-now",
        "scheduled_for": None,  # Send now never sets this
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
        "updated_at": (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat(),
        "sent_count": 1800,
        "status": "sending",
    }

    class _CampaignsTable(FakeQueryBuilder):
        def __init__(self, rows):
            super().__init__(data=rows)
            self.update_calls = []

        def update(self, vals):
            self.update_calls.append(vals)
            return super().update(vals)

    campaigns = _CampaignsTable(rows=[running])
    # A recipient went out 20 seconds ago: the loop is alive.
    just_now = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    fake_db.set_table("campaigns", campaigns)
    fake_db.set_table("contacts", FakeQueryBuilder(data=[{"sent_at": just_now}]))

    result = scheduled_worker.reset_stuck_sending_campaigns()
    assert result["reset_to_partial"] == 0, (
        "a campaign that sent 20 seconds ago is not stuck — flipping it "
        "invites a concurrent second send loop"
    )
    assert campaigns.update_calls == []


def test_stuck_reset_skips_a_campaign_that_has_not_sent_yet(fake_db):
    """Between /send returning and the first Graph call landing there are
    no sent contacts at all. That is normal, not stuck, so the row's own
    age is the fallback."""
    from workers import scheduled_worker

    fresh = {
        "id": "c-just-started",
        "scheduled_for": None,
        "created_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
        "updated_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
        "sent_count": 0,
        "status": "sending",
    }

    class _CampaignsTable(FakeQueryBuilder):
        def __init__(self, rows):
            super().__init__(data=rows)
            self.update_calls = []

        def update(self, vals):
            self.update_calls.append(vals)
            return super().update(vals)

    campaigns = _CampaignsTable(rows=[fresh])
    fake_db.set_table("campaigns", campaigns)
    fake_db.set_table("contacts", FakeQueryBuilder(data=[]))

    result = scheduled_worker.reset_stuck_sending_campaigns()
    assert result["reset_to_partial"] == 0
    assert campaigns.update_calls == []


def test_stuck_reset_skips_when_progress_cannot_be_measured(fake_db):
    """If the contacts lookup fails we cannot prove the campaign is stuck.

    Leaving a dead campaign in 'sending' costs an hour until the next
    beat. Flipping a live one costs its recipients a duplicate email, so
    the tie goes to doing nothing.
    """
    from workers import scheduled_worker

    old_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

    class _CampaignsTable(FakeQueryBuilder):
        def __init__(self, rows):
            super().__init__(data=rows)
            self.update_calls = []

        def update(self, vals):
            self.update_calls.append(vals)
            return super().update(vals)

    class _ExplodingContacts(FakeQueryBuilder):
        def execute(self):
            raise RuntimeError("contacts unavailable")

    campaigns = _PreMigrationCampaigns(rows=[{
        "id": "c-unknown",
        "scheduled_for": None,
        "created_at": old_iso,
        "sent_count": 3,
        "status": "sending",
    }])
    fake_db.set_table("campaigns", campaigns)
    fake_db.set_table("contacts", _ExplodingContacts(data=[]))

    result = scheduled_worker.reset_stuck_sending_campaigns()
    assert result["reset_to_partial"] == 0
    assert campaigns.update_calls == []


def test_stuck_reset_skips_recent_campaigns(fake_db):
    """A scheduled campaign whose last send is inside the 30-min window is
    legitimately processing, not stuck."""
    from workers import scheduled_worker

    recent_iso = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    fresh = {
        "id": "c-fresh",
        "scheduled_for": recent_iso,
        "created_at": recent_iso,
        "updated_at": recent_iso,
        "sent_count": 0,
        "status": "sending",
    }

    class _CampaignsTable(FakeQueryBuilder):
        def __init__(self, rows):
            super().__init__(data=rows)
            self.update_calls = []

        def update(self, vals):
            self.update_calls.append(vals)
            return super().update(vals)

    campaigns = _CampaignsTable(rows=[fresh])
    fake_db.set_table("campaigns", campaigns)
    fake_db.set_table("contacts", FakeQueryBuilder(data=[]))

    result = scheduled_worker.reset_stuck_sending_campaigns()
    assert result["reset_to_partial"] + result["reset_to_scheduled"] == 0
    assert campaigns.update_calls == []


class _PreMigrationCampaigns(FakeQueryBuilder):
    """campaigns without migration 025.

    PostgREST rejects an unknown column at the QUERY level, so selecting
    updated_at raises rather than returning rows without the key. That is the
    same trap migration 024 taught: a missing column is not a missing value.
    """

    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []
        self.select_attempts = []

    def select(self, *a, **kw):
        cols = a[0] if a else ""
        self.select_attempts.append(cols)
        if "updated_at" in cols:
            raise Exception('column campaigns.updated_at does not exist')
        return self

    def update(self, vals):
        self.update_calls.append(vals)
        return super().update(vals)


def test_resumed_run_is_not_judged_by_its_previous_run(fake_db):
    """THE case updated_at exists for.

    The interim fix measured freshness from the newest contacts.sent_at. For
    a campaign resumed after a quota reset that timestamp is from the PREVIOUS
    run — days old — so the campaign read as stale the instant it started
    sending again, and the mid-flight flip to 'partial' (and the duplicate
    send behind it) was reachable during its whole first 30 minutes.

    updated_at is stamped by the trigger on every write, including the
    per-recipient increment_stat, so a resumed run is fresh from its first
    update.
    """
    from workers import scheduled_worker

    class _CampaignsTable(FakeQueryBuilder):
        def __init__(self, rows):
            super().__init__(data=rows)
            self.update_calls = []

        def update(self, vals):
            self.update_calls.append(vals)
            return super().update(vals)

    long_ago = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    campaigns = _CampaignsTable(rows=[{
        "id": "c-resumed",
        "scheduled_for": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "created_at": long_ago,
        # Resumed a minute ago; its newest sent_at is still from last week.
        "updated_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        "sent_count": 250,
        "status": "sending",
    }])
    fake_db.set_table("campaigns", campaigns)
    fake_db.set_table("contacts", FakeQueryBuilder(data=[{"sent_at": long_ago}]))

    result = scheduled_worker.reset_stuck_sending_campaigns()
    assert result["reset_to_partial"] == 0, (
        "a campaign resumed one minute ago is not stuck, however old its "
        "previous run's sends are"
    )
    assert campaigns.update_calls == []


def test_falls_back_to_sent_at_when_migration_025_has_not_run(fake_db):
    """The column is selected optimistically every beat, so the sweep starts
    using it the moment Ali applies the migration — no deploy. Until then the
    2026-08-08 behaviour has to still work."""
    from workers import scheduled_worker

    old_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    campaigns = _PreMigrationCampaigns(rows=[{
        "id": "c-pre-025",
        "scheduled_for": None,
        "created_at": old_iso,
        "sent_count": 5,
        "status": "sending",
    }])
    fake_db.set_table("campaigns", campaigns)
    fake_db.set_table("contacts", FakeQueryBuilder(data=[{"sent_at": old_iso}]))

    result = scheduled_worker.reset_stuck_sending_campaigns()
    assert any("updated_at" in c for c in campaigns.select_attempts), (
        "the wide select must be retried every beat, not cached off"
    )
    assert result["reset_to_partial"] == 1
    assert all(u.get("status") == "partial" for u in campaigns.update_calls)


def test_a_row_without_updated_at_is_never_flipped(fake_db):
    """No basis to judge means do nothing. Flipping a live campaign costs its
    recipients a duplicate email; leaving a dead one costs an hour."""
    from workers import scheduled_worker

    class _CampaignsTable(FakeQueryBuilder):
        def __init__(self, rows):
            super().__init__(data=rows)
            self.update_calls = []

        def update(self, vals):
            self.update_calls.append(vals)
            return super().update(vals)

    campaigns = _CampaignsTable(rows=[{
        "id": "c-null-updated",
        "scheduled_for": None,
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),
        "updated_at": None,
        "sent_count": 1,
        "status": "sending",
    }])
    fake_db.set_table("campaigns", campaigns)
    fake_db.set_table("contacts", FakeQueryBuilder(data=[]))

    result = scheduled_worker.reset_stuck_sending_campaigns()
    assert result["reset_to_partial"] == 0
    assert campaigns.update_calls == []


# ── /campaigns/{id}/resume ──


def test_resume_404_for_other_users_campaign(client, fake_db, auth_bypass):
    other = {"id": "c-x", "user_id": "different-user", "status": "partial"}
    with patch("models.campaign.get_campaign", return_value=other):
        resp = client.post("/campaigns/c-x/resume")
    assert resp.status_code == 404


def test_resume_409_when_status_not_partial(client, fake_db, auth_bypass):
    sent = {"id": "c-sent", "user_id": FAKE_USER["id"], "status": "sent"}
    with patch("models.campaign.get_campaign", return_value=sent):
        resp = client.post("/campaigns/c-sent/resume")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "not_resumable"


def test_resume_marks_sent_when_no_pending(client, fake_db, auth_bypass):
    """Edge case: campaign is 'partial' but actually all contacts are
    already 'sent'. Resume should clean up the status, not enqueue."""
    partial = {"id": "c-done", "user_id": FAKE_USER["id"], "status": "partial"}
    with patch("models.campaign.get_campaign", return_value=partial), \
         patch("models.contact.get_resumable_contacts", return_value=[]), \
         patch("models.campaign.update_campaign") as mock_update:
        resp = client.post("/campaigns/c-done/resume")

    assert resp.status_code == 200
    body = resp.json()
    assert body["queued"] == 0
    assert body["status"] == "sent"
    update_arg = mock_update.call_args.args[1]
    assert update_arg.get("status") == "sent"


def test_resume_flips_to_scheduled_with_now(client, fake_db, auth_bypass):
    partial = {"id": "c-resume", "user_id": FAKE_USER["id"], "status": "partial"}
    pending = [{"id": f"co-{i}"} for i in range(3)]
    with patch("models.campaign.get_campaign", return_value=partial), \
         patch("models.contact.get_resumable_contacts", return_value=pending), \
         patch("models.campaign.update_campaign") as mock_update:
        resp = client.post("/campaigns/c-resume/resume")

    assert resp.status_code == 200
    body = resp.json()
    assert body["queued"] == 3
    assert body["status"] == "scheduled"
    update_arg = mock_update.call_args.args[1]
    assert update_arg.get("status") == "scheduled"
    assert "scheduled_for" in update_arg


# ── stats includes engaged + replied ──


def test_stats_response_includes_engaged_and_replied(client, fake_db, auth_bypass):
    """The /stats endpoint should always return engaged_count and
    replied_count fields (zero when no engagement data)."""
    campaign = {
        "id": "c-stats",
        "user_id": FAKE_USER["id"],
        "name": "Test",
        "status": "sent",
        "total_contacts": 10,
        "sent_count": 10,
        "open_count": 3,
        "click_count": 2,
    }
    contacts_data = [
        {"id": "1", "opened_at": "2026-01-01", "clicked_at": None, "replied_at": None},
        {"id": "2", "opened_at": "2026-01-01", "clicked_at": "2026-01-02", "replied_at": None},
        {"id": "3", "opened_at": None, "clicked_at": None, "replied_at": "2026-01-03"},
        {"id": "4", "opened_at": None, "clicked_at": None, "replied_at": None},
    ]
    fake_db.set_table("contacts", FakeQueryBuilder(data=contacts_data))

    with patch("models.campaign.get_campaign", return_value=campaign), \
         patch("models.followup.get_campaign_followups", return_value=[]):
        resp = client.get("/campaigns/c-stats/stats")

    assert resp.status_code == 200
    data = resp.json()
    # 3 distinct contacts engaged (1,2,3); only contact 3 replied
    assert data["engaged_count"] == 3
    assert data["replied_count"] == 1
    # rates should be present
    assert "engaged_rate" in data
    assert "reply_rate" in data
