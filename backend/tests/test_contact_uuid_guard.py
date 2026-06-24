"""Regression test: get_contact must not query the DB with a non-UUID id.

The public tracking routes (/t, /c, /unsubscribe) take a `contact_id`
straight from the URL. Email scanners and link-truncating clients hit
those routes with garbage / truncated ids (e.g. "NjhjYWRjMT"). Because
contacts.id is a Postgres UUID column, a non-UUID value made the driver
raise `invalid input syntax for type uuid` (22P02) → unhandled 500 →
PostHog $exception noise.

get_contact now validates the id format and short-circuits to None for
anything that isn't a UUID, so every tracking route falls into its
existing "contact not found" path (a clean 200) instead of crashing.
"""
from unittest.mock import MagicMock, patch

from models import contact as contact_model


def test_get_contact_rejects_non_uuid_without_db_call():
    """A truncated / non-UUID id returns None and never touches the DB."""
    with patch("models.contact.get_db") as mock_db:
        for bad_id in ("NjhjYWRjMT", "", "not-a-uuid", "123", "contact-001"):
            assert contact_model.get_contact(bad_id) is None
        mock_db.assert_not_called()


def test_get_contact_valid_uuid_queries_db():
    """A well-formed UUID still hits the DB and returns the row."""
    row = {"id": "550e8400-e29b-41d4-a716-446655440000", "email": "a@b.com"}
    with patch("models.contact.get_db") as mock_db:
        (
            mock_db.return_value.table.return_value.select.return_value
            .eq.return_value.execute.return_value
        ) = MagicMock(data=[row])
        result = contact_model.get_contact("550e8400-e29b-41d4-a716-446655440000")
        assert result == row
        mock_db.assert_called()


def test_get_contact_accepts_uppercase_uuid():
    """UUIDs are case-insensitive; an uppercase one must not be rejected."""
    with patch("models.contact.get_db") as mock_db:
        (
            mock_db.return_value.table.return_value.select.return_value
            .eq.return_value.execute.return_value
        ) = MagicMock(data=[])
        contact_model.get_contact("550E8400-E29B-41D4-A716-446655440000")
        mock_db.assert_called()
