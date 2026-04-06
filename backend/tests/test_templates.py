"""Templates router tests."""

from unittest.mock import patch


FAKE_TEMPLATE = {
    "id": "tpl-001",
    "user_id": "00000000-0000-0000-0000-000000000001",
    "name": "Welcome",
    "subject": "Welcome {{firstName}}",
    "body": "<p>Hello!</p>",
}


def test_create_template_free_user_blocked(client, auth_bypass, fake_db):
    """Free plan users should not be able to create templates."""
    resp = client.post(
        "/templates",
        json={"name": "Test", "subject": "Hi", "body": "Hello"},
    )
    assert resp.status_code == 402


def test_create_template_standard_user(client, auth_bypass_standard, fake_db):
    """Standard plan users can create templates."""
    with patch(
        "models.template.create_template", return_value=FAKE_TEMPLATE
    ):
        resp = client.post(
            "/templates",
            json={"name": "Welcome", "subject": "Hi", "body": "Hello"},
        )
    assert resp.status_code == 200
    assert resp.json()["template_id"] == "tpl-001"


def test_list_templates_standard(client, auth_bypass_standard, fake_db):
    with patch("models.template.list_templates", return_value=[FAKE_TEMPLATE]):
        resp = client.get("/templates")
    assert resp.status_code == 200
    assert len(resp.json()["templates"]) == 1


def test_delete_template_standard(client, auth_bypass_standard, fake_db):
    with patch("models.template.delete_template"):
        resp = client.delete("/templates/tpl-001")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


def test_list_templates_free_blocked(client, auth_bypass, fake_db):
    resp = client.get("/templates")
    assert resp.status_code == 402
