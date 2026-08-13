"""The string table and the catalog have to agree — in every language.

This is the backend twin of extension/tests/locale-consistency.test.js, and it
exists for the same reason that one does: on 2026-07-14 three keys turned out
to be missing from ten locale files at once, and nothing failed. Chrome fell
back to English silently, and the only symptom was a user reading a sentence
in the wrong language.

Emails are worse than the panel in one specific way. A panel string renders
the moment someone opens the tab, so a mistake is seen immediately, by us as
well as them. An email template renders once, inside a Celery beat, addressed
to a paying customer, at whatever hour the beat runs. Nobody sees it fail.

So: every key the catalog names must exist, no string may be dead, the
placeholders must match English's exactly, and every template must render in
every language we ship.
"""
import json
import re
from pathlib import Path

import pytest

from emails import DEFAULT_LANG, available_languages, render, strings_for
from emails.catalog import TEMPLATES

_BACKEND = Path(__file__).resolve().parent.parent
_STRINGS = _BACKEND / "emails" / "strings"

_PLACEHOLDER = re.compile(r"\$\{(\w+)\}")

#: Supplied by render() itself rather than by the caller.
_INJECTED = {"name", "support_email"}

#: Referenced as f"month.{n}" rather than as a literal, which is the whole
#: point of them: the date phrase is one string in the table so a language
#: that writes the day first can write it first.
_DYNAMIC_FAMILIES = ("month.",)


def _english() -> dict:
    return json.loads((_STRINGS / f"{DEFAULT_LANG}.json").read_text(encoding="utf-8"))


def _keys_of(template) -> set[str]:
    keys = {template.subject, template.heading}
    for block in template.blocks:
        keys.update(block[1:])
    return keys


def _catalog_keys() -> set[str]:
    keys: set[str] = set()
    for template in TEMPLATES.values():
        keys |= _keys_of(template)
    return keys


def _placeholders(strings: dict, keys: set[str]) -> set[str]:
    found: set[str] = set()
    for key in keys:
        found |= set(_PLACEHOLDER.findall(strings[key]))
    return found


# ── The catalog and English ──


def test_every_key_the_catalog_names_exists():
    missing = sorted(_catalog_keys() - set(_english()))
    assert not missing, f"catalog references strings that do not exist: {missing}"


def test_no_string_is_dead():
    """A key nothing references is either a template someone deleted or a typo
    in the one place that was supposed to use it. Both are worth knowing about
    before thirteen people translate it."""
    source = "\n".join(
        p.read_text(encoding="utf-8")
        for p in _BACKEND.rglob("*.py")
        if "venv" not in p.parts and "__pycache__" not in p.parts
    )
    orphans = []
    for key in sorted(set(_english()) - _catalog_keys()):
        if key.startswith(_DYNAMIC_FAMILIES):
            continue
        if f'"{key}"' in source or f"'{key}'" in source:
            continue
        orphans.append(key)
    assert not orphans, f"strings nothing references: {orphans}"


def test_the_month_names_are_all_there():
    strings = _english()
    missing = [m for m in range(1, 13) if f"month.{m}" not in strings]
    assert not missing, f"months with no name: {missing}"


def test_markup_markers_are_paired():
    """An odd number of ** turns the rest of a sentence bold in HTML and
    leaves stray asterisks in the text part. Cheap to check, invisible to
    review in a language you cannot read."""
    for lang in available_languages():
        for key, raw in strings_for(lang).items():
            assert raw.count("**") % 2 == 0, f"{lang}/{key}: unpaired **"
            assert raw.count("`") % 2 == 0, f"{lang}/{key}: unpaired backtick"
            assert raw.count("[") == raw.count("]"), f"{lang}/{key}: unpaired []"


# ── Every language ──


@pytest.mark.parametrize("lang", available_languages())
def test_a_translation_has_exactly_english_s_keys(lang):
    if lang == DEFAULT_LANG:
        pytest.skip("english is the reference")
    english = set(_english())
    theirs = set(json.loads((_STRINGS / f"{lang}.json").read_text(encoding="utf-8")))
    assert theirs == english, (
        f"{lang} is missing {sorted(english - theirs)} and has "
        f"{sorted(theirs - english)} that English does not"
    )


@pytest.mark.parametrize("lang", available_languages())
def test_a_translation_keeps_the_same_placeholders(lang):
    """${skipped} dropped from a translation is a sentence with a hole in it;
    ${skiped} added is a KeyError inside a beat at 03:00."""
    english = _english()
    theirs = strings_for(lang)
    for key, raw in english.items():
        assert set(_PLACEHOLDER.findall(theirs[key])) == set(
            _PLACEHOLDER.findall(raw)
        ), f"{lang}/{key}: placeholders differ from English"


@pytest.mark.parametrize("lang", available_languages())
@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_every_template_renders_in_every_language(lang, template):
    """The one that would actually have caught it. Variables come from
    ENGLISH's placeholders, deliberately: if a translation invents one, this
    raises, which is the point."""
    english = _english()
    keys = _keys_of(TEMPLATES[template]) | {"common.greeting"}
    supplied = {
        name: "X" for name in _placeholders(english, keys) - _INJECTED
    }

    msg = render(template, lang=lang, name="Ada", **supplied)

    assert msg.subject.strip()
    assert msg.text.strip()
    assert msg.html.startswith("<div") and msg.html.endswith("</div>")
    assert "${" not in msg.subject + msg.text + msg.html, (
        "a placeholder survived rendering"
    )


# ── Language resolution ──


@pytest.mark.parametrize(
    "given",
    [None, "", "en", "en-GB", "kl", "not a language", "zz_ZZ"],
)
def test_an_unknown_language_is_english_not_an_error(given):
    """NULL is every user whose extension predates the column, and it will be
    most of them for weeks. It has to be the quiet path."""
    msg = render("reauth", lang=given, reason="invalid_grant")
    assert msg.subject == _english()["reauth.subject"]


def test_a_regional_tag_falls_back_to_its_base_language():
    """pt-BR when only a generic pt exists, and vice versa. Tested through the
    resolver rather than through a file that may not exist yet."""
    from emails import _normalise

    assert _normalise("pt-br") == "pt_BR"
    assert _normalise("ZH-hant") == "zh_HANT"
    assert _normalise(None) == "en"


def test_a_translation_missing_one_key_falls_back_for_that_key_only(tmp_path):
    """Key-by-key overlay, not all-or-nothing. A half-finished language file
    should render the sentences it has, not throw the whole message away."""
    import emails

    partial = _STRINGS / "zz.json"
    partial.write_text(
        json.dumps({"reauth.subject": "Zzz"}, ensure_ascii=False), encoding="utf-8"
    )
    try:
        emails._load.cache_clear()
        emails.strings_for.cache_clear()
        msg = render("reauth", lang="zz", reason="invalid_grant")
        assert msg.subject == "Zzz"
        # Normalised: the text part is hard-wrapped, so the sentence is not
        # contiguous in it.
        assert " ".join(_english()["reauth.expired"].split()) in " ".join(
            msg.text.split()
        )
    finally:
        partial.unlink()
        emails._load.cache_clear()
        emails.strings_for.cache_clear()
