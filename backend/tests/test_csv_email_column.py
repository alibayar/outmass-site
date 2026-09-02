"""The server must accept every CSV the panel accepts.

On 2026-09-02 the panel learned to find the address column by its contents,
so "Email Address", "E-mail", "Eposta" and "邮箱" all started working. The
server did not learn it. The result was not "no worse than before" — it was
worse:

    before   the file was refused at the file picker, in the user's own
             language, with the example CSV offered next to the message
    after    the file was accepted, previewed, test-sent, the campaign row was
             created, and THEN the contact upload returned
             400 "Column 'email' is required in the CSV header" — an English
             sentence that no locale file translates, shown through alert(),
             leaving a campaign with 0 recipients sitting in Reports

Dhirender, the user the panel fix was written for, would have been turned away
later and harder than before it.

The cases live in fixtures/email_column_cases.json and are read by the panel's
suite too, so the two detectors cannot drift again.
"""
import csv as _csv
import io
import json
import pathlib
from unittest.mock import patch

import pytest

from tests.conftest import FAKE_USER, FakeQueryBuilder
from utils.csv_headers import find_email_column, normalise_header

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "email_column_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]

NL = "\n"


def _split(case):
    """The fixture's lines, parsed the way the server parses them."""
    text = NL.join([case["header"]] + case["rows"])
    all_rows = list(_csv.reader(io.StringIO(text)))
    return all_rows[0], all_rows[1:]


@pytest.mark.parametrize("case", CASES, ids=[c["why"][:60] for c in CASES])
def test_the_column_is_found_the_same_way_the_panel_finds_it(case):
    headers, rows = _split(case)
    got = find_email_column(headers, rows)
    assert got == case["expect"], (
        f"{case['why']}{NL}  header: {case['header']}{NL}"
        f"  expected column {case['expect']}, got {got}"
    )


def test_the_fixture_is_the_one_the_panel_reads():
    """A case added on one side must be visible to the other.

    If the panel suite ever stops reading this JSON, the parity is
    decorative — which is exactly the state that shipped on 2026-09-02.
    """
    js = (pathlib.Path(__file__).parents[2] / "extension" / "tests"
          / "csv-email-column.test.js").read_text(encoding="utf-8")
    assert "email_column_cases.json" in js, (
        "the panel suite no longer reads the shared fixture — the two "
        "detectors can drift again, which is the bug this file exists for"
    )


def test_headers_normalise_to_the_same_string():
    for spelling in ("Email Address", "email_address", "E-Mail Address",
                     "EMAILADDRESS", " Email  Address "):
        assert normalise_header(spelling) == "emailaddress", spelling


def test_a_short_row_does_not_raise():
    """Ragged files are ordinary. A row with fewer cells than the header must
    read as absent, not as an IndexError that 500s the upload."""
    assert find_email_column(
        ["name", "email"], [["Ada"], ["Bo", "c@d.com"], [], None]
    ) == 1


# ── the half no unit test can see: the actual endpoint ──


def _campaign(cid):
    return {
        "id": cid, "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "s", "body": "b", "name": "n",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 0,
    }


INSERTED = {"inserted": 3, "skipped_duplicate": 0,
            "skipped_suppressed": 0, "skipped_invalid": 0}


def _csv_text(header, *rows):
    return NL.join((header,) + rows) + NL


def _upload(client, fake_db, csv_string, cid="cE1"):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[_campaign(cid)]))
    with patch("routers.campaigns.contact_model.bulk_insert",
               return_value=INSERTED) as bi:
        resp = client.post(f"/campaigns/{cid}/contacts",
                           json={"csv_string": csv_string})
    return resp, bi


ATS_FILE = _csv_text(
    "First Name,Last Name,Email Address,Company",
    "Ada,Lovelace,ada@example.com,Acme",
    "Bo,Peep,bo@example.com,Beta",
    "Cy,Young,cy@example.com,Gamma",
)


def test_the_file_the_panel_accepts_uploads(client, fake_db, auth_bypass):
    """The whole point. This exact shape is what an ATS export writes, what
    Dhirender uploaded twice, and what 0.3.3's panel accepts."""
    resp, _ = _upload(client, fake_db, ATS_FILE)
    assert resp.status_code == 200, (
        f"the panel accepts this file and the server refuses it: {resp.text}"
        f"{NL}That gap is a created campaign with no recipients and an "
        f"untranslated alert."
    )


@pytest.mark.parametrize("header", [
    "Email Address", "E-mail", "Work Email", "email_address", "EMAIL ADDRESS",
])
def test_every_spelling_the_panel_accepts_uploads(client, fake_db, auth_bypass, header):
    resp, _ = _upload(client, fake_db, _csv_text(
        f"Name,{header}", "Ada,a@b.com", "Bo,c@d.com", "Cy,e@f.com"))
    assert resp.status_code == 200, f"{header}: {resp.text}"


def test_a_header_only_the_data_can_explain_uploads(client, fake_db, auth_bypass):
    """Thirteen languages, and nobody here can proofread twelve of them. The
    content pass is the only reason this works for a header we never listed."""
    resp, _ = _upload(client, fake_db, _csv_text(
        "Ad,Eposta", "Ada,a@b.com", "Bo,c@d.com", "Cy,e@f.com"))
    assert resp.status_code == 200, resp.text


def test_a_padded_unlisted_header_is_sampled_by_its_real_name(
    client, fake_db, auth_bypass
):
    """DictReader keys rows by the header AS WRITTEN.

    Sampling by the trimmed name reads back nothing, so a padded header the
    name list does not know would fall to a content pass with no content and
    be refused. The name pass hides this for " email "; only an unlisted
    padded header exposes it.
    """
    resp, _ = _upload(client, fake_db, _csv_text(
        " kontakt ,Name", "a@b.com,Ada", "c@d.com,Bo", "e@f.com,Cy"))
    assert resp.status_code == 200, resp.text


def test_a_file_with_no_address_column_is_still_refused(client, fake_db, auth_bypass):
    """The rejection has to survive. Accepting anything would send a campaign
    to a column of first names."""
    resp, _ = _upload(client, fake_db, _csv_text(
        "Name,Note", "Ada,called them", "Bo,no answer", "Cy,left vm"))
    assert resp.status_code == 400
    assert "email" in resp.json()["detail"].lower()


def test_the_resolved_column_is_stored_under_the_key_everything_reads(
    client, fake_db, auth_bypass
):
    """Downstream — merge tags, dedupe, the suppression check, the worker —
    has read contact["email"] since the first version. Detection must change
    which column feeds it, not what is stored."""
    resp, bi = _upload(client, fake_db, ATS_FILE)

    assert resp.status_code == 200, resp.text
    rows = bi.call_args.args[1]
    assert rows[0]["email"] == "ada@example.com"
    assert "Email Address" not in rows[0], (
        "the address column was ALSO stored as a custom field, so "
        "{{Email Address}} exists as a merge tag and the column is duplicated"
    )
    # The other columns must survive as merge tags exactly as before.
    assert rows[0]["First Name"] == "Ada"
    assert rows[0]["Company"] == "Acme"
