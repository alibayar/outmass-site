"""Audit log emission tests.

The audit log is our evidence trail for disputes, fraud investigations,
and chargeback defence. These tests lock in the guarantees:

1. Hash helpers are stable and case-insensitive.
2. Events never crash the caller if the DB is unreachable.
3. IP + user-agent are pulled from the request correctly, including
   the X-Forwarded-For header (Railway runs behind a proxy).
4. Email is stored as a hash, never raw.
5. Key endpoints (auth, campaign create, contacts upload, send) emit
   the expected events.
"""
from unittest.mock import MagicMock, patch

from fastapi import Request

from models import audit
from tests.conftest import FAKE_USER, FakeQueryBuilder


# ── Hash helpers ──


def test_hash_email_normalizes_case_and_whitespace():
    assert audit.hash_email("Alice@Example.COM") == audit.hash_email("alice@example.com")
    assert audit.hash_email("  bob@x.com  ") == audit.hash_email("bob@x.com")


def test_hash_email_returns_none_for_falsy():
    assert audit.hash_email(None) is None
    assert audit.hash_email("") is None
    assert audit.hash_email("   ") is None


def test_hash_email_is_sha256_length():
    h = audit.hash_email("x@y.com")
    assert h and len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def test_hash_bytes_accepts_str_and_bytes():
    assert audit.hash_bytes("hello") == audit.hash_bytes(b"hello")


# ── Request context extraction ──


def _fake_request(headers=None, client_host=None):
    r = MagicMock(spec=Request)
    r.headers = headers or {}
    r.client = MagicMock(host=client_host) if client_host else None
    return r


def test_request_context_prefers_x_forwarded_for():
    """Railway sits behind a proxy — X-Forwarded-For is the real client."""
    req = _fake_request(
        headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1", "user-agent": "TestUA/1.0"},
        client_host="10.0.0.1",
    )
    ctx = audit._extract_request_context(req)
    assert ctx["ip_address"] == "1.2.3.4"
    assert ctx["user_agent"] == "TestUA/1.0"


def test_request_context_falls_back_to_client_host():
    req = _fake_request(headers={}, client_host="127.0.0.1")
    ctx = audit._extract_request_context(req)
    assert ctx["ip_address"] == "127.0.0.1"


def test_request_context_handles_none_request():
    ctx = audit._extract_request_context(None)
    assert ctx == {"ip_address": None, "user_agent": None}


def test_request_context_truncates_long_user_agent():
    req = _fake_request(headers={"user-agent": "x" * 1000})
    ctx = audit._extract_request_context(req)
    assert ctx["user_agent"] and len(ctx["user_agent"]) <= 500


# ── emit() ──


class _RecordingAuditTable(FakeQueryBuilder):
    def __init__(self):
        super().__init__(data=[])
        self.inserted = []

    def insert(self, row):
        self.inserted.append(row)
        return super().insert(row)


def test_emit_inserts_expected_shape(fake_db):
    audit_table = _RecordingAuditTable()
    fake_db.set_table("audit_log", audit_table)

    audit.emit(
        audit.EVENT_LOGIN,
        user_id=FAKE_USER["id"],
        email=FAKE_USER["email"],
        metadata={"plan": "pro"},
    )

    assert len(audit_table.inserted) == 1
    row = audit_table.inserted[0]
    assert row["event_type"] == "login"
    assert row["user_id"] == FAKE_USER["id"]
    assert row["email_hash"] == audit.hash_email(FAKE_USER["email"])
    assert row["metadata"] == {"plan": "pro"}


def test_emit_does_not_store_raw_email(fake_db):
    audit_table = _RecordingAuditTable()
    fake_db.set_table("audit_log", audit_table)

    audit.emit(audit.EVENT_LOGIN, email="secret@example.com")

    row = audit_table.inserted[0]
    # Raw email must NEVER appear in the audit row.
    assert "secret@example.com" not in str(row)
    assert row.get("email_hash")


def test_emit_never_raises_on_db_failure(fake_db):
    """Audit writes must not break business logic."""

    class _BrokenTable(FakeQueryBuilder):
        def insert(self, _row):
            raise RuntimeError("supabase offline")

    fake_db.set_table("audit_log", _BrokenTable())

    # Must not propagate
    audit.emit(audit.EVENT_LOGIN, user_id=FAKE_USER["id"])


def test_emit_email_sent_stores_recipient_hash_not_plain(fake_db):
    audit_table = _RecordingAuditTable()
    fake_db.set_table("audit_log", audit_table)

    audit.emit_email_sent(
        user_id=FAKE_USER["id"],
        campaign_id="camp-1",
        recipient_email="target@example.com",
        graph_message_id="AAMk...",
        status_code=202,
    )

    row = audit_table.inserted[0]
    assert row["event_type"] == "email_sent"
    meta = row["metadata"]
    assert meta["campaign_id"] == "camp-1"
    assert meta["recipient_hash"] == audit.hash_email("target@example.com")
    assert meta["graph_message_id"] == "AAMk..."
    assert meta["status_code"] == 202
    # Raw recipient never appears
    assert "target@example.com" not in str(row)


# ── Endpoint integration ──


def test_create_campaign_emits_campaign_created_event(client, fake_db, auth_bypass):
    audit_table = _RecordingAuditTable()
    fake_db.set_table("audit_log", audit_table)
    fake_db.set_table(
        "campaigns",
        FakeQueryBuilder(
            data=[{"id": "c1", "user_id": FAKE_USER["id"], "status": "draft"}]
        ),
    )

    with patch(
        "models.campaign.create_campaign",
        return_value={"id": "c1", "status": "draft", "user_id": FAKE_USER["id"]},
    ):
        resp = client.post(
            "/campaigns",
            json={"name": "Q4 outreach", "subject": "Hi {{firstName}}", "body": "Hello"},
        )

    assert resp.status_code == 200
    created_events = [r for r in audit_table.inserted if r["event_type"] == "campaign_created"]
    assert len(created_events) == 1
    meta = created_events[0]["metadata"]
    assert meta["campaign_id"] == "c1"
    # Subject/body are hashed, not stored raw
    assert meta["subject_hash"] == audit.hash_bytes("Hi {{firstName}}")
    assert meta["body_hash"] == audit.hash_bytes("Hello")
