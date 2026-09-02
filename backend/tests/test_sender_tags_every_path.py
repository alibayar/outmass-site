"""Every send path resolves the sender tags. All three. Every time.

This repo has now shipped the same shape of bug four times: a fix lands in one
of the three send paths and the other two keep the old behaviour, because the
send-now path is the one a developer exercises by hand and the workers are the
ones real campaigns actually go through.

    2026-09-01  render_body — scheduled sends arrived as one block
    (earlier)   the suppression-skip write
    2026-09-02  build_merge_context(contact) with no sender_info

The third is the one this file exists for. `{{senderName}}`, `{{senderPosition}}`,
`{{senderCompany}}`, `{{senderPhone}}` and `{{senderLogo}}` resolved correctly
in the panel preview, in the test send and in Send Now — and shipped as literal
braces on every scheduled campaign, every paced remainder and every follow-up.
Those are the paths paying users are on: anyone using a daily cap or a
schedule, which is the whole reason to buy this rather than paste into BCC.

`_merge` leaves an unknown tag exactly as written, so the recipient reads
"{{senderName}}" in a cold outreach email sent from the customer's own
mailbox. That is the worst failure this product has: not a crash, not a lost
send, but a message that makes the sender look careless to someone they were
trying to impress.

The guard is behavioural on purpose. A structural test ("does the call have
two arguments") passes the moment somebody adds a default back.
"""
import inspect

import pytest

from utils.merge_tags import build_merge_context

SENDER = {
    "id": "user-1",
    "sender_name": "Hélène Carpentier",
    "sender_position": "Workplace Consultant",
    "sender_company": "Circular Workplaces",
    "sender_phone": "+33 1 23 45 67 89",
    "sender_logo_url": "https://cdn.example.com/logo.png",
    "unsubscribe_text": "Se désabonner",
}

CONTACT = {
    "first_name": "Ada", "last_name": "Lovelace",
    "email": "ada@example.com", "company": "Acme", "position": "CTO",
    "custom_fields": {"hook": "your Q3 refit"},
}

BODY = (
    "Hi {{firstName}},\n\n"
    "About {{hook}} at {{company}}.\n\n"
    "Best,\n{{senderName}}\n{{senderPosition}}, {{senderCompany}}\n"
    "{{senderPhone}}\n{{senderLogo}}\n"
)

SENDER_TAGS = ("{{senderName}}", "{{senderPosition}}", "{{senderCompany}}",
               "{{senderPhone}}", "{{senderLogo}}")


def _merge_with(ctx):
    """The same substitution every send path uses."""
    from workers.scheduled_worker import _merge

    return _merge(BODY, ctx)


def test_the_context_resolves_every_sender_tag():
    out = _merge_with(build_merge_context(CONTACT, SENDER))
    for tag in SENDER_TAGS:
        assert tag not in out, f"{tag} shipped with its braces on"
    assert "Hélène Carpentier" in out
    assert 'src="https://cdn.example.com/logo.png"' in out


# ── the part that keeps catching us: which paths pass it ──


SEND_FUNCTIONS = [
    ("scheduled_worker", "_send_email"),
    ("followup_worker", "_send_followup_email"),
]


@pytest.mark.parametrize("module_name,func_name", SEND_FUNCTIONS)
def test_every_worker_send_takes_sender_info(module_name, func_name):
    """A send function that cannot be given the sender cannot resolve the
    tags, whatever its body does."""
    import importlib

    mod = importlib.import_module(f"workers.{module_name}")
    sig = inspect.signature(getattr(mod, func_name))
    assert "sender_info" in sig.parameters, (
        f"workers.{module_name}.{func_name} takes no sender_info, so every "
        f"email it sends carries literal {{{{senderName}}}} braces"
    )
    assert sig.parameters["sender_info"].default is inspect.Parameter.empty, (
        f"sender_info has a default in {module_name}.{func_name} — a caller "
        f"that forgets it is silent again, which is how this shipped"
    )


def test_build_merge_context_refuses_to_be_called_without_a_sender():
    """No default. Forgetting must be a TypeError at the call, not a literal
    brace in a stranger's inbox."""
    with pytest.raises(TypeError):
        build_merge_context(CONTACT)


@pytest.mark.parametrize("module_name,func_name", SEND_FUNCTIONS)
def test_every_worker_call_site_actually_passes_it(module_name, func_name):
    """The signature is necessary and not sufficient: the call sites have to
    hand over the row they already have. Both workers already read
    `unsubscribe_text` off the same `user`, which is what made the omission so
    easy to miss in review."""
    import importlib
    import re

    mod = importlib.import_module(f"workers.{module_name}")
    src = inspect.getsource(mod)
    calls = re.findall(
        rf"{func_name}\(\s*(.*?)\)\s*$",
        src, re.DOTALL | re.MULTILINE,
    )
    invocations = [c for c in calls if "client=" in c]
    assert invocations, f"no call to {func_name} found in {module_name}"
    for args in invocations:
        assert "sender_info=" in args, (
            f"a call to {func_name} in {module_name} does not pass "
            f"sender_info:\n{args[:300]}"
        )


def test_a_user_with_no_sender_settings_gets_empty_strings_not_braces():
    """Most users have never opened Settings. An unset sender name must
    disappear, not arrive as punctuation."""
    out = _merge_with(build_merge_context(CONTACT, {"id": "u"}))
    for tag in SENDER_TAGS:
        assert tag not in out, f"{tag} survived for a user with no settings"
    assert "<img" not in out, "an unset logo produced an image tag"
