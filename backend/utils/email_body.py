"""Turning what someone typed into the HTML that actually gets sent.

Graph sends with `contentType: HTML`, so a newline in a plain-text body is not
a line break — it is whitespace, and the whole message arrives as one block.

That conversion lived in `routers/campaigns.py` and nowhere else. The
send-now path called it; `workers/scheduled_worker.py` and
`workers/followup_worker.py` merged the template and went straight to link
wrapping. So every campaign a user SCHEDULED, and every follow-up, went out
with its formatting collapsed, while the panel's preview — which does convert
— looked correct.

Helene wrote on 2026-09-01, five recipients into a scheduled campaign:
"the formating which was sent for my CBRE campaign did not work and everything
sent as a block even if the preview looked fine." She was describing this
exactly, and it had been true of every scheduled send the product ever made.

The second bug is the order. The router did:

    merged = _merge_template(campaign["body"], ctx)
    merged = _text_to_html(merged)          # <- detection sees MERGED text

`_text_to_html` passes a body through untouched if it finds a tag, so once the
merge had run first, a recipient whose CSV row happened to contain something
like `<info@example.com>` flipped the whole message into "author wrote HTML,
leave it alone" — and that one recipient got a block while everyone else got
paragraphs. The preview uses the first CSV row, so it showed whichever answer
row one produced.

Both are the same mistake in different clothes: the decision belongs to the
TEMPLATE, which the author wrote, and never to the DATA, which they merely
uploaded. This module is the one place that decision is made, so the three
send paths cannot drift apart again.
"""
import re

# `<` followed by a letter, `!` or `/` — enough to recognise authored markup
# without catching "a < b" or "<3".
HTML_TAG_RE = re.compile(r"<[a-z!/][^>]*>", re.IGNORECASE)


def looks_like_html(template: str | None) -> bool:
    """Did the author write HTML? Ask the template, never the merged result."""
    return bool(template and HTML_TAG_RE.search(template))


def plain_to_html(text: str) -> str:
    """Escape, then make newlines visible. Always converts — no detection."""
    if not text:
        return text or ""
    escaped = (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
    # Normalise CRLF first so a Windows-authored template behaves the same.
    escaped = escaped.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.replace("\n", "<br>") for p in escaped.split("\n\n")]
    return "<p>" + "</p><p>".join(paragraphs) + "</p>"


def render_body(template: str | None, merged: str | None) -> str:
    """The body to send, given what the author wrote and what merging produced.

    `template` decides the mode; `merged` is what gets converted. Passing the
    merged text as both arguments reintroduces the bug this module exists to
    fix, so callers must keep them apart.
    """
    if merged is None:
        merged = ""
    if looks_like_html(template):
        # The author wrote markup; their line breaks are their own business.
        return merged
    return plain_to_html(merged)
