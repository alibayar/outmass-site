"""Tests for _persist_ms_tokens — the OAuth-callback token storage rules.

Background (2026-07-16 incident): Microsoft omits the refresh_token on
some repeat consents, notably the incremental OneDrive flow. The old
code gated the ENTIRE write on refresh_token being present, which also
discarded the new wider-scope access_token and the has_onedrive_scope
flag. Result: /api/onedrive/browse kept using the stale Mail-only
access token (still valid for ~1h), returned needs_files_scope forever,
and the sidebar re-launched the consent window in a loop.

Rules under test:
  1. access_token is ALWAYS updated for an existing row.
  2. refresh_token is only written when Microsoft returned one.
  3. has_onedrive_scope goes (and stays) True once a OneDrive consent
     completes — even when that consent returned no refresh_token.
  4. No stored row + no refresh_token → nothing inserted (a row that
     can never refresh is useless); no crash.
"""
from tests.conftest import FakeQueryBuilder


class _RecordingTable(FakeQueryBuilder):
    """Records update() and insert() payloads for assertions."""

    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []
        self.insert_calls = []

    def update(self, vals):
        self.update_calls.append(vals)
        return self

    def insert(self, rows):
        self.insert_calls.append(rows)
        return self


def _run(fake_db, existing_rows, **kwargs):
    from routers.auth import _persist_ms_tokens

    table = _RecordingTable(rows=existing_rows)
    fake_db.set_table("user_tokens", table)
    _persist_ms_tokens(**kwargs)
    return table


def test_existing_row_with_refresh_token_updates_everything(fake_db):
    table = _run(
        fake_db,
        [{"id": "t1", "has_onedrive_scope": False}],
        user_id="u1",
        access_token="new-access",
        refresh_token="new-refresh",
        wants_onedrive=False,
    )
    assert len(table.update_calls) == 1
    row = table.update_calls[0]
    assert row["access_token"] == "new-access"
    assert row["refresh_token"] == "new-refresh"
    assert row["has_onedrive_scope"] is False
    assert not table.insert_calls


def test_missing_refresh_token_still_updates_access_token_and_scope(fake_db):
    """THE regression: incremental OneDrive consent without a
    refresh_token must still persist the new Files-scoped access token
    and flip has_onedrive_scope — otherwise browse loops on 403."""
    table = _run(
        fake_db,
        [{"id": "t1", "has_onedrive_scope": False}],
        user_id="u1",
        access_token="files-scoped-access",
        refresh_token=None,
        wants_onedrive=True,
    )
    assert len(table.update_calls) == 1
    row = table.update_calls[0]
    assert row["access_token"] == "files-scoped-access"
    assert row["has_onedrive_scope"] is True
    # Must NOT clobber the stored refresh_token with nothing
    assert "refresh_token" not in row


def test_onedrive_scope_flag_is_sticky_across_mail_only_signin(fake_db):
    """A later Mail-only sign-in must not clear an earlier OneDrive
    grant — the consent record at Microsoft outlives our tokens."""
    table = _run(
        fake_db,
        [{"id": "t1", "has_onedrive_scope": True}],
        user_id="u1",
        access_token="mail-access",
        refresh_token="mail-refresh",
        wants_onedrive=False,
    )
    assert table.update_calls[0]["has_onedrive_scope"] is True


def test_first_signin_with_refresh_token_inserts_row(fake_db):
    table = _run(
        fake_db,
        [],
        user_id="u1",
        access_token="a",
        refresh_token="r",
        wants_onedrive=False,
    )
    assert len(table.insert_calls) == 1
    row = table.insert_calls[0]
    assert row["user_id"] == "u1"
    assert row["access_token"] == "a"
    assert row["refresh_token"] == "r"
    assert not table.update_calls


def test_first_signin_without_refresh_token_inserts_nothing(fake_db):
    """No row + no refresh_token: don't insert a half-usable row (it
    could never refresh), don't crash the callback either."""
    table = _run(
        fake_db,
        [],
        user_id="u1",
        access_token="a",
        refresh_token=None,
        wants_onedrive=True,
    )
    assert not table.insert_calls
    assert not table.update_calls
