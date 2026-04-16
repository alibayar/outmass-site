"""
Functional tests — Templates + Plan Gating
Tests real Supabase DB operations.
"""

from database import get_db


def test_templates_blocked_for_free_user(authed_client, test_user):
    """Free plan users should get 402 on template endpoints."""
    if test_user.get("plan") != "free":
        # Temporarily set plan to free for this test
        get_db().table("users").update({"plan": "free"}).eq(
            "id", test_user["id"]
        ).execute()

    resp = authed_client.post(
        "/templates",
        json={"name": "Blocked", "subject": "Hi", "body": "Body"},
    )
    assert resp.status_code == 402
    assert resp.json()["detail"]["error"] == "feature_locked"

    resp = authed_client.get("/templates")
    assert resp.status_code == 402


def test_template_crud_standard_user(authed_client, test_user, cleanup):
    """Standard+ user can create, list, and delete templates."""
    original_plan = test_user.get("plan", "free")

    # Upgrade to standard for test
    get_db().table("users").update({"plan": "starter"}).eq(
        "id", test_user["id"]
    ).execute()

    try:
        # Create
        resp = authed_client.post(
            "/templates",
            json={
                "name": "Functional Test Template",
                "subject": "Hello {{firstName}}",
                "body": "<p>Welcome to {{company}}</p>",
            },
        )
        assert resp.status_code == 200
        template_id = resp.json()["template_id"]
        cleanup.templates.append(template_id)

        # List
        resp = authed_client.get("/templates")
        assert resp.status_code == 200
        templates = resp.json()["templates"]
        assert any(t["id"] == template_id for t in templates)
        tpl = next(t for t in templates if t["id"] == template_id)
        assert tpl["name"] == "Functional Test Template"
        assert tpl["subject"] == "Hello {{firstName}}"

        # Delete
        resp = authed_client.delete(f"/templates/{template_id}")
        assert resp.status_code == 200

        # Verify deleted
        resp = authed_client.get("/templates")
        templates = resp.json()["templates"]
        assert not any(t["id"] == template_id for t in templates)

        # Remove from cleanup since already deleted
        cleanup.templates.remove(template_id)

    finally:
        # Restore original plan
        get_db().table("users").update({"plan": original_plan}).eq(
            "id", test_user["id"]
        ).execute()


def test_csv_export_blocked_for_free(authed_client, test_user, cleanup):
    """Free plan users cannot export CSV."""
    original_plan = test_user.get("plan", "free")
    get_db().table("users").update({"plan": "free"}).eq(
        "id", test_user["id"]
    ).execute()

    try:
        # Create campaign
        resp = authed_client.post(
            "/campaigns",
            json={"name": "Export Block Test", "subject": "Hi", "body": "B"},
        )
        cid = resp.json()["campaign_id"]
        cleanup.campaigns.append(cid)

        resp = authed_client.get(f"/campaigns/{cid}/export")
        assert resp.status_code == 402

    finally:
        get_db().table("users").update({"plan": original_plan}).eq(
            "id", test_user["id"]
        ).execute()


def test_csv_export_works_for_standard(authed_client, test_user, cleanup):
    """Standard plan users can export CSV."""
    original_plan = test_user.get("plan", "free")
    get_db().table("users").update({"plan": "starter"}).eq(
        "id", test_user["id"]
    ).execute()

    try:
        # Create campaign with contacts
        resp = authed_client.post(
            "/campaigns",
            json={"name": "Export Test", "subject": "Hi", "body": "B"},
        )
        cid = resp.json()["campaign_id"]
        cleanup.campaigns.append(cid)

        resp = authed_client.post(
            f"/campaigns/{cid}/contacts",
            json={
                "contacts": [
                    {"email": "export1@example.com", "firstName": "Ali"},
                    {"email": "export2@example.com", "firstName": "Veli"},
                ]
            },
        )
        assert resp.json()["count"] == 2

        # Export
        resp = authed_client.get(f"/campaigns/{cid}/export")
        assert resp.status_code == 200
        csv_data = resp.json()["csv_data"]
        assert "export1@example.com" in csv_data
        assert "export2@example.com" in csv_data
        assert "Ali" in csv_data

        # Cleanup contacts
        contacts = (
            get_db()
            .table("contacts")
            .select("id")
            .eq("campaign_id", cid)
            .execute()
        )
        for c in contacts.data:
            cleanup.contacts.append(c["id"])

    finally:
        get_db().table("users").update({"plan": original_plan}).eq(
            "id", test_user["id"]
        ).execute()


def test_scheduled_sending_blocked_for_free(authed_client, test_user, cleanup):
    """Free plan users cannot schedule campaigns."""
    original_plan = test_user.get("plan", "free")
    get_db().table("users").update({"plan": "free"}).eq(
        "id", test_user["id"]
    ).execute()

    try:
        resp = authed_client.post(
            "/campaigns",
            json={
                "name": "Scheduled Block Test",
                "subject": "Hi",
                "body": "B",
                "scheduled_for": "2026-12-31T10:00:00Z",
            },
        )
        assert resp.status_code == 402

    finally:
        get_db().table("users").update({"plan": original_plan}).eq(
            "id", test_user["id"]
        ).execute()


def test_scheduled_sending_works_for_standard(authed_client, test_user, cleanup):
    """Standard plan users can schedule campaigns."""
    original_plan = test_user.get("plan", "free")
    get_db().table("users").update({"plan": "starter"}).eq(
        "id", test_user["id"]
    ).execute()

    try:
        resp = authed_client.post(
            "/campaigns",
            json={
                "name": "Scheduled Test",
                "subject": "Hi",
                "body": "B",
                "scheduled_for": "2026-12-31T10:00:00Z",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "scheduled"
        cleanup.campaigns.append(resp.json()["campaign_id"])

    finally:
        get_db().table("users").update({"plan": original_plan}).eq(
            "id", test_user["id"]
        ).execute()
