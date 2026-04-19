"""Tests for the launch notify-me endpoint."""
from tests.conftest import FakeQueryBuilder


class _LaunchTable(FakeQueryBuilder):
    """Captures inserts + lets tests seed existing rows for dup check."""

    def __init__(self, existing=None):
        super().__init__(data=[])
        self._existing = list(existing or [])
        self.captured = []
        self._mode = None  # "select" vs "insert"

    def select(self, *a, **kw):
        self._mode = "select"
        return self

    def insert(self, rows):
        self._mode = "insert"
        if isinstance(rows, list):
            self.captured.extend(rows)
        else:
            self.captured.append(rows)
        return self

    def execute(self):
        from unittest.mock import MagicMock

        if self._mode == "select":
            self._mode = None
            return MagicMock(data=list(self._existing), count=None)
        self._mode = None
        return MagicMock(data=self.captured, count=None)


def test_notify_accepts_new_email(client, fake_db):
    table = _LaunchTable()
    fake_db.set_table("launch_subscribers", table)
    resp = client.post(
        "/launch/notify",
        json={"email": "alice@example.com", "locale": "en", "source": "landing"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "subscribed"
    assert body["email"] == "alice@example.com"
    assert len(table.captured) == 1
    assert table.captured[0]["email"] == "alice@example.com"
    assert table.captured[0]["locale"] == "en"
    assert table.captured[0]["source"] == "landing"


def test_notify_lowercases_email(client, fake_db):
    table = _LaunchTable()
    fake_db.set_table("launch_subscribers", table)
    resp = client.post(
        "/launch/notify", json={"email": "Alice@Example.COM"}
    )
    assert resp.status_code == 200
    assert table.captured[0]["email"] == "alice@example.com"


def test_notify_detects_duplicate_case_insensitive(client, fake_db):
    table = _LaunchTable(existing=[{"id": "x", "email": "alice@example.com"}])
    fake_db.set_table("launch_subscribers", table)
    resp = client.post(
        "/launch/notify", json={"email": "ALICE@example.com"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_subscribed"
    # Nothing new inserted
    assert table.captured == []


def test_notify_rejects_malformed_email(client, fake_db):
    fake_db.set_table("launch_subscribers", _LaunchTable())
    resp = client.post("/launch/notify", json={"email": "not-an-email"})
    assert resp.status_code == 400


def test_notify_rejects_empty_email(client, fake_db):
    fake_db.set_table("launch_subscribers", _LaunchTable())
    resp = client.post("/launch/notify", json={"email": "   "})
    assert resp.status_code == 400


def test_notify_defaults_source_when_missing(client, fake_db):
    table = _LaunchTable()
    fake_db.set_table("launch_subscribers", table)
    resp = client.post("/launch/notify", json={"email": "bob@example.com"})
    assert resp.status_code == 200
    assert table.captured[0]["source"] == "landing"
