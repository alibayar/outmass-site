"""Tests for the send-time quota cap signal.

When a campaign has more pending recipients than the user's remaining monthly
quota, /send caps the batch (pending[:remaining]) — that part always worked.
But the cap used to be SILENT: the response said "queued: 47" and nothing told
the user the other 53 were skipped for quota, so they believed the whole list
went out. These tests lock in the explicit signal:

    quota_capped   — True when the batch was truncated by quota
    quota_skipped  — how many pending recipients did NOT enter this batch

Also locks the 402 limit_exceeded message being English (it was hardcoded
Turkish while most users are English-speaking).
"""
from unittest.mock import AsyncMock, patch

from config import FREE_PLAN_MONTHLY_LIMIT
from tests.conftest import FAKE_USER, FakeQueryBuilder


def _campaign(cid):
    return {
        "id": cid, "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{firstName}}", "body": "Welcome {{firstName}}",
        "name": "Quota test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 5,
    }


def _contacts(n):
    return [
        {"id": f"k{i}", "email": f"u{i}@example.com", "status": "pending",
         "unsubscribed": False, "first_name": "A", "last_name": "B",
         "company": "", "position": "", "custom_fields": {}}
        for i in range(n)
    ]


def _install(fake_db, campaign, contacts, user):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    fake_db.set_table("contacts", FakeQueryBuilder(data=contacts))
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))
    fake_db.set_table("ab_tests", FakeQueryBuilder(data=[]))
    fake_db.set_table("users", FakeQueryBuilder(data=[user]))


def _override_user(user):
    from routers.auth import get_current_user
    from main import app

    async def _u():
        return user

    app.dependency_overrides[get_current_user] = _u
    return app


def test_send_caps_to_remaining_quota_and_reports_it(client, fake_db):
    """2 quota left, 5 pending → queued=2, quota_capped=True, quota_skipped=3."""
    user = {**FAKE_USER, "emails_sent_this_month": FREE_PLAN_MONTHLY_LIMIT - 2}
    app = _override_user(user)
    try:
        camp = _campaign("cq1")
        _install(fake_db, camp, _contacts(5), user)
        with patch("models.ms_token.get_fresh_access_token", return_value="tok"), \
             patch("routers.campaigns._send_single_email",
                   new=AsyncMock(return_value={"success": True})):
            resp = client.post("/campaigns/cq1/send",
                               headers={"Authorization": "Bearer t"})
    finally:
        from routers.auth import get_current_user
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["queued"] == 2
    assert body["quota_capped"] is True
    assert body["quota_skipped"] == 3


def test_send_within_quota_reports_no_cap(client, fake_db, auth_bypass):
    """Plenty of quota → quota_capped=False, quota_skipped=0."""
    camp = _campaign("cq2")
    _install(fake_db, camp, _contacts(3), FAKE_USER)
    with patch("models.ms_token.get_fresh_access_token", return_value="tok"), \
         patch("routers.campaigns._send_single_email",
               new=AsyncMock(return_value={"success": True})):
        resp = client.post("/campaigns/cq2/send",
                           headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["queued"] == 3
    assert body["quota_capped"] is False
    assert body["quota_skipped"] == 0


def test_capped_send_queues_quota_email(client, fake_db):
    """quota_skipped > 0 → the 'recipients saved, auto-resume' email is
    dispatched with the right numbers and the next rolling reset date."""
    from models import user as user_model

    user = {**FAKE_USER, "emails_sent_this_month": FREE_PLAN_MONTHLY_LIMIT - 2}
    app = _override_user(user)
    try:
        camp = _campaign("cq4")
        _install(fake_db, camp, _contacts(5), user)
        with patch("models.ms_token.get_fresh_access_token", return_value="tok"), \
             patch("routers.campaigns._send_single_email",
                   new=AsyncMock(return_value={"success": True})), \
             patch("routers.campaigns.welcome_email.send_quota_capped_email") as mail:
            resp = client.post("/campaigns/cq4/send",
                               headers={"Authorization": "Bearer t"})
    finally:
        from routers.auth import get_current_user
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    mail.assert_called_once()
    args = mail.call_args.args
    assert args[0] == user["email"]
    assert args[2] == 3  # skipped
    assert args[3] == FREE_PLAN_MONTHLY_LIMIT
    assert args[4] == user_model.next_reset_date(user).isoformat()


def test_uncapped_send_queues_no_quota_email(client, fake_db, auth_bypass):
    camp = _campaign("cq5")
    _install(fake_db, camp, _contacts(3), FAKE_USER)
    with patch("models.ms_token.get_fresh_access_token", return_value="tok"), \
         patch("routers.campaigns._send_single_email",
               new=AsyncMock(return_value={"success": True})), \
         patch("routers.campaigns.welcome_email.send_quota_capped_email") as mail:
        resp = client.post("/campaigns/cq5/send",
                           headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    mail.assert_not_called()


def test_limit_exceeded_message_is_english(client, fake_db):
    """Quota fully used → 402 limit_exceeded with an ENGLISH message."""
    user = {**FAKE_USER, "emails_sent_this_month": FREE_PLAN_MONTHLY_LIMIT}
    app = _override_user(user)
    try:
        camp = _campaign("cq3")
        _install(fake_db, camp, _contacts(2), user)
        with patch("models.ms_token.get_fresh_access_token", return_value="tok"):
            resp = client.post("/campaigns/cq3/send",
                               headers={"Authorization": "Bearer t"})
    finally:
        from routers.auth import get_current_user
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 402
    detail = resp.json()["detail"]
    assert detail["error"] == "limit_exceeded"
    assert "monthly limit" in detail["message"].lower()
    assert "ulastiniz" not in detail["message"]  # no leftover Turkish
