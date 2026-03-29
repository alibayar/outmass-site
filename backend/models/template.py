"""
OutMass — Template model helpers
"""

from database import get_db


def create_template(user_id: str, name: str, subject: str, body: str) -> dict:
    result = (
        get_db()
        .table("templates")
        .insert({
            "user_id": user_id,
            "name": name,
            "subject": subject,
            "body": body,
        })
        .execute()
    )
    return result.data[0]


def list_templates(user_id: str) -> list[dict]:
    result = (
        get_db()
        .table("templates")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )
    return result.data


def get_template(template_id: str) -> dict | None:
    result = (
        get_db()
        .table("templates")
        .select("*")
        .eq("id", template_id)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def delete_template(template_id: str, user_id: str):
    get_db().table("templates").delete().eq("id", template_id).eq(
        "user_id", user_id
    ).execute()
