"""An email may not tell somebody to click a button that does not exist.

Several emails name a control in the panel: "click **Upgrade Plan**", "click
the **Reconnect to Outlook** banner", "under **Account** → **Manage
Subscription**". Those are instructions. If the label in the email is not the
label on the screen, the reader hunts for it, does not find it, and writes to
support — or gives up, which on the reconnect and quota-cap emails means a
paying customer stops sending.

Found by the 2026-08-14 translation review, and the shape of it is the part
worth remembering: the reviewers reported it as a translation error in ten
languages, and it was not. **The English source itself said "click
**Upgrade**" while the English panel button says "Upgrade Plan".** Every
translator faithfully translated a label that was already wrong. One source
defect, multiplied by thirteen.

test_email_catalog.py checks that the ``**`` markers are paired. Nothing
checked that what sits between them is real.

## Two strictnesses, on purpose

English is **strict**: the source is where this class of bug is born, and it
is the one file everybody here can read. It must stay exact.

The translations carry an allowlist of the mismatches that exist today. They
are real, they are known, and fixing them means editing twelve files in
languages nobody here can proofread — which is its own risk and its own
change. The allowlist may only ever shrink; a new entry fails the test.
"""
import json
import re
from pathlib import Path

import pytest

from emails import available_languages, strings_for

_BACKEND = Path(__file__).resolve().parent.parent
_LOCALES = _BACKEND.parent / "extension" / "_locales"

_BOLD = re.compile(r"\*\*(.+?)\*\*")

#: email string key -> the panel message keys it quotes as clickable things.
#:
#: Adding an email that names a control means adding it here. That is the
#: point: the alternative is guessing which bolded words are UI and which are
#: emphasis, and a guess would either miss real ones or reject "**just reply
#: to this email**".
QUOTED = {
    "quota_capped.sooner": ["btnUpgrade"],
    "welcome.step3": ["btnPreview", "btnTestSend", "btnSend"],
    "reauth.how_to_fix": ["reauthBannerText"],
    "upgrade.point_manage": ["tabAccount", "btnManageSub"],
    "inactivity_30d.stop_panel": ["tabAccount", "btnManageSub"],
}

#: (language, email key, panel key) triples that do NOT match today.
#:
#: Every one is a real defect found on 2026-08-14. They are listed rather
#: than fixed because correcting them means writing in twelve languages, and
#: doing that from a single unreviewed suggestion each is a worse risk than
#: carrying the debt visibly for a few days.
#:
#: Remove entries as they are fixed. Never add one.
KNOWN_MISMATCHES: set[tuple[str, str, str]] = {
    ("ar", "reauth.how_to_fix", "reauthBannerText"),
    ("de", "inactivity_30d.stop_panel", "btnManageSub"),
    ("de", "quota_capped.sooner", "btnUpgrade"),
    ("de", "reauth.how_to_fix", "reauthBannerText"),
    ("de", "upgrade.point_manage", "btnManageSub"),
    ("es", "reauth.how_to_fix", "reauthBannerText"),
    ("es", "welcome.step3", "btnTestSend"),
    ("fr", "quota_capped.sooner", "btnUpgrade"),
    ("fr", "reauth.how_to_fix", "reauthBannerText"),
    ("fr", "welcome.step3", "btnTestSend"),
    ("hi", "reauth.how_to_fix", "reauthBannerText"),
    ("ja", "inactivity_30d.stop_panel", "btnManageSub"),
    ("ja", "upgrade.point_manage", "btnManageSub"),
    ("pt_BR", "reauth.how_to_fix", "reauthBannerText"),
    ("pt_BR", "welcome.step3", "btnPreview"),
    ("pt_PT", "quota_capped.sooner", "btnUpgrade"),
    ("pt_PT", "reauth.how_to_fix", "reauthBannerText"),
    ("ru", "quota_capped.sooner", "btnUpgrade"),
    ("ru", "reauth.how_to_fix", "reauthBannerText"),
    ("ru", "welcome.step3", "btnTestSend"),
    ("tr", "reauth.how_to_fix", "reauthBannerText"),
    ("zh_TW", "welcome.step3", "btnSend"),
    ("zh_TW", "welcome.step3", "btnTestSend"),
}


def _panel(lang: str) -> dict:
    path = _LOCALES / lang / "messages.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v.get("message", "") for k, v in raw.items()}


def _bolded(s: str) -> list[str]:
    return [m.group(1) for m in _BOLD.finditer(s)]


def _mismatches(lang: str) -> list[tuple[str, str, str, str]]:
    """(email_key, panel_key, panel_value, what the email actually bolded)."""
    panel = _panel(lang)
    if not panel:
        return []
    emails = strings_for(lang)
    out = []
    for email_key, panel_keys in QUOTED.items():
        bolded = _bolded(emails[email_key])
        for panel_key in panel_keys:
            label = panel.get(panel_key)
            if not label:
                continue
            # Exact for a button; substring for reauthBannerText, whose panel
            # value is a whole sentence that opens with the banner's name.
            if any(frag == label or frag in label for frag in bolded):
                continue
            out.append((email_key, panel_key, label, " | ".join(bolded)))
    return out


def test_the_bold_extractor_finds_labels():
    """Self-test before the scan is believed. A checker that extracts nothing
    reports every file clean, which is how a sender detector shipped on
    2026-08-14 passing while examining nothing."""
    assert _bolded("click **Upgrade Plan** now") == ["Upgrade Plan"]
    assert _bolded("**a** and **b**") == ["a", "b"]
    assert _bolded("no markup here") == []


def test_english_quotes_labels_that_exist():
    """Strict. The source is where this bug is born and where it multiplies."""
    bad = _mismatches("en")
    assert not bad, "\n".join(
        f"en/{k}: the email bolds [{got}] but the panel's {pk} says {label!r}"
        for k, pk, label, got in bad
    )


@pytest.mark.parametrize("lang", [x for x in available_languages() if x != "en"])
def test_a_translation_quotes_labels_that_exist(lang):
    found = {(lang, k, pk) for k, pk, _, _ in _mismatches(lang)}
    new = found - KNOWN_MISMATCHES
    assert not new, (
        f"{lang}: the email names a control the {lang} panel does not have: "
        f"{sorted(new)}. Either fix the email string, or — if this is "
        f"deliberate — add it to KNOWN_MISMATCHES with a reason."
    )


def test_the_allowlist_does_not_outlive_the_defects():
    """An allowlist nobody prunes becomes a list of things that are fine.

    Every entry here is a customer being sent to a button that is not there.
    When one is fixed its entry must go, or the next real one hides behind it.
    """
    stale = []
    for lang, email_key, panel_key in KNOWN_MISMATCHES:
        if (email_key, panel_key) not in {
            (k, pk) for k, pk, _, _ in _mismatches(lang)
        }:
            stale.append((lang, email_key, panel_key))
    assert not stale, (
        f"these are fixed and can leave KNOWN_MISMATCHES: {sorted(stale)}"
    )
