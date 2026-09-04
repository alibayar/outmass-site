"""A campaign silent too long asks before it resumes.

faisal@samaed.com, 2026-08-11. `Wave 6 SYC Jeddah` sent 154 on 27 June and
stopped partway, leaving 208 people never written to. Those 208 sat for six
weeks with nothing telling him. He signed in on 10 August at 15:15, did
nothing else — no send, no schedule, sidebar opened and closed — and at 06:04
the next morning 204 emails went out to his customers. He called it
embarrassing and said he had been ready to stop using OutMass over it.

What released it was the dormancy hold in auto_resume_partial_campaigns, whose
docstring says so in as many words: "It self-heals: one sign-in writes the
column and the next run resumes."

Three things have to stay true at once, and each has a test here:

  * a campaign silent past AUTO_RESUME_MAX_IDLE_DAYS does not resume by
    itself — it emails its owner and waits for the Resume button;
  * it emails ONCE, however many times the two-hourly beat sees it. The
    quota-capped notification added on 2026-09-03 was one condition away from
    fifty-two identical emails to a single customer;
  * a campaign waiting on QUOTA still resumes silently, because four live
    places promise exactly that — the store listing in twelve languages,
    send_quota_capped_email, alertQuotaCapped in fourteen locales, and the
    message owed to marketing@hrds.com. The threshold is what keeps both
    promises: no quota wait can reach thirty-five days.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from config import AUTO_RESUME_MAX_IDLE_DAYS
from tests.conftest import FAKE_USER


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _campaign(cid="c1", created_days_ago=90, notified=None, migrated=True):
    """A partial campaign as `select *` returns it.

    ``migrated=False`` drops stalled_notice_at from the row entirely, which is
    what PostgREST returns before migration 036 is applied — not a NULL, an
    absent key. The guard reads the difference.
    """
    row = {
        "id": cid,
        "user_id": FAKE_USER["id"],
        "name": "Wave 6 SYC Jeddah",
        "status": "partial",
        "created_at": _iso(created_days_ago),
    }
    if migrated:
        row["stalled_notice_at"] = notified
    return row


def _run(campaigns, user=None, resumable=None, last_sent=None, count=None):
    """One pass of the beat. Returns (result, update_mock, email_mock).

    `resumable` is the PAGE the beat reads (capped at SUPABASE_MAX_ROWS in
    production); `count` is the server-side COUNT. They are separate arguments
    because the difference between them is a bug this file has to keep out.
    """
    from workers import scheduled_worker

    user = user if user is not None else {**FAKE_USER, "emails_sent_this_month": 0}
    resumable = resumable if resumable is not None else [{"id": "k%d" % i}
                                                         for i in range(208)]

    with patch(
        "models.campaign.get_resumable_partial_campaigns", return_value=campaigns
    ), patch(
        "models.user.get_by_id", return_value=user
    ), patch(
        "models.user.check_monthly_reset"
    ), patch(
        "models.contact.get_resumable_contacts", return_value=resumable
    ), patch(
        "models.contact.count_resumable_contacts",
        return_value=len(resumable) if count is None else count,
    ), patch(
        "models.contact.get_last_sent_at", return_value=last_sent
    ), patch(
        "models.campaign.update_campaign"
    ) as update, patch(
        "utils.welcome_email.send_campaign_stalled_email", return_value=True
    ) as email:
        result = scheduled_worker.auto_resume_partial_campaigns()
    return result, update, email


# ── The incident ──


def test_a_six_week_silence_asks_instead_of_sending():
    """faisal's Wave 6, replayed: the beat must not put 204 emails out."""
    result, update, email = _run(
        [_campaign()], last_sent=_iso(45)
    )

    assert result["resumed"] == 0, "the campaign must not go back to 'scheduled'"
    assert result["held_stale"] == 1

    # Exactly one write, and it is the marker — nothing set a status.
    assert update.call_count == 1
    campaign_id, updates = update.call_args.args
    assert campaign_id == "c1"
    assert set(updates) == {"stalled_notice_at"}
    assert updates["stalled_notice_at"]


def test_the_owner_is_told_what_is_waiting_and_what_to_press():
    result, update, email = _run([_campaign()], last_sent=_iso(45))

    assert email.call_count == 1
    args = email.call_args.args
    assert args[0] == FAKE_USER["email"]
    assert args[2] == "Wave 6 SYC Jeddah", "the campaign has to be named"
    assert args[3] == 208, "the number of people still waiting"
    assert args[4] == 45, "how long it has been silent, in whole days"


def test_the_count_is_counted_not_measured_off_a_capped_page():
    """The number in the email must not be the length of a truncated read.

    get_resumable_contacts is capped at SUPABASE_MAX_ROWS (1,000). Truncation
    of exactly that read stranded 109 of faisal's recipients on 2026-08-31,
    and the largest list on his account today is 1,210 — so a campaign big
    enough to hit the cap is not hypothetical. len(page) would tell its owner
    1,000 people are waiting when 1,210 are.
    """
    page = [{"id": "k%d" % i} for i in range(1000)]
    _, _, email = _run([_campaign()], resumable=page, count=1210,
                       last_sent=_iso(45))

    assert email.call_args.args[3] == 1210


def test_it_asks_once_not_every_two_hours():
    """The beat runs twelve times a day. The marker is the whole guard."""
    result, update, email = _run(
        [_campaign(notified=_iso(3))], last_sent=_iso(45)
    )

    assert result["held_stale"] == 1
    assert result["resumed"] == 0
    email.assert_not_called()
    update.assert_not_called()


def test_a_failed_marker_stays_quiet_and_still_holds():
    """If we cannot record the ask, we do not make it — and we still hold.

    Two separate decisions, and the first draft of this guard conflated them:
    a failed marker write returned False and fell through to the resume. By
    the time that branch runs, the row has already been shown to carry the
    column, so the only way to reach it is a transient write failure — and
    answering a network blip with several hundred emails on someone's behalf
    is the incident this whole change exists to prevent.

    Silence is retried for free. The marker was never written, so the next
    pass in two hours tries again and sends the email then.
    """
    from workers import scheduled_worker

    def _refuse_the_marker(campaign_id, updates):
        # A blip on this one write. Every other write still works, which is
        # what makes the fall-through reachable at all.
        if "stalled_notice_at" in updates:
            raise RuntimeError("connection reset by peer")

    with patch(
        "models.campaign.get_resumable_partial_campaigns",
        return_value=[_campaign()],
    ), patch(
        "models.user.get_by_id",
        return_value={**FAKE_USER, "emails_sent_this_month": 0},
    ), patch(
        "models.user.check_monthly_reset"
    ), patch(
        "models.contact.get_resumable_contacts", return_value=[{"id": "k1"}]
    ), patch(
        "models.contact.count_resumable_contacts", return_value=1
    ), patch(
        "models.contact.get_last_sent_at", return_value=_iso(45)
    ), patch(
        "models.campaign.update_campaign", side_effect=_refuse_the_marker
    ) as update, patch(
        "utils.welcome_email.send_campaign_stalled_email"
    ) as email:
        result = scheduled_worker.auto_resume_partial_campaigns()

    email.assert_not_called()
    assert result["resumed"] == 0, "a blip must never turn into a send"
    assert result["held_stale"] == 1
    assert result["held_stale_unnotified"] == 1
    assert all(
        u.args[1].get("status") != "scheduled" for u in update.call_args_list
    ), "nothing may put this campaign back into the send queue"


def test_a_failed_email_still_leaves_the_campaign_held():
    """MailerSend refusing must not turn into a send nobody asked for."""
    from workers import scheduled_worker

    with patch(
        "models.campaign.get_resumable_partial_campaigns",
        return_value=[_campaign()],
    ), patch(
        "models.user.get_by_id",
        return_value={**FAKE_USER, "emails_sent_this_month": 0},
    ), patch(
        "models.user.check_monthly_reset"
    ), patch(
        "models.contact.get_resumable_contacts", return_value=[{"id": "k1"}]
    ), patch(
        "models.contact.count_resumable_contacts", return_value=1
    ), patch(
        "models.contact.get_last_sent_at", return_value=_iso(45)
    ), patch(
        "models.campaign.update_campaign"
    ) as update, patch(
        "utils.welcome_email.send_campaign_stalled_email",
        side_effect=RuntimeError("mailersend down"),
    ):
        result = scheduled_worker.auto_resume_partial_campaigns()

    assert result["held_stale"] == 1
    assert result["held_stale_unnotified"] == 1
    assert result["resumed"] == 0
    assert set(update.call_args.args[1]) == {"stalled_notice_at"}


def test_a_refused_email_is_counted_not_swallowed():
    """MailerSend returning False is the same silence as raising.

    _dispatch never raises — a missing API key, a 429 and a timeout all come
    back as False — so a version that only counted exceptions would report
    zero for the one failure that actually happens.
    """
    from workers import scheduled_worker

    with patch(
        "models.campaign.get_resumable_partial_campaigns",
        return_value=[_campaign()],
    ), patch(
        "models.user.get_by_id",
        return_value={**FAKE_USER, "emails_sent_this_month": 0},
    ), patch(
        "models.user.check_monthly_reset"
    ), patch(
        "models.contact.get_resumable_contacts", return_value=[{"id": "k1"}]
    ), patch(
        "models.contact.count_resumable_contacts", return_value=1
    ), patch(
        "models.contact.get_last_sent_at", return_value=_iso(45)
    ), patch(
        "models.campaign.update_campaign"
    ), patch(
        "utils.welcome_email.send_campaign_stalled_email", return_value=False
    ):
        result = scheduled_worker.auto_resume_partial_campaigns()

    assert result["held_stale"] == 1
    assert result["held_stale_unnotified"] == 1
    assert result["resumed"] == 0


# ── What must NOT change ──


def test_a_campaign_waiting_on_quota_still_resumes_by_itself():
    """The four live promises, in one test.

    A free user whose list needs forty monthly batches waits at most one
    rolling cycle between them. Thirty days is inside the threshold and has to
    stay inside it, or the store listing, the quota-capped email and
    alertQuotaCapped all become false in twelve to fourteen languages.
    """
    result, update, email = _run([_campaign()], last_sent=_iso(30))

    assert result["resumed"] == 1
    assert result["held_stale"] == 0
    email.assert_not_called()
    assert update.call_args.args[1]["status"] == "scheduled"


def test_the_threshold_is_a_ceiling_not_a_target():
    """Exactly AUTO_RESUME_MAX_IDLE_DAYS resumes; a day past it asks."""
    at_limit, _, email_at = _run(
        [_campaign()], last_sent=_iso(AUTO_RESUME_MAX_IDLE_DAYS - 0.01)
    )
    past_limit, _, email_past = _run(
        [_campaign()], last_sent=_iso(AUTO_RESUME_MAX_IDLE_DAYS + 1)
    )

    assert at_limit["resumed"] == 1
    email_at.assert_not_called()
    assert past_limit["resumed"] == 0
    assert email_past.call_count == 1


def test_the_guard_is_inert_until_migration_036_lands():
    """Code can deploy before the column exists without emailing anyone.

    The row arrives from `select *`, so a missing key IS the signal. Every
    other test in tests/test_auto_resume.py builds rows without it, which
    makes that whole file a check that yesterday's behaviour survives.
    """
    result, update, email = _run(
        [_campaign(migrated=False)], last_sent=_iso(120)
    )

    assert result["resumed"] == 1
    assert result["held_stale"] == 0
    email.assert_not_called()


def test_a_dormant_owner_is_held_without_being_emailed():
    """Order of guards: away is not the same as needing to decide.

    Emailing here would mean a deploy announcing itself to everyone whose
    campaign has been parked, including people who never come back. The ask
    belongs at the moment we would otherwise have sent — which is the moment
    they return.
    """
    away = {
        **FAKE_USER,
        "emails_sent_this_month": 0,
        "last_activity_at": _iso(60),
    }
    result, update, email = _run([_campaign()], user=away, last_sent=_iso(45))

    assert result["held_owner_dormant"] == 1
    assert result["held_stale"] == 0
    email.assert_not_called()
    update.assert_not_called()


def test_a_finished_campaign_closes_quietly():
    """Nothing left to send is bookkeeping, not a decision to put to anyone."""
    result, update, email = _run(
        [_campaign()], resumable=[], last_sent=_iso(200)
    )

    assert result["closed_as_sent"] == 1
    email.assert_not_called()
    assert update.call_args.args[1] == {"status": "sent"}


def test_never_sent_falls_back_to_when_it_was_created():
    """A campaign parked before its first delivery has no sent_at to read.

    "Created forty days ago, delivered nothing" is exactly as stale as
    "delivered once, forty days ago", and reading None as fresh would let the
    oldest campaigns in the table through the one guard written for them.
    """
    result, _, email = _run(
        [_campaign(created_days_ago=90)], last_sent=None
    )

    assert result["held_stale"] == 1
    assert email.call_args.args[4] == 90


def test_an_unreadable_anchor_resumes_rather_than_stranding():
    """We do not hold a campaign forever on a string we failed to parse."""
    result, _, email = _run([_campaign()], last_sent="not-a-timestamp")

    assert result["resumed"] == 1
    email.assert_not_called()


# ── The other half: pressing Resume clears the marker ──


def test_resume_endpoint_clears_the_marker(client, auth_bypass):
    """Otherwise the next stall, a year later, would be met with silence."""
    campaign = {
        "id": "c1",
        "user_id": FAKE_USER["id"],
        "status": "partial",
        "stalled_notice_at": _iso(2),
    }
    with patch("models.campaign.get_campaign", return_value=campaign), patch(
        "models.contact.get_resumable_contacts", return_value=[{"id": "k1"}]
    ), patch("models.campaign.update_campaign") as update:
        resp = client.post("/campaigns/c1/resume")

    assert resp.status_code == 200
    assert update.call_args.args[1]["stalled_notice_at"] is None


def test_resume_does_not_name_a_column_that_does_not_exist(client, auth_bypass):
    """Before migration 036, Resume has to keep working for everyone.

    Naming an absent column fails the whole PostgREST request, which would
    turn a missing migration into a broken button rather than an inert guard.
    """
    campaign = {"id": "c1", "user_id": FAKE_USER["id"], "status": "partial"}
    with patch("models.campaign.get_campaign", return_value=campaign), patch(
        "models.contact.get_resumable_contacts", return_value=[{"id": "k1"}]
    ), patch("models.campaign.update_campaign") as update:
        resp = client.post("/campaigns/c1/resume")

    assert resp.status_code == 200
    assert "stalled_notice_at" not in update.call_args.args[1]
