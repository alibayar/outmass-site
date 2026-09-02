"""A tracked click must land on the address the sender typed.

`_wrap_links` rewrites every href into `/c/{contact}?url=<encoded>`. It
percent-encoded the href exactly as it found it — but an href lives in HTML,
where a two-parameter link is written `?a=1&amp;b=2`. Encoding that verbatim
means the redirect delivers the reader to a page whose second parameter is
literally named `amp;b`.

    typed      https://acme.com/deck?utm_source=outmass&utm_medium=email
    delivered  https://acme.com/deck?utm_source=outmass&amp;utm_medium=email

For a cold-outreach tool that is a pointed failure: UTM parameters are how the
sender proves the campaign worked, and the campaign silently reports nothing
while the link still appears to work.

It was reachable before only by hand-writing HTML. Since autolink started
turning typed addresses into links — and correctly escaping the ampersand
while doing so — every plain-text body with a two-parameter link reaches it.

Three copies of this function exist (send-now, scheduled, follow-up) and the
test runs all three, because the last four bugs in this repo were all "fixed
in one send path".
"""
import urllib.parse

import pytest

TYPED = "https://acme.com/deck?utm_source=outmass&utm_medium=email"


def _wrappers():
    from routers.campaigns import _wrap_links as send_now
    from workers.followup_worker import _wrap_links as followup
    from workers.scheduled_worker import _wrap_links as scheduled

    return [("send-now", send_now), ("scheduled", scheduled),
            ("follow-up", followup)]


def _destination(wrapped: str) -> str:
    """What the redirect will actually send the reader to."""
    import re

    m = re.search(r'href="([^"]+)"', wrapped)
    assert m, f"no href in {wrapped!r}"
    query = urllib.parse.urlparse(m.group(1)).query
    return urllib.parse.parse_qs(query)["url"][0]


@pytest.mark.parametrize("name,wrap", _wrappers(), ids=lambda v: v if isinstance(v, str) else "")
def test_an_escaped_ampersand_does_not_reach_the_destination(name, wrap):
    html = f'<p>Deck: <a href="https://acme.com/deck?utm_source=outmass&amp;utm_medium=email">deck</a></p>'
    dest = _destination(wrap(html, "contact-1"))

    assert "amp;" not in dest, (
        f"{name}: the reader lands on {dest} — the second parameter is named "
        f"'amp;utm_medium', so the sender's campaign tracking records nothing"
    )
    assert dest == TYPED, f"{name}: {dest}"


@pytest.mark.parametrize("name,wrap", _wrappers(), ids=lambda v: v if isinstance(v, str) else "")
def test_a_plain_body_with_two_parameters_survives_the_whole_pipeline(name, wrap):
    """End to end from what the user typed, through autolink, to the click.

    This is the path that made a pre-existing bug reachable: nobody in this
    product's user base hand-writes HTML, and everybody pastes a UTM link.
    """
    from utils.email_body import render_body

    body = f"Have a look:\n{TYPED}"
    dest = _destination(wrap(render_body(body, body), "contact-1"))
    assert dest == TYPED, f"{name}: {dest}"


@pytest.mark.parametrize("name,wrap", _wrappers(), ids=lambda v: v if isinstance(v, str) else "")
def test_ordinary_links_are_unchanged(name, wrap):
    """The unescaping must not disturb a link that was already correct."""
    plain = "https://example.com/a/b"
    html = f'<a href="{plain}">x</a>'
    assert _destination(wrap(html, "c1")) == plain, name


@pytest.mark.parametrize("name,wrap", _wrappers(), ids=lambda v: v if isinstance(v, str) else "")
def test_a_percent_sign_in_the_url_is_not_double_decoded(name, wrap):
    """html.unescape only touches HTML entities. A URL carrying its own
    percent-encoding must arrive with it intact, or a link to a page with a
    space in its name breaks."""
    encoded = "https://example.com/Q3%20report.pdf"
    dest = _destination(wrap(f'<a href="{encoded}">x</a>', "c1"))
    assert dest == encoded, f"{name}: {dest}"
