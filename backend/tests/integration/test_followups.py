"""
Functional tests — Follow-ups + A/B Tests
Tests real Supabase DB operations.
"""

from database import get_db


def test_create_followup(authed_client, cleanup):
    """Create a follow-up for a campaign."""
    resp = authed_client.post(
        "/campaigns",
        json={"name": "Followup Test", "subject": "Hi", "body": "B"},
    )
    cid = resp.json()["campaign_id"]
    cleanup.campaigns.append(cid)

    resp = authed_client.post(
        f"/campaigns/{cid}/followups",
        json={
            "delay_days": 3,
            "subject": "Follow-up: {{firstName}}",
            "body": "<p>Did you see our email?</p>",
            "condition": "not_opened",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "followup_id" in data
    cleanup.follow_ups.append(data["followup_id"])


def test_list_followups(authed_client, cleanup):
    """List follow-ups for a campaign."""
    resp = authed_client.post(
        "/campaigns",
        json={"name": "Followup List Test", "subject": "Hi", "body": "B"},
    )
    cid = resp.json()["campaign_id"]
    cleanup.campaigns.append(cid)

    # Create two follow-ups
    resp1 = authed_client.post(
        f"/campaigns/{cid}/followups",
        json={"delay_days": 2, "subject": "FU1", "body": "Body1"},
    )
    fid1 = resp1.json()["followup_id"]
    cleanup.follow_ups.append(fid1)

    resp2 = authed_client.post(
        f"/campaigns/{cid}/followups",
        json={"delay_days": 5, "subject": "FU2", "body": "Body2"},
    )
    fid2 = resp2.json()["followup_id"]
    cleanup.follow_ups.append(fid2)

    # List
    resp = authed_client.get(f"/campaigns/{cid}/followups")
    assert resp.status_code == 200
    followups = resp.json()["followups"]
    assert len(followups) >= 2
    fids = [f["id"] for f in followups]
    assert fid1 in fids
    assert fid2 in fids


def test_delete_followup(authed_client, cleanup):
    """Delete a follow-up."""
    resp = authed_client.post(
        "/campaigns",
        json={"name": "Followup Delete Test", "subject": "Hi", "body": "B"},
    )
    cid = resp.json()["campaign_id"]
    cleanup.campaigns.append(cid)

    resp = authed_client.post(
        f"/campaigns/{cid}/followups",
        json={"delay_days": 3, "subject": "Delete Me", "body": "Body"},
    )
    fid = resp.json()["followup_id"]

    # Delete (soft-delete: sets status to 'cancelled')
    resp = authed_client.delete(f"/campaigns/{cid}/followups/{fid}")
    assert resp.status_code == 200

    # Verify status is cancelled
    resp = authed_client.get(f"/campaigns/{cid}/followups")
    followup = next(f for f in resp.json()["followups"] if f["id"] == fid)
    assert followup["status"] == "cancelled"

    # Track for cleanup
    cleanup.follow_ups.append(fid)


def test_create_ab_test(authed_client, test_user, cleanup):
    """Create an A/B test for a campaign (Pro plan only)."""
    original_plan = test_user.get("plan", "free")
    get_db().table("users").update({"plan": "pro"}).eq(
        "id", test_user["id"]
    ).execute()

    try:
        resp = authed_client.post(
            "/campaigns",
            json={"name": "AB Test", "subject": "Subject A", "body": "B"},
        )
        cid = resp.json()["campaign_id"]
        cleanup.campaigns.append(cid)

        resp = authed_client.post(
            f"/campaigns/{cid}/ab-test",
            json={
                "subject_a": "Subject A",
                "subject_b": "Subject B",
                "test_percentage": 20,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ab_test_id" in data
        cleanup.ab_tests.append(data["ab_test_id"])

        # Get AB test
        resp = authed_client.get(f"/campaigns/{cid}/ab-test")
        assert resp.status_code == 200
        ab = resp.json()
        assert ab["subject_a"] == "Subject A"
        assert ab["subject_b"] == "Subject B"

    finally:
        get_db().table("users").update({"plan": original_plan}).eq(
            "id", test_user["id"]
        ).execute()


def test_ab_test_blocked_for_free(authed_client, test_user, cleanup):
    """Free plan users cannot create A/B tests."""
    original_plan = test_user.get("plan", "free")
    get_db().table("users").update({"plan": "free"}).eq(
        "id", test_user["id"]
    ).execute()

    try:
        resp = authed_client.post(
            "/campaigns",
            json={"name": "AB Block Test", "subject": "S", "body": "B"},
        )
        cid = resp.json()["campaign_id"]
        cleanup.campaigns.append(cid)

        resp = authed_client.post(
            f"/campaigns/{cid}/ab-test",
            json={"subject_a": "A", "subject_b": "B", "test_percentage": 20},
        )
        assert resp.status_code == 402

    finally:
        get_db().table("users").update({"plan": original_plan}).eq(
            "id", test_user["id"]
        ).execute()
