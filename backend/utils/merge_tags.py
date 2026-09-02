"""Merge-tag validators used by campaign create/send paths."""
import re

# Tags resolvable from the authenticated user's sender profile
# (always available, no CSV column needed).
SENDER_TAGS = frozenset({
    "senderName", "senderPosition", "senderCompany", "senderPhone",
    # Expands to a whole <img> tag, not to the address. A user who has to
    # write <img src="{{senderLogo}}"> themselves is back to needing HTML,
    # which is the thing the field exists to remove.
    "senderLogo",
})

# Tags resolvable from a standard contact row (produced by bulk_insert
# regardless of which CSV columns were uploaded).
CONTACT_TAGS = frozenset({
    "firstName", "lastName", "email", "company", "position",
})

STANDARD_TAGS = SENDER_TAGS | CONTACT_TAGS

_WELLFORMED = re.compile(r"\{\{(\w+)\}\}")


def find_malformed_tags(template: str) -> list[str]:
    """Return substrings that look like broken merge tags.

    Examples of malformed input:
        "{{firstName"   -> missing close brace
        "firstName}}"   -> missing open brace
        "{{}}"          -> empty tag

    A well-formed `{{key}}` is stripped before detection, so plain text
    with a single `{` or `}` (e.g. "$5 { off }") is not flagged.
    """
    if not template:
        return []
    # Strip well-formed `{{key}}` tags first.
    stripped = _WELLFORMED.sub("", template)

    malformed: list[str] = []
    seen: set[str] = set()

    def add(frag: str):
        frag = frag.strip()
        if frag and frag not in seen:
            seen.add(frag)
            malformed.append(frag)

    # Scan left-to-right, consuming "{{...}}" (any content) and lone "{{"/"}}".
    i = 0
    n = len(stripped)
    while i < n:
        if stripped[i:i + 2] == "{{":
            close = stripped.find("}}", i + 2)
            if close == -1:
                # Unclosed: capture "{{" + everything to end of line/string
                end = stripped.find("\n", i)
                if end == -1:
                    end = n
                add(stripped[i:end])
                i = end
            else:
                # "{{...}}" made it through the first pass, which means the
                # inner content is NOT \w+ (e.g. empty "{{}}" or "{{ foo }}").
                add(stripped[i:close + 2])
                i = close + 2
        elif stripped[i:i + 2] == "}}":
            # Lone "}}" with no preceding "{{": capture "<text>}}" backwards
            start = stripped.rfind("\n", 0, i)
            start = start + 1 if start != -1 else 0
            add(stripped[start:i + 2])
            i += 2
        else:
            i += 1

    return malformed


def find_unknown_tags(template: str, contact_keys: set[str]) -> list[str]:
    """Return well-formed tag names not resolvable against the given context.

    `contact_keys` is the set of column names present in the uploaded CSV
    (e.g. {"firstName", "customField"}). Sender tags (senderName, etc.)
    and standard contact tags are always considered known.
    """
    if not template:
        return []
    allowed = STANDARD_TAGS | set(contact_keys)
    unknowns: list[str] = []
    seen: set[str] = set()
    for tag in _WELLFORMED.findall(template):
        if tag not in allowed and tag not in seen:
            seen.add(tag)
            unknowns.append(tag)
    return unknowns


def _text(value) -> str:
    """A merge value as text. NULL becomes empty, never the word "None".

    contact.get("first_name", "") returns the DEFAULT only when the KEY is
    absent. PostgREST always returns the column, so a NULL first_name comes
    back as the key present and the value None — the default never fires — and
    str(None) put the literal word "None" into the greeting of a real email.

    Found 2026-09-01, hours before the product's first ever follow-up was due
    to go out, because the customer it was for had written: "Please make sure
    the formatting is right and firstname is showing up correctly."
    """
    return "" if value is None else str(value)


LOGO_MAX_HEIGHT_PX = 56


def _logo_tag(url) -> str:
    """A signature logo as a complete <img>, or nothing at all.

    Empty when unset, so a template carrying {{senderLogo}} degrades to a
    blank line rather than a broken image icon in somebody's outbound mail.

    https only, checked here as well as at save time: the column predates
    nothing, but a value written before the validator existed, or by hand,
    must not become an <img src> we generated. A rejected value renders as
    nothing, which is the same as unset.

    The quote escaping matters. The URL goes inside a double-quoted attribute,
    so a value containing `"` could otherwise close it and open another
    attribute in mail we send under the user's name.
    """
    text = _text(url).strip()
    if not text.lower().startswith("https://"):
        return ""
    safe = (
        text.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
    return (
        f'<img src="{safe}" alt="" '
        f'style="max-height:{LOGO_MAX_HEIGHT_PX}px;border:0" />'
    )


def build_merge_context(contact: dict, sender_info: dict | None) -> dict:
    """The merge values for one recipient, in one place.

    All three send paths built this dict themselves and all three had the same
    None bug. Sharing it is the point: this repo has twice shipped a fix into
    one send path and left it out of the other two (render_body on 2026-09-01,
    the suppression-skip write before it).

    `sender_info` has NO DEFAULT on purpose, and that is the third instance of
    the same story. When it defaulted to None, the two workers called this
    with one argument and every scheduled send, every resumed remainder and
    every follow-up delivered `{{senderName}}` and `{{senderLogo}}` to the
    recipient with the braces still on — while the send-now path, which does
    pass it, looked correct in every test and every preview. Forgetting is now
    a TypeError instead of a literal brace in somebody's cold outreach. Pass
    the user row; pass None only where there deliberately is no sender.
    """
    ctx = {
        "firstName": _text(contact.get("first_name")),
        "lastName": _text(contact.get("last_name")),
        "email": _text(contact.get("email")),
        "company": _text(contact.get("company")),
        "position": _text(contact.get("position")),
    }
    if sender_info:
        ctx["senderName"] = _text(sender_info.get("sender_name"))
        ctx["senderPosition"] = _text(sender_info.get("sender_position"))
        ctx["senderCompany"] = _text(sender_info.get("sender_company"))
        ctx["senderPhone"] = _text(sender_info.get("sender_phone"))
        ctx["senderLogo"] = _logo_tag(sender_info.get("sender_logo_url"))
    # A custom column can be NULL for one row and filled for the next, which
    # is exactly how a spreadsheet arrives.
    for key, value in (contact.get("custom_fields") or {}).items():
        ctx[key] = _text(value)
    return ctx
