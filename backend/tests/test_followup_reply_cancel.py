"""Reply-cancels-followup: a contact with replied_at set must be
excluded from EVERY follow-up condition. Bumping someone who already
answered reads as spam; users assume this behavior exists (the site
once claimed it before the feature did — 2026-07-15 claims audit).
"""
from tests.conftest import FakeQueryBuilder


class _RecordingContacts(FakeQueryBuilder):
    """Records .is_() filters so we can assert the reply exclusion."""

    def __init__(self, rows):
        super().__init__(data=rows)
        self.is_calls = []

    def is_(self, column, value):
        self.is_calls.append((column, value))
        return self


def _run_filter(fake_db, condition):
    from workers.followup_worker import _get_filtered_contacts

    contacts = _RecordingContacts(rows=[])
    fake_db.set_table("contacts", contacts)
    _get_filtered_contacts(fake_db, "camp-1", condition)
    return contacts.is_calls


def test_replied_contacts_excluded_for_not_opened(fake_db):
    calls = _run_filter(fake_db, "not_opened")
    assert ("replied_at", "null") in calls
    assert ("opened_at", "null") in calls


def test_replied_contacts_excluded_for_not_clicked(fake_db):
    calls = _run_filter(fake_db, "not_clicked")
    assert ("replied_at", "null") in calls
    assert ("clicked_at", "null") in calls


def test_replied_contacts_excluded_for_unknown_condition(fake_db):
    """Even a condition with no extra filter (e.g. legacy 'all') must
    still exclude repliers."""
    calls = _run_filter(fake_db, "all")
    assert ("replied_at", "null") in calls
