"""Merge-tag validators used by campaign create/send paths."""
import re

# Tags resolvable from the authenticated user's sender profile
# (always available, no CSV column needed).
SENDER_TAGS = frozenset({
    "senderName", "senderPosition", "senderCompany", "senderPhone",
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
