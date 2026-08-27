"""Naming WHOSE problem a failed sign-in was.

On 2026-08-10, asked "why did today's new users not get in", the honest
answer was that we could not tell. Every failure without a recognised AADSTS
code landed in one bucket called "unclassified", which mixed three unrelated
states:

  * Microsoft denied the request and did not say why
  * Microsoft sent a code we have no meaning for
  * Microsoft said `invalid_client` — a statement that the rejection was
    about OUR app registration, sitting right next to an unknown code and
    read by nothing

The third one is the sharp case. A user was turned away with AADSTS650051 —
which Microsoft does not publish in its own error reference — and was told
"please try again", advice that could never have worked if the cause really
was our registration.

These tests pin the split, and the attribution property that answers the
question directly: user, tenant, app, microsoft, or an honest unknown.
"""
import pytest

from routers import auth


def _classify(error, description=None):
    return auth._classify_ms_error(error, description)


# ── the case that prompted this ──


def test_650051_is_microsofts_race_not_our_registration():
    """Corrected 2026-08-27, and the correction is the interesting part.

    This test used to assert that AADSTS650051 meant our app registration was
    refused, because `invalid_client` sat beside it. Both of that day's
    sign-ups hit it and both were signed in within thirty seconds of retrying
    - which a refused registration cannot do, since it would fail every time.
    Microsoft's own Q&A threads describe 650051 as the service principal
    already existing in the target tenant while Entra has not finished
    provisioning it: a transient that clears on retry.

    The cost of the old belief was not the label. It was the sentence the
    label produced: "This is our fault, not yours. Please report it" - asking
    the user to do the one thing that cannot help, and not to do the one that
    can.
    """
    c = _classify("invalid_client", "AADSTS650051: Something undocumented.")
    assert c["meaning"] == "tenant_provisioning_race"
    assert c["attributed_to"] == "microsoft"
    # The raw code still travels for support.
    assert c["aadsts"] == "AADSTS650051"


def test_650051_tells_the_user_to_retry():
    """The whole point of the reclassification, pinned where it is visible."""
    c = _classify("invalid_client", "AADSTS650051: Something undocumented.")
    settle = auth._ms_settle_code(c, fallback="invalid_client")
    assert "Retry" in settle
    assert "our fault" not in settle
    assert "AADSTS650051" in settle
    assert len(settle) <= 64


def test_invalid_client_without_any_code_still_names_the_app():
    """The OAuth error value alone is a definite statement."""
    c = _classify("invalid_client", None)
    assert c["meaning"] == "app_registration_rejected"
    assert c["attributed_to"] == "app"
    assert c["aadsts"] is None


# ── the two unknowns must stay apart ──


def test_unknown_code_and_no_code_are_different_states():
    unknown_code = _classify("access_denied", "AADSTS999999: brand new.")
    no_code = _classify("access_denied", "the user is gone")

    assert unknown_code["meaning"] == "unclassified_code"
    assert no_code["meaning"] == "no_code_from_microsoft"
    assert unknown_code["meaning"] != no_code["meaning"], (
        "merging these is what made the largest slice of sign-in losses "
        "unreadable"
    )
    assert unknown_code["attributed_to"] == "unknown"
    assert no_code["attributed_to"] == "unknown"


def test_a_known_code_outranks_the_oauth_error_value():
    """AADSTS65004 is specific; access_denied is not. The specific one wins."""
    c = _classify("access_denied", "AADSTS65004: User declined to consent.")
    assert c["meaning"] == "user_declined_consent"
    assert c["attributed_to"] == "user"


# ── the split that matters for what we DO about it ──


@pytest.mark.parametrize("code,expected", [
    ("AADSTS65004", "user"),      # they chose to say no
    ("AADSTS50076", "user"),      # their MFA step
    ("AADSTS90094", "tenant"),    # their IT must approve
    ("AADSTS53003", "tenant"),    # conditional access
    ("AADSTS50105", "tenant"),    # not assigned to the app
    ("AADSTS700016", "tenant"),   # app absent from their org
    ("AADSTS7000218", "app"),     # our secret
    ("AADSTS50011", "app"),       # our redirect uri
])
def test_user_and_tenant_failures_are_not_the_same_problem(code, expected):
    """"The person refused" and "their employer refused" need different
    responses; until now both arrived as consent_declined."""
    assert _classify("access_denied", f"{code}: whatever")["attributed_to"] == expected


def test_microsoft_side_errors_are_attributed_to_microsoft():
    for err in ("server_error", "temporarily_unavailable"):
        assert _classify(err, None)["attributed_to"] == "microsoft"


# ── the sentences the user actually reads ──


def test_no_code_message_does_not_blame_the_user():
    """We cannot distinguish a refusal from a tenant block here, so the
    sentence must not pretend to.

    Called the way the callback calls it — with the raw `error` as fallback —
    because the first version of this test omitted it and therefore never
    exercised the branch that appends the RFC code.
    """
    err = "access_denied"
    msg = auth._ms_settle_code(_classify(err, "no code here"), fallback=err)
    assert msg.startswith("Sign-in did not complete. Retry or contact us")
    assert "declined" not in msg.lower()
    # The RFC word is the only class signal when there is no AADSTS number,
    # so it must survive — but as a parenthetical, not as the whole message.
    assert msg.endswith("(access denied)")


def test_app_fault_message_keeps_the_rfc_code():
    err = "invalid_client"
    msg = auth._ms_settle_code(_classify(err, None), fallback=err)
    assert "our fault" in msg
    assert msg.endswith("(invalid client)")
    assert len(msg) <= 64


def test_app_fault_message_reaches_a_user_with_no_code():
    msg = auth._ms_settle_code(_classify("invalid_client", None))
    assert "our fault" in msg


def test_unknown_code_message_carries_the_code():
    msg = auth._ms_settle_code(_classify("access_denied", "AADSTS999999: x"))
    assert "AADSTS999999" in msg
    assert "send us this code" in msg


# ── structural: the sentences must survive the wire ──


def test_every_message_survives_the_sanitizer_unchanged():
    """The fragment sanitizer keeps only [A-Za-z0-9 .,:()-]. An apostrophe or
    an `@` is silently deleted, so "don't" ships as "dont" and an email
    address as a mangled domain. Any message that changes shape here is a
    message we did not actually write."""
    for key, msg in auth._SETTLE_MESSAGES.items():
        assert auth._settle_fragment(msg) == msg, (
            f"{key} loses characters in transit: {msg!r} -> "
            f"{auth._settle_fragment(msg)!r}"
        )


# The 48-char budget is already enforced by
# test_auth_settle_redirect.py::test_settle_messages_are_deliverable, which
# caught this file's first draft at 49. Not duplicated here — two tests
# asserting one rule drift apart, and the older one has the better message.


def test_every_named_meaning_has_an_attribution():
    """A meaning with no side is a meaning that cannot be acted on."""
    named = set(auth._AADSTS_MEANINGS.values()) | set(auth._APP_LEVEL_ERRORS.values())
    missing = named - set(auth._MEANING_ATTRIBUTION)
    assert not missing, f"no attribution for: {sorted(missing)}"


# ── the alert that would have found 650051 seventeen days earlier ──


def test_only_failures_on_our_side_page_the_operator(monkeypatch):
    """AADSTS650051 had been turning users away since at least 2026-08-10 and
    was found on 08-27 only because somebody went looking. The events existed
    the whole time; nothing said so.

    A consent decline must stay silent: a channel that reports people's
    choices as incidents stops being read, and then the real ones go with it.
    """
    import routers.billing as billing

    sent = []
    monkeypatch.setattr(billing, "_telegram_alert", lambda m: sent.append(m))

    auth._alert_if_ours("authorize", _classify(
        "invalid_client", "AADSTS650051: undocumented"), "api.getoutmass.com")
    auth._alert_if_ours("authorize", _classify(
        "access_denied", "AADSTS65004: The user declined."), "api.getoutmass.com")

    assert len(sent) == 1
    assert "tenant_provisioning_race" in sent[0]
    assert "AADSTS650051" in sent[0]


def test_a_broken_alert_channel_cannot_break_the_sign_in(monkeypatch):
    """The user is mid-sign-in and this is garnish."""
    import routers.billing as billing

    def boom(_m):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(billing, "_telegram_alert", boom)
    auth._alert_if_ours("authorize", _classify(
        "invalid_client", "AADSTS650051: undocumented"), "api.getoutmass.com")
