"""Daily send cap (multi-day spread) tests.

A campaign with daily_send_cap=N sends at most N contacts per beat-day;
the worker then advances scheduled_for by ~24h and stays 'scheduled' until
no resumable contacts remain. Shipped for a Starter customer who upgraded
for exactly this after a blog post promised it prematurely (2026-07-15).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.conftest import FAKE_STARTER_USER


def _contacts(n):
    return [
        {"id": f"ct-{i}", "email": f"r{i}@example.com", "unsubscribed": False}
        for i in range(n)
    ]


def _campaign(cap):
    return {
        "id": "camp-1",
        "user_id": FAKE_STARTER_USER["id"],
        "subject": "Hi {{firstName}}",
        "body": "Hello",
        "daily_send_cap": cap,
        "attachments": [],
    }


def _run_worker(cap, resumable_side_effect):
    from workers import scheduled_worker

    sent_ids = []
    updates = []

    with patch("models.campaign.get_due_scheduled_campaigns", return_value=[_campaign(cap)]), \
         patch("models.user.get_by_id", return_value=dict(FAKE_STARTER_USER)), \
         patch("workers.scheduled_worker.get_fresh_access_token", return_value="tok"), \
         patch("models.contact.get_resumable_contacts", side_effect=resumable_side_effect), \
         patch("models.contact.mark_sent", side_effect=lambda cid: sent_ids.append(cid)), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.update_campaign", side_effect=lambda cid, payload: updates.append(payload)), \
         patch("models.user.increment_sent_count"), \
         patch("workers.scheduled_worker._send_email", return_value={"success": True}), \
         patch("workers.scheduled_worker.time.sleep"):
        scheduled_worker.process_scheduled_campaigns()

    return sent_ids, updates


def test_cap_limits_todays_batch_and_requeues_tomorrow(fake_db):
    """5 pending, cap 2 → exactly 2 sent, campaign back to 'scheduled' ~+1 day."""
    sent_ids, updates = _run_worker(
        cap=2,
        resumable_side_effect=[_contacts(5), _contacts(3)],
    )

    assert len(sent_ids) == 2
    final = updates[-1]
    assert final["status"] == "scheduled"
    next_run = datetime.fromisoformat(final["scheduled_for"])
    delta = next_run - datetime.now(timezone.utc)
    assert timedelta(hours=23) < delta < timedelta(hours=25)


def test_cap_campaign_completes_when_list_exhausted(fake_db):
    """Final batch (nothing resumable afterwards) → status 'sent', no requeue."""
    sent_ids, updates = _run_worker(
        cap=5,
        resumable_side_effect=[_contacts(2), []],
    )

    assert len(sent_ids) == 2
    assert updates[-1] == {"status": "sent"}


def test_no_cap_keeps_existing_single_pass_behavior(fake_db):
    """cap None/absent → whole batch goes out and campaign closes as before."""
    sent_ids, updates = _run_worker(
        cap=None,
        resumable_side_effect=[_contacts(3)],
    )

    assert len(sent_ids) == 3
    assert updates[-1] == {"status": "sent"}


# ── create endpoint accepts / validates the field ──


def test_create_rejects_cap_without_schedule(client, fake_db, auth_bypass_standard):
    resp = client.post(
        "/campaigns",
        json={"name": "C", "subject": "s", "body": "b", "daily_send_cap": 30},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "cap_requires_schedule"


def test_create_passes_cap_through_and_clamps(client, fake_db, auth_bypass_standard):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return {"id": "camp-9", "status": "scheduled"}

    with patch("routers.campaigns.campaign_model.create_campaign", side_effect=fake_create):
        resp = client.post(
            "/campaigns",
            json={
                "name": "C",
                "subject": "s",
                "body": "b",
                "scheduled_for": "2026-08-01T09:00:00Z",
                "daily_send_cap": 999999,
            },
        )

    assert resp.status_code == 200
    assert captured["daily_send_cap"] == 5000  # clamped


def test_create_zero_cap_means_no_cap(client, fake_db, auth_bypass_standard):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return {"id": "camp-9", "status": "scheduled"}

    with patch("routers.campaigns.campaign_model.create_campaign", side_effect=fake_create):
        resp = client.post(
            "/campaigns",
            json={
                "name": "C",
                "subject": "s",
                "body": "b",
                "scheduled_for": "2026-08-01T09:00:00Z",
                "daily_send_cap": 0,
            },
        )

    assert resp.status_code == 200
    assert captured["daily_send_cap"] is None
