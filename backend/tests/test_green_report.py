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
