"""A security scanner fetching the pixel is not a person reading the email.

Hélène Carpentier, 2026-09-02, looking at a 100% open rate:

    "I do not believe the 100% open rate is correct, as I have received so
    many out of office, so I do not believe all emails were opened."

She was right, and the evidence had been sitting in the events table since the
feature shipped. Her CBRE campaign produced **93 open events for 15
recipients** — six each. The first fourteen arrived 9 to 16 seconds after
their own send. One address appeared five times: 9s, 26s, 36s, 81s, 113s. All
from a generic desktop Chrome user-agent.

The only fetches that named a mail client ("ms-office") came at 65, 163, 166
and 202 seconds, from two people. So the honest open rate on that campaign was
nearer two in fifteen than fifteen in fifteen.

`_tracking_metadata` had been recording seconds-since-send and user-agent all
along, with a comment saying "we don't filter anything yet — this just
captures the evidence so a later heuristic can be calibrated on real data
instead of guesses." This is that calibration, on that data.

**The metric was the visible half.** mark_opened writes contacts.opened_at,
and the follow-up condition 'not_opened' reads it — so a scanner opening the
pixel nine seconds after delivery removed that recipient from the follow-up
entirely. Somebody who never saw the email, dropped from the sequence meant to
reach them, silently.
"""
from unittest.mock import patch

import pytest

from routers.tracking import looks_automated

CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
OFFICE = "Mozilla/4.0 (compatible; ms-office; MSOffice 16)"


# ── the classifier, against the rows that produced it ──


@pytest.mark.parametrize("secs,label", [
    (9, "andy.morgan, first fetch"),
    (10, "amy.nicol"),
    (11, "hannah.lax"),
    (16, "michael.lynch"),
    (26, "andy.morgan again"),
    (0, "instant"),
])
def test_a_fast_anonymous_fetch_is_automated(secs, label):
    assert looks_automated({"secs_since_sent": secs, "ua": CHROME}), label


@pytest.mark.parametrize("secs,label", [
    (65, "bethany.pomiankowski, the earliest real client fetch"),
    (163, "karl.tahsin"),
    (202, "karl.tahsin again"),
    (1221, "ben.carr, twenty minutes later"),
])
def test_a_real_open_is_counted(secs, label):
    assert not looks_automated({"secs_since_sent": secs, "ua": CHROME}), label
    assert not looks_automated({"secs_since_sent": secs, "ua": OFFICE}), label


def test_a_client_that_names_itself_is_never_automated():
    """Outlook fetching remote images two seconds after delivery is Outlook.

    The timing signal only means anything for a fetcher that will not say what
    it is; a client identifying itself has already answered the question.
    """
    assert not looks_automated({"secs_since_sent": 2, "ua": OFFICE})
    assert not looks_automated({"secs_since_sent": 0, "ua": "Apple Mail/16.0"})


def test_no_timing_means_counted():
    """Not knowing is not evidence.

    The failure that matters is discarding somebody's real open, not
    tolerating a scanner's, so an event we cannot place in time is kept.
    """
    for meta in ({"ua": CHROME}, {"secs_since_sent": None, "ua": CHROME},
                 {"secs_since_sent": "not a number", "ua": CHROME}):
        assert not looks_automated(meta), meta


def test_the_threshold_is_configurable_and_conservative():
    """30 seconds sits between the scanner cluster (9-26s) and the earliest
    real client fetch on record (65s), with room on both sides."""
    from config import AUTOMATED_OPEN_WINDOW_SECONDS

    assert 20 <= AUTOMATED_OPEN_WINDOW_SECONDS <= 45, (
        f"{AUTOMATED_OPEN_WINDOW_SECONDS}s no longer sits between the observed "
        f"scanner cluster and the earliest observed real open"
    )


# ── what the open endpoint does with it ──


CONTACT = {
    "id": "contact-001",
    "campaign_id": "campaign-001",
    "email": "andy.morgan@cbre.com",
    "status": "sent",
    "opened_at": None,
    "clicked_at": None,
    "ab_variant": None,
    "unsubscribed": False,
}


def _open(client, secs, ua):
    """Fetch the pixel with a controlled seconds-since-send."""
    marked, bumped, events = [], [], []
    with patch("routers.tracking.contact_model.get_contact", return_value=CONTACT), \
         patch("routers.tracking._tracking_metadata",
               return_value={"secs_since_sent": secs, "ua": ua, "ip": "1.2.3.4"}), \
         patch("routers.tracking.contact_model.mark_opened",
               side_effect=marked.append), \
         patch("routers.tracking.campaign_model.increment_stat",
               side_effect=lambda cid, stat, *a: bumped.append(stat)), \
         patch("routers.tracking._record_event",
               side_effect=lambda c, ca, t, meta: events.append((t, meta))):
        resp = client.get("/t/contact-001")
    return resp, marked, bumped, events


def test_a_scanner_open_is_recorded_but_not_counted(client, fake_db):
    resp, marked, bumped, events = _open(client, 9, CHROME)

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/gif"
    assert bumped == [], "a scanner fetch was counted as an open"
    assert marked == [], (
        "a scanner fetch marked the contact opened — which also drops them "
        "from any follow-up conditioned on 'not opened'"
    )
    assert events and events[0][0] == "open", "the evidence must still be kept"
    assert events[0][1]["automated"] is True, (
        "the event does not carry the classification, so the threshold can "
        "never be re-calibrated on it"
    )


def test_a_real_open_is_counted_and_marked(client, fake_db):
    resp, marked, bumped, events = _open(client, 65, OFFICE)

    assert "open_count" in bumped
    assert marked == ["contact-001"]
    assert events[0][1]["automated"] is False


def test_the_pixel_is_returned_either_way(client, fake_db):
    """Whatever we decide about counting, the image must render. A recipient
    seeing a broken image because of our bookkeeping is the one outcome that
    is entirely our fault."""
    for secs, ua in ((5, CHROME), (500, OFFICE)):
        resp, *_ = _open(client, secs, ua)
        assert resp.status_code == 200
        assert resp.content.startswith(b"GIF89a"), "not a GIF"


def test_an_ab_test_is_not_decided_by_scanners(client, fake_db):
    """The variant open counters sit inside the same guard.

    An A/B test whose winner is chosen by Defender opening both variants nine
    seconds after delivery is worse than no test: it produces a confident
    answer from noise.
    """
    import inspect

    from routers import tracking

    src = inspect.getsource(tracking.track_open)
    guard = src.index("not automated and not contact.get(")
    ab = src.index('contact.get("ab_variant")')
    assert guard < ab, (
        "the A/B open counter is no longer inside the automated-open guard"
    )
