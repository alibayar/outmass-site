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
from html import unescape as _html_unescape

# `<` followed by a letter, `!` or `/` — enough to recognise authored markup
# without catching "a < b" or "<3".
HTML_TAG_RE = re.compile(r"<[a-z!/][^>]*>", re.IGNORECASE)


# Tags that lay out a document. If the author used any of these they are
# writing HTML and their whitespace is theirs to arrange.
#
# <a>, <b>, <strong>, <em>, <i>, <u>, <span> and <img> are deliberately NOT
# here. Somebody adding a link to an otherwise plain message has not started
# writing HTML — they have written a normal email that happens to contain a
# link, and they still expect their paragraphs to survive.
BLOCK_TAG_RE = re.compile(
    r"</?(p|div|br|table|tr|td|th|tbody|thead|ul|ol|li|h[1-6]|blockquote|"
    r"pre|hr|section|article|body|html|head|style)\b",
    re.IGNORECASE,
)


def looks_like_html(template: str | None) -> bool:
    """Did the author write HTML? Ask the template, never the merged result."""
    return bool(template and HTML_TAG_RE.search(template))


# Merge tags whose VALUE is markup. A template can look like plain text and
# still be placing an image, because the tag is what places it — and on the
# plain branch everything is escaped, so the <img> would arrive as the literal
# characters `&lt;img …`. The author typing {{senderLogo}} IS the author
# placing an image, so the template counts as carrying inline markup.
MARKUP_TAGS = ("{{senderLogo}}",)


def has_markup_tag(template: str | None) -> bool:
    return bool(template) and any(t in template for t in MARKUP_TAGS)


def has_block_markup(template: str | None) -> bool:
    """Did the author lay the document out themselves?

    This distinction exists because of the question Hélène asked on
    2026-09-01, hours after we fixed her formatting: "Is there also a way to
    add links into the text?"

    There was, and taking it would have handed her back the exact bug she had
    just reported. A single <a href> made looks_like_html true, the whole body
    was passed through untouched, and every newline in it became whitespace
    again. The honest answer to "can I add a link" would have been "yes, and
    your paragraphs will collapse".
    """
    return bool(template and BLOCK_TAG_RE.search(template))


def _paragraphs(text: str) -> str:
    """Blank line to new paragraph, single newline to line break."""
    # Normalise CRLF first so a Windows-authored template behaves the same.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = [p.replace("\n", "<br>") for p in text.split("\n\n")]
    return "<p>" + "</p><p>".join(parts) + "</p>"


def plain_to_html(text: str) -> str:
    """Escape, then make newlines visible. Always converts — no detection."""
    if not text:
        return text or ""
    escaped = (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
    return _paragraphs(escaped)


def inline_html_to_html(text: str) -> str:
    """Newlines converted, existing markup left alone.

    The middle case: an ordinary message carrying a link or a bold word.
    Nothing is escaped, because the author's own <a href> has to survive — and
    the alternative on this branch is not "escaped", it is "not converted at
    all", which is what shipped before. So this strictly widens what renders
    correctly; it does not widen what is trusted.
    """
    if not text:
        return text or ""
    return _paragraphs(text)



# A bare web address typed into the composer.
#
# Hélène Carpentier, 2026-09-01: "Is there also a way to add links into the
# text? (that was not obvious how to do that)". It was not obvious because the
# only way was to type HTML. Every mail client she has ever used turns a typed
# address into a link on its own, so the honest fix is to do that rather than
# to teach her a tag.
#
# Deliberately conservative: an explicit scheme, or a leading `www.`. Bare
# "example.com" is NOT matched — too many ordinary sentences end in a word that
# looks like a domain ("...the .com boom", "see figure 2.png"), and a wrong
# link in someone's outbound mail is worse than a missing one they can add.
# The preceding-character class is spelled out rather than written `\w`
# because this pattern has a twin in extension/sidebar.js and the two must
# agree character for character. JavaScript's `\w` is ASCII; Python's is
# Unicode, so `官网www.outmass.app` — a URL after a CJK word, where no space
# is expected — linked in the panel's preview and arrived as plain text in the
# delivered mail. `re.ASCII` would fix that and break the other half, since it
# would also narrow `\s` and glue an ideographic space onto the address.
_URL_RE = re.compile(
    r"(?<![A-Za-z0-9_@/.])"         # not mid-word, mid-address or mid-path
    r"(https?://[^\s<>\"']+|www\.[^\s<>\"']+)",
    re.IGNORECASE,
)
# Trailing punctuation belongs to the sentence, not to the address.
_URL_TRAIL = ".,;:!?)]}'\""

# Everything already inside a tag, so linkifying can step over it. Splitting on
# anchors AND on tags means we never rewrite an href, an alt, or the text
# between <a> and </a>.
_SKIP_RE = re.compile(r"(<a\b[^>]*>.*?</a>|<[^>]+>)", re.IGNORECASE | re.DOTALL)


_ENTITY_RE = re.compile(r"&(#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")


def unescape_href(url: str) -> str:
    """Decode the HTML entities in an href, and nothing else.

    An href lives in HTML, so `?a=1&b=2` is written `?a=1&amp;b=2` and has to
    be decoded before the address is percent-encoded for the click redirect —
    otherwise the reader lands on a parameter named `amp;b`.

    `html.unescape` is the wrong tool for that. It also decodes 106 legacy
    entities that need no semicolon, so `?a=1&region=eu` becomes `?a=1®ion=eu`
    and `&notify=`, `&section=`, `&copy=` go the same way. That would have
    replaced one broken-link bug with a narrower one — hand-typed HTML instead
    of typed plain text.

    Requiring the semicolon is the whole difference: `&amp;` decodes, a query
    parameter that merely begins with letters does not.
    """
    return _ENTITY_RE.sub(lambda m: _html_unescape(m.group(0)), url or "")


def autolink(html: str) -> str:
    """Turn typed web addresses into links, leaving existing markup alone."""
    def link_one(m):
        url = m.group(1)
        trail = ""
        while url and url[-1] in _URL_TRAIL:
            trail = url[-1] + trail
            url = url[:-1]
        if not url:
            return m.group(0)
        href = url if url.lower().startswith(("http://", "https://")) else "https://" + url
        return f'<a href="{href}">{url}</a>{trail}'

    # Odd indices are the skipped spans; only rewrite the text between them.
    parts = _SKIP_RE.split(html)
    for i in range(0, len(parts), 2):
        parts[i] = _URL_RE.sub(link_one, parts[i])
    return "".join(parts)


def render_body(template: str | None, merged: str | None) -> str:
    """The body to send, given what the author wrote and what merging produced.

    `template` decides the mode; `merged` is what gets converted. Passing the
    merged text as both arguments reintroduces the bug this module exists to
    fix, so callers must keep them apart.
    """
    if merged is None:
        merged = ""
    if has_block_markup(template):
        # The author laid the document out; their whitespace is their own
        # business.
        return merged
    if looks_like_html(template) or has_markup_tag(template):
        # Inline markup only — a link, a bold word, a signature logo. Still an
        # ordinary message, so its line breaks still mean line breaks.
        return autolink(inline_html_to_html(merged))
    return autolink(plain_to_html(merged))
