"""Nobody changes a live transactional email by accident.

Ten templates go out to real customers: welcome, quota-capped, upgrade
thank-you, plan-dropped in two variants, reconnect, account-deleted, and three
inactivity tiers. They live as inline string concatenation across four files,
each one duplicated by hand into a text body and an HTML body, and until now
nothing anywhere asserted a single word of them.

This pins every one. It is not a style check — it is the safety net under the
localisation work (#36), which has to move all ten into a string table. A
refactor that changes what an existing customer receives is a different change
from the one being asked for, and without a golden the difference is invisible.

To change copy deliberately: edit the template, run
    UPDATE_EMAIL_GOLDENS=1 pytest tests/test_email_copy_golden.py
read the diff in git, and commit both. The failure message says so too, so
nobody has to find this docstring first.

An environment variable rather than a --flag: pytest only reads
pytest_addoption from conftest.py, so a custom flag declared in a test file is
silently ignored and the test passes while doing nothing. It was written that
way first and the flag errored out on the very next run — which is the only
reason this note exists.
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "email_golden_en.json"


def _render_all() -> dict:
    """Every template, with fixed inputs, exactly as a customer would get it."""
    out = {}

    # ── welcome_email.py: four senders, five messages ──
    from utils import welcome_email as we

    captured = {}

    def _fake(email, subject, text, html):
        captured[_fake.key] = {"subject": subject, "text": text, "html": html}
        return True

    cases = [
        ("welcome", lambda: we.send_welcome_email("a@b.com", "Ada Lovelace")),
        ("quota_capped",
         lambda: we.send_quota_capped_email("a@b.com", "Ada", 250, 2500, "2026-09-14")),
        ("upgrade", lambda: we.send_upgrade_email("a@b.com", "Ada", "starter")),
        ("plan_dropped_payment_failed",
         lambda: we.send_plan_dropped_email("a@b.com", "Ada", "payment_failed")),
        ("plan_dropped_promo_ended",
         lambda: we.send_plan_dropped_email("a@b.com", "Ada", "promo_ended")),
    ]
    with patch.object(we, "_dispatch", _fake):
        for key, fn in cases:
            _fake.key = key
            fn()
    out.update(captured)

    # ── the two that POST to MailerSend themselves ──
    sent = {}

    def _cap(url, headers=None, json=None, timeout=None):
        sent.clear()
        sent.update(json)

        class R:
            status_code = 202
            text = ""

        return R()

    from models import ms_token

    with patch("models.ms_token.httpx.post", side_effect=_cap), \
         patch("models.ms_token.MAILERSEND_API_KEY", "k"):
        ms_token._send_reauth_email("a@b.com", "Ada", "invalid_grant")
    out["reauth"] = {"subject": sent.get("subject"),
                     "text": sent.get("text", ""), "html": sent.get("html", "")}

    from routers import account

    with patch("routers.account.httpx.post", side_effect=_cap), \
         patch("routers.account.MAILERSEND_API_KEY", "k"):
        account._send_deletion_confirmation_email("a@b.com", "Ada", "arch-123")
    out["account_deleted"] = {"subject": sent.get("subject"),
                              "text": sent.get("text", ""), "html": sent.get("html", "")}

    # ── the three escalation tiers ──
    from workers.inactivity_nudge import TIERS

    for tier in TIERS:
        out[f"inactivity_{tier.name}"] = {
            "subject": tier.subject,
            "text": "",
            "html": tier.build_html("Ada", tier.threshold_days),
        }

    return out


@pytest.fixture(scope="module")
def rendered():
    return _render_all()


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_every_template_is_pinned(rendered, golden):
    """A new email must arrive with a golden, or it ships unreviewed."""
    assert set(rendered) == set(golden), (
        f"templates without a golden: {sorted(set(rendered) - set(golden))}; "
        f"goldens without a template: {sorted(set(golden) - set(rendered))}"
    )


@pytest.mark.parametrize("part", ["subject", "text", "html"])
def test_the_copy_has_not_changed(rendered, golden, part):
    """The whole point. Ten templates, three parts each, compared verbatim."""
    if os.environ.get("UPDATE_EMAIL_GOLDENS"):
        GOLDEN.write_text(
            json.dumps(rendered, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        pytest.skip("goldens rewritten")

    changed = [k for k in sorted(golden) if rendered[k][part] != golden[k][part]]
    assert not changed, (
        f"the {part} changed for: {changed}. If that was deliberate, run "
        "`UPDATE_EMAIL_GOLDENS=1 pytest tests/test_email_copy_golden.py`, read "
        "the diff in git, and commit both. If it was not, something edited "
        "copy that goes to paying customers."
    )


# ── What pinning them revealed ──


def test_the_quota_numbers_are_read_not_typed(rendered):
    """welcome said '250 emails/month' as a literal until 2026-08-13 — the
    same drift that had terms.html promising a 50-email free tier for months
    after config.py moved to 250. The number must come from config."""
    from config import monthly_limit_for_plan

    free = f"{monthly_limit_for_plan('free'):,}"
    assert free in rendered["welcome"]["text"], (
        "the welcome email no longer quotes the real free limit"
    )


HTML_ONLY = {
    "reauth", "account_deleted",
    "inactivity_30d_nudge", "inactivity_60d_warning", "inactivity_90d_warning",
}


@pytest.mark.parametrize("key", sorted(HTML_ONLY))
def test_the_html_only_templates_are_recorded_as_such(rendered, key):
    """Five of the ten send no text/plain part at all.

    Recorded rather than fixed here, because it is a real finding and not this
    test's job: a message with no plain-text alternative scores worse with
    spam filters and renders as nothing in a text-only client. We spent
    2026-08-13 on SPF/DKIM/DMARC precisely because whether our mail arrives
    matters — and half of it is single-part HTML.

    When the localisation work gives these a text body, delete them from
    HTML_ONLY and this test starts enforcing that they keep one.
    """
    assert rendered[key]["text"] == "", (
        f"{key} now has a text part — remove it from HTML_ONLY so the check "
        "flips from documenting the gap to defending the fix"
    )


def test_every_other_template_has_both_parts(rendered):
    for key, parts in sorted(rendered.items()):
        if key in HTML_ONLY:
            continue
        assert parts["text"].strip(), f"{key} lost its plain-text part"
        assert parts["html"].strip(), f"{key} lost its HTML part"
