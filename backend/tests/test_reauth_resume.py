"""Reconnecting must put back the work a dead token took away.

Until 2026-08-11 it did not. scheduled_worker marks a campaign 'failed_auth'
when the refresh token is permanently dead, get_due_scheduled_campaigns
selects status='scheduled', and nothing anywhere read 'failed_auth' back —
two writes, zero reads across backend/ and extension/. So the campaign left
the queue for ever, its recipients never heard from the customer, and the
reconnect email told them it had merely "paused".

No production rows carried 'failed_auth' when this was found, so it was a
trap rather than live damage. The users whose tokens have died simply had
nothing queued at the time.

The fake table below filters for real. The shared FakeQueryBuilder returns
`self` from .eq(), which would make "resumed the right row" and "resumed
every row in the database" look identical — the exact distinction these
tests exist to draw.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from utils import reauth_resume


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class _FilteringTable:
    """A Supabase-ish table that actually honours .eq()."""

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.updates = []          # (values, filters) per executed update
        self._filters = []
        self._update = None

    def select(self, *a, **kw):
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def update(self, vals):
        self._update = dict(vals)
        return self

    def execute(self):
        filters, self._filters = self._filters, []
        if self._update is not None:
            vals, self._update = self._update, None
            self.updates.append((vals, filters))
            for r in self.rows:
                if all(r.get(c) == v for c, v in filters):
                    r.update(vals)
            return SimpleNamespace(data=[])
        matched = [
            r for r in self.rows if all(r.get(c) == v for c, v in filters)
        ]
        return SimpleNamespace(data=matched)


class _DB:
    def __init__(self, **tables):
        self.tables = tables

    def table(self, name):
        return self.tables.setdefault(name, _FilteringTable([]))


@pytest.fixture()
def alert():
    with patch("routers.billing._telegram_alert") as a:
        yield a


def _run(db, user_id="u-1"):
    with patch("database.get_db", return_value=db):
        return reauth_resume.resume_auth_stranded_work(user_id)


# ── The regression ──


def test_a_recent_stranded_campaign_goes_back_in_the_queue(alert):
    campaigns = _FilteringTable([
        {"id": "c1", "user_id": "u-1", "status": "failed_auth",
         "scheduled_for": _iso(2)},
    ])
    db = _DB(campaigns=campaigns, follow_ups=_FilteringTable([]))

    result = _run(db)

    assert result["campaigns"] == 1
    assert campaigns.rows[0]["status"] == "scheduled"
    alert.assert_not_called()


def test_follow_ups_are_recovered_the_same_way(alert):
    follow_ups = _FilteringTable([
        {"id": "f1", "user_id": "u-1", "status": "failed_auth",
         "scheduled_for": _iso(1)},
    ])
    db = _DB(campaigns=_FilteringTable([]), follow_ups=follow_ups)

    result = _run(db)

    assert result["followups"] == 1
    assert follow_ups.rows[0]["status"] == "scheduled"


# ── The bound ──


def test_an_old_stranded_campaign_is_left_alone_and_reported(alert):
    """The hazard the codebase already named in _capped_in_last_quota_cycle:
    a months-old abandoned send must not resurrect itself into a stale list.
    Left alone, but NOT silently — silence is the failure this whole module
    exists to fix."""
    campaigns = _FilteringTable([
        {"id": "c-old", "user_id": "u-1", "status": "failed_auth",
         "scheduled_for": _iso(60)},
    ])
    db = _DB(campaigns=campaigns, follow_ups=_FilteringTable([]))

    result = _run(db)

    assert result["campaigns"] == 0
    assert result["skipped_old"] == 1
    assert campaigns.rows[0]["status"] == "failed_auth"
    alert.assert_called_once()
    assert "c-old" in alert.call_args.args[0]


def test_a_row_with_no_schedule_is_treated_as_too_old(alert):
    """We cannot tell when it was meant to run, and guessing toward SENDING
    is the wrong guess — the cost of a wrong send is a stale blast to real
    recipients; the cost of a wrong skip is an operator alert."""
    campaigns = _FilteringTable([
        {"id": "c-null", "user_id": "u-1", "status": "failed_auth",
         "scheduled_for": None},
    ])
    db = _DB(campaigns=campaigns, follow_ups=_FilteringTable([]))

    result = _run(db)

    assert result["campaigns"] == 0
    assert result["skipped_old"] == 1
    assert campaigns.rows[0]["status"] == "failed_auth"


def test_the_window_is_read_from_config(alert):
    """A campaign 30 days stale resumes only if the operator widened the
    window — pinning this stops the bound quietly becoming decorative."""
    campaigns = _FilteringTable([
        {"id": "c30", "user_id": "u-1", "status": "failed_auth",
         "scheduled_for": _iso(30)},
    ])
    db = _DB(campaigns=campaigns, follow_ups=_FilteringTable([]))

    with patch.object(reauth_resume, "AUTH_RESUME_MAX_AGE_DAYS", 45):
        result = _run(db)

    assert result["campaigns"] == 1


# ── Multi-day campaigns ──


def test_a_multi_day_campaign_is_judged_on_its_rolled_schedule(alert):
    """A daily-capped campaign rewrites scheduled_for to +24h after every
    batch, so its scheduled_for is the day it was last ALIVE, not the day it
    was created. A month-long drip stranded yesterday must resume; measuring
    from a creation date would wrongly abandon it."""
    campaigns = _FilteringTable([
        {"id": "c-drip", "user_id": "u-1", "status": "failed_auth",
         "scheduled_for": _iso(1), "daily_send_cap": 50,
         "created_at": _iso(40)},
    ])
    db = _DB(campaigns=campaigns, follow_ups=_FilteringTable([]))

    result = _run(db)

    assert result["campaigns"] == 1
    assert campaigns.rows[0]["status"] == "scheduled"


def test_resuming_never_touches_the_daily_cap_or_the_schedule(alert):
    """Resumption puts the campaign back in the queue and nothing else. The
    worker re-applies daily_send_cap on every run, so a multi-day campaign
    continues at its own rate instead of dumping the backlog in one blast —
    but only while this stays a status-only write."""
    campaigns = _FilteringTable([
        {"id": "c-drip", "user_id": "u-1", "status": "failed_auth",
         "scheduled_for": _iso(3), "daily_send_cap": 50},
    ])
    db = _DB(campaigns=campaigns, follow_ups=_FilteringTable([]))

    _run(db)

    written = [vals for vals, _ in campaigns.updates]
    assert written == [{"status": "scheduled"}], (
        f"resumption wrote more than the status: {written}"
    )
    assert campaigns.rows[0]["daily_send_cap"] == 50


# ── Blast radius ──


def test_only_this_user_and_only_stranded_rows_are_touched(alert):
    campaigns = _FilteringTable([
        {"id": "mine", "user_id": "u-1", "status": "failed_auth",
         "scheduled_for": _iso(1)},
        {"id": "theirs", "user_id": "u-2", "status": "failed_auth",
         "scheduled_for": _iso(1)},
        {"id": "draft", "user_id": "u-1", "status": "draft",
         "scheduled_for": _iso(1)},
        {"id": "done", "user_id": "u-1", "status": "sent",
         "scheduled_for": _iso(1)},
    ])
    db = _DB(campaigns=campaigns, follow_ups=_FilteringTable([]))

    result = _run(db)

    assert result["campaigns"] == 1
    by_id = {r["id"]: r["status"] for r in campaigns.rows}
    assert by_id == {"mine": "scheduled", "theirs": "failed_auth",
                     "draft": "draft", "done": "sent"}


# ── It must never break a sign-in ──


def test_a_database_failure_cannot_break_the_reconnect(alert):
    """A sign-in that fails is strictly worse than a campaign that stays
    paused. Both call sites are inside the reconnect path."""
    class _Exploding:
        def table(self, _name):
            raise RuntimeError("supabase down")

    assert _run(_Exploding()) == {
        "campaigns": 0, "followups": 0, "skipped_old": 0
    }


def test_a_failing_alert_channel_cannot_break_it_either():
    campaigns = _FilteringTable([
        {"id": "c-old", "user_id": "u-1", "status": "failed_auth",
         "scheduled_for": _iso(90)},
    ])
    db = _DB(campaigns=campaigns, follow_ups=_FilteringTable([]))

    with patch("routers.billing._telegram_alert",
               side_effect=RuntimeError("telegram down")):
        result = _run(db)

    assert result["skipped_old"] == 1


def test_no_user_id_is_a_no_op(alert):
    assert _run(_DB(), user_id="") == {
        "campaigns": 0, "followups": 0, "skipped_old": 0
    }


# ── Wired into both reconnect paths ──


def test_both_reconnect_paths_call_it():
    """auth.py clears requires_reauth in TWO places — the web callback and
    the SPA token exchange. Clearing the flag in one and resuming in the
    other would leave half the users stranded, which is the shape of bug
    this codebase keeps finding (see the Railway per-service env vars)."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "routers" / "auth.py").read_text(
        encoding="utf-8"
    )
    calls = [
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "resume_auth_stranded_work"
    ]
    assert len(calls) == 2, (
        f"expected the resume call in both reconnect paths, found {len(calls)}"
    )
