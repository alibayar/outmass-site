"""A merge tag must never put the word "None" into someone's greeting.

Hélène Carpentier asked for a follow-up to be attached to her campaign on
2026-09-01 and wrote, in the same message:

    "Please make sure the formatting is right and firstname is showing up
    correctly."

It was not. `contact.get("first_name", "")` returns the DEFAULT only when the
KEY is missing, and PostgREST always returns the column — so a NULL first_name
arrives as the key present with the value None, the default never fires, and
`str(None)` renders:

    Hi None,

as the first line of a real email, from the customer's own mailbox, to their
own prospect. All three send paths had it, built independently, because all
three built the merge context themselves.

That last part is the reason this file also has a structural test. Twice now a
fix has landed in one send path and been left out of the other two — render_body
on 2026-09-01, the suppression-skip write before it. The contexts are one
function now, and the test says so.
"""
import inspect

import pytest

from utils.merge_tags import build_merge_context


def test_a_null_first_name_renders_as_nothing_not_as_none():
    """The defect, in the shape it actually arrives from the database."""
    ctx = build_merge_context({"first_name": None, "email": "a@example.com"})

    assert ctx["firstName"] == "", (
        f"firstName is {ctx['firstName']!r} - a recipient whose row has no "
        f"first name is greeted 'Hi None,'"
    )


@pytest.mark.parametrize(
    "column", ["first_name", "last_name", "company", "position", "email"]
)
def test_every_contact_field_survives_a_null(column):
    ctx = build_merge_context({column: None})
    assert None not in ctx.values()
    assert "None" not in "".join(ctx.values())


def test_a_missing_key_is_also_empty():
    """A contact dict that simply lacks the column - the case the original
    `.get(key, "")` was written for, which must keep working."""
    ctx = build_merge_context({"email": "a@example.com"})
    assert ctx["firstName"] == ""
    assert ctx["company"] == ""


def test_a_null_custom_field_is_empty_too():
    """A spreadsheet column filled for one row and blank for the next is the
    ordinary case, not the exotic one."""
    ctx = build_merge_context(
        {"first_name": "Ada", "custom_fields": {"city": None, "plan": "Pro"}}
    )
    assert ctx["city"] == ""
    assert ctx["plan"] == "Pro"
    assert ctx["firstName"] == "Ada"


def test_a_null_sender_field_is_empty_too():
    ctx = build_merge_context({"email": "a@example.com"}, {"sender_name": None})
    assert ctx["senderName"] == ""


def test_real_values_pass_through_unchanged():
    """The fix must not scrub anything that was working."""
    ctx = build_merge_context(
        {
            "first_name": "Hélène",
            "last_name": "Carpentier",
            "email": "helene@circularworkplaces.com",
            "company": "Circular Workplaces",
            "position": "Founder",
            "custom_fields": {"sector": "Sustainability"},
        },
        {"sender_name": "Ali", "sender_company": "Metis"},
    )
    assert ctx["firstName"] == "Hélène"
    assert ctx["company"] == "Circular Workplaces"
    assert ctx["sector"] == "Sustainability"
    assert ctx["senderName"] == "Ali"


def test_a_numeric_custom_field_becomes_text():
    """CSV columns arrive as whatever the parser made of them."""
    ctx = build_merge_context({"custom_fields": {"seats": 12, "active": False}})
    assert ctx["seats"] == "12"
    assert ctx["active"] == "False"


# ── the structural half ──


def test_all_three_send_paths_build_the_context_the_same_way():
    """Three copies is how this bug existed in three places at once.

    Every path that merges a template into an email must call the shared
    builder. A path that builds its own dict is a path where the next fix does
    not land - which has now happened twice.
    """
    from routers import campaigns as router
    from workers import followup_worker, scheduled_worker

    paths = {
        "send-now": router._send_single_email,
        "scheduled": scheduled_worker._send_email,
        "follow-up": followup_worker._send_followup_email,
    }
    for label, fn in paths.items():
        src = inspect.getsource(fn)
        assert "build_merge_context(" in src, (
            f"the {label} path builds its own merge context again - the None "
            f"bug, and every future fix, applies to it alone"
        )
        assert '"firstName": contact.get(' not in src, (
            f"the {label} path still hand-rolls firstName"
        )


def test_the_builder_covers_every_documented_contact_tag():
    """CONTACT_TAGS is what the panel validates a template against. A tag it
    accepts and the builder does not supply renders as itself, in the email."""
    from utils.merge_tags import CONTACT_TAGS

    ctx = build_merge_context(
        {"first_name": "A", "custom_fields": {}}, {"sender_name": "B"}
    )
    missing = [t for t in CONTACT_TAGS if t not in ctx]
    assert not missing, (
        f"the panel accepts {missing} but no send path supplies them - they "
        f"would arrive in the email as literal {{{{tag}}}} text"
    )
