"""
OutMass — Integration Test Configuration
Uses real Supabase DB. Cleans up test data after each test.
"""

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env.test BEFORE importing app modules
env_test = Path(__file__).resolve().parent.parent.parent / ".env.test"
load_dotenv(env_test, override=True)

# Ensure backend/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from database import get_db
from routers.auth import create_jwt, get_current_user
from fastapi.testclient import TestClient
from main import app


# ── Cleanup tracker ──
# Tracks all IDs created during tests so we can delete them after


class CleanupTracker:
    """Tracks DB rows created during tests for cleanup."""

    def __init__(self):
        self.campaigns = []
        self.contacts = []
        self.templates = []
        self.ab_tests = []
        self.follow_ups = []
        self.events = []
        self.suppression_ids = []

    def cleanup(self):
        db = get_db()
        # Delete in reverse dependency order (children before parents)
        for eid in self.events:
            db.table("events").delete().eq("id", eid).execute()
        for cid in self.contacts:
            db.table("contacts").delete().eq("id", cid).execute()
        for fid in self.follow_ups:
            db.table("follow_ups").delete().eq("id", fid).execute()
        for aid in self.ab_tests:
            db.table("ab_tests").delete().eq("id", aid).execute()
        for tid in self.templates:
            db.table("templates").delete().eq("id", tid).execute()
        for sid in self.suppression_ids:
            db.table("suppression_list").delete().eq("id", sid).execute()
        # Campaigns last (other tables reference them via FK)
        # Also clean any remaining child rows by campaign_id
        for cid in self.campaigns:
            db.table("events").delete().eq("campaign_id", cid).execute()
            db.table("contacts").delete().eq("campaign_id", cid).execute()
            db.table("follow_ups").delete().eq("campaign_id", cid).execute()
            db.table("ab_tests").delete().eq("campaign_id", cid).execute()
            db.table("campaigns").delete().eq("id", cid).execute()


@pytest.fixture()
def cleanup():
    """Provides a CleanupTracker, cleans up after test finishes."""
    tracker = CleanupTracker()
    yield tracker
    tracker.cleanup()


# ── Real test user from DB ──


@pytest.fixture(scope="session")
def test_user():
    """Find the real test user from DB by email."""
    email = os.getenv("TEST_USER_EMAIL")
    if not email:
        pytest.skip("TEST_USER_EMAIL not set in .env.test")

    db = get_db()
    result = db.table("users").select("*").eq("email", email).execute()
    if not result.data:
        pytest.skip(f"User {email} not found in DB. Log in via extension first.")
    return result.data[0]


@pytest.fixture()
def auth_header(test_user):
    """Generate a valid JWT Authorization header for the test user."""
    token = create_jwt(test_user["id"], test_user["email"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def client():
    """FastAPI TestClient that hits real DB."""
    return TestClient(app)


@pytest.fixture()
def authed_client(client, auth_header):
    """Client with auth headers pre-set."""

    class AuthedClient:
        def __init__(self, c, headers):
            self._client = c
            self._headers = headers

        def get(self, url, **kw):
            kw.setdefault("headers", {}).update(self._headers)
            return self._client.get(url, **kw)

        def post(self, url, **kw):
            kw.setdefault("headers", {}).update(self._headers)
            return self._client.post(url, **kw)

        def put(self, url, **kw):
            kw.setdefault("headers", {}).update(self._headers)
            return self._client.put(url, **kw)

        def delete(self, url, **kw):
            kw.setdefault("headers", {}).update(self._headers)
            return self._client.delete(url, **kw)

        def request(self, method, url, **kw):
            kw.setdefault("headers", {}).update(self._headers)
            return self._client.request(method, url, **kw)

    return AuthedClient(client, auth_header)
