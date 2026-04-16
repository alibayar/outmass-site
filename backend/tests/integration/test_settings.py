"""
Functional tests — Settings + Suppression List
Tests real Supabase DB operations.
"""


def test_get_settings(authed_client, test_user):
    """Get settings returns real user data."""
    resp = authed_client.get("/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == test_user["email"]
    assert data["plan"] in ("free", "starter", "pro")
    assert "track_opens" in data
    assert "track_clicks" in data
    assert "timezone" in data


def test_update_settings_track_opens(authed_client):
    """Toggle track_opens off and back on."""
    # Turn off
    resp = authed_client.put("/settings", json={"track_opens": False})
    assert resp.status_code == 200
    assert resp.json()["track_opens"] is False

    # Verify it persisted
    resp = authed_client.get("/settings")
    assert resp.json()["track_opens"] is False

    # Turn back on
    resp = authed_client.put("/settings", json={"track_opens": True})
    assert resp.status_code == 200

    resp = authed_client.get("/settings")
    assert resp.json()["track_opens"] is True


def test_update_settings_timezone(authed_client):
    """Change timezone and verify persistence."""
    resp = authed_client.put("/settings", json={"timezone": "UTC"})
    assert resp.status_code == 200

    resp = authed_client.get("/settings")
    assert resp.json()["timezone"] == "UTC"

    # Restore
    resp = authed_client.put("/settings", json={"timezone": "Europe/Istanbul"})
    assert resp.status_code == 200


def test_update_settings_unsubscribe_text(authed_client):
    """Change unsubscribe text."""
    resp = authed_client.put(
        "/settings", json={"unsubscribe_text": "Test unsub text"}
    )
    assert resp.status_code == 200

    resp = authed_client.get("/settings")
    assert resp.json()["unsubscribe_text"] == "Test unsub text"

    # Restore
    resp = authed_client.put(
        "/settings", json={"unsubscribe_text": "Abonelikten cik"}
    )


def test_suppression_add_and_list(authed_client, cleanup):
    """Add email to suppression list, verify it appears in list."""
    test_email = "functional-test-suppression@example.com"

    resp = authed_client.post(
        "/settings/suppression", json={"email": test_email}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] in ("added", "already_exists")

    # List and find it
    resp = authed_client.get("/settings/suppression")
    assert resp.status_code == 200
    emails = [e["email"] for e in resp.json()["emails"]]
    assert test_email in emails

    # Track for cleanup
    from database import get_db

    result = (
        get_db()
        .table("suppression_list")
        .select("id")
        .eq("email", test_email)
        .execute()
    )
    for r in result.data:
        cleanup.suppression_ids.append(r["id"])


def test_suppression_duplicate(authed_client, cleanup):
    """Adding same email twice should return already_exists."""
    test_email = "functional-test-dup@example.com"

    resp = authed_client.post(
        "/settings/suppression", json={"email": test_email}
    )
    assert resp.json()["status"] == "added"

    resp = authed_client.post(
        "/settings/suppression", json={"email": test_email}
    )
    assert resp.json()["status"] == "already_exists"

    # Cleanup
    from database import get_db

    result = (
        get_db()
        .table("suppression_list")
        .select("id")
        .eq("email", test_email)
        .execute()
    )
    for r in result.data:
        cleanup.suppression_ids.append(r["id"])


def test_suppression_remove(authed_client, cleanup):
    """Add then remove an email from suppression list."""
    test_email = "functional-test-remove@example.com"

    authed_client.post("/settings/suppression", json={"email": test_email})

    resp = authed_client.request(
        "DELETE", "/settings/suppression", json={"email": test_email}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "removed"

    # Verify it's gone
    resp = authed_client.get("/settings/suppression")
    emails = [e["email"] for e in resp.json()["emails"]]
    assert test_email not in emails
