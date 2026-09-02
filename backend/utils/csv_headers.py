"""Which column holds the address — by name, then by what it contains.

The panel learned this on 2026-09-02 and the server did not, which is the
worse half of the same bug. `extension/sidebar.js` started accepting
"Email Address"; `upload_contacts` still demanded a header spelled exactly
`email`. So the file was accepted at the file picker, previewed, test-sent,
the campaign row was created — and then the contact upload returned 400 with
an English sentence no locale file translates, leaving a 0-recipient campaign
in Reports. Dhirender, who was turned away twice by the panel's old check,
would have been turned away later and harder.

This module is the server's half. It is deliberately a line-for-line mirror of
`findEmailColumn` in extension/sidebar.js, and
`tests/fixtures/email_column_cases.json` is read by BOTH test suites so the two
cannot drift the way render_body and textToHtml did before render_cases.json
existed.

The content pass is the half that matters. A name list only ever contains
spellings somebody thought of, in a product shipping in thirteen languages;
a column whose values are addresses is the address column whatever its header
says.
"""
import re

# Spellings common enough to be worth answering before looking at the data —
# which matters for a correctly-named column that happens to be empty.
EMAIL_HEADER_NAMES = frozenset({
    "email", "emailaddress", "emails", "mail", "mailaddress",
    "workemail", "businessemail", "primaryemail", "contactemail",
    "personalemail", "emailid", "eaddress",
})

EMAIL_SHAPE = re.compile(r"^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]{2,}$")

# Sample rather than scan: a 10,000-row upload should not pay for this, and
# twenty rows settle it.
SAMPLE_ROWS = 20
# Four fifths, and at least three values to judge on. A column that is mostly
# addresses is the address column; one with a couple of stray "info@" strings
# in a notes field is not, and two rows is not enough to name a column from
# its contents at all.
MIN_SEEN = 3
MIN_RATIO = 0.8

_NON_ALNUM = re.compile(r"[^a-z0-9]")


def normalise_header(header) -> str:
    """Case, spaces, hyphens and underscores stop mattering.

    "Email Address", "email_address", "E-Mail" and "EMAILADDRESS" are one
    header written four ways, and every CRM and ATS export picks a different
    one.
    """
    return _NON_ALNUM.sub("", str(header or "").lower())


def find_email_column(headers, sample_rows) -> int:
    """Index of the address column in `headers`, or -1.

    `sample_rows` are positional value lists, aligned with `headers`. Ragged
    and short rows are tolerated: a missing cell reads as absent, not as an
    error.
    """
    headers = list(headers or [])

    for i, header in enumerate(headers):
        if normalise_header(header) in EMAIL_HEADER_NAMES:
            return i

    best, best_score = -1, 0
    for i in range(len(headers)):
        hits = seen = 0
        for row in list(sample_rows or [])[:SAMPLE_ROWS]:
            value = ""
            if row is not None and i < len(row):
                value = str(row[i] or "").strip()
            if not value:
                continue
            seen += 1
            if EMAIL_SHAPE.match(value):
                hits += 1
        if seen >= MIN_SEEN and hits / seen >= MIN_RATIO and hits > best_score:
            best, best_score = i, hits

    return best
