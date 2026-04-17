"""Tests for contact.bulk_insert: dedup, normalization, suppression filtering."""
from models import contact as contact_model
from tests.conftest import FakeQueryBuilder


class CaptureInsert(FakeQueryBuilder):
    """FakeQueryBuilder that records the rows passed to insert()."""

    def __init__(self):
        super().__init__(data=[])
        self.captured: list[dict] = []

    def insert(self, rows):
        if isinstance(rows, list):
            self.captured.extend(rows)
            self._data = list(rows)
        else:
            self.captured.append(rows)
            self._data = [rows]
        return self


def test_bulk_insert_dedupes_within_csv(fake_db):
    cap = CaptureInsert()
    fake_db.set_table("contacts", cap)
    rows = [
        {"email": "alice@example.com", "firstName": "Alice"},
        {"email": "alice@example.com", "firstName": "Alice2"},
        {"email": "bob@example.com", "firstName": "Bob"},
    ]
    result = contact_model.bulk_insert("camp1", rows)
    emails = [r["email"] for r in cap.captured]
    assert emails.count("alice@example.com") == 1
    assert "bob@example.com" in emails
    assert result["skipped_duplicate"] == 1


def test_bulk_insert_normalizes_email_case_insensitive(fake_db):
    cap = CaptureInsert()
    fake_db.set_table("contacts", cap)
    rows = [
        {"email": "Alice@Example.COM"},
        {"email": "alice@example.com"},  # dupe after normalize
    ]
    result = contact_model.bulk_insert("camp1", rows)
    assert len(cap.captured) == 1
    assert cap.captured[0]["email"] == "alice@example.com"
    assert result["skipped_duplicate"] == 1


def test_bulk_insert_filters_suppressed_emails(fake_db):
    cap = CaptureInsert()
    fake_db.set_table("contacts", cap)
    rows = [
        {"email": "keep@example.com"},
        {"email": "Blocked@Example.com"},  # uppercase, still matches suppression
    ]
    result = contact_model.bulk_insert(
        "camp1", rows, suppressed={"blocked@example.com"}
    )
    assert [r["email"] for r in cap.captured] == ["keep@example.com"]
    assert result["skipped_suppressed"] == 1


def test_bulk_insert_counts_invalid_separately(fake_db):
    cap = CaptureInsert()
    fake_db.set_table("contacts", cap)
    rows = [
        {"email": "valid@example.com"},
        {"email": "not-an-email"},
        {"email": ""},
    ]
    result = contact_model.bulk_insert("camp1", rows)
    assert result["inserted"] == 1
    assert result["skipped_invalid"] == 2


def test_bulk_insert_empty_list_returns_zero(fake_db):
    cap = CaptureInsert()
    fake_db.set_table("contacts", cap)
    result = contact_model.bulk_insert("camp1", [])
    assert result["inserted"] == 0
    assert result["skipped_invalid"] == 0
