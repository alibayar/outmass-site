"""
OutMass — Test Configuration & Fixtures
Mocks Supabase so tests run without a real database.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure backend/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Supabase Mock ──


class FakeQueryBuilder:
    """Chainable mock that mimics Supabase query builder."""

    def __init__(self, data=None, count=None):
        self._data = data or []
        self._count = count

    # Chainable methods
    def select(self, *a, **kw):
        return self

    def insert(self, rows):
        if isinstance(rows, list):
            self._data = rows
        else:
            self._data = [rows]
        return self

    def update(self, vals):
        self._data = [vals]
        return self

    def delete(self):
        return self

    def eq(self, *a):
        return self

    def neq(self, *a):
        return self

    def lte(self, *a):
        return self

    def gte(self, *a):
        return self

    def is_(self, *a):
        return self

    def order(self, *a, **kw):
        return self

    def limit(self, *a):
        return self

    def execute(self):
        return MagicMock(data=self._data, count=self._count)


class FakeSupabase:
    """Minimal mock of supabase.Client."""

    def __init__(self):
        self._tables = {}
        self._rpc_results = {}

    def table(self, name):
        return self._tables.get(name, FakeQueryBuilder())

    def rpc(self, name, params=None):
        return FakeQueryBuilder(self._rpc_results.get(name, []))

    def set_table(self, name, builder):
        self._tables[name] = builder

    def set_rpc(self, name, data):
        self._rpc_results[name] = data


@pytest.fixture()
def fake_db():
    """Provide a FakeSupabase and patch database.get_db everywhere it's imported."""
    db = FakeSupabase()
    patches = [
        patch("database.get_db", return_value=db),
        patch("routers.settings.get_db", return_value=db),
        patch("routers.tracking.get_db", return_value=db),
        patch("routers.auth.get_db", return_value=db, create=True),
    ]
    for p in patches:
        p.start()
    yield db
    for p in patches:
        p.stop()


# ── Test User ──

FAKE_USER = {
    "id": "00000000-0000-0000-0000-000000000001",
    "microsoft_id": "ms-test-123",
    "email": "test@example.com",
    "name": "Test User",
    "plan": "free",
    "emails_sent_this_month": 5,
    "month_reset_date": "2026-04-01",
    "track_opens": True,
    "track_clicks": True,
    "unsubscribe_text": "Abonelikten cik",
    "timezone": "Europe/Istanbul",
}

FAKE_PRO_USER = {**FAKE_USER, "plan": "pro"}
FAKE_STANDARD_USER = {**FAKE_USER, "plan": "standard"}


@pytest.fixture()
def auth_bypass():
    """Bypass JWT auth — inject FAKE_USER as current user."""
    from routers.auth import get_current_user

    async def _override():
        return FAKE_USER

    from main import app

    app.dependency_overrides[get_current_user] = _override
    yield FAKE_USER
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def auth_bypass_pro():
    """Bypass JWT auth — inject FAKE_PRO_USER."""
    from routers.auth import get_current_user

    async def _override():
        return FAKE_PRO_USER

    from main import app

    app.dependency_overrides[get_current_user] = _override
    yield FAKE_PRO_USER
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def auth_bypass_standard():
    """Bypass JWT auth — inject FAKE_STANDARD_USER."""
    from routers.auth import get_current_user

    async def _override():
        return FAKE_STANDARD_USER

    from main import app

    app.dependency_overrides[get_current_user] = _override
    yield FAKE_STANDARD_USER
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def client():
    """FastAPI TestClient (no auth override — use with auth_bypass fixtures)."""
    from main import app

    return TestClient(app)
