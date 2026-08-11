"""The public pages must state the quotas the code actually enforces.

Written 2026-08-11, after docs/terms.html was found still promising a
50-email free tier months after config.py went to 250 — and promising
"2,000" for Starter, which has been 2,500 for just as long. The marketing
pages (index.html, pricing.html) had been updated; the legal page had not.
That is the usual shape: whoever raises a limit updates the page that sells
and forgets the page that binds.

This is the SECOND time these exact numbers drifted. docs/store-listing/
README.md records the first — three months of store listings advertising
"free = 50/mo, Starter = 2,000/mo" after both had changed — and the fix
then was check-limits.js, which guards the store copy only. Nothing guarded
the website, so the same two numbers rotted again in a different file.

Deliberately compares against the DEFAULTS literal in config.py rather than
the imported values: a Railway override changes what we enforce, and if we
ever set one, the public pages have to be updated by hand anyway. What this
catches is the real failure — the number moved in code and nowhere else.
"""
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_CONFIG = _REPO / "backend" / "config.py"
_DOCS = _REPO / "docs"


def _default_limit(name: str) -> int:
    """Read a plan limit's default straight out of the config source."""
    src = _CONFIG.read_text(encoding="utf-8")
    m = re.search(rf'{name} = int\(os\.getenv\("{name}", "(\d+)"\)\)', src)
    assert m, f"{name} is not declared the way this test expects — update both"
    return int(m.group(1))


@pytest.fixture(scope="module")
def limits() -> dict[str, int]:
    return {
        "free": _default_limit("FREE_PLAN_MONTHLY_LIMIT"),
        "starter": _default_limit("STARTER_PLAN_MONTHLY_LIMIT"),
        "pro": _default_limit("PRO_PLAN_MONTHLY_LIMIT"),
    }


def _forms(n: int) -> tuple[str, ...]:
    """Both the bare and thousands-separated spellings, since the pages use
    '250' and '2,500' interchangeably."""
    return (str(n), f"{n:,}")


# Every public page that states a plan quota. Adding a page that makes the
# claim without adding it here is the gap this test exists to close, so keep
# the list honest rather than convenient.
_PAGES_WITH_PLAN_CLAIMS = ("terms.html", "pricing.html", "index.html")


@pytest.mark.parametrize("page", _PAGES_WITH_PLAN_CLAIMS)
def test_public_page_states_the_enforced_limits(page, limits):
    text = (_DOCS / page).read_text(encoding="utf-8")
    for plan, value in limits.items():
        assert any(f in text for f in _forms(value)), (
            f"docs/{page} never states the {plan} limit of {value}. Either the "
            f"limit moved in config.py and this page was not updated, or the "
            f"page stopped making the claim — if the latter, drop it from "
            f"_PAGES_WITH_PLAN_CLAIMS with a note saying why."
        )


# The stale spellings, as regexes. The leading \b matters more than it
# looks: the first draft of this test used a plain substring and "50 emails
# per month" matched inside the CORRECTED "250 emails per month", so the
# guard failed on the very fix it was written to protect. A checker that
# cannot tell the bad string from the good one is worse than no checker.
_STALE_CLAIMS = {
    r"\b50 emails per month": "the pre-250 free tier",
    r"\b2,000 emails": "the pre-2,500 Starter tier",
    r"\(50, 2,000": "the old three-number quota sentence",
}


def test_the_stale_patterns_can_tell_good_from_bad():
    """Self-test the guard before trusting it. Same lesson as the f-string
    checker on 2026-08-10 that reported a clean sweep for a class it could
    not actually see."""
    known_bad = "The free tier is limited to 50 emails per month."
    known_good = "The free tier is limited to 250 emails per month."
    pattern = r"\b50 emails per month"
    assert re.search(pattern, known_bad), "the pattern misses the real defect"
    assert not re.search(pattern, known_good), (
        "the pattern fires on the corrected text — this is the substring bug "
        "the first draft shipped with"
    )


def test_the_two_numbers_that_have_now_rotted_twice_are_gone(limits):
    """A targeted check on the specific stale pair, because a page can name
    the right number in one sentence and the wrong one in the next — which
    is exactly what terms.html did: section 6 said 50, section 9 said
    '(50, 2,000, or 10,000)'. Presence-only assertions miss that."""
    for page in _PAGES_WITH_PLAN_CLAIMS:
        text = (_DOCS / page).read_text(encoding="utf-8")
        for pattern, what in _STALE_CLAIMS.items():
            assert not re.search(pattern, text), (
                f"docs/{page} still carries {pattern!r} — {what}. Free is now "
                f"{limits['free']}, Starter {limits['starter']}."
            )


def test_the_ai_writer_quota_is_not_confused_with_the_free_tier():
    """'50/mo' is still correct for the AI writer and appears on pricing.html
    and index.html. It is only wrong when it describes SENDING. This test
    stops a future cleanup from deleting the legitimate 50 while chasing the
    stale one — the two were adjacent on the same page."""
    from config import AI_GENERATION_MONTHLY_LIMIT

    assert AI_GENERATION_MONTHLY_LIMIT == 50, (
        "the AI writer quota moved; docs/pricing.html and docs/index.html say "
        "'AI Email Writer (50/mo)' and now need updating too"
    )
    text = (_DOCS / "pricing.html").read_text(encoding="utf-8")
    assert "AI Email Writer</strong> (50/mo" in text
