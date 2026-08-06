"""Migration 024 unrun must be INERT — proven against PostgREST's real
failure mode, not a mock that shrugs.

The first version of the Mail.Read split claimed "a missing
has_mail_read_scope column reads as True everywhere". That was false:
PostgREST rejects unknown columns at the query level and supabase-py raises
postgrest.exceptions.APIError — it never returns a row that merely lacks the
key. Concretely, with migration 024 unrun the old code did this:

  * get_fresh_access_token → APIError 42703 → every send endpoint 500s and
    the followup/scheduled/reply beats die at the FIRST user they touch.
  * _persist_ms_tokens → 42703 on its select (and PGRST204 on its write) →
    every OAuth callback 500s through main.py's global handler, skipping
    _error_page and the settle redirect that keeps auth popups from hanging.

The suites couldn't see any of it because they fake the DB with MagicMock,
which accepts any column name. Every fake in THIS file is schema-faithful:
it raises a real APIError exactly where PostgREST would — 42703 for an
unknown column in a select, PGRST204 for an unknown key in a write, both at
execute() time. That is the regression fence: if the column guard is ever
removed, these tests reproduce the outage instead of staying green.

Also covered here: the guard's probe cache (steady state must not pay a
permanent double query), self-healing after the migration runs (no restart),
the guard's precision (foreign APIErrors must still raise), the audit record
carrying the scopes actually exchanged, and the narrow-re-sign-in token
invalidation.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest
from postgrest.exceptions import APIError

from config import MS_GRAPH_FIRST_SIGNIN_SCOPES, MS_GRAPH_SCOPES
from models import ms_token
from routers import auth as auth_module
from routers.auth import _encode_state
from tests.conftest import FAKE_USER, FakeQueryBuilder, FakeSupabase

CHROME_EXT = "adcfddainnkjomddlappnnbeomhlcbmm"

# user_tokens as it exists in production TODAY, before migration 024.
PRE_024_COLUMNS = frozenset(
    {
        "id",
        "user_id",
        "access_token",
        "refresh_token",
        "has_onedrive_scope",
        "created_at",
        "updated_at",
    }
)
POST_024_COLUMNS = PRE_024_COLUMNS | {"has_mail_read_scope"}


def _undefined_column_error(column: str) -> APIError:
    """What PostgreSQL/PostgREST answer for SELECTing an unknown column."""
    return APIError(
        {
            "message": f"column user_tokens.{column} does not exist",
            "code": "42703",
            "hint": None,
            "details": None,
        }
    )


def _schema_cache_error(column: str) -> APIError:
    """What PostgREST answers for an unknown key in an INSERT/UPDATE body."""
    return APIError(
        {
            "message": (
                f"Could not find the '{column}' column of 'user_tokens' "
                "in the schema cache"
            ),
            "code": "PGRST204",
            "hint": None,
            "details": None,
        }
    )


class SchemaTable(FakeQueryBuilder):
    """A user_tokens fake that enforces a column set the way PostgREST does.

    * select() naming an unknown column → APIError 42703, raised at
      execute() (that is when the HTTP request happens in supabase-py).
    * update()/insert() carrying an unknown key → APIError PGRST204 at
      execute(), BEFORE anything is written — mirroring PostgREST, which
      rejects the payload at schema-cache mapping time.
    * `write_columns` may lag `select_columns` to model the brief
      post-migration window where PostgREST's schema cache is stale.
    """

    def __init__(self, rows, select_columns, write_columns=None):
        super().__init__(data=list(rows))
        self._rows = list(rows)
        self.select_columns = set(select_columns)
        self.write_columns = set(
            write_columns if write_columns is not None else select_columns
        )
        self.select_attempts = []  # each: list of requested column names
        self.update_attempts = []  # each: payload dict (attempted)
        self.insert_attempts = []
        self.committed_writes = []  # each: ("update"|"insert", payload) that succeeded
        self._pending = ("select", None, None)

    def select(self, cols, *a, **kw):
        requested = [c.strip() for c in cols.split(",")]
        self.select_attempts.append(requested)
        unknown = [c for c in requested if c != "*" and c not in self.select_columns]
        err = _undefined_column_error(unknown[0]) if unknown else None
        self._pending = ("select", requested, err)
        return self

    def update(self, vals):
        payload = dict(vals)
        self.update_attempts.append(payload)
        self._pending = ("update", payload, self._write_error(payload))
        return self

    def insert(self, rows):
        payload = dict(rows[0] if isinstance(rows, list) else rows)
        self.insert_attempts.append(payload)
        self._pending = ("insert", payload, self._write_error(payload))
        return self

    def _write_error(self, payload):
        unknown = [k for k in payload if k not in self.write_columns]
        return _schema_cache_error(unknown[0]) if unknown else None

    def execute(self):
        kind, payload, err = self._pending
        self._pending = ("select", None, None)
        if err is not None:
            raise err
        if kind == "select":
            return MagicMock(data=list(self._rows))
        self.committed_writes.append((kind, payload))
        return MagicMock(data=[payload])


class AlwaysErrorTable(FakeQueryBuilder):
    """Raises one fixed APIError on every execute() — for precision tests."""

    def __init__(self, err):
        super().__init__(data=[])
        self._err = err

    def execute(self):
        raise self._err


# ── get_fresh_access_token: the path every send and every beat runs ──


def _get_fresh(table, user_id="u1"):
    """Run the REAL get_fresh_access_token against a schema-faithful fake,
    with the stored token expired (401 probe) and the refresh succeeding."""
    db = FakeSupabase()
    db.set_table("user_tokens", table)
    captured = {}

    def _fake_post(url, data=None, **kwargs):
        captured["scope"] = data.get("scope")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "access_token": "fresh-access",
            "refresh_token": "fresh-refresh",
        }
        return resp

    expired = MagicMock()
    expired.status_code = 401

    with patch.object(ms_token, "get_db", return_value=db), \
         patch.object(ms_token.httpx, "get", return_value=expired), \
         patch.object(ms_token.httpx, "post", side_effect=_fake_post):
        token = ms_token.get_fresh_access_token(user_id)
    return token, captured


_PRE_024_ROW = {
    "id": "t1",
    "user_id": "u1",
    "access_token": "stale",
    "refresh_token": "r",
    "has_onedrive_scope": False,
}


def test_refresh_survives_unrun_migration_and_stays_wide():
    """THE blocker: pre-024, the select raises 42703. The guard must fall
    back to a column-free select, keep the refresh scope WIDE (everyone who
    can exist pre-024 granted Mail.Read), and complete the refresh."""
    table = SchemaTable([dict(_PRE_024_ROW)], select_columns=PRE_024_COLUMNS)
    token, captured = _get_fresh(table)

    assert token == "fresh-access", "the refresh must complete, not raise"
    assert captured["scope"] == MS_GRAPH_SCOPES, (
        "pre-024 rows all belong to users who granted Mail.Read — narrowing "
        "here would silently kill reply detection for the whole base"
    )
    # First attempt was optimistic (with the column), fallback was without.
    assert "has_mail_read_scope" in table.select_attempts[0]
    assert "has_mail_read_scope" not in table.select_attempts[1]
    # The post-refresh token write went through too.
    assert ("update", {"access_token": "fresh-access", "refresh_token": "fresh-refresh"}) in table.committed_writes


def test_missing_column_is_cached_not_reprobed_per_call():
    """Requirement: no permanent double query. After one failed probe the
    process remembers and every later query is a single column-free select."""
    table = SchemaTable([dict(_PRE_024_ROW)], select_columns=PRE_024_COLUMNS)
    _get_fresh(table)
    assert len(table.select_attempts) == 2  # probe + fallback, once

    _get_fresh(table)
    assert len(table.select_attempts) == 3, (
        "second call must go straight to the fallback — one query, no probe"
    )
    assert "has_mail_read_scope" not in table.select_attempts[2]


def test_steady_state_after_migration_is_one_query_with_no_overhead():
    """The other half of requirement 2: once the column exists, the
    optimistic select just succeeds — exactly one query, no fallback."""
    row = {**_PRE_024_ROW, "has_mail_read_scope": True}
    table = SchemaTable([row], select_columns=POST_024_COLUMNS)
    token, captured = _get_fresh(table)

    assert token == "fresh-access"
    assert captured["scope"] == MS_GRAPH_SCOPES
    assert len(table.select_attempts) == 1


def test_column_appearing_heals_without_redeploy_or_restart():
    """Self-heal (requirement 3): once the probe window elapses, a process
    that cached 'missing' re-probes, finds the column, and starts READING
    it — proven by a narrow user's refresh going narrow again."""
    pre = SchemaTable([dict(_PRE_024_ROW)], select_columns=PRE_024_COLUMNS)
    _get_fresh(pre)
    assert ms_token._mail_read_column_state["missing"] is True

    # Migration 024 runs. Same process, no restart — only the probe window
    # elapsing (5 min in prod, forced here).
    narrow_row = {**_PRE_024_ROW, "has_mail_read_scope": False}
    post = SchemaTable([narrow_row], select_columns=POST_024_COLUMNS)
    ms_token._mail_read_column_state["retry_at"] = 0.0

    token, captured = _get_fresh(post)
    assert token == "fresh-access"
    assert captured["scope"] == MS_GRAPH_FIRST_SIGNIN_SCOPES, (
        "the healed process must actually READ the column again — a stale "
        "'missing' cache would over-request Mail.Read for this narrow user "
        "and AADSTS65001 their every background send"
    )
    assert ms_token._mail_read_column_state["missing"] is False


def test_foreign_api_errors_are_not_swallowed():
    """Precision (requirement 4): the guard catches exactly the missing-024
    column. Any other APIError — RLS denial, some OTHER missing column —
    must keep propagating, or real outages become silent wide-scope guesses."""
    rls = APIError(
        {
            "message": "permission denied for table user_tokens",
            "code": "42501",
            "hint": None,
            "details": None,
        }
    )
    db = FakeSupabase()
    db.set_table("user_tokens", AlwaysErrorTable(rls))
    with patch.object(ms_token, "get_db", return_value=db):
        with pytest.raises(APIError):
            ms_token.get_fresh_access_token("u1")
    assert ms_token._mail_read_column_state["missing"] is False

    other_column = _undefined_column_error("some_future_column")
    db.set_table("user_tokens", AlwaysErrorTable(other_column))
    with patch.object(ms_token, "get_db", return_value=db):
        with pytest.raises(APIError):
            ms_token.get_fresh_access_token("u1")
    assert ms_token._mail_read_column_state["missing"] is False


def test_user_has_mail_read_scope_is_true_via_fallback_not_via_crash():
    """/settings' scope lookup pre-024: True, and through the DESIGNED
    fallback (two selects: probe + column-free), not by the catch-all arm
    swallowing an exception after a single failed query."""
    table = SchemaTable([dict(_PRE_024_ROW)], select_columns=PRE_024_COLUMNS)
    db = FakeSupabase()
    db.set_table("user_tokens", table)
    with patch.object(ms_token, "get_db", return_value=db):
        assert ms_token.user_has_mail_read_scope("u1") is True
    assert len(table.select_attempts) == 2


# ── the OAuth callback: no sign-in may fail pre-migration ──


class _MSGraphStub:
    """Async-context httpx.AsyncClient stub: token exchange + Graph /me."""

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None, **kw):
        return MagicMock(
            status_code=200,
            content=b"{}",
            json=lambda: {
                "access_token": "ms-access",
                "refresh_token": "ms-refresh",
            },
        )

    async def get(self, url, **kw):
        return MagicMock(
            status_code=200,
            json=lambda: {
                "id": "ms-test-123",
                "mail": "test@example.com",
                "displayName": "Test User",
            },
        )


def _run_callback(client, state):
    with patch.object(auth_module, "AZURE_CLIENT_SECRET", "test-secret"), \
         patch("routers.auth.httpx.AsyncClient", _MSGraphStub), \
         patch(
             "routers.auth.user_model.upsert_user",
             return_value=(dict(FAKE_USER), False),
         ):
        return client.get(
            "/auth/callback",
            params={"code": "abc", "state": state},
            follow_redirects=False,
        )


def test_signin_completes_end_to_end_with_migration_unrun(client, fake_db):
    """THE other half of the blocker: pre-024, _persist_ms_tokens raised
    42703/PGRST204 outside any try, so main.py's global handler turned every
    OAuth callback into a bare 500 — no _error_page, no settle redirect,
    hung auth popups. The full callback must instead complete and hand the
    extension its JWT."""
    table = SchemaTable(
        [dict(_PRE_024_ROW)], select_columns=PRE_024_COLUMNS
    )
    fake_db.set_table("user_tokens", table)

    # The state a real pre-flip sign-in carries: Mail.Read was requested.
    resp = _run_callback(client, _encode_state(CHROME_EXT, include_mail_read=True))

    assert resp.status_code == 307, (
        f"sign-in must redirect to the extension, got {resp.status_code}"
    )
    assert "chromiumapp.org/auth#" in resp.headers["location"]
    assert "jwt=" in resp.headers["location"]

    # Tokens were persisted — via the column-free fallback, flag omitted.
    committed = [w for w in table.committed_writes if w[0] == "update"]
    assert committed, "the token write must survive the missing column"
    payload = committed[-1][1]
    assert "has_mail_read_scope" not in payload
    assert payload["access_token"] == "ms-access"
    assert payload["refresh_token"] == "ms-refresh"


def test_persist_write_falls_back_when_schema_cache_is_stale(fake_db):
    """The window right after migration 024 runs: the SELECT sees the column
    (PostgreSQL has it) while PostgREST's schema cache still rejects it in
    write payloads with PGRST204. The write must retry without the key
    instead of 500ing the callback."""
    table = SchemaTable(
        [{"id": "t1", "has_onedrive_scope": False, "has_mail_read_scope": True}],
        select_columns=POST_024_COLUMNS,
        write_columns=PRE_024_COLUMNS,
    )
    fake_db.set_table("user_tokens", table)

    auth_module._persist_ms_tokens(
        user_id="u1",
        access_token="a",
        refresh_token="r",
        wants_onedrive=False,
        wants_mail_read=True,
    )

    assert "has_mail_read_scope" in table.update_attempts[0], (
        "the select succeeded, so the first write should still be optimistic"
    )
    assert "has_mail_read_scope" not in table.update_attempts[1]
    assert table.committed_writes, "the retry without the key must land"


def test_unrecordable_narrow_consent_is_loud(fake_db, caplog):
    """Flag flipped BEFORE migration 024 (operator-order violation): a brand
    new narrow user's consent cannot be recorded and migration 024 will later
    backfill it wrongly to TRUE → AADSTS65001 on their refreshes. The row
    still gets written (sign-in must not fail), but at ERROR volume."""
    table = SchemaTable([], select_columns=PRE_024_COLUMNS)
    fake_db.set_table("user_tokens", table)

    with caplog.at_level(logging.ERROR, logger="routers.auth"):
        auth_module._persist_ms_tokens(
            user_id="u1",
            access_token="a",
            refresh_token="r",
            wants_onedrive=False,
            wants_mail_read=False,
        )

    committed = [w for w in table.committed_writes if w[0] == "insert"]
    assert committed and "has_mail_read_scope" not in committed[0][1]
    assert "FIRST_SIGNIN_INCLUDE_MAIL_READ" in caplog.text, (
        "the operator must be told exactly which switch was flipped too early"
    )


# ── audit: the consent record must state what was actually exchanged ──


def _oauth_granted_metadata(client, state):
    with patch.object(auth_module.audit, "emit") as emit:
        resp = _run_callback(client, state)
    assert resp.status_code == 307
    granted = [
        c
        for c in emit.call_args_list
        if c.args and c.args[0] == auth_module.audit.EVENT_OAUTH_GRANTED
    ]
    assert len(granted) == 1
    return granted[0].kwargs["metadata"]


def test_audit_records_narrow_scope_for_a_narrow_signin(client, fake_db):
    """The chargeback/legal trail must never assert consent to Mail.Read
    from a user who was never shown it — a false consent record is worse
    than none."""
    meta = _oauth_granted_metadata(
        client, _encode_state(CHROME_EXT, include_mail_read=False)
    )
    assert meta["scopes"] == MS_GRAPH_FIRST_SIGNIN_SCOPES
    assert "Mail.Read" not in meta["scopes"]


def test_audit_still_records_the_full_scope_for_a_wide_signin(client, fake_db):
    meta = _oauth_granted_metadata(
        client, _encode_state(CHROME_EXT, include_mail_read=True)
    )
    assert meta["scopes"] == MS_GRAPH_SCOPES


# ── narrow re-sign-in must not leave a narrow token for Strategy 1 ──


def _persist_against(rows, **kwargs):
    table = SchemaTable(rows, select_columns=POST_024_COLUMNS)
    db = FakeSupabase()
    db.set_table("user_tokens", table)
    with patch("database.get_db", return_value=db):
        auth_module._persist_ms_tokens(user_id="u1", **kwargs)
    return table


def test_narrow_resignin_invalidates_instead_of_storing_a_narrow_token():
    """Post-flip, an established Mail.Read user who plainly re-signs-in gets
    a token WITHOUT Mail.Read from the exchange. Storing it would let
    Strategy 1's /me probe (scope-blind) serve it for ~1h while reply
    detection 403s silently. We store NULL instead: Strategy 1 is skipped
    and the next use refreshes with the full recorded consent."""
    table = _persist_against(
        [{"id": "t1", "has_onedrive_scope": False, "has_mail_read_scope": True}],
        access_token="narrow-access",
        refresh_token="fresh-refresh",
        wants_onedrive=False,
        wants_mail_read=False,
    )
    payload = table.committed_writes[-1][1]
    assert payload["access_token"] is None, (
        "a token narrower than the recorded consent must never be stored"
    )
    assert payload["has_mail_read_scope"] is True, "consent stays sticky"
    assert payload["refresh_token"] == "fresh-refresh", (
        "the fresh refresh_token is exactly what the recovery refresh needs"
    )


def test_matching_wide_signin_still_stores_its_token():
    table = _persist_against(
        [{"id": "t1", "has_onedrive_scope": False, "has_mail_read_scope": True}],
        access_token="wide-access",
        refresh_token="r",
        wants_onedrive=False,
        wants_mail_read=True,
    )
    assert table.committed_writes[-1][1]["access_token"] == "wide-access"


def test_narrow_users_own_narrow_signin_stores_its_token():
    """No narrowing happened — the exchange matches the recorded consent."""
    table = _persist_against(
        [{"id": "t1", "has_onedrive_scope": False, "has_mail_read_scope": False}],
        access_token="narrow-access",
        refresh_token="r",
        wants_onedrive=False,
        wants_mail_read=False,
    )
    payload = table.committed_writes[-1][1]
    assert payload["access_token"] == "narrow-access"
    assert payload["has_mail_read_scope"] is False


def test_onedrive_upgrade_that_narrows_mail_also_invalidates():
    """The combined case: post-flip, a wide user opts into OneDrive. The
    exchange widens the OneDrive axis but narrows the Mail axis, so neither
    the new token (no Mail.Read) nor the old one (no Files) is right.
    NULL forces a refresh that requests the full recorded consent — wide
    Mail AND Files — so the picker works without re-opening the 2026-07-16
    consent loop and reply detection never 403s."""
    table = _persist_against(
        [{"id": "t1", "has_onedrive_scope": False, "has_mail_read_scope": True}],
        access_token="files-but-narrow-mail",
        refresh_token=None,
        wants_onedrive=True,
        wants_mail_read=False,
    )
    payload = table.committed_writes[-1][1]
    assert payload["access_token"] is None
    assert payload["has_onedrive_scope"] is True, (
        "the OneDrive grant must still be recorded — it is what makes the "
        "recovery refresh request Files scopes"
    )
    assert payload["has_mail_read_scope"] is True
