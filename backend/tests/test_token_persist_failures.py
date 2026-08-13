"""Two ways a Microsoft connection dies without anyone being told.

Task #42 — "a new user's refresh token died on day one" — sat uninvestigated
for weeks because there was no evidence to investigate WITH. Mapping the token
paths on 2026-08-14 found the two candidates, and they share a shape: the
sign-in succeeds, the user is told nothing, and the failure only surfaces as
scheduled sends that quietly do nothing.

ONE — a rotated refresh token thrown away. Microsoft rotates: a successful
refresh returns a NEW refresh token and the one we sent may already be spent.
That write sat inside a try whose except caught only httpx.HTTPError, so a
database failure escaped the function entirely — into the caller's unguarded
per-contact loop — with the new token unsaved and the old one dead.

TWO — a first sign-in with no refresh token at all. No row is written, so
get_fresh_access_token later finds nothing and returns None. Every later
failure is an absence rather than an error, which is why nothing anywhere
reported it. From the outside it looks exactly like a token that died on day
one; from the inside it never lived.
"""
from unittest.mock import MagicMock, patch

import pytest

from models import ms_token


class _ExplodingUpdate:
    """A user_tokens table whose update() fails the way postgrest does."""

    def table(self, name):
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def update(self, *a, **k):
        raise RuntimeError("could not connect to the database")

    def execute(self):
        return MagicMock(data=[])


def _refresh(new_refresh, db):
    """Drive get_fresh_access_token down the refresh branch."""
    row = {"access_token": None, "refresh_token": "rt_old"}
    ms_resp = MagicMock(status_code=200)
    ms_resp.json.return_value = {
        "access_token": "at_new",
        "refresh_token": new_refresh,
    }

    with patch("models.ms_token.get_db", return_value=db), \
         patch("models.ms_token.select_user_tokens",
               return_value=MagicMock(data=[row])), \
         patch("models.ms_token.httpx.post", return_value=ms_resp), \
         patch("models.ms_token._alert_token_persist_failed") as alert:
        token = ms_token.get_fresh_access_token("u-42")
    return token, alert


# ── One: the rotated token ──


def test_a_failed_persist_does_not_escape_into_the_send_loop():
    """The caller iterates contacts with no try of its own. An exception here
    aborted the whole run partway through a campaign."""
    token, _ = _refresh("rt_rotated", _ExplodingUpdate())

    assert token == "at_new", "the caller lost a perfectly good access token"


def test_losing_a_rotated_refresh_token_tells_an_operator():
    """Nothing else can see it. Microsoft is satisfied, the user is signed in
    and working, and the only later trace is a refresh that fails for a reason
    nobody can reconstruct — which is how #42 came to be unanswerable."""
    _, alert = _refresh("rt_rotated", _ExplodingUpdate())

    alert.assert_called_once_with("u-42")


def test_a_failed_persist_of_an_UNCHANGED_token_is_not_an_alert():
    """Microsoft does not always rotate. When it returned the same token we
    already hold, the write failing costs nothing — the stored value is still
    correct — and alerting on it would be the false alarm that teaches an
    operator to skim past the real one."""
    _, alert = _refresh("rt_old", _ExplodingUpdate())

    alert.assert_not_called()


def test_the_alert_says_what_the_user_will_experience():
    sent = []
    with patch("routers.billing._telegram_alert", side_effect=lambda m: sent.append(m)):
        ms_token._alert_token_persist_failed("u-42")

    assert sent and "u-42" in sent[0]
    assert "reconnect" in sent[0].lower(), (
        "the alert does not say what happens to the customer"
    )


def test_the_alert_cannot_raise():
    """It runs in the recovery path of a failure. A failure in it must not
    become the exception."""
    with patch("routers.billing._telegram_alert",
               side_effect=RuntimeError("telegram down")):
        ms_token._alert_token_persist_failed("u-42")


# ── Two: the first sign-in that stored nothing ──


def test_a_first_signin_with_no_refresh_token_flags_the_user():
    """It used to log a warning and stop. The user was left believing they
    were connected, with nothing stored and no banner, until a campaign they
    scheduled silently did nothing."""
    from routers import auth as auth_router

    db = MagicMock()
    db.table.return_value.insert.return_value.execute.return_value = MagicMock()

    with patch("database.get_db", return_value=db), \
         patch("routers.auth.ms_token_model.select_user_tokens",
               return_value=MagicMock(data=[])), \
         patch("routers.auth.ms_token_model.mail_read_column_attemptable",
               return_value=False), \
         patch("routers.auth.ms_token_model.mark_requires_reauth") as flag:
        auth_router._persist_ms_tokens(
            user_id="u-new",
            access_token="at",
            refresh_token=None,
            wants_onedrive=False,
        )

    flag.assert_called_once()
    assert flag.call_args.args[0] == "u-new"


def test_the_reason_recorded_is_specific_enough_to_investigate():
    """#42 was unanswerable because nothing recorded WHY. A reason of
    'refresh_failed' would have been the same dead end."""
    from routers import auth as auth_router

    db = MagicMock()

    with patch("database.get_db", return_value=db), \
         patch("routers.auth.ms_token_model.select_user_tokens",
               return_value=MagicMock(data=[])), \
         patch("routers.auth.ms_token_model.mail_read_column_attemptable",
               return_value=False), \
         patch("routers.auth.ms_token_model.mark_requires_reauth") as flag:
        auth_router._persist_ms_tokens(
            user_id="u-new", access_token="at", refresh_token=None,
            wants_onedrive=False,
        )

    reason = flag.call_args.args[1]
    assert reason == "no_refresh_token_on_first_signin", reason


def test_a_first_signin_WITH_a_refresh_token_is_not_flagged():
    """The ordinary case, which is every sign-in that has ever worked."""
    from routers import auth as auth_router

    db = MagicMock()

    with patch("database.get_db", return_value=db), \
         patch("routers.auth.ms_token_model.select_user_tokens",
               return_value=MagicMock(data=[])), \
         patch("routers.auth.ms_token_model.mail_read_column_attemptable",
               return_value=False), \
         patch("routers.auth.ms_token_model.mark_requires_reauth") as flag:
        auth_router._persist_ms_tokens(
            user_id="u-ok", access_token="at", refresh_token="rt",
            wants_onedrive=False,
        )

    flag.assert_not_called()
