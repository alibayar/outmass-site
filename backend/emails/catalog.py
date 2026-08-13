"""The ten transactional emails, as structure rather than as strings.

Structure lives here; words live in ``strings/<lang>.json``. That split is the
whole point: a translator adds one file with the same keys and gets ten
correctly-shaped emails, in both text and HTML, without touching Python.

Every message is heading → greeting → body, so ``render()`` supplies the first
two and each entry below describes only its body. That is not a coincidence
worth preserving at all costs — it is just what all ten happened to be, and
noticing it removed two repeated blocks from every template.

## Adding a template

1. Add its strings to ``strings/en.json``.
2. Add an entry here.
3. Add a golden: ``UPDATE_EMAIL_GOLDENS=1 pytest tests/test_email_copy_golden.py``
   and read the diff.

``tests/test_email_catalog.py`` will fail if a key you reference is missing
from any language, if a language has keys nothing references, or if a
translation's ``${placeholders}`` differ from English's.

## Notes for whoever translates these

* ``${name}``, ``${days}`` and friends are substituted at send time. Keep them
  exactly as written, including the braces. Move them wherever the sentence
  needs them — that is the reason they are named rather than positional.
* ``**bold**``, `` `code` `` and ``[label](url)`` are the only markup. Keep the
  markers paired; translate the label of a link, never the URL.
* ``{{firstName}}`` in welcome.step2 is a merge tag the user types into their
  own campaign. It is a literal. Do not translate it.
* Subject lines are what someone sees in their inbox list. Short beats
  faithful.
"""

from dataclasses import dataclass

from emails.render import H, LINES, NOTE, OL, P, UL  # noqa: F401 — re-exported

# ── Shared block fragments ──

_SIGNATURE_ALI = (
    LINES,
    "common.signature_ali",
    "common.signature_founder",
    "common.signature_site",
)
_SIGNATURE_SHORT = (LINES, "common.signature_ali", "common.signature_outmass")
_TEAM = (NOTE, "common.team_signoff")


@dataclass(frozen=True)
class EmailTemplate:
    subject: str
    heading: str
    blocks: tuple

    #: Which anonymous greeting to use when we have no name.
    #:
    #: False → common.greeting_anon_warm ("Hi there,"), the four
    #: onboarding/billing emails, which have always read that way.
    #: True → common.greeting_anon ("Hi,"), the other five. Preserved rather
    #: than unified because these are live customer emails and a refactor that
    #: quietly rewords one is a different change from the one being made.
    anon_greeting: bool = True


TEMPLATES: dict[str, EmailTemplate] = {
    "welcome": EmailTemplate(
        subject="welcome.subject",
        heading="welcome.heading",
        anon_greeting=False,
        blocks=(
            (P, "welcome.intro", "welcome.steps_lead"),
            (OL, "welcome.step1", "welcome.step2", "welcome.step3"),
            (P, "welcome.free_plan", "welcome.reply"),
            _SIGNATURE_ALI,
            (NOTE, "welcome.ps"),
        ),
    ),
    "quota_capped": EmailTemplate(
        subject="quota_capped.subject",
        heading="quota_capped.heading",
        anon_greeting=False,
        blocks=(
            (
                P,
                "quota_capped.saved",
                "quota_capped.automatic",
                "quota_capped.sooner",
                "quota_capped.questions",
            ),
            _SIGNATURE_ALI,
        ),
    ),
    "upgrade": EmailTemplate(
        subject="upgrade.subject",
        heading="upgrade.heading",
        anon_greeting=False,
        blocks=(
            (P, "upgrade.intro"),
            (
                UL,
                "upgrade.point_quota",
                "upgrade.point_billing",
                "upgrade.point_manage",
            ),
            (P, "upgrade.reply", "upgrade.thanks"),
            _SIGNATURE_ALI,
        ),
    ),
    # Two templates rather than one with an `if`. They are two different
    # letters: one is the end of a dunning chain the reader already knows
    # about, the other is a promotional plan quietly running out, and saying
    # anything about payment in the second would be wrong.
    "plan_dropped_payment_failed": EmailTemplate(
        subject="plan_dropped.subject_payment_failed",
        heading="plan_dropped.subject_payment_failed",
        anon_greeting=False,
        blocks=(
            (
                P,
                "plan_dropped.opening_payment_failed",
                "plan_dropped.free_quota",
                "plan_dropped.carry_on_payment_failed",
                "plan_dropped.questions",
            ),
            _SIGNATURE_SHORT,
        ),
    ),
    "plan_dropped_promo_ended": EmailTemplate(
        subject="plan_dropped.subject_promo_ended",
        heading="plan_dropped.subject_promo_ended",
        anon_greeting=False,
        blocks=(
            (
                P,
                "plan_dropped.opening_promo_ended",
                "plan_dropped.free_quota",
                "plan_dropped.carry_on_promo_ended",
                "plan_dropped.questions",
            ),
            _SIGNATURE_SHORT,
        ),
    ),
    "reauth": EmailTemplate(
        subject="reauth.subject",
        heading="reauth.heading",
        blocks=(
            (P, "reauth.expired", "reauth.how_to_fix"),
            (NOTE, "reauth.reason"),
            _TEAM,
        ),
    ),
    "account_deleted": EmailTemplate(
        subject="account_deleted.subject",
        heading="account_deleted.heading",
        blocks=(
            (
                P,
                "account_deleted.removed",
                "account_deleted.audit_record",
                "account_deleted.subscription",
            ),
            (NOTE, "account_deleted.archive_reference"),
            _TEAM,
        ),
    ),
    "inactivity_30d_nudge": EmailTemplate(
        subject="inactivity_30d.subject",
        heading="inactivity_30d.heading",
        blocks=(
            (
                P,
                "inactivity_30d.noticed",
                "inactivity_30d.still_using",
                "inactivity_30d.tell_us",
                "inactivity_30d.stop_paying",
            ),
            (UL, "inactivity_30d.stop_panel", "inactivity_30d.stop_reply"),
            (NOTE, "inactivity_30d.why_receiving"),
            _TEAM,
        ),
    ),
    "inactivity_60d_warning": EmailTemplate(
        subject="inactivity_60d.subject",
        heading="inactivity_60d.heading",
        blocks=(
            (P, "inactivity_60d.noticed", "inactivity_60d.three_ways"),
            (
                UL,
                "inactivity_60d.way_keep",
                "inactivity_60d.way_tell",
                "inactivity_60d.way_cancel",
            ),
            (NOTE, "inactivity_60d.one_more"),
            _TEAM,
        ),
    ),
    "inactivity_90d_warning": EmailTemplate(
        subject="inactivity_90d.subject",
        heading="inactivity_90d.heading",
        blocks=(
            (
                P,
                "inactivity_90d.noticed",
                "inactivity_90d.to_stop",
                "inactivity_90d.what_stopped",
                "inactivity_90d.not_yet",
            ),
            (NOTE, "inactivity_90d.last_one"),
            _TEAM,
        ),
    ),
}
