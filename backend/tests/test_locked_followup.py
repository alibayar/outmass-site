"""A follow-up survives the plan that could not run it.

Until 2026-09-01 the only moment a follow-up could be attached to a campaign
was the instant Send was pressed. Refused because follow-ups are Pro, the
subject and body the user had just written were discarded, and that campaign
could never have one — not after upgrading, not ever, because the panel has no
other way to create one.

Tim Haverkamp hit it three minutes after paying for Starter: enabled
follow-ups, scheduled 108 recipients, was refused, and clicked "manage
subscription" thirty-four seconds later.

Now the configuration is saved with status 'locked'. The worker's queries all
ask for 'scheduled', so it does nothing until someone presses activate.
"""
from unittest.mock import patch

import pytest

from tests.conftest import FAKE_PRO_USER, FAKE_USER

NEW = {"X-Extension-Version": "0.3.1"}
OLD = {"X-Extension-Version": "0.3.0"}
CAMPAIGN = {"id": "camp-1", "user_id": FAKE_USER["id"], "name": "C",
            "status": "sent", "total_contacts": 10}
PAYLOAD = {"delay_days": 3, "subject": "Following up",
           "body": "Just checking in", "condition": "not_opened"}


@pytest.fixture()
def _campaign():
    with patch("models.campaign.get_campaign", return_value=dict(CAMPAIGN)):
        yield


# ── creating ──


def test_a_new_client_without_pro_gets_its_follow_up_SAVED(client, fake_db, auth_bypass, _campaign):
    created = {}

    def _create(**kwargs):
        created.update(kwargs)
        return {"id": "fu-1"}

    with patch("models.followup.create_followup", side_effect=_create):
        resp = client.post("/campaigns/camp-1/followups", json=PAYLOAD, headers=NEW)

    assert resp.status_code == 200, resp.text
    assert resp.json()["locked"] is True, (
        "the panel has to be able to tell 'saved for later' from 'scheduled' — "
        "without this flag it would tell the user their follow-up is running"
    )
    assert created["status"] == "locked", (
        f"a follow-up the plan cannot run must be stored inert, got "
        f"{created.get('status')!r} — 'scheduled' here would send it"
    )
    assert created["subject"] == "Following up", "the wording must survive"


def test_an_old_client_without_pro_still_gets_402(client, fake_db, auth_bypass, _campaign):
    """Backward compatibility, and it is not cosmetic.

    A 0.3.0 panel has no branch for `locked`. It reads any 200 as "your
    follow-up is scheduled" and shows nothing — which is precisely the silent
    failure this feature exists to end, reintroduced by way of fixing it.
    """
    with patch("models.followup.create_followup") as create:
        resp = client.post("/campaigns/camp-1/followups", json=PAYLOAD, headers=OLD)

    assert resp.status_code == 402
    assert create.call_count == 0, "nothing may be stored for a client that cannot see it"


def test_an_unversioned_client_still_gets_402(client, fake_db, auth_bypass, _campaign):
    """No header at all is an old client, or something we do not know."""
    resp = client.post("/campaigns/camp-1/followups", json=PAYLOAD)
    assert resp.status_code == 402


def test_pro_is_untouched_and_still_schedules(client, fake_db, auth_bypass_pro, _campaign):
    created = {}

    def _create(**kwargs):
        created.update(kwargs)
        return {"id": "fu-1"}

    with patch("models.followup.create_followup", side_effect=_create):
        resp = client.post("/campaigns/camp-1/followups", json=PAYLOAD, headers=NEW)

    assert resp.status_code == 200
    assert "locked" not in resp.json()
    assert created["status"] == "scheduled"


# ── activating ──


def _locked(**over):
    row = {"id": "fu-1", "campaign_id": "camp-1", "status": "locked",
           "delay_days": 3, "subject": "s", "body": "b"}
    row.update(over)
    return row


def test_activation_needs_pro(client, fake_db, auth_bypass, _campaign):
    with patch("models.followup.get_campaign_followups", return_value=[_locked()]):
        resp = client.post("/campaigns/camp-1/followups/fu-1/activate")
    assert resp.status_code == 402


def test_activating_something_already_running_is_refused(client, fake_db, auth_bypass_pro, _campaign):
    """Not a no-op: re-activating a 'scheduled' or 'sent' follow-up would send
    it to the same people twice."""
    with patch("models.followup.get_campaign_followups",
               return_value=[_locked(status="sent")]):
        resp = client.post("/campaigns/camp-1/followups/fu-1/activate")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "not_locked"


def test_an_activation_that_would_send_at_once_asks_first(client, fake_db, auth_bypass_pro, _campaign):
    """The hazard the whole endpoint is shaped around.

    Follow-ups are due per recipient at sent_at + delay_days. On a campaign
    that finished weeks ago every one of those moments has passed, so
    activating is not scheduling — it is sending, now, to everyone. The user
    is told the number before it happens, never after.
    """
    with patch("models.followup.get_campaign_followups", return_value=[_locked()]), \
         patch("models.followup.count_due_immediately", return_value=87), \
         patch("models.followup.update_followup_status") as flip:
        resp = client.post("/campaigns/camp-1/followups/fu-1/activate")

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "would_send_immediately"
    assert resp.json()["detail"]["count"] == 87, "the user must be told how many"
    assert flip.call_count == 0, "nothing may be activated by the request that asks"


def test_a_confirmed_immediate_activation_goes_through(client, fake_db, auth_bypass_pro, _campaign):
    with patch("models.followup.get_campaign_followups", return_value=[_locked()]), \
         patch("models.followup.count_due_immediately", return_value=87), \
         patch("models.followup.update_followup_status") as flip:
        resp = client.post(
            "/campaigns/camp-1/followups/fu-1/activate?confirm_immediate=true"
        )

    assert resp.status_code == 200
    assert resp.json()["sending_immediately_to"] == 87
    flip.assert_called_once_with("fu-1", "scheduled")


def test_a_future_dated_activation_needs_no_confirmation(client, fake_db, auth_bypass_pro, _campaign):
    """Nobody is due yet, so there is nothing to warn about."""
    with patch("models.followup.get_campaign_followups", return_value=[_locked()]), \
         patch("models.followup.count_due_immediately", return_value=0), \
         patch("models.followup.update_followup_status") as flip:
        resp = client.post("/campaigns/camp-1/followups/fu-1/activate")

    assert resp.status_code == 200
    flip.assert_called_once_with("fu-1", "scheduled")


# ── the safety property everything else rests on ──


def test_the_worker_selects_scheduled_and_never_locked():
    """A locked row must be invisible to every query that sends.

    This is the whole reason 'locked' is safe to store: not a flag anyone
    remembers to check, but a status the sending queries do not select. If a
    query is ever widened to `in_(["scheduled", "locked"])`, saved-but-unpaid
    follow-ups start going out.
    """
    import inspect

    from models import followup as followup_model

    src = inspect.getsource(followup_model.get_pending_followups)
    assert '"scheduled"' in src, "the due query must pin an explicit status"
    assert "locked" not in src, (
        "get_pending_followups now mentions 'locked' — a follow-up the user "
        "has not activated would be sent"
    )


def test_activation_on_an_archived_campaign_is_refused(client, fake_db, auth_bypass_pro):
    """Archiving is the user's stop switch, and the worker honours it first.

    followup_worker cancels an archived campaign's follow-up before doing
    anything else. Activating here would answer 200, tell the user "Follow-up
    started", and be silently undone on the next beat — nothing sent, and the
    user told something untrue.
    """
    archived = {**CAMPAIGN, "archived": True}
    with patch("models.campaign.get_campaign", return_value=archived), \
         patch("models.followup.get_campaign_followups", return_value=[_locked()]), \
         patch("models.followup.update_followup_status") as flip:
        resp = client.post("/campaigns/camp-1/followups/fu-1/activate")

    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "campaign_archived"
    assert flip.call_count == 0


def test_a_truncated_bump_memory_refuses_rather_than_guessing():
    """The set of who has already been followed up must be complete or absent.

    A contact missing from it reads as "not bumped yet" and is emailed a
    SECOND time from the customer's own mailbox. Supabase caps a response at
    SUPABASE_MAX_ROWS and returns the short list with no error, so the only
    safe response to a read that came back exactly at the ceiling is to stop.

    Reachable since 01e18bb: the threshold used to be CSV_UPLOAD_ROW_LIMIT
    (10000), which PostgREST could never serve, so this branch was dead.
    """
    from unittest.mock import MagicMock

    from config import SUPABASE_MAX_ROWS
    from models import followup as followup_model

    rows = [{"contact_id": f"c{i}"} for i in range(SUPABASE_MAX_ROWS)]
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=rows)
    db = MagicMock()
    db.table.return_value = chain

    with patch("models.followup.get_db", return_value=db):
        with pytest.raises(RuntimeError, match="ceiling"):
            followup_model.get_bumped_contact_ids("fu-1")


def test_a_short_bump_memory_is_returned_normally():
    """The ordinary case must still work, or every follow-up stops."""
    from unittest.mock import MagicMock

    from models import followup as followup_model

    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=[{"contact_id": "c1"}, {"contact_id": "c2"}])
    db = MagicMock()
    db.table.return_value = chain

    with patch("models.followup.get_db", return_value=db):
        assert followup_model.get_bumped_contact_ids("fu-1") == {"c1", "c2"}
