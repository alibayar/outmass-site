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
