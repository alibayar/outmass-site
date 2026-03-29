"""
OutMass — A/B Test model helpers
"""

from database import get_db


def create_ab_test(
    campaign_id: str,
    user_id: str,
    subject_a: str,
    subject_b: str,
    test_percentage: int = 20,
) -> dict:
    result = (
        get_db()
        .table("ab_tests")
        .insert({
            "campaign_id": campaign_id,
            "user_id": user_id,
            "subject_a": subject_a,
            "subject_b": subject_b,
            "test_percentage": test_percentage,
            "status": "testing",  # testing → evaluated → winner_sent
            "opens_a": 0,
            "opens_b": 0,
            "winner": None,
        })
        .execute()
    )
    return result.data[0]


def get_ab_test(campaign_id: str) -> dict | None:
    result = (
        get_db()
        .table("ab_tests")
        .select("*")
        .eq("campaign_id", campaign_id)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def increment_opens(ab_test_id: str, variant: str):
    """Increment opens for variant A or B."""
    field = "opens_a" if variant == "A" else "opens_b"
    test = get_db().table("ab_tests").select(field).eq("id", ab_test_id).execute()
    if test.data and len(test.data) > 0:
        new_val = test.data[0].get(field, 0) + 1
        get_db().table("ab_tests").update({field: new_val}).eq(
            "id", ab_test_id
        ).execute()


def update_ab_test(ab_test_id: str, updates: dict):
    get_db().table("ab_tests").update(updates).eq("id", ab_test_id).execute()
