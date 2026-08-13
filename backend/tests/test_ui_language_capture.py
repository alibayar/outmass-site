"""Knowing what language to write to somebody in.

The panel speaks fourteen languages and every email we send is English. The
blocker was never the templates — it is that we do not know anyone's language,
and there was no column for it until migration 030.

The value comes from the panel: getActiveLocale() in extension/i18n.js already
resolves the Settings override, then Chrome's UI language, then "en". It now
rides the X-UI-Language header on every authenticated request, which is why
there is no new endpoint and no version gate: an older build simply never
sends it, the column stays NULL, and every email falls back to English exactly
as before.

Nothing here reads Accept-Language. It describes the browser rather than the
person, and this product's own Settings screen deliberately overrides it —
guessing from the header would write Turkish to an English speaker in Istanbul.

The extension half of the agreement is tested in
extension/tests/ui-language-header.test.js, which asserts the service worker
and the panel compute the same tag.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt as pyjwt
import pytest

from config import JWT_ALGORITHM, JWT_SECRET
from models.user import _is_valid_language, maybe_touch_activity
from tests.conftest import FAKE_USER, FakeQueryBuilder


# ── The tag we are willing to store ──


@pytest.mark.parametrize(
    "given,expected",
    [
        ("en", "en"),
        ("tr", "tr"),
        ("pt-BR", "pt-BR"),
        ("zh-Hant-TW", "zh-Hant-TW"),
        ("  de  ", "de"),
        # Rejected
        (None, None),
        ("", None),
        ("   ", None),
        ("e", None),                      # too short to be a language
        ("en-US-x-verylongprivate", None),  # over the column's 16-char CHECK
        ("en_US", None),                  # underscore: the panel sends hyphens
        ("tr; DROP TABLE users", None),
        ("<script>", None),
        ("türkçe", None),                 # non-ASCII is not a BCP-47 tag
        (123, None),
    ],
)
def test_only_something_shaped_like_a_language_is_stored(given, expected):
    """Rejects rather than truncates, like _is_valid_version does: a truncated
    tag is a tag that still looks fine and means something else.

    The 16-char cap matters twice — the column carries its own CHECK, and a
    write the database refuses would surface as an exception inside the auth
    dependency on every single request from that user."""
    assert _is_valid_language(given) == expected


# ── When it gets written ──


def _user(language=None, activity_fresh=True):
    now = datetime.now(timezone.utc)
    return {
        "id": "u1",
        "last_activity_at": (
            now - timedelta(minutes=1 if activity_fresh else 600)
        ).isoformat(),
        "preferred_language": language,
        "last_seen_extension_version": "0.2.1",
    }


def _writes(user, **kwargs):
    with patch("models.user.get_db") as db:
        maybe_touch_activity(user, **kwargs)
        calls = db.return_value.table.return_value.update.call_args_list
    return [c.args[0] for c in calls]


def test_a_new_language_is_written_immediately():
    """Not gated on the 15-minute activity timer. Language changes about
    never, so the write costs nothing, and gating it would mean somebody who
    just switched language in Settings could get an email in the old one."""
    user = _user(language=None)
    writes = _writes(user, preferred_language="tr")

    assert writes and writes[0]["preferred_language"] == "tr"
    assert user["preferred_language"] == "tr", "the row in memory must agree"


def test_the_same_language_writes_nothing():
    """This runs on every authenticated request. A write per request would be
    a database call per request for a value that has not changed."""
    assert _writes(_user(language="tr"), preferred_language="tr") == []


def test_a_changed_language_is_followed():
    writes = _writes(_user(language="en"), preferred_language="ja")
    assert writes[0]["preferred_language"] == "ja"


def test_no_header_leaves_the_column_alone():
    """Every build that predates this sends nothing, and will for weeks. It
    must not clear what a newer build already told us — the same browser can
    run an old pinned build alongside a current one."""
    assert _writes(_user(language="tr")) == []
    assert _writes(_user(language="tr"), preferred_language=None) == []


def test_a_nonsense_header_is_ignored_not_stored():
    """The header is client-supplied, so it is not trusted. It is also not
    worth a 400: a request that otherwise succeeds must not fail because
    somebody's browser reported something strange."""
    assert _writes(_user(language="tr"), preferred_language="' OR 1=1--") == []


def test_language_and_version_ride_the_same_write():
    """One UPDATE, not two. Both are changed-value checks on the same row."""
    user = _user(language="en")
    writes = _writes(user, extension_version="0.3.0", preferred_language="de")
    assert len(writes) == 1
    assert writes[0]["preferred_language"] == "de"
    assert writes[0]["last_seen_extension_version"] == "0.3.0"


# ── Through the actual request ──


def _token():
    now = datetime.now(timezone.utc)
    return pyjwt.encode(
        {
            "sub": FAKE_USER["id"],
            "email": FAKE_USER["email"],
            "iat": now,
            "exp": now + timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def _request(client, fake_db, headers):
    fake_db.set_table("users", FakeQueryBuilder(data=[dict(FAKE_USER)]))
    with patch("models.user.maybe_touch_activity") as touch:
        resp = client.get(
            "/billing/status",
            headers={"Authorization": f"Bearer {_token()}", **headers},
        )
    return resp, touch


def test_the_header_reaches_the_writer(client, fake_db):
    """FastAPI maps the parameter x_ui_language onto X-UI-Language. A rename
    on either side is silent — the header just stops arriving — which is why
    the extension suite checks the same two names from the other end."""
    resp, touch = _request(client, fake_db, {"X-UI-Language": "pt-BR"})

    assert resp.status_code == 200
    assert touch.call_args.kwargs["preferred_language"] == "pt-BR"


def test_an_old_build_sends_nothing_and_still_works(client, fake_db):
    resp, touch = _request(client, fake_db, {})

    assert resp.status_code == 200
    assert touch.call_args.kwargs["preferred_language"] is None


# ── And it reaches the template ──


def test_the_stored_language_is_what_the_email_renders_in():
    """The end of the chain. Everything above is pointless if the senders do
    not pass it on."""
    from utils import welcome_email

    with patch("utils.welcome_email.render") as render, \
         patch("utils.welcome_email._dispatch"):
        render.return_value.subject = "s"
        render.return_value.text = "t"
        render.return_value.html = "h"
        welcome_email.send_welcome_email("a@b.com", "Ada", "tr")

    assert render.call_args.kwargs["lang"] == "tr"
