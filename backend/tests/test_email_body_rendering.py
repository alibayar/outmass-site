"""A scheduled campaign must arrive looking like the preview.

Graph sends with contentType HTML, where a newline is whitespace. Converting
plain text lived in routers/campaigns.py and nowhere else, so the send-now
path converted and the two workers did not. Every campaign a user SCHEDULED,
and every follow-up, went out as one block — while the panel's preview, which
does convert, looked right.

Helene wrote on 2026-09-01, five recipients into a scheduled campaign:
"the formating which was sent for my CBRE campaign did not work and everything
sent as a block even if the preview looked fine." Her template contained no
markup and none of her 66 rows did either, which rules out every other
explanation and leaves this one.

The second bug in the same area was the order. The router decided whether the
author had written HTML by inspecting the text AFTER merging, so one CSV value
containing something like <info@example.com> could flip the whole message into
"leave it alone" for that recipient only.

Both reduce to the same rule, which is what these tests pin: the TEMPLATE
decides the mode, the MERGED text gets converted, and all three send paths ask
the same function.
"""
import inspect

from utils.email_body import looks_like_html, plain_to_html, render_body


# ── the rule itself ──


def test_plain_text_newlines_become_line_breaks():
    out = render_body("Hello\nthere", "Hello\nthere")
    assert "<br>" in out, (
        "a newline in a plain-text body must become a line break — without it "
        "the whole message arrives as one block, which is what Helene received"
    )


def test_a_blank_line_becomes_a_paragraph():
    out = render_body("One\n\nTwo", "One\n\nTwo")
    assert "</p><p>" in out, "a blank line must separate paragraphs"


def test_authored_html_is_left_alone():
    template = "<p>Hello</p>\n<p>there</p>"
    out = render_body(template, template)
    assert out == template, (
        "an author who wrote markup owns their own line breaks; re-escaping "
        "would show them their own tags as text"
    )


def test_the_mode_comes_from_the_template_not_the_merged_data():
    """The router's original bug, in one assertion.

    The template is plain text. The merge dropped an address in angle brackets
    into it — a real thing to find in a CSV. If the decision is taken from the
    merged text, that one recipient's line breaks collapse while everyone
    else's survive, and the preview (which uses row one) shows whichever
    answer row one happened to produce.
    """
    template = "Hi {{name}},\n\nBest,\nAli"
    merged = "Hi <info@example.com>,\n\nBest,\nAli"

    out = render_body(template, merged)

    assert "<br>" in out, (
        "user DATA flipped the formatting mode — the decision belongs to the "
        "template, which the author wrote, not the CSV they uploaded"
    )
    assert "&lt;info@example.com&gt;" in out, (
        "a merged value that looks like a tag must be escaped, not emitted as "
        "markup"
    )


def test_looks_like_html_ignores_arithmetic_and_emoticons():
    assert not looks_like_html("a < b and c > d")
    assert not looks_like_html("love it <3")
    assert looks_like_html("<p>hello</p>")
    assert looks_like_html("<br/>")


def test_empty_input_survives():
    assert render_body("", "") == ""
    assert render_body(None, None) == ""
    assert plain_to_html("") == ""


# ── and every send path has to use it ──


def test_all_three_send_paths_render_the_body_the_same_way():
    """The omission was structural, not a typo.

    routers/campaigns.py had the conversion; scheduled_worker.py and
    followup_worker.py each merged the template and went straight to link
    wrapping. Nothing connected them, so nothing noticed for months. This
    check is the connection.
    """
    from routers import campaigns as router
    from workers import followup_worker, scheduled_worker

    paths = {
        "send-now / test-send": router._send_single_email,
        "scheduled campaigns": scheduled_worker._send_email,
        "follow-ups": followup_worker._send_followup_email,
    }

    for label, fn in paths.items():
        src = inspect.getsource(fn)
        assert "render_body(" in src, (
            f"the {label} path does not call render_body — its recipients get "
            f"the raw text inside an HTML message, which is one block"
        )


def test_no_send_path_decides_the_mode_from_merged_text():
    """render_body(x, x) is the bug wearing the fix's clothes.

    Passing the merged text as both arguments type-checks, runs, and
    reintroduces exactly the behaviour the second bug had.
    """
    from routers import campaigns as router
    from workers import followup_worker, scheduled_worker

    for label, fn in {
        "send-now / test-send": router._send_single_email,
        "scheduled campaigns": scheduled_worker._send_email,
        "follow-ups": followup_worker._send_followup_email,
    }.items():
        src = inspect.getsource(fn)
        assert "render_body(merged_body, merged_body)" not in src, (
            f"the {label} path passes the merged text as the template — user "
            f"data decides the formatting mode again"
        )


# ── the middle case: an ordinary email that happens to contain a link ──
#
# Hélène asked on 2026-09-01, hours after we fixed her formatting: "Is there
# also a way to add links into the text?" There was, and taking it would have
# handed her back the exact bug she had just reported — one <a href> made the
# whole body count as authored HTML, and every newline in it became whitespace.


def test_a_link_does_not_collapse_the_paragraphs_around_it():
    from utils.email_body import render_body

    template = (
        "Hi {{firstName}},\n\nHave a nice day,\n\nHelene Carpentier\n"
        'Founder, Circular Workplaces\n<a href="https://x.com">x.com</a>'
    )
    merged = template.replace("{{firstName}}", "Ada")
    out = render_body(template, merged)

    assert "<p>Hi Ada,</p>" in out, (
        f"the paragraphs collapsed around the link: {out!r}"
    )
    assert '<a href="https://x.com">x.com</a>' in out, "the link was mangled"
    assert "&lt;a href" not in out, "the author's own link was escaped"
    assert "Circular Workplaces<br>" in out, "the signature lost its line break"


def test_bold_and_italics_behave_the_same_way():
    from utils.email_body import render_body

    t = "Line one with <b>bold</b>\nLine two"
    assert render_body(t, t) == "<p>Line one with <b>bold</b><br>Line two</p>"


def test_a_real_html_document_is_still_left_alone():
    """A block tag means the author laid it out; do not second-guess them."""
    from utils.email_body import render_body

    for t in (
        "<p>One</p>\n<p>Two</p>",
        "<div>One</div>\nTwo",
        "<table><tr><td>x</td></tr></table>",
        "One<br>Two",
        "<ul><li>a</li></ul>",
        "<h1>Title</h1>\nBody",
    ):
        assert render_body(t, t) == t, f"{t!r} was rewritten"


def test_a_csv_value_in_angle_brackets_is_still_escaped_on_a_plain_template():
    """The template decides. Data never promotes a message to HTML."""
    from utils.email_body import render_body

    out = render_body("Hi {{email}}", "Hi <info@example.com>")
    assert "&lt;info@example.com&gt;" in out


def test_the_inline_branch_does_not_escape_but_the_plain_branch_does():
    """Stated as a property, because the difference is the whole design.

    On the inline branch the alternative was never 'escaped' — it was 'not
    converted at all'. So this widens what renders correctly, not what is
    trusted.
    """
    from utils.email_body import render_body

    assert "&lt;" in render_body("plain", "a < b")
    assert render_body("has <b>markup</b>", "a <b>b</b>") == "<p>a <b>b</b></p>"
