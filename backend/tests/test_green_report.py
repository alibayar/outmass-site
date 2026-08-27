"""The report must never describe a population it did not read.

Its predecessor was a local script, and on its first real run it read an empty
users table and printed:

    [ ok ] 0 account(s) with a dead Microsoft connection
    [ ok ] 0 account(s) sitting at their monthly cap
    [    ] 0/0 know their language

Every line true, every line meaningless — and it read as health. That is the
fourth time in two days a check that examined nothing reported clean, so the
emptiness case gets more tests here than the happy path does.

The rest of this file exists because a report is a thing you look at once a
day and stop reading closely. If it can be wrong it will be wrong quietly.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from workers.green_report import (
    EmptyDatabase,
    Line,
    as_telegram,
    as_text,
    build,
    send_green_report,
)


def _db(rows):
    db = MagicMock()
    db.table.return_value.select.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=rows)
    )
    return db


def _row(**over):
    now = datetime.now(timezone.utc)
    base = {
        "email": "a@b.com",
        "plan": "free",
        "created_at": (now - timedelta(days=30)).isoformat(),
        "last_seen_extension_version": "0.2.1",
        "stripe_subscription_id": None,
        "stripe_customer_id": None,
        "month_reset_date": "2026-08-01",
        "last_cycle_invoice_at": None,
        "emails_sent_this_month": 3,
        "emails_sent_total": 30,
        "requires_reauth": False,
        "preferred_language": None,
    }
    base.update(over)
    return base


# ── Emptiness ──


def test_zero_rows_raises_instead_of_reporting_clean():
    """The whole reason this module exists rather than the script that
    preceded it."""
    with pytest.raises(EmptyDatabase):
        build(_db([]))


def test_the_emptiness_message_names_the_likeliest_cause():
    """An anon key makes row-level security answer with an empty set and no
    error — the one failure mode that is indistinguishable from health unless
    somebody says so out loud."""
    with pytest.raises(EmptyDatabase) as e:
        build(_db([]))
    assert "anon key" in str(e.value)
    assert "row-level security" in str(e.value).lower()


def test_an_empty_database_still_reaches_the_operator():
    """Silence would be the worst outcome: a report that stops arriving looks
    exactly like a report with nothing to say."""
    sent = []
    with patch("routers.billing._telegram_alert", side_effect=lambda t: sent.append(t)), \
         patch("database.get_db"), \
         patch("workers.green_report.build", side_effect=EmptyDatabase("anon key?")):
        result = send_green_report()

    assert result == {"error": "empty_database"}
    assert sent and "could not run" in sent[0]


def test_a_crash_still_reaches_the_operator():
    sent = []
    with patch("routers.billing._telegram_alert", side_effect=lambda t: sent.append(t)), \
         patch("database.get_db"), \
         patch("workers.green_report.build", side_effect=RuntimeError("boom")):
        result = send_green_report()

    assert "boom" in result["error"]
    assert sent and "crashed" in sent[0]


# ── The report actually reports ──


def test_the_row_count_is_stated_before_anything_else():
    """The population a report describes must never be implicit again."""
    lines = build(_db([_row(), _row(email="c@d.com")]))
    assert "2 user row(s)" in lines[0].text


def test_a_dead_connection_is_not_quietly_a_pass():
    lines = build(_db([_row(requires_reauth=True)]))
    dead = [ln for ln in lines if "dead Microsoft" in ln.text]
    assert dead and dead[0].mark == "check"
    assert "a@b.com" in dead[0].text, "it must name who, or it is not actionable"


def test_a_capped_account_is_named():
    lines = build(_db([_row(plan="free", emails_sent_this_month=250)]))
    capped = [ln for ln in lines if "monthly cap" in ln.text]
    assert capped and capped[0].mark == "check" and "a@b.com" in capped[0].text


def test_a_confirmed_renewal_reads_as_confirmed():
    lines = build(_db([_row(
        stripe_subscription_id="sub_1",
        month_reset_date="2026-08-14",
        last_cycle_invoice_at="2026-08-14T20:20:00+00:00",
    )]))
    assert any(ln.mark == "ok" and "Stripe confirmed" in ln.text for ln in lines)


def test_a_backstop_rollover_is_flagged_not_celebrated():
    """anchor and stamp disagreeing means the webhook was late or lost, and
    the date anchor rolled it. That is the signal the column exists for."""
    lines = build(_db([_row(
        stripe_subscription_id="sub_1",
        month_reset_date="2026-08-14",
        last_cycle_invoice_at="2026-08-17T20:20:00+00:00",
    )]))
    flagged = [ln for ln in lines if "backstop rolled it" in ln.text]
    assert flagged and flagged[0].mark == "check"


def test_a_renewal_older_than_the_stamp_is_not_read_as_a_missed_one():
    """The blank that cost an hour on 2026-08-27.

    A subscriber whose renewal happened before the stamping code shipped can
    never carry a stamp. Printed as a bare "none yet" it looks exactly like a
    payment that never arrived - and Stripe had collected that one perfectly.
    """
    lines = build(_db([_row(
        email="gsanders@example.com",
        stripe_subscription_id="sub_1",
        month_reset_date="2026-07-08",
        last_cycle_invoice_at=None,
    )]))
    said = [ln for ln in lines if "gsanders@example.com" in ln.text]
    assert said, "the subscriber should still get a line"
    assert said[0].mark != "check", "a pre-stamping renewal is not a problem"
    assert "before stamping began" in said[0].text
    # And it names the date that WILL prove the path works.
    assert "2026-09-08" in said[0].text


def test_a_renewal_that_has_not_come_round_yet_says_so():
    future_anchor = (
        datetime.now(timezone.utc).date().replace(day=1) + timedelta(days=32)
    ).replace(day=1)
    lines = build(_db([_row(
        email="mercedes@example.com",
        stripe_subscription_id="sub_1",
        month_reset_date=future_anchor.isoformat(),
        last_cycle_invoice_at=None,
    )]))
    said = [ln for ln in lines if "mercedes@example.com" in ln.text]
    assert said and said[0].mark != "check"
    assert "not due yet" in said[0].text


def test_a_renewal_that_passed_without_an_invoice_is_a_check():
    """The one state actually worth reading: due, and nothing arrived.

    35 days back puts the renewal roughly five days in the past — recent
    enough to be after the stamping cutoff on any run from now on, which is
    what separates this case from the pre-stamping one above.
    """
    overdue_anchor = datetime.now(timezone.utc).date() - timedelta(days=35)
    lines = build(_db([_row(
        email="silent@example.com",
        stripe_subscription_id="sub_1",
        month_reset_date=overdue_anchor.isoformat(),
        last_cycle_invoice_at=None,
    )]))
    said = [ln for ln in lines if "silent@example.com" in ln.text]
    assert said and said[0].mark == "check"
    assert "no invoice arrived" in said[0].text


def _posthog(rows):
    """Stand in for the query endpoint with a fixed result set."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"results": rows}
    return resp


def test_gate_two_counts_instead_of_asking_someone_to_count(monkeypatch):
    """It used to print "PostHog, by hand" every morning to someone who was
    never going to run the query by hand - and was still printing it on the
    day two sign-ups turned out to have been refused."""
    from workers import green_report

    monkeypatch.setattr(green_report, "POSTHOG_PERSONAL_API_KEY", "phx_test")
    monkeypatch.setattr(green_report.httpx, "post", lambda *a, **k: _posthog([
        ["oauth_started", "", 10],
        ["login", "", 8],
        ["ms_auth_failed", "user", 1],
        ["ms_auth_failed", "microsoft", 1],
    ]))
    lines = green_report._signin_gate_lines()
    text = " | ".join(ln.text for ln in lines)
    assert "10 attempt(s), 8 completed (80%)" in text
    assert "1 user" in text and "1 microsoft" in text


def test_gate_two_only_raises_a_flag_for_losses_we_can_act_on(monkeypatch):
    """A consent decline is a person choosing. Marking it as a problem would
    train the reader to ignore the mark."""
    from workers import green_report

    monkeypatch.setattr(green_report, "POSTHOG_PERSONAL_API_KEY", "phx_test")
    monkeypatch.setattr(green_report.httpx, "post", lambda *a, **k: _posthog([
        ["oauth_started", "", 5],
        ["login", "", 3],
        ["ms_auth_failed", "user", 2],
    ]))
    lines = green_report._signin_gate_lines()
    ratio = [ln for ln in lines if "completed" in ln.text]
    assert ratio and ratio[0].mark == "ok", "user declines are not our incident"
    assert not any("our side of the line" in ln.text for ln in lines)


def test_gate_one_says_which_process_it_read():
    """Railway variables are per-service. A report that reads the beat's key
    and presents it as the answer is the confident wrongness this exists to
    catch — so the service is in the sentence."""
    lines = build(_db([_row()]), role="beat")
    gate = [ln for ln in lines if ln.text.startswith("beat:") or "no Stripe key on the beat" in ln.text]
    assert gate, [ln.text for ln in lines][:6]
    assert any("WEB service" in ln.text for ln in lines), (
        "it must point at the instrument that answers for web"
    )


# ── The two front-ends cannot drift ──


def test_freshness_canary_quiet_on_recent_activity():
    """A row touched within 24h keeps the canary informational."""
    now = datetime.now(timezone.utc)
    rows = [_row(), _row()]
    rows[0]["last_activity_at"] = (now - timedelta(hours=2)).isoformat()
    rows[1]["last_activity_at"] = (now - timedelta(days=9)).isoformat()

    lines = build(_db(rows))
    fresh = [l for l in lines if "freshest activity" in l.text]
    assert len(fresh) == 1
    assert fresh[0].mark == ""  # INFO
    assert "2.0h ago" in fresh[0].text
    assert "STALE" not in fresh[0].text


def test_freshness_canary_flags_a_stale_read():
    """When the NEWEST activity the read can see is older than a day, the
    canary flips to a warning — the 2026-08-17/18 morning reports described
    a ~17h-old world and nothing in them said so."""
    now = datetime.now(timezone.utc)
    rows = [_row()]
    rows[0]["last_activity_at"] = (now - timedelta(hours=40)).isoformat()

    lines = build(_db(rows))
    fresh = [l for l in lines if "freshest activity" in l.text]
    assert len(fresh) == 1
    assert fresh[0].mark == "check"
    assert "STALE" in fresh[0].text


def test_freshness_canary_survives_missing_timestamps():
    rows = [_row()]
    rows[0]["last_activity_at"] = None

    lines = build(_db(rows))
    assert any("no activity timestamps" in l.text for l in lines)


def test_rhythm_says_not_configured_without_a_key(monkeypatch):
    """Without a PostHog key the section must say so rather than vanish or
    crash the report.

    Forced empty rather than assumed: with a real key in the environment this
    test used to query production and fail on the live answer.
    """
    from workers import green_report

    monkeypatch.setattr(green_report, "POSTHOG_PERSONAL_API_KEY", "")
    lines = build(_db([_row()]))
    text = as_text(lines)
    assert "Rhythm" in text
    assert "check not configured" in text


def test_rhythm_computes_busiest_peak_and_quiet():
    """A fixture week with a loud Monday-evening band and dead small hours:
    the section must name Monday, put the 6h peak on the band, and put the
    4h deploy window on the only all-zero stretch (02:00-06:00)."""
    from workers import green_report

    rows = (
        [[1, h, 4] for h in (15, 16, 17, 18, 19, 20)]   # Monday band
        + [[2, h, 2] for h in (15, 16, 17, 18, 19, 20)]  # Tuesday echo
        + [[1, 6, 1], [1, 22, 1], [2, 7, 1], [2, 23, 1], [3, 8, 1],
           [3, 9, 1], [4, 10, 1], [4, 12, 1], [5, 11, 1], [5, 13, 1],
           [6, 0, 1], [6, 14, 1], [7, 1, 1], [7, 21, 1]]
    )
    with patch("workers.green_report.POSTHOG_PERSONAL_API_KEY", "phx"), \
         patch("workers.green_report.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200, json=lambda: {"results": rows}
        )
        lines = green_report._rhythm_lines()

    text = as_text(lines)
    assert "busiest: Monday" in text
    assert "peak: 15:00–21:00 TSİ" in text
    assert "quietest: 02:00–06:00 TSİ" in text
    # The query must exclude our own accounts and count only user-initiated
    # events — send_completed is the machine finishing, not a user present.
    q = post.call_args.kwargs["json"]["query"]["query"]
    assert "outmassapp@outlook.com" in q
    assert "send_clicked" in q
    assert "send_completed" not in q
    assert "INTERVAL 30 DAY" in q


def test_rhythm_survives_a_posthog_outage():
    from workers import green_report

    with patch("workers.green_report.POSTHOG_PERSONAL_API_KEY", "phx"), \
         patch("workers.green_report.httpx.post", side_effect=Exception("down")):
        lines = green_report._rhythm_lines()

    assert any("check unavailable" in ln.text for ln in lines)


def test_rhythm_with_no_activity_says_so():
    """Zero rows is 'nobody was here', which is information — not a peak
    at 00:00 computed over nothing (the empty-report lesson, again)."""
    from workers import green_report

    with patch("workers.green_report.POSTHOG_PERSONAL_API_KEY", "phx"), \
         patch("workers.green_report.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200, json=lambda: {"results": []}
        )
        lines = green_report._rhythm_lines()

    assert any("no user-initiated activity" in ln.text for ln in lines)
    assert not any("peak:" in ln.text for ln in lines)


def test_telegram_drops_the_prose_and_the_terminal_keeps_it():
    lines = [
        Line("head", "A section"),
        Line("ok", "a verdict"),
        Line("", "a paragraph of reasoning", detail=True),
    ]
    short, long = as_telegram(lines), as_text(lines)

    assert "a verdict" in short and "a verdict" in long
    assert "a paragraph of reasoning" in long
    assert "a paragraph of reasoning" not in short, (
        "Telegram caps at 4096 characters and is read on a phone"
    )


def test_the_telegram_form_stays_inside_telegram_s_limit():
    """Built from a deliberately large tenant so the check means something:
    a report that silently truncates is one you cannot trust the bottom of."""
    rows = [
        _row(email=f"user{i}@example.com", requires_reauth=bool(i % 3),
             stripe_subscription_id=f"sub_{i}" if i % 4 == 0 else None,
             emails_sent_this_month=250 if i % 5 == 0 else 3)
        for i in range(60)
    ]
    assert len(as_telegram(build(_db(rows)))) < 4096


def test_every_mark_has_an_icon():
    """A mark with no icon renders as a bare dot and silently loses its
    severity — the report would still 'work'."""
    lines = [Line(m, f"line {m}") for m in ("ok", "check", "FAIL", "")]
    out = as_telegram(lines)
    assert "✅" in out and "🟡" in out and "🔴" in out


def test_the_task_is_registered_with_celery():
    """A beat entry naming a task celery never imported fails at runtime, on
    a schedule, where nobody is watching."""
    from workers.celery_app import celery

    assert "workers.green_report" in celery.conf.include
    assert (
        celery.conf.beat_schedule["green-check"]["task"]
        == "workers.green_report.send_green_report"
    )
