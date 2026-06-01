"""Settings router tests."""

from tests.conftest import FakeQueryBuilder


def test_get_settings(client, auth_bypass, fake_db):
    resp = client.get("/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@example.com"
    assert data["plan"] == "free"
    assert data["track_opens"] is True
    assert data["timezone"] == "Europe/Istanbul"


def test_get_settings_exposes_plan_limits(client, auth_bypass, fake_db):
    """The extension reads monthly_limit/upload_limit from the backend
    (parametric) instead of hardcoding. Free plan → 250/250."""
    resp = client.get("/settings")
    data = resp.json()
    assert data["monthly_limit"] == 250
    assert data["upload_limit"] == 250


def test_plan_limit_values_are_current():
    """Guard: pins the plan-limit defaults so they can't silently drift.
    (Env can still override these at runtime in Railway.)"""
    from config import (
        FREE_PLAN_MONTHLY_LIMIT,
        STARTER_PLAN_MONTHLY_LIMIT,
        PRO_PLAN_MONTHLY_LIMIT,
        FREE_UPLOAD_ROW_LIMIT,
        STARTER_UPLOAD_ROW_LIMIT,
        PRO_UPLOAD_ROW_LIMIT,
        monthly_limit_for_plan,
        upload_limit_for_plan,
    )

    assert FREE_PLAN_MONTHLY_LIMIT == 250
    assert STARTER_PLAN_MONTHLY_LIMIT == 2500
    assert PRO_PLAN_MONTHLY_LIMIT == 10000
    assert FREE_UPLOAD_ROW_LIMIT == 250
    assert STARTER_UPLOAD_ROW_LIMIT == 2500
    assert PRO_UPLOAD_ROW_LIMIT == 10000
    # helpers map correctly + unknown plan falls back to free
    assert monthly_limit_for_plan("pro") == 10000
    assert monthly_limit_for_plan("starter") == 2500
    assert monthly_limit_for_plan("free") == 250
    assert monthly_limit_for_plan("garbage") == 250
    assert upload_limit_for_plan("starter") == 2500
    assert upload_limit_for_plan(None) == 250


def test_get_settings_unauthorized(client):
    resp = client.get("/settings")
    assert resp.status_code in (401, 422)


def test_update_settings(client, auth_bypass, fake_db):
    fake_db.set_table("users", FakeQueryBuilder([{"id": "1"}]))
    resp = client.put(
        "/settings",
        json={
            "track_opens": False,
            "timezone": "UTC",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "updated"
    assert data["track_opens"] is False
    assert data["timezone"] == "UTC"


def test_update_settings_empty(client, auth_bypass, fake_db):
    """Empty update should still return 200."""
    resp = client.put("/settings", json={})
    assert resp.status_code == 200


def test_suppression_list_empty(client, auth_bypass, fake_db):
    fake_db.set_table("suppression_list", FakeQueryBuilder([]))
    resp = client.get("/settings/suppression")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0


def test_add_suppression(client, auth_bypass, fake_db):
    fake_db.set_table("suppression_list", FakeQueryBuilder([]))
    resp = client.post("/settings/suppression", json={"email": "spam@test.com"})
    assert resp.status_code == 200
    # Could be "added" or "already_exists" depending on mock state
    assert resp.json()["status"] in ("added", "already_exists")


def test_add_suppression_empty_email(client, auth_bypass, fake_db):
    fake_db.set_table("suppression_list", FakeQueryBuilder([]))
    resp = client.post("/settings/suppression", json={"email": ""})
    assert resp.status_code == 400


def test_remove_suppression(client, auth_bypass, fake_db):
    fake_db.set_table("suppression_list", FakeQueryBuilder([]))
    resp = client.request(
        "DELETE", "/settings/suppression", json={"email": "spam@test.com"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "removed"
