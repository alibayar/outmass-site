"""A user must be able to stop their own campaign.

Until 2026-09-01 there was no way to. No endpoint, no button, nothing hidden
in a menu. `Helene@circularworkplaces.com` found that out five recipients into
a 66-person send and wrote:

    "Now I see nowhere to edit the campaign or even stop it! Please could you
    let me know how to do that or I will have to close the account to stop it."

Revoking OAuth was accurately her only lever. Her campaign was stopped by hand
with an UPDATE while she waited.

Stopping is two writes and both matter. 'cancelled' removes it from
get_due_scheduled_campaigns, which selects 'scheduled'. archived=true removes
it from get_resumable_partial_campaigns so auto-resume cannot pick it back up,
and it is what makes the follow-up worker cancel a pending follow-up for the
same campaign — a bump for a campaign someone stopped is the same mistake
arriving three days late.
"""
from unittest.mock import patch

from tests.conftest import FAKE_USER


def _campaign(**over):
    row = {
        "id": "camp-1",
        "user_id": FAKE_USER["id"],
        "name": "C",
        "status": "scheduled",
        "sent_count": 5,
        "total_contacts": 66,
        "archived": False,
    }
    row.update(over)
    return row


def test_stopping_writes_both_cancelled_and_archived(client, fake_db, auth_bypass):
    """One without the other leaves a door open.

    Only 'cancelled': the auto-resume beat still sees a resumable campaign.
    Only archived: the scheduled beat still selects status 'scheduled'.
    """
    updates = {}
    with patch("models.campaign.get_campaign", return_value=_campaign()), \
         patch("models.contact.count_resumable_contacts", return_value=61), \
         patch("models.campaign.update_campaign",
               side_effect=lambda cid, payload: updates.update(payload)):
        resp = client.post("/campaigns/camp-1/stop")

    assert resp.status_code == 200, resp.text
    assert updates.get("status") == "cancelled", (
        f"status was not cancelled, got {updates!r} — the scheduled beat "
        f"selects 'scheduled' and would send the rest anyway"
    )
    assert updates.get("archived") is True, (
        "archived was not set — auto-resume would pick the campaign back up, "
        "and the pending follow-up would still go out"
    )


def test_the_response_says_how_many_were_already_reached(client, fake_db, auth_bypass):
    """Stopping is not undoing, and the difference has to be visible.

    The panel puts this number in front of the user, because it is the one
    part of the situation nobody can take back.
    """
    with patch("models.campaign.get_campaign", return_value=_campaign(sent_count=5)), \
         patch("models.contact.count_resumable_contacts", return_value=61), \
         patch("models.campaign.update_campaign"):
        resp = client.post("/campaigns/camp-1/stop")

    body = resp.json()
    assert body["already_sent"] == 5, "the reached count must be reported"
    assert body["not_contacted"] == 61, "the spared count must be reported"


def test_a_finished_campaign_cannot_be_stopped(client, fake_db, auth_bypass):
    """409, not a quiet success.

    The caller believes something is running. Answering "stopped" when there
    was nothing to stop is a lie about the thing they are anxious about.
    """
    with patch("models.campaign.get_campaign", return_value=_campaign(status="sent")), \
         patch("models.campaign.update_campaign") as upd:
        resp = client.post("/campaigns/camp-1/stop")

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "not_stoppable"
    assert upd.call_count == 0


def test_an_already_stopped_campaign_cannot_be_stopped_again(client, fake_db, auth_bypass):
    with patch("models.campaign.get_campaign", return_value=_campaign(status="cancelled")), \
         patch("models.campaign.update_campaign") as upd:
        resp = client.post("/campaigns/camp-1/stop")

    assert resp.status_code == 409
    assert upd.call_count == 0


def test_every_status_a_send_can_be_in_is_stoppable(client, fake_db, auth_bypass):
    """The list is the whole promise.

    A status missing from it is a campaign the user watches running with a
    button that refuses. 'sending' and 'partial' matter most — those are the
    two a person is looking at when they want it to stop.
    """
    from routers.campaigns import STOPPABLE_STATUSES

    for status in ("scheduled", "sending", "partial", "failed_auth",
                   "ab_testing", "awaiting_winner", "sending_winner"):
        assert status in STOPPABLE_STATUSES, (
            f"a campaign in status {status!r} cannot be stopped — that is a "
            f"live send with no brake"
        )

    for status in ("sent", "cancelled"):
        assert status not in STOPPABLE_STATUSES, (
            f"{status!r} is terminal; offering to stop it promises something "
            f"that does not happen"
        )


def test_somebody_else_s_campaign_is_a_404(client, fake_db, auth_bypass):
    with patch("models.campaign.get_campaign",
               return_value=_campaign(user_id="someone-else")), \
         patch("models.campaign.update_campaign") as upd:
        resp = client.post("/campaigns/camp-1/stop")

    assert resp.status_code == 404
    assert upd.call_count == 0
