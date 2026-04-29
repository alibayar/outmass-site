"""Tests for the OneDrive share-link endpoint and the email-attachment
footer rendering.

The endpoint contract:
  - POST /api/onedrive/share-link {item_id}
  - 200 → {share_url, name}
  - 401 → user has no MS connection at all
  - 403 → user has Mail scopes but not Files.ReadWrite (incremental
          consent path) → structured {error: "needs_files_scope"}
  - 404 → item not found
  - 502 → other Graph errors

Footer rendering must:
  - Escape user-controlled name and url to prevent HTML injection
  - Skip malformed entries silently
  - Return empty string for empty / None / non-list inputs
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Auth gate ──


def test_share_link_requires_auth(client, fake_db):
    resp = client.post("/api/onedrive/share-link", json={"item_id": "abc"})
    assert resp.status_code in (401, 422)


# ── Happy path ──


def test_share_link_returns_url_on_success(client, fake_db, auth_bypass):
    """200 from Graph createLink → endpoint returns share_url + name."""
    create_resp = MagicMock()
    create_resp.status_code = 200
    create_resp.json.return_value = {
        "link": {"webUrl": "https://1drv.ms/abc123"}
    }
    name_resp = MagicMock()
    name_resp.status_code = 200
    name_resp.json.return_value = {"name": "brochure.pdf"}

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = create_resp
    mock_client.get.return_value = name_resp

    with patch("models.ms_token.get_fresh_access_token", return_value="tok"), \
         patch("routers.onedrive.get_fresh_access_token", return_value="tok"), \
         patch("httpx.AsyncClient", return_value=mock_client):
        resp = client.post(
            "/api/onedrive/share-link",
            json={"item_id": "01ABCXYZ"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["share_url"] == "https://1drv.ms/abc123"
    assert data["name"] == "brochure.pdf"


# ── Incremental consent (403) ──


def test_share_link_returns_needs_files_scope_on_403(client, fake_db, auth_bypass):
    """User authorized Mail scopes but not Files.ReadWrite — extension
    needs to know to launch the incremental consent flow."""
    graph_resp = MagicMock(status_code=403)
    graph_resp.text = "insufficient_scope"

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = graph_resp

    with patch("routers.onedrive.get_fresh_access_token", return_value="tok"), \
         patch("httpx.AsyncClient", return_value=mock_client):
        resp = client.post(
            "/api/onedrive/share-link",
            json={"item_id": "01XYZ"},
        )

    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["error"] == "needs_files_scope"


# ── No MS token ──


def test_share_link_returns_needs_reauth_when_no_ms_token(client, fake_db, auth_bypass):
    """No MS access token at all → match the rest of the app's
    requires_reauth path so the sidebar banner appears."""
    with patch("routers.onedrive.get_fresh_access_token", return_value=None):
        resp = client.post(
            "/api/onedrive/share-link",
            json={"item_id": "x"},
        )

    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail["error"] == "needs_reauth"


# ── 404 from Graph ──


def test_share_link_404_when_item_missing(client, fake_db, auth_bypass):
    graph_resp = MagicMock(status_code=404)
    graph_resp.text = "{}"

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = graph_resp

    with patch("routers.onedrive.get_fresh_access_token", return_value="tok"), \
         patch("httpx.AsyncClient", return_value=mock_client):
        resp = client.post(
            "/api/onedrive/share-link",
            json={"item_id": "deleted-item"},
        )

    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "file_not_found"


# ── Footer rendering ──


def test_render_footer_empty_inputs():
    from utils.email_attachments import render_attachments_footer
    assert render_attachments_footer(None) == ""
    assert render_attachments_footer([]) == ""
    assert render_attachments_footer("not a list") == ""


def test_render_footer_skips_invalid_entries():
    from utils.email_attachments import render_attachments_footer
    # Mix of valid + invalid; only valid should appear
    html = render_attachments_footer([
        {"name": "ok.pdf", "url": "https://example.com/ok"},
        {"name": "no-url"},  # missing url
        "not a dict",        # wrong type
        {"url": "https://example.com/no-name"},  # missing name → still rendered with default
        {},                  # empty
    ])
    assert "ok.pdf" in html
    assert "https://example.com/ok" in html
    assert "no-url" not in html  # missing url skipped


def test_render_footer_escapes_html():
    """Malicious filename or URL must not break out into the email DOM."""
    from utils.email_attachments import render_attachments_footer
    html = render_attachments_footer([{
        "name": '<script>alert(1)</script>',
        "url": 'javascript:"><script>alert(2)</script>',
    }])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_footer_includes_paperclip_emoji():
    from utils.email_attachments import render_attachments_footer
    html = render_attachments_footer([{
        "name": "x.pdf", "url": "https://x"
    }])
    assert "\U0001F4CE" in html  # 📎


# ── Campaign create accepts attachments ──


def test_create_campaign_stores_attachments(client, fake_db, auth_bypass):
    from tests.conftest import FAKE_USER

    with patch(
        "models.campaign.create_campaign",
        return_value={"id": "c1", "status": "draft", "user_id": FAKE_USER["id"]},
    ) as mock_create:
        resp = client.post(
            "/campaigns",
            json={
                "name": "Outreach",
                "subject": "Hi",
                "body": "Hello",
                "attachments": [
                    {"name": "deck.pdf", "url": "https://onedrive.live.com/x"},
                    {"name": "case.docx", "url": "https://onedrive.live.com/y"},
                ],
            },
        )

    assert resp.status_code == 200
    assert mock_create.called
    kwargs = mock_create.call_args.kwargs
    assert len(kwargs["attachments"]) == 2
    assert kwargs["attachments"][0]["name"] == "deck.pdf"


def test_create_campaign_caps_attachments_at_ten(client, fake_db, auth_bypass):
    """Defense-in-depth: the picker UI only allows a few, but the API
    must reject runaway lists too."""
    from tests.conftest import FAKE_USER

    many = [
        {"name": f"f{i}.pdf", "url": f"https://x/{i}"} for i in range(50)
    ]
    with patch(
        "models.campaign.create_campaign",
        return_value={"id": "c1", "status": "draft", "user_id": FAKE_USER["id"]},
    ) as mock_create:
        resp = client.post(
            "/campaigns",
            json={
                "name": "X", "subject": "Y", "body": "Z",
                "attachments": many,
            },
        )

    assert resp.status_code == 200
    kwargs = mock_create.call_args.kwargs
    assert len(kwargs["attachments"]) == 10
