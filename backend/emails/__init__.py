"""Rendering entry point for every email OutMass sends a customer.

    from emails import render
    msg = render("welcome", lang=user.get("preferred_language"),
                 name="Ada", free_quota="250")
    msg.subject, msg.text, msg.html

Language resolution is deliberately forgiving. ``lang`` arrives from the
extension's ``getActiveLocale()`` as a BCP-47 tag — "pt-BR", "zh-TW", "en-GB",
or NULL for every user whose build predates the column. Anything we do not
have a file for falls back to English, and a file missing individual keys
falls back key-by-key. An email in the wrong language is a mistake the reader
notices; an email in English is a default they do not.
"""

import json
from functools import lru_cache
from pathlib import Path

from emails.catalog import TEMPLATES, EmailTemplate  # noqa: F401 — re-exported
from emails.render import H, P, Rendered, render_blocks

_STRINGS_DIR = Path(__file__).resolve().parent / "strings"
DEFAULT_LANG = "en"

#: Where every email says to write back. One constant, injected into every
#: render as ``${support_email}``, so changing it is one edit rather than one
#: edit per language file.
SUPPORT_EMAIL = "support@getoutmass.com"

#: Base languages that read right to left. Arabic is the only one we ship;
#: the others are here so adding Hebrew or Persian is a string table and not
#: a code change plus a bug report about upside-down punctuation.
RTL_LANGUAGES = {"ar", "he", "fa", "ur"}


def is_rtl(lang: str | None) -> bool:
    return _normalise(lang).split("_")[0] in RTL_LANGUAGES


def available_languages() -> list[str]:
    return sorted(p.stem for p in _STRINGS_DIR.glob("*.json"))


def _normalise(lang: str | None) -> str:
    """"pt-br" → "pt_BR"; "en-GB" → "en_GB". Shape only, no validation."""
    if not lang:
        return DEFAULT_LANG
    parts = str(lang).replace("-", "_").split("_")
    out = parts[0].lower()
    if len(parts) > 1 and parts[1]:
        out += "_" + parts[1].upper()
    return out


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    path = _STRINGS_DIR / f"{name}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


#: Regions whose base-language fallback would land on the wrong script.
#:
#: "zh" here is Simplified, which is right for the mainland and for a bare
#: "zh", and wrong for Hong Kong and Macau — they read Traditional, and
#: falling back on the base language alone would hand them the other script.
#: The panel has the same three Chinese locales for the same reason.
_REGION_ALIASES = {"zh_HK": "zh_TW", "zh_MO": "zh_TW"}


@lru_cache(maxsize=None)
def strings_for(lang: str | None) -> dict:
    """English, overlaid with whatever the requested language actually has.

    Overlay rather than replace: a translation that is missing a key renders
    that one sentence in English instead of raising in a Celery beat at
    03:00. The parity test makes that state a build failure, not a plan.
    """
    merged = dict(_load(DEFAULT_LANG))
    tag = _normalise(lang)
    if tag == DEFAULT_LANG:
        return merged
    # "pt_BR" first, then "pt": a Brazilian file if we have one, the generic
    # Portuguese one if we do not.
    for candidate in (tag, _REGION_ALIASES.get(tag, ""), tag.split("_")[0]):
        overlay = _load(candidate)
        if overlay:
            merged.update(overlay)
            break
    return merged


def fill(raw: str, **variables) -> str:
    """Substitute ${placeholders} in one string from the table.

    For the handful of cases where a caller has to assemble a phrase before
    handing it to a template — the quota-cap email's "on September 14, when
    your monthly quota resets", which is one string in the table so that a
    language writing the day first can write it first.
    """
    from emails.render import _substitute

    return _substitute(raw, variables, escape=False)


def format_number(n: int, lang: str | None = None) -> str:
    """Group a number the way the reader's language groups numbers.

    Python's ``f"{n:,}"`` is English. German, Turkish, Spanish and both
    Portuguese variants use the comma as the DECIMAL separator, so an upgrade
    email telling a new Pro customer they may send "10,000 E-Mails" was
    telling them **ten** — on the one email whose entire job is to confirm
    what they just bought. French and Russian group with a space, not a
    comma at all.

    The separator is a string in the table (``common.number_group``) rather
    than a table in code, because it is a property of the language and it is
    the translator who knows it. The panel has always done this correctly in
    its own copy; the emails did not, for one day.

    Grouping is plain thousands. Indian lakh/crore grouping differs above
    99,999 and every number we print here is a plan limit under that.
    """
    sep = strings_for(lang).get("common.number_group", ",")
    return f"{int(n):,}".replace(",", sep)


def month_name(month: int, lang: str | None = None) -> str:
    """January…December in the reader's language.

    Not strftime: %B is the C locale's idea of the month, which on a server is
    always English. The names are ordinary strings in the table, and so is the
    date format around them — "on ${month} ${day}" lets a language that writes
    the day first simply write it first.
    """
    return strings_for(lang)[f"month.{int(month)}"]


def render(
    template: str,
    *,
    lang: str | None = None,
    name: str | None = None,
    **variables,
) -> Rendered:
    """One template, one language, both parts.

    ``name`` is separate from the rest because every message opens with a
    greeting and each one has to decide what to say when we do not have a
    name — see ``EmailTemplate.anon_greeting``.
    """
    tpl = TEMPLATES[template]
    strings = strings_for(lang)

    first = (name or "").strip().split(" ")[0] if name else ""
    if first:
        greeting = (P, "common.greeting")
    elif tpl.anon_greeting:
        greeting = (P, "common.greeting_anon")
    else:
        # A whole greeting, not a word slotted into one. English can write
        # "Hi ${name}," with name="there"; Turkish and Japanese cannot, and
        # forcing them to would produce a sentence with a placeholder-shaped
        # hole in it. Each language writes both anonymous greetings itself.
        greeting = (P, "common.greeting_anon_warm")

    variables = {"name": first, "support_email": SUPPORT_EMAIL, **variables}

    blocks = [(H, tpl.heading), greeting, *tpl.blocks]
    text, html = render_blocks(blocks, strings, variables, rtl=is_rtl(lang))

    from emails.render import _substitute  # local: internal helper

    subject = _substitute(strings[tpl.subject], variables, escape=False)
    return Rendered(subject=subject, text=text, html=html)
