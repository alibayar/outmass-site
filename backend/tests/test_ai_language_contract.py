"""The AI writer's language picker and the backend must agree.

`_LANG_NAMES.get(code, "English")` fails silently: a code the map doesn't know
produces a perfectly successful English email, so a user who picked their own
language just gets the wrong one with no error anywhere. That is exactly what
would have shipped in 0.1.27 — the sidebar gained a Portuguese option while
the backend map still ended at "ja".

These tests pin both halves of the contract.
"""
import os
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routers.ai import _LANG_NAMES

SIDEBAR_JS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "extension",
    "sidebar.js",
)

# Matches the AI-writer picker rows: '<option value="pt">' + t("aiLangPt") + ...
# Case-insensitive character class on purpose: a region-qualified value like
# "pt_BR" or "zh_CN" must be CAUGHT by this check, not quietly skipped by a
# lowercase-only pattern.
_AI_LANG_OPTION = re.compile(r'<option value="([A-Za-z_]{2,5})">\'\s*\+\s*t\("aiLang')


def test_every_picker_language_has_a_backend_name():
    if not os.path.exists(SIDEBAR_JS):
        pytest.skip("extension/sidebar.js not present in this checkout")

    with open(SIDEBAR_JS, encoding="utf-8") as fh:
        src = fh.read()
    codes = _AI_LANG_OPTION.findall(src)

    assert codes, "picker options not found — did the AI modal markup change?"

    # A regex that silently matches fewer rows than exist would make the
    # assertion below vacuous, so pin the count to the t("aiLang…") calls.
    #
    # The count is hoisted into a local rather than inlined into the f-string
    # below on purpose: `f"{src.count('t(\"aiLang')}"` puts a backslash inside
    # an f-string expression, which PEP 701 only legalised in Python 3.12.
    # Local dev runs 3.14 and swallowed it; CI pins 3.11 (.github/workflows/
    # ci.yml) and raised SyntaxError at COLLECTION time, so pytest aborted
    # before running anything — all 555 backend tests were dark in CI from
    # 2026-07-29 until this was found on 08-08. A syntax error in one test
    # file silently disables every other one, so keep this expression plain.
    label_count = src.count('t("aiLang')
    assert len(codes) == label_count, (
        f"regex matched {len(codes)} picker options but the file has "
        f"{label_count} aiLang labels — the pattern is stale, "
        "so some options are escaping this check"
    )

    missing = [c for c in codes if c not in _LANG_NAMES]
    assert not missing, (
        f"sidebar offers {missing} but routers.ai._LANG_NAMES has no entry — "
        "those users would silently receive English emails"
    )


def test_portuguese_reaches_the_model_as_portuguese(client, auth_bypass_pro, fake_db):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "content": [{"type": "text", "text": '{"subject": "Olá", "body": "<p>Olá</p>"}'}]
    }

    with patch("routers.ai.ANTHROPIC_API_KEY", "sk-test"), \
         patch("routers.ai.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        resp = client.post(
            "/ai/generate-email",
            json={"prompt": "Cold outreach for our SaaS", "language": "pt"},
        )

    assert resp.status_code == 200
    sent = mock_client.post.call_args.kwargs["json"]
    user_message = sent["messages"][0]["content"]
    assert "Write in Portuguese." in user_message


def test_unknown_language_still_falls_back_to_english(client, auth_bypass_pro, fake_db):
    """Documents the fallback so nobody 'fixes' it into a 500 for old clients."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "content": [{"type": "text", "text": '{"subject": "S", "body": "<p>B</p>"}'}]
    }

    with patch("routers.ai.ANTHROPIC_API_KEY", "sk-test"), \
         patch("routers.ai.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        resp = client.post(
            "/ai/generate-email",
            json={"prompt": "hi", "language": "xx-not-a-language"},
        )

    assert resp.status_code == 200
    sent = mock_client.post.call_args.kwargs["json"]
    assert "Write in English." in sent["messages"][0]["content"]
