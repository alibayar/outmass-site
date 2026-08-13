"""One body per email, rendered into both parts.

Every transactional email used to exist twice: a plain-text body and an HTML
body, written by hand, next to each other, with no mechanism keeping them
saying the same thing. They had already drifted — the welcome email's step 2
began "In the panel, upload…" in text and "Upload…" in HTML, and its third
bullet promised slightly different things in each. Nobody had noticed, because
nobody reads both.

Translating that shape into fourteen languages would have meant fourteen
copies of the drift. So the copy now lives once, in a string table, and this
module turns it into text and HTML. A translator writes one sentence; both
parts change together, or neither does.

## The markup

Deliberately three things and no more. Every additional marker is a way for a
translator to break a message in a language nobody here can proofread.

    **bold**              <strong> in HTML, markers dropped in text
    `code`                <code> in HTML, markers dropped in text
    [label](url)          <a> in HTML; in text, the URL if the label is part
                          of it, "label (url)" otherwise, and bare label for
                          mailto: — "support@x (mailto:support@x)" reads like
                          a bug.

There is no italic. `<em>` appeared twice in the old templates and both were
emphasis that bold carries just as well.

## The variables

``${name}`` style — Python's string.Template — chosen over ``str.format``
because the welcome email contains the literal merge tag ``{{firstName}}``,
which under .format would have to be written ``{{{{firstName}}}}`` in every
one of fourteen files. A missing variable raises rather than rendering an
empty hole; tests/test_email_catalog.py renders every template in every
language to make that a build failure rather than a customer's Tuesday.

## What text rendering does NOT do

It skips headings. The old text bodies had none — they opened with "Hi Ada,"
while HTML opened with an <h2> — and in every template the heading either
repeats the subject line or paraphrases it. Emitting it into text would add
words no reader has ever seen.
"""

import html as _html
import re
import textwrap
from dataclasses import dataclass
from string import Template

# ── Blocks ──
#
# Six kinds, which is exactly enough for all ten templates. Each is a tuple so
# the catalog reads as data rather than as constructor calls.

H = "h"          # heading — HTML only, see module docstring
P = "p"          # paragraph
UL = "ul"        # bulleted list
OL = "ol"        # numbered list
LINES = "lines"  # a signature block: one line each, no blank lines between
NOTE = "note"    # small print — the grey footer text

TEXT_WIDTH = 72

# One shell for all ten. There used to be three: max-width 520, 540 and 560,
# two different font stacks, and an <h2> that was brand blue in five templates
# and black in the other five. Which one a customer got depended on which file
# the message happened to live in.
_SHELL_OPEN = (
    '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
    'Roboto,sans-serif;max-width:560px;margin:0 auto;color:#323130;">'
)
_SHELL_CLOSE = "</div>"
_H_STYLE = "color:#0078d4;font-size:20px;margin:0 0 14px;"
_P_STYLE = "font-size:14px;line-height:1.6;"
_LIST_STYLE = "color:#323130;font-size:14px;line-height:1.7;padding-left:20px;"
_NOTE_STYLE = "color:#797775;font-size:12px;line-height:1.5;"
_LINK_STYLE = "color:#0078d4;"

_TOKEN = re.compile(
    r"\*\*(?P<bold>.+?)\*\*"
    r"|`(?P<code>[^`]+)`"
    r"|\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)"
)


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


def _esc(s: str) -> str:
    """Body-text escaping: & < > only.

    quote=False on purpose. Every message here is full of apostrophes
    ("there's", "we'll", "don't") and turning each into &#x27; would make the
    HTML unreadable to the next person who has to diff it, for no gain — an
    apostrophe cannot terminate anything in element content.
    """
    return _html.escape(s, quote=False)


def _inline_html(raw: str) -> str:
    """Markup → HTML, escaping each piece for the context it lands in."""
    out: list[str] = []
    pos = 0
    for m in _TOKEN.finditer(raw):
        out.append(_esc(raw[pos:m.start()]))
        if m.group("bold") is not None:
            out.append(f"<strong>{_esc(m.group('bold'))}</strong>")
        elif m.group("code") is not None:
            out.append(f"<code>{_esc(m.group('code'))}</code>")
        else:
            # quote=True here and nowhere else: this one lands inside an
            # attribute, where a stray quote would end it early.
            url = _html.escape(m.group("url"), quote=True)
            out.append(
                f'<a href="{url}" style="{_LINK_STYLE}">'
                f"{_esc(m.group('label'))}</a>"
            )
        pos = m.end()
    out.append(_esc(raw[pos:]))
    return "".join(out)


def _inline_text(raw: str) -> str:
    """Markup → plain text. Bold and code lose their markers; links keep
    whichever of label and URL a reader can actually use."""
    def repl(m: re.Match) -> str:
        if m.group("bold") is not None:
            return m.group("bold")
        if m.group("code") is not None:
            return m.group("code")
        label, url = m.group("label"), m.group("url")
        if url.startswith("mailto:"):
            return label
        if label in url:
            return url
        return f"{label} ({url})"

    return _TOKEN.sub(repl, raw)


def _substitute(s: str, variables: dict, *, escape: bool) -> str:
    """Fill ${placeholders}. Raises KeyError if the catalog and the string
    table disagree — which is the point; a silently empty sentence in a
    language nobody here reads would never be found."""
    if escape:
        variables = {
            k: _html.escape(str(v), quote=True) for k, v in variables.items()
        }
    else:
        variables = {k: str(v) for k, v in variables.items()}
    return Template(s).substitute(variables)


def _wrap(s: str, indent: str = "", first: str | None = None) -> str:
    """Hard-wrap for the text part.

    break_long_words and break_on_hyphens are both off: this text contains
    URLs and email addresses, and a wrapped URL is a dead URL.
    """
    return textwrap.fill(
        s,
        width=TEXT_WIDTH,
        initial_indent=first if first is not None else indent,
        subsequent_indent=indent,
        break_long_words=False,
        break_on_hyphens=False,
    )


def render_blocks(blocks: list, strings: dict, variables: dict) -> tuple[str, str]:
    """(text, html) for one message body.

    ``blocks`` is a list of (kind, key...) tuples from the catalog; ``strings``
    maps key → raw copy in the target language.
    """
    text_parts: list[str] = []
    html_parts: list[str] = [_SHELL_OPEN]
    first_note = True

    for block in blocks:
        kind, keys = block[0], block[1:]
        raws = [strings[k] for k in keys]

        if kind == H:
            html_parts.append(
                f'<h2 style="{_H_STYLE}">'
                f"{_substitute(_inline_html(raws[0]), variables, escape=True)}</h2>"
            )
            continue

        if kind == P:
            for raw in raws:
                text_parts.append(
                    _wrap(_substitute(_inline_text(raw), variables, escape=False))
                )
                html_parts.append(
                    f'<p style="{_P_STYLE}">'
                    f"{_substitute(_inline_html(raw), variables, escape=True)}</p>"
                )
            continue

        if kind in (UL, OL):
            tag = "ul" if kind == UL else "ol"
            lines = []
            for i, raw in enumerate(raws, 1):
                plain = _substitute(_inline_text(raw), variables, escape=False)
                marker = "- " if kind == UL else f"{i}. "
                lines.append(_wrap(plain, indent=" " * len(marker), first=marker))
            text_parts.append("\n".join(lines))
            items = "".join(
                f"<li>{_substitute(_inline_html(raw), variables, escape=True)}</li>"
                for raw in raws
            )
            html_parts.append(f'<{tag} style="{_LIST_STYLE}">{items}</{tag}>')
            continue

        if kind == LINES:
            plain = [
                _substitute(_inline_text(raw), variables, escape=False) for raw in raws
            ]
            text_parts.append("\n".join(plain))
            joined = "<br>".join(
                _substitute(_inline_html(raw), variables, escape=True) for raw in raws
            )
            html_parts.append(f'<p style="{_P_STYLE}">{joined}</p>')
            continue

        if kind == NOTE:
            for raw in raws:
                text_parts.append(
                    _wrap(_substitute(_inline_text(raw), variables, escape=False))
                )
                style = _NOTE_STYLE + ("margin-top:18px;" if first_note else "")
                html_parts.append(
                    f'<p style="{style}">'
                    f"{_substitute(_inline_html(raw), variables, escape=True)}</p>"
                )
                first_note = False
            continue

        raise ValueError(f"unknown block kind: {kind!r}")

    html_parts.append(_SHELL_CLOSE)
    return "\n\n".join(text_parts) + "\n", "".join(html_parts)
