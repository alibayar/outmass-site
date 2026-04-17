"""Tests for cross-campaign dedup (Pro feature).

Behavior:
- Free/Starter users: flag is ignored entirely (no query overhead either).
- Pro users with dedup_enabled=False: flag is ignored.
- Pro users with dedup_enabled=True (default): upload_contacts filters out
  emails already present in previous campaigns (sent within lookback window,
  or pending regardless of age). The current campaign is excluded from the
  "previous" set.
- Response payload includes `skipped_previous` count.
"""
from unittest.mock import patch

from tests.conftest import (
    FAKE_USER,
    FAKE_PRO_USER,
    FAKE_STARTER_USER,
    FakeQueryBuilder,
)


# ── Fixtures & helpers ──


class _ContactsTable(FakeQueryBuilder):
    """Fake `contacts` table that branches on status filter.

    Maintains lists:
        sent_rows: returned when status == 'sent' and gte(sent_at, ...)
        pending_rows: returned when status == 'pending'
    Everything else returns [].
    """

    def __init__(self, sent_rows=None, pending_rows=None):
        super().__init__(data=[])
        self._sent_rows = sent_rows or []
        self._pending_rows = pending_rows or []
        self._status = None

    def eq(self, field, value):
        if field == "status":
            self._status = value
        return self

    def gte(self, *a):
        return self

    def insert(self, rows):
        # Mirror the real contacts insert path so bulk_insert succeeds.
        self._data = list(rows) if isinstance(rows, list) else [rows]
        self._status = None  # reset for next chain
        return self

    def execute(self):
        from unittest.mock import MagicMock

        if self._status == "sent":
            data = list(self._sent_rows)
        elif self._status == "pending":
            data = list(self._pending_rows)
        else:
            data = self._data
        self._status = None
        return MagicMock(data=data, count=self._count)


def _campaign(cid: str, user_id: str) -> dict:
    return {
        "id": cid, "user_id": user_id, "status": "draft",
        "subject": "s", "body": "b", "name": "n",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }


def _install(fake_db, campaign, sent_rows=None, pending_rows=None,
             other_campaign_ids=None):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign] + [
        {"id": cid, "user_id": campaign["user_id"]}
        for cid in (other_campaign_ids or [])
    ]))
    fake_db.set_table("contacts", _ContactsTable(sent_rows, pending_rows))
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))


# ── Tests ──


def test_free_user_no_dedup_query(client, fake_db, auth_bypass):
    """Free user: dedup flag ignored, all contacts inserted."""
    camp = _campaign("cF1", FAKE_USER["id"])
    _install(
        fake_db, camp,
        sent_rows=[{"email": "alice@example.com"}],  # would hit if enforced
        other_campaign_ids=["cOld"],
    )
    csv = "email\nalice@example.com\nbob@example.com\n"
    resp = client.post("/campaigns/cF1/contacts", json={"csv_string": csv})
    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped_previous"] == 0
    assert body["count"] == 2


def test_pro_user_dedup_skips_previous_sent(client, fake_db, auth_bypass_pro):
    """Pro user + enabled: alice already sent within window → skipped."""
    camp = _campaign("cP1", FAKE_PRO_USER["id"])
    _install(
        fake_db, camp,
        sent_rows=[{"email": "alice@example.com"}],
        other_campaign_ids=["cOld"],
    )
    csv = "email\nalice@example.com\nbob@example.com\n"
    resp = client.post("/campaigns/cP1/contacts", json={"csv_string": csv})
    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped_previous"] == 1
    assert body["count"] == 1  # only bob inserted


def test_pro_user_dedup_skips_pending_regardless_of_age(client, fake_db, auth_bypass_pro):
    """Pending contacts are always treated as 'previously contacted'."""
    camp = _campaign("cP2", FAKE_PRO_USER["id"])
    _install(
        fake_db, camp,
        pending_rows=[{"email": "carol@example.com"}],
        other_campaign_ids=["cQueued"],
    )
    csv = "email\ncarol@example.com\ndave@example.com\n"
    resp = client.post("/campaigns/cP2/contacts", json={"csv_string": csv})
    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped_previous"] == 1
    assert body["count"] == 1


def test_pro_user_dedup_disabled_skips_nothing(client, fake_db):
    """Pro user with explicitly disabled flag: no dedup applied."""
    from routers.auth import get_current_user
    from main import app

    pro_disabled = {**FAKE_PRO_USER, "cross_campaign_dedup_enabled": False}

    async def _override():
        return pro_disabled

    app.dependency_overrides[get_current_user] = _override
    try:
        camp = _campaign("cP3", pro_disabled["id"])
        _install(
            fake_db, camp,
            sent_rows=[{"email": "eve@example.com"}],
            other_campaign_ids=["cOld"],
        )
        csv = "email\neve@example.com\n"
        resp = client.post("/campaigns/cP3/contacts", json={"csv_string": csv})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped_previous"] == 0
    assert body["count"] == 1


def test_starter_user_no_dedup(client, fake_db, auth_bypass_standard):
    """Starter plan: dedup feature is Pro-only, so ignored even if enabled."""
    camp = _campaign("cS1", FAKE_STARTER_USER["id"])
    _install(
        fake_db, camp,
        sent_rows=[{"email": "frank@example.com"}],
        other_campaign_ids=["cOld"],
    )
    csv = "email\nfrank@example.com\n"
    resp = client.post("/campaigns/cS1/contacts", json={"csv_string": csv})
    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped_previous"] == 0
    assert body["count"] == 1


def test_pro_user_current_campaign_excluded_from_previous(client, fake_db, auth_bypass_pro):
    """A user re-uploading to the same campaign isn't counted as 'previous'."""
    camp = _campaign("cP4", FAKE_PRO_USER["id"])
    # Simulate: previous query finds no other campaigns (only this one).
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[camp]))
    fake_db.set_table("contacts", _ContactsTable(
        sent_rows=[{"email": "grace@example.com"}],
    ))
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))
    csv = "email\ngrace@example.com\n"
    resp = client.post("/campaigns/cP4/contacts", json={"csv_string": csv})
    assert resp.status_code == 200
    body = resp.json()
    # No other campaign IDs → no prior contacts fetched → no skip.
    assert body["skipped_previous"] == 0
    assert body["count"] == 1


# ── Settings endpoint ──


def test_update_settings_accepts_dedup_fields(client, fake_db, auth_bypass):
    fake_db.set_table("users", FakeQueryBuilder(data=[FAKE_USER]))
    resp = client.put("/settings", json={
        "cross_campaign_dedup_enabled": False,
        "cross_campaign_dedup_days": 30,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["cross_campaign_dedup_enabled"] is False
    assert body["cross_campaign_dedup_days"] == 30


def test_update_settings_clamps_dedup_days(client, fake_db, auth_bypass):
    fake_db.set_table("users", FakeQueryBuilder(data=[FAKE_USER]))
    resp = client.put("/settings", json={"cross_campaign_dedup_days": 5})
    assert resp.status_code == 200
    # Clamped to 7
    assert resp.json()["cross_campaign_dedup_days"] == 7

    resp = client.put("/settings", json={"cross_campaign_dedup_days": 9999})
    assert resp.status_code == 200
    # Clamped to 730
    assert resp.json()["cross_campaign_dedup_days"] == 730


def test_get_settings_exposes_dedup_defaults(client, fake_db, auth_bypass):
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cross_campaign_dedup_enabled"] is True
    assert body["cross_campaign_dedup_days"] == 60
