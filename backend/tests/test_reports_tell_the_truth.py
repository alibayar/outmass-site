"""The Reports tab must not show a number that is confidently wrong.

Three defects, found 2026-09-01 by an adversarial review of the delivery-report
proposal — none of them by the existing 1,300-test suite, because every one of
them produces a plausible number rather than an error.

  1. Engagement rates divided by campaigns.sent_count, which counts EMAILS.
     A follow-up bumps it without adding a recipient, so the first campaign to
     actually receive one would have reported "180 sent" for a list of 100 and
     four rates at roughly half their true value. Invisible until the moment
     the feature we charge $19 for starts working.
  2. Engagement counts falling to 0 on a failed or truncated read. Zero is an
     answer, and it is the answer the user is most afraid of: nobody replied.
  3. click_count incremented on every click while its denominator counts
     people, so click_rate could pass 100%. The open path has guarded against
     exactly this since it was written; the click path never did.

The common shape: a wrong number is worse than a missing one, because it is
read as a result. miriam is the standing example — she was staring at 244
bounce notices, and a status-derived panel would have told her 417 sent, 0
failed.
"""
from unittest.mock import MagicMock, patch

from tests.conftest import FAKE_USER


def _campaign(**over):
    row = {
        "id": "camp-1",
        "user_id": FAKE_USER["id"],
        "name": "C",
        "status": "sent",
        "total_contacts": 100,
        "sent_count": 180,        # 100 originals + an 80-recipient follow-up
        "open_count": 40,
        "click_count": 10,
        "archived": False,
    }
    row.update(over)
    return row


def _contact_rows(n, opened=0, clicked=0, replied=0):
    rows = []
    for i in range(n):
        rows.append({
            "id": f"ct-{i}",
            "opened_at": "2026-09-01T00:00:00Z" if i < opened else None,
            "clicked_at": "2026-09-01T00:00:00Z" if i < clicked else None,
            "replied_at": "2026-09-01T00:00:00Z" if i < replied else None,
        })
    return rows


def _stats(client, fake_db, campaign, contact_rows, delivered, engagement_raises=False):
    """Drive GET /campaigns/{id}/stats with a controlled contacts table."""
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    if engagement_raises:
        chain.execute.side_effect = RuntimeError("postgrest 503")
    else:
        chain.execute.return_value = MagicMock(data=contact_rows)
    db = MagicMock()
    db.table.return_value = chain

    with patch("models.campaign.get_campaign", return_value=campaign), \
         patch("models.contact.count_delivered_contacts", return_value=delivered), \
         patch("models.followup.get_campaign_followups", return_value=[]), \
         patch("routers.campaigns.get_db", return_value=db):
        return client.get(f"/campaigns/{campaign['id']}/stats")


# ── 1. the denominator ──


def test_rates_are_divided_by_people_reached_not_emails_sent(
    client, fake_db, auth_bypass
):
    """A follow-up must not halve every rate on the campaign it belongs to."""
    resp = _stats(
        client, fake_db,
        _campaign(sent_count=180, open_count=40),
        _contact_rows(100, opened=40),
        delivered=100,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["open_rate"] == 40.0, (
        f"open_rate is {body['open_rate']}, not 40.0 — 40 opens among 100 "
        f"recipients was divided by the 180 EMAILS the campaign sent, which "
        f"is what happens the first time a follow-up actually goes out"
    )
    assert body["click_rate"] == 10.0


def test_the_two_numbers_are_reported_separately(client, fake_db, auth_bypass):
    """Both are true; they answer different questions, so both are sent."""
    body = _stats(
        client, fake_db, _campaign(sent_count=180),
        _contact_rows(100), delivered=100,
    ).json()

    assert body["sent_count"] == 180, "emails sent must still be reported"
    assert body["delivered_count"] == 100, (
        "the panel has no way to show people-reached separately from "
        "emails-sent unless the endpoint reports it"
    )


# ── 2. no confident zero ──


def test_a_failed_engagement_read_reports_nothing_rather_than_zero(
    client, fake_db, auth_bypass
):
    """'0 replies' and 'we could not check' must not look identical.

    The old code caught the exception and set both counts to 0, so a
    transient database error rendered as a definitive, discouraging result.
    """
    body = _stats(
        client, fake_db, _campaign(), _contact_rows(100),
        delivered=100, engagement_raises=True,
    ).json()

    assert body["replied_count"] is None, (
        f"a failed read reported {body['replied_count']!r} replies — the user "
        f"reads that as 'nobody answered me'"
    )
    assert body["engaged_count"] is None
    assert body["reply_rate"] is None
    assert body["engaged_rate"] is None


def test_a_truncated_engagement_page_reports_nothing_rather_than_a_short_count(
    client, fake_db, auth_bypass
):
    """Above the row ceiling the numerator is short and the denominator is not.

    That produces a low but plausible engagement rate on exactly the campaigns
    big enough for it to matter.
    """
    from config import SUPABASE_MAX_ROWS

    body = _stats(
        client, fake_db,
        _campaign(total_contacts=1500, sent_count=1500),
        _contact_rows(SUPABASE_MAX_ROWS, opened=400, replied=50),
        delivered=1500,
    ).json()

    assert body["replied_count"] is None, (
        f"reported {body['replied_count']!r} replies from a page that stopped "
        f"at {SUPABASE_MAX_ROWS} of 1500 recipients — short by an unknown "
        f"amount and indistinguishable from a real number"
    )


def test_a_campaign_within_the_ceiling_still_reports_real_numbers(
    client, fake_db, auth_bypass
):
    """The guard must not blank out the ordinary case."""
    body = _stats(
        client, fake_db, _campaign(), _contact_rows(100, opened=40, replied=7),
        delivered=100,
    ).json()

    assert body["replied_count"] == 7
    assert body["reply_rate"] == 7.0
    assert body["engaged_count"] == 40


# ── 3. the click counter ──


FAKE_CONTACT = {
    "id": "contact-001",
    "campaign_id": "campaign-001",
    "email": "user@example.com",
    "status": "sent",
    "opened_at": None,
    "clicked_at": None,
    "ab_variant": None,
    "unsubscribed": False,
}


def test_the_first_click_counts(client, fake_db):
    bumped = []
    with patch("routers.tracking.contact_model.get_contact", return_value=FAKE_CONTACT), \
         patch("routers.tracking.contact_model.mark_clicked"), \
         patch("routers.tracking._record_event"), \
         patch("routers.tracking.campaign_model.increment_stat",
               side_effect=lambda cid, stat, *a: bumped.append(stat)):
        resp = client.get(
            "/c/contact-001?url=https://example.com", follow_redirects=False
        )

    assert resp.status_code in (302, 307)
    assert "click_count" in bumped, "the first click must be counted"


def test_a_second_click_by_the_same_person_does_not_count_again(client, fake_db):
    """click_rate = click_count / people. If the numerator counts clicks and
    the denominator counts people, the rate can exceed 100% — and one
    recipient reading an email twice is enough on a small list."""
    already = {**FAKE_CONTACT, "clicked_at": "2026-09-01T09:00:00Z"}
    bumped = []
    with patch("routers.tracking.contact_model.get_contact", return_value=already), \
         patch("routers.tracking.contact_model.mark_clicked"), \
         patch("routers.tracking._record_event"), \
         patch("routers.tracking.campaign_model.increment_stat",
               side_effect=lambda cid, stat, *a: bumped.append(stat)):
        resp = client.get(
            "/c/contact-001?url=https://example.com", follow_redirects=False
        )

    assert resp.status_code in (302, 307), "the redirect must still happen"
    assert "click_count" not in bumped, (
        "a repeat click incremented click_count again — that is how a click "
        "rate passes 100%"
    )


def test_the_open_and_click_paths_agree_about_counting_once():
    """Structural: the asymmetry is what caused this, so name it.

    The open path has guarded on first-open since it was written. The click
    path was copied from it without the guard.
    """
    import inspect

    from routers import tracking

    src = inspect.getsource(tracking)
    assert 'if not contact.get("opened_at")' in src, "the open guard is gone"
    assert 'if not contact.get("clicked_at")' in src, (
        "the click counter is unguarded again — every repeat click inflates "
        "click_count against a denominator that counts people"
    )


# ── the CSV export ──


def test_the_export_pages_past_the_row_ceiling():
    """An export is the one place a short answer looks exactly like a complete
    one: the file cannot say what it is missing. faisal's 1,210-recipient
    campaign would have exported 1,000 rows and looked whole."""
    from config import SUPABASE_MAX_ROWS
    from models import contact as contact_model

    pages = [
        [{"id": f"a-{i}"} for i in range(SUPABASE_MAX_ROWS)],
        [{"id": f"b-{i}"} for i in range(210)],
    ]
    calls = []

    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain

    def _range(start, end):
        calls.append((start, end))
        return chain

    chain.range.side_effect = _range
    chain.execute.side_effect = [MagicMock(data=p) for p in pages]
    db = MagicMock()
    db.table.return_value = chain

    with patch("models.contact.get_db", return_value=db):
        rows = contact_model.get_all_contacts("camp-1")

    assert len(rows) == SUPABASE_MAX_ROWS + 210, (
        f"export returned {len(rows)} rows of 1210 — the user gets a file that "
        f"looks complete and is not"
    )
    assert len(calls) == 2, f"expected two pages, got ranges {calls!r}"
    assert calls[0] == (0, SUPABASE_MAX_ROWS - 1)


def test_the_export_stops_asking_when_a_page_comes_back_short():
    """One round trip for every campaign smaller than the ceiling."""
    from models import contact as contact_model

    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.execute.return_value = MagicMock(data=[{"id": "a"}, {"id": "b"}])
    db = MagicMock()
    db.table.return_value = chain

    with patch("models.contact.get_db", return_value=db):
        rows = contact_model.get_all_contacts("camp-1")

    assert len(rows) == 2
    assert chain.execute.call_count == 1, (
        "a small campaign must cost one query, not two"
    )
