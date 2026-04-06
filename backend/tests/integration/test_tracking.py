"""
Functional tests — Tracking (open pixel, click redirect, unsubscribe)
Tests real Supabase DB operations.
"""

from database import get_db


def _create_campaign_with_contact(authed_client, cleanup):
    """Helper: create a campaign + 1 contact, return (campaign_id, contact_id)."""
    resp = authed_client.post(
        "/campaigns",
        json={"name": "Tracking Test", "subject": "Hi", "body": "Body"},
    )
    cid = resp.json()["campaign_id"]
    cleanup.campaigns.append(cid)

    resp = authed_client.post(
        f"/campaigns/{cid}/contacts",
        json={
            "contacts": [
                {"email": "track-test@example.com", "firstName": "Tracker"}
            ]
        },
    )
    assert resp.json()["count"] == 1

    # Get the contact ID
    contacts = (
        get_db()
        .table("contacts")
        .select("id")
        .eq("campaign_id", cid)
        .execute()
    )
    contact_id = contacts.data[0]["id"]
    cleanup.contacts.append(contact_id)

    return cid, contact_id


def test_open_pixel_increments_count(authed_client, client, cleanup):
    """GET /t/{contact_id} should record open and increment campaign.open_count."""
    cid, contact_id = _create_campaign_with_contact(authed_client, cleanup)

    # Hit the tracking pixel
    resp = client.get(f"/t/{contact_id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/gif"

    # Verify contact.opened_at is set
    contact = get_db().table("contacts").select("*").eq("id", contact_id).execute()
    assert contact.data[0]["opened_at"] is not None

    # Verify campaign.open_count incremented
    campaign = get_db().table("campaigns").select("open_count").eq("id", cid).execute()
    assert campaign.data[0]["open_count"] >= 1

    # Track events for cleanup
    events = (
        get_db()
        .table("events")
        .select("id")
        .eq("contact_id", contact_id)
        .execute()
    )
    for e in events.data:
        cleanup.events.append(e["id"])


def test_open_pixel_dedup(authed_client, client, cleanup):
    """Opening twice should only increment open_count once."""
    cid, contact_id = _create_campaign_with_contact(authed_client, cleanup)

    # Open twice
    client.get(f"/t/{contact_id}")
    client.get(f"/t/{contact_id}")

    # open_count should be 1 (dedup on first open)
    campaign = get_db().table("campaigns").select("open_count").eq("id", cid).execute()
    assert campaign.data[0]["open_count"] == 1

    events = (
        get_db()
        .table("events")
        .select("id")
        .eq("contact_id", contact_id)
        .execute()
    )
    for e in events.data:
        cleanup.events.append(e["id"])


def test_click_redirect_works(authed_client, client, cleanup):
    """GET /c/{contact_id}?url=... should redirect and record click."""
    cid, contact_id = _create_campaign_with_contact(authed_client, cleanup)

    resp = client.get(
        f"/c/{contact_id}?url=https://example.com",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://example.com"

    # Verify contact.clicked_at is set
    contact = get_db().table("contacts").select("*").eq("id", contact_id).execute()
    assert contact.data[0]["clicked_at"] is not None

    # Verify campaign.click_count incremented
    campaign = get_db().table("campaigns").select("click_count").eq("id", cid).execute()
    assert campaign.data[0]["click_count"] >= 1

    events = (
        get_db()
        .table("events")
        .select("id")
        .eq("contact_id", contact_id)
        .execute()
    )
    for e in events.data:
        cleanup.events.append(e["id"])


def test_click_rejects_javascript_url(client):
    """javascript: URLs should be rejected (XSS protection)."""
    resp = client.get("/c/some-id?url=javascript:alert(1)")
    assert resp.status_code == 400


def test_unsubscribe_flow(authed_client, client, cleanup):
    """Full unsubscribe: GET page → POST confirm → verify suppression."""
    cid, contact_id = _create_campaign_with_contact(authed_client, cleanup)

    # Step 1: GET unsubscribe page
    resp = client.get(f"/unsubscribe/{contact_id}")
    assert resp.status_code == 200
    assert "Abonelikten Cik" in resp.text

    # Step 2: POST to confirm
    resp = client.post(f"/unsubscribe/{contact_id}")
    assert resp.status_code == 200
    assert "Basariyla Cikildi" in resp.text

    # Step 3: Verify contact is unsubscribed
    contact = get_db().table("contacts").select("*").eq("id", contact_id).execute()
    assert contact.data[0]["unsubscribed"] is True

    # Step 4: Verify added to suppression list
    campaign = get_db().table("campaigns").select("user_id").eq("id", cid).execute()
    user_id = campaign.data[0]["user_id"]
    suppression = (
        get_db()
        .table("suppression_list")
        .select("id, email")
        .eq("user_id", user_id)
        .eq("email", "track-test@example.com")
        .execute()
    )
    assert len(suppression.data) >= 1
    for s in suppression.data:
        cleanup.suppression_ids.append(s["id"])
