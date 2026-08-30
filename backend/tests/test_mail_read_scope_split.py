"""Mail.Read leaves the first sign-in ask — without narrowing anyone's token.

Microsoft renders Mail.Read as "Read your mail", the most alarming line on a
consent screen shown to someone who has not sent a single email with OutMass
yet. It exists only for reply detection, which cannot matter before the first
campaign. Measured 2026-08-06: ~31% of first-time Chrome users and ~54% of
first-time Edge users never finish the consent screen, and publisher
verification (2026-06-24) did not move that number.

The whole risk of this change lives in ONE place: a refresh-token request must
scope-match the user's prior consent. Ask for a scope they never granted and
Microsoft answers AADSTS65001 and the WHOLE refresh fails — every background
send for that user stops. Ask for LESS than they granted and Microsoft happily
issues a narrower token, which silently kills reply detection for the entire
existing base. Both directions are covered below.

The split is also env-gated: with FIRST_SIGNIN_INCLUDE_MAIL_READ true (the
default) this code must behave byte-for-byte like the old code, so the deploy
is inert until Ali runs migration 024 and flips the variable.
"""
from unittest.mock import MagicMock, patch

from config import (
    MS_GRAPH_FIRST_SIGNIN_SCOPES,
    MS_GRAPH_ONEDRIVE_SCOPES,
    MS_GRAPH_SCOPES,
)
from routers import auth as auth_module
from routers.auth import _encode_state, _state_includes_mail_read

CHROME_EXT = "adcfddainnkjomddlappnnbeomhlcbmm"


# ── the scope constants themselves ──


def test_first_signin_scopes_drop_only_mail_read():
    """Nothing else may fall out of the ask by accident."""
    full = set(MS_GRAPH_SCOPES.split())
    narrow = set(MS_GRAPH_FIRST_SIGNIN_SCOPES.split())
    assert full - narrow == {"https://graph.microsoft.com/Mail.Read"}
    assert "offline_access" in narrow, "no refresh token without offline_access"
    assert "https://graph.microsoft.com/Mail.Send" in narrow, "sending is the product"


# ── /auth/login ──


# A build new enough to decide for itself whether it needs Mail.Read. The
# helper sends it by default because that is the interesting case; the tests
# below that care about an OLD client pass v=None or an older string
# explicitly, because that is the case the gate exists for.
NEW_CLIENT = "0.2.3"


def _authorize_scope(client, v=NEW_CLIENT, **params):
    if v is not None:
        params["v"] = v
    resp = client.get(
        "/auth/login",
        params={"ext": CHROME_EXT, **params},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(resp.headers["location"]).query)["scope"][0]


def test_flag_on_is_byte_for_byte_the_old_behaviour(client):
    """The deploy must change nothing until the variable is flipped."""
    with patch.object(auth_module, "FIRST_SIGNIN_INCLUDE_MAIL_READ", True):
        assert _authorize_scope(client) == MS_GRAPH_SCOPES


def test_flag_off_asks_a_new_user_for_less(client):
    with patch.object(auth_module, "FIRST_SIGNIN_INCLUDE_MAIL_READ", False):
        scope = _authorize_scope(client)
    assert scope == MS_GRAPH_FIRST_SIGNIN_SCOPES
    assert "Mail.Read" not in scope
    assert "Mail.Send" in scope


def test_explicit_upgrade_asks_for_mail_read_even_when_flag_is_off(client):
    with patch.object(auth_module, "FIRST_SIGNIN_INCLUDE_MAIL_READ", False):
        scope = _authorize_scope(client, include_mail_read="true")
    assert "Mail.Read" in scope


def test_onedrive_upgrade_still_composes_with_the_narrow_base(client):
    with patch.object(auth_module, "FIRST_SIGNIN_INCLUDE_MAIL_READ", False):
        scope = _authorize_scope(client, include_onedrive="true")
    assert scope == f"{MS_GRAPH_FIRST_SIGNIN_SCOPES} {MS_GRAPH_ONEDRIVE_SCOPES}"
    assert "Mail.Read" not in scope, (
        "opting into OneDrive must not smuggle Mail.Read back in — that would "
        "reintroduce the scary permission at the worst moment"
    )


# ── the version gate: who is allowed to be given less ──
#
# The flag used to be owed a flip "once 0.2.3 is on both stores and enough
# people have updated" — a condition nothing in the system could evaluate and
# only a human could remember, weeks later, after two store reviews on
# someone else's schedule. These tests are what replaced that condition, so
# that flipping the flag is safe on the day it is wanted.


def test_a_client_too_old_to_ask_keeps_the_wide_scope(client):
    """The whole reason /auth/login reads a version.

    A pre-0.2.3 panel has no code for "should this sign-in include
    Mail.Read". It never sends include_mail_read, so a RETURNING user on that
    build looks exactly like a new user on a modern one. Hand it the narrow
    consent and that user loses reply detection — and their next refresh asks
    Microsoft for a scope they no longer hold, which is AADSTS65001 and a
    dead sign-in.
    """
    with patch.object(auth_module, "FIRST_SIGNIN_INCLUDE_MAIL_READ", False):
        scope = _authorize_scope(client, v=None)
    assert "Mail.Read" in scope, (
        "a client that cannot ask for Mail.Read was given the narrow consent"
    )
    assert scope == MS_GRAPH_SCOPES


def test_an_older_numbered_client_also_keeps_it(client):
    with patch.object(auth_module, "FIRST_SIGNIN_INCLUDE_MAIL_READ", False):
        assert _authorize_scope(client, v="0.2.2") == MS_GRAPH_SCOPES


def test_an_unreadable_version_is_treated_as_old(client):
    """Someone else's request, a proxy rewriting the query, a hand-typed URL:
    unknown is not a reason to give less."""
    with patch.object(auth_module, "FIRST_SIGNIN_INCLUDE_MAIL_READ", False):
        assert _authorize_scope(client, v="nonsense") == MS_GRAPH_SCOPES


def test_a_double_digit_patch_is_not_read_as_older(client):
    """String comparison would say "0.2.10" < "0.2.3" and quietly keep the
    wide ask for everyone who had updated furthest."""
    with patch.object(auth_module, "FIRST_SIGNIN_INCLUDE_MAIL_READ", False):
        assert "Mail.Read" not in _authorize_scope(client, v="0.2.10")


def test_the_flag_still_wins_for_a_new_client(client):
    """The gate narrows who the flag applies to; it does not override it.
    With the flag on — today — even a modern client gets the wide ask."""
    with patch.object(auth_module, "FIRST_SIGNIN_INCLUDE_MAIL_READ", True):
        assert _authorize_scope(client, v=NEW_CLIENT) == MS_GRAPH_SCOPES


def test_an_old_client_asking_explicitly_is_still_honoured(client):
    """Version gates who may be given LESS, never who may ask for more. A
    pre-0.2.3 client upgrading for OneDrive or reply detection still gets
    what it asked for."""
    with patch.object(auth_module, "FIRST_SIGNIN_INCLUDE_MAIL_READ", False):
        scope = _authorize_scope(client, v=None, include_mail_read="true")
    assert "Mail.Read" in scope


# ── state round-trip ──


def test_state_records_what_was_asked_for(client):
    with patch.object(auth_module, "FIRST_SIGNIN_INCLUDE_MAIL_READ", False):
        resp = client.get(
            "/auth/login",
            params={"ext": CHROME_EXT, "v": NEW_CLIENT},
            follow_redirects=False,
        )
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    assert _state_includes_mail_read(state) is False


def test_legacy_state_without_the_flag_means_mail_read_was_asked_for():
    """A sign-in already in flight when this deploys carries the OLD state
    shape. Reading its silence as "no Mail.Read" would make the token exchange
    under-request and quietly drop the scope from a user who consented to it.
    """
    import base64
    import json

    legacy = (
        base64.urlsafe_b64encode(
            json.dumps({"ext": CHROME_EXT, "n": "abc"}).encode()
        )
        .decode()
        .rstrip("=")
    )
    assert _state_includes_mail_read(legacy) is True
    assert _state_includes_mail_read(None) is True, "no state at all: assume the old ask"
    assert _state_includes_mail_read("!!!not-base64!!!") is True


def test_state_with_the_flag_set_round_trips():
    assert _state_includes_mail_read(_encode_state(CHROME_EXT, include_mail_read=True))
    assert (
        _state_includes_mail_read(
            _encode_state(CHROME_EXT, include_mail_read=False)
        )
        is False
    )


# ── refresh-token scope matching: the part that can break every user ──


def _refresh_scope_for(row):
    """Run the real get_fresh_access_token far enough to capture the scope it
    would send to Microsoft."""
    from models import ms_token

    captured = {}

    def _fake_post(url, data=None, **kwargs):
        captured["scope"] = data.get("scope")
        resp = MagicMock()
        resp.status_code = 400  # stop right after the scope decision
        resp.json.return_value = {"error": "stop"}
        resp.text = "stop"
        return resp

    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[row])
    )

    # 401 on the validity probe makes the stored token look expired, so the
    # code proceeds to the refresh — which is the request we want to inspect.
    expired = MagicMock()
    expired.status_code = 401

    with patch.object(ms_token, "get_db", return_value=db), \
         patch.object(ms_token.httpx, "get", return_value=expired), \
         patch.object(ms_token.httpx, "post", side_effect=_fake_post), \
         patch.object(ms_token, "_mark_requires_reauth"):
        ms_token.get_fresh_access_token("u1")
    assert "scope" in captured, "the refresh request never happened — test setup is wrong"
    return captured["scope"]


def test_existing_users_keep_asking_for_mail_read():
    """The base case that must never regress: everyone who signed in before
    the split has Mail.Read, and their refresh must keep requesting it."""
    scope = _refresh_scope_for(
        {"access_token": "a", "refresh_token": "r", "has_mail_read_scope": True}
    )
    assert scope == MS_GRAPH_SCOPES


def test_a_row_predating_the_migration_keeps_mail_read():
    """Migration 024 may not have run yet, so the key can be absent. Missing
    must read as True — every pre-024 row belongs to someone who granted it."""
    scope = _refresh_scope_for({"access_token": "a", "refresh_token": "r"})
    assert scope == MS_GRAPH_SCOPES, (
        "an absent column made every established user's refresh narrower — "
        "reply detection would die silently for the whole base"
    )


def test_a_narrow_user_does_not_request_mail_read():
    """And the other direction: asking for a scope they never granted is
    AADSTS65001, which fails the ENTIRE refresh, not just reply detection."""
    scope = _refresh_scope_for(
        {"access_token": "a", "refresh_token": "r", "has_mail_read_scope": False}
    )
    assert scope == MS_GRAPH_FIRST_SIGNIN_SCOPES
    assert "Mail.Read" not in scope


def test_onedrive_and_mail_read_compose_on_refresh():
    scope = _refresh_scope_for(
        {
            "access_token": "a",
            "refresh_token": "r",
            "has_mail_read_scope": False,
            "has_onedrive_scope": True,
        }
    )
    assert scope == f"{MS_GRAPH_FIRST_SIGNIN_SCOPES} {MS_GRAPH_ONEDRIVE_SCOPES}"

    both = _refresh_scope_for(
        {
            "access_token": "a",
            "refresh_token": "r",
            "has_mail_read_scope": True,
            "has_onedrive_scope": True,
        }
    )
    assert both == f"{MS_GRAPH_SCOPES} {MS_GRAPH_ONEDRIVE_SCOPES}"


# ── persistence stickiness ──


def _persist(existing_row, wants_mail_read):
    captured = {}
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[existing_row] if existing_row else [])
    )

    def _update(vals):
        captured.update(vals)
        return MagicMock(eq=lambda *a: MagicMock(execute=lambda: None))

    def _insert(vals):
        captured.update(vals)
        return MagicMock(execute=lambda: None)

    db.table.return_value.update = _update
    db.table.return_value.insert = _insert

    with patch("database.get_db", return_value=db):
        auth_module._persist_ms_tokens(
            user_id="u1",
            access_token="a",
            refresh_token="r",
            wants_onedrive=False,
            wants_mail_read=wants_mail_read,
        )
    return captured


def test_consent_is_sticky_once_granted():
    """A later narrow sign-in must not revoke a grant the user already made —
    the consent record outlives any individual token."""
    row = _persist({"id": "t1", "has_mail_read_scope": True}, wants_mail_read=False)
    assert row["has_mail_read_scope"] is True


def test_upgrade_flips_the_flag_on():
    row = _persist({"id": "t1", "has_mail_read_scope": False}, wants_mail_read=True)
    assert row["has_mail_read_scope"] is True


def test_brand_new_narrow_user_is_recorded_as_narrow():
    """No prior row means no prior consent — only this flow's own ask counts.
    Defaulting a new user to True would make their refresh request Mail.Read
    and fail with AADSTS65001 on every background send."""
    row = _persist(None, wants_mail_read=False)
    assert row["has_mail_read_scope"] is False
