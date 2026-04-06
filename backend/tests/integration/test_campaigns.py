"""
Functional tests — Campaign CRUD + Contact Upload
Tests real Supabase DB operations.
"""


def test_create_campaign(authed_client, cleanup):
    """Create a campaign and verify it exists in DB."""
    resp = authed_client.post(
        "/campaigns",
        json={
            "name": "Test Campaign Functional",
            "subject": "Hello {{firstName}}",
            "body": "<p>Test body</p>",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "campaign_id" in data
    assert data["status"] == "draft"
    cleanup.campaigns.append(data["campaign_id"])


def test_list_campaigns(authed_client, cleanup):
    """Create a campaign then verify it appears in the list."""
    # Create
    resp = authed_client.post(
        "/campaigns",
        json={"name": "List Test", "subject": "Test", "body": "Body"},
    )
    cid = resp.json()["campaign_id"]
    cleanup.campaigns.append(cid)

    # List
    resp = authed_client.get("/campaigns")
    assert resp.status_code == 200
    campaigns = resp.json()["campaigns"]
    assert any(c["id"] == cid for c in campaigns)


def test_campaign_stats(authed_client, cleanup):
    """Get stats for a campaign."""
    resp = authed_client.post(
        "/campaigns",
        json={"name": "Stats Test", "subject": "Test", "body": "Body"},
    )
    cid = resp.json()["campaign_id"]
    cleanup.campaigns.append(cid)

    resp = authed_client.get(f"/campaigns/{cid}/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["campaign_id"] == cid
    assert stats["name"] == "Stats Test"
    assert stats["sent_count"] == 0
    assert stats["open_rate"] == 0.0
    assert stats["click_rate"] == 0.0


def test_campaign_stats_not_found(authed_client):
    """Stats for non-existent campaign should 404."""
    resp = authed_client.get("/campaigns/00000000-0000-0000-0000-000000000000/stats")
    assert resp.status_code == 404


def test_upload_contacts_csv(authed_client, cleanup):
    """Upload contacts via CSV string and verify count."""
    # Create campaign
    resp = authed_client.post(
        "/campaigns",
        json={"name": "CSV Upload Test", "subject": "Hi", "body": "Body"},
    )
    cid = resp.json()["campaign_id"]
    cleanup.campaigns.append(cid)

    # Upload contacts via CSV
    csv_data = "email,firstName,lastName,company\ntest1@example.com,Ali,Bayar,TestCo\ntest2@example.com,Mehmet,Yilmaz,AcmeCo"
    resp = authed_client.post(
        f"/campaigns/{cid}/contacts",
        json={"csv_string": csv_data},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert len(data.get("preview", [])) >= 1

    # Verify via stats
    resp = authed_client.get(f"/campaigns/{cid}/stats")
    assert resp.json()["total_contacts"] == 2

    # Track contacts for cleanup
    from database import get_db

    contacts = (
        get_db()
        .table("contacts")
        .select("id")
        .eq("campaign_id", cid)
        .execute()
    )
    for c in contacts.data:
        cleanup.contacts.append(c["id"])


def test_upload_contacts_json(authed_client, cleanup):
    """Upload contacts via JSON array."""
    resp = authed_client.post(
        "/campaigns",
        json={"name": "JSON Upload Test", "subject": "Hi", "body": "Body"},
    )
    cid = resp.json()["campaign_id"]
    cleanup.campaigns.append(cid)

    resp = authed_client.post(
        f"/campaigns/{cid}/contacts",
        json={
            "contacts": [
                {"email": "json1@example.com", "firstName": "Test", "company": "Co"},
                {"email": "json2@example.com", "firstName": "Test2", "company": "Co2"},
                {"email": "json3@example.com", "firstName": "Test3", "company": "Co3"},
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 3

    from database import get_db

    contacts = (
        get_db()
        .table("contacts")
        .select("id")
        .eq("campaign_id", cid)
        .execute()
    )
    for c in contacts.data:
        cleanup.contacts.append(c["id"])


def test_upload_contacts_invalid_emails_skipped(authed_client, cleanup):
    """Contacts with invalid emails should be skipped."""
    resp = authed_client.post(
        "/campaigns",
        json={"name": "Invalid Email Test", "subject": "Hi", "body": "Body"},
    )
    cid = resp.json()["campaign_id"]
    cleanup.campaigns.append(cid)

    resp = authed_client.post(
        f"/campaigns/{cid}/contacts",
        json={
            "contacts": [
                {"email": "valid@example.com", "firstName": "Valid"},
                {"email": "not-an-email", "firstName": "Invalid"},
                {"email": "", "firstName": "Empty"},
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 1  # Only valid email

    from database import get_db

    contacts = (
        get_db()
        .table("contacts")
        .select("id")
        .eq("campaign_id", cid)
        .execute()
    )
    for c in contacts.data:
        cleanup.contacts.append(c["id"])


def test_upload_no_contacts_returns_400(authed_client, cleanup):
    """Uploading empty contacts should 400."""
    resp = authed_client.post(
        "/campaigns",
        json={"name": "Empty Upload", "subject": "Hi", "body": "Body"},
    )
    cid = resp.json()["campaign_id"]
    cleanup.campaigns.append(cid)

    resp = authed_client.post(
        f"/campaigns/{cid}/contacts",
        json={"csv_string": ""},
    )
    assert resp.status_code == 400
