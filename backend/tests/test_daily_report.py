"""Daily report worker tests.

Tests the message formatting and delivery logic without hitting
the real Telegram API or a real database.
"""

from unittest.mock import patch, MagicMock

from tests.conftest import FakeQueryBuilder


# ── Helper: builds a minimal fake DB shape for the report ──


def _setup_fake_db(
    fake_db,
    total_users=247,
    new_today=12,
    free=210,
    starter=28,
    pro=9,
    paying_starter=None,
    paying_pro=None,
    gifts=0,
    new_paid=0,
    emails_sent=1847,
    opens=743,
    clicks=128,
):
    """Wire up fake_db tables so the report queries return expected counts.

    paying_* default to the plan-column counts (everyone pays) so the older
    tests keep their expectations; set them lower to model gift/comp rows.
    """
    if paying_starter is None:
        paying_starter = starter
    if paying_pro is None:
        paying_pro = pro

    # users table: the report runs several differently-filtered selects on the
    # same table, so this stateful builder decodes the filter chain (.eq plan /
    # .not_.is_ sub-id / .in_ plans / .gte dates) and returns matching counts.
    class UsersBuilder(FakeQueryBuilder):
        def __init__(self):
            super().__init__([])
            self._reset()

        def _reset(self):
            self._plan_filter = None
            self._after_filter = None
            self._paid_after = None
            self._plans = None
            self._sub = None
            self._negate = False

        @property
        def not_(self):
            self._negate = True
            return self

        def is_(self, field, value):
            if field == "stripe_subscription_id":
                self._sub = "not_null" if self._negate else "null"
            self._negate = False
            return self

        def in_(self, field, values):
            if field == "plan":
                self._plans = list(values)
            return self

        def eq(self, field, value):
            if field == "plan":
                self._plan_filter = value
            return self

        def gte(self, field, value):
            if field == "created_at":
                self._after_filter = value
            if field == "plan_updated_at":
                self._paid_after = value
            return self

        def _rows(self, prefix, n):
            return [
                {"id": f"{prefix}-{i}", "email": f"{prefix}-{i}@x.com"}
                for i in range(n)
            ]

        def execute(self):
            if self._sub == "not_null":
                if self._plan_filter == "starter":
                    data = self._rows("u-paystarter", paying_starter)
                elif self._plan_filter == "pro":
                    data = self._rows("u-paypro", paying_pro)
                elif self._plans and self._paid_after:
                    data = self._rows("u-newpaid", new_paid)
                else:
                    data = []
            elif self._sub == "null" and self._plans:
                data = self._rows("u-gift", gifts)
            elif self._plan_filter == "free":
                data = self._rows("u-free", free)
            elif self._plan_filter == "starter":
                data = self._rows("u-starter", starter)
            elif self._plan_filter == "pro":
                data = self._rows("u-pro", pro)
            elif self._after_filter:
                data = self._rows("u-new", new_today)
            else:
                data = self._rows("u", total_users)
            self._reset()
            return MagicMock(data=data, count=len(data))

    class EventsBuilder(FakeQueryBuilder):
        def __init__(self):
            super().__init__([])
            self._event_type = None

        def eq(self, field, value):
            if field == "event_type":
                self._event_type = value
            return self

        def gte(self, field, value):
            return self

        def execute(self):
            counts = {"sent": emails_sent, "open": opens, "click": clicks}
            n = counts.get(self._event_type, 0)
            data = [{"id": f"e-{i}"} for i in range(n)]
            self._event_type = None
            return MagicMock(data=data, count=len(data))

    fake_db.set_table("users", UsersBuilder())
    fake_db.set_table("events", EventsBuilder())


# ── Tests ──


def test_build_report_includes_user_totals(fake_db):
    """Report should show total users and today's signups."""
    _setup_fake_db(fake_db, total_users=247, new_today=12)

    from workers.daily_report import build_report
    msg = build_report()

    assert "247" in msg  # total users
    assert "+12" in msg  # new today


def test_build_report_includes_plan_breakdown(fake_db):
    """Report should show Free / Starter / Pro counts."""
    _setup_fake_db(fake_db, free=210, starter=28, pro=9)

    from workers.daily_report import build_report
    msg = build_report()

    assert "210" in msg  # free count
    assert "28" in msg  # starter
    assert "9" in msg  # pro


def test_build_report_calculates_mrr(fake_db):
    """MRR = starter × $9 + pro × $19."""
    _setup_fake_db(fake_db, starter=28, pro=9)
    # MRR = 28*9 + 9*19 = 252 + 171 = 423

    from workers.daily_report import build_report
    msg = build_report()

    assert "$423" in msg


def test_build_report_mrr_zero_when_no_paid_users(fake_db):
    """MRR should be $0 when everyone is on free plan."""
    _setup_fake_db(fake_db, free=100, starter=0, pro=0)

    from workers.daily_report import build_report
    msg = build_report()

    assert "$0" in msg


def test_build_report_includes_email_activity(fake_db):
    """Report should show today's emails sent / opens / clicks."""
    _setup_fake_db(fake_db, emails_sent=1847, opens=743, clicks=128)

    from workers.daily_report import build_report
    msg = build_report()

    assert "1847" in msg or "1,847" in msg
    assert "743" in msg
    assert "128" in msg


def test_build_report_calculates_open_rate(fake_db):
    """Open rate = opens / sent × 100, rounded to 1 decimal."""
    _setup_fake_db(fake_db, emails_sent=1000, opens=400, clicks=50)
    # Open rate = 40.0%, click rate = 5.0%

    from workers.daily_report import build_report
    msg = build_report()

    assert "40.0%" in msg
    assert "5.0%" in msg


def test_build_report_handles_zero_sent(fake_db):
    """When no emails sent today, open/click rates should not divide by zero."""
    _setup_fake_db(fake_db, emails_sent=0, opens=0, clicks=0)

    from workers.daily_report import build_report
    msg = build_report()

    # Should not crash, and should show 0 or N/A
    assert "0" in msg


def test_send_daily_report_posts_to_telegram(fake_db):
    """send_daily_report should POST to Telegram Bot API when configured."""
    _setup_fake_db(fake_db)

    with patch("workers.daily_report.TELEGRAM_BOT_TOKEN", "fake-token-123"), \
         patch("workers.daily_report.TELEGRAM_CHAT_ID", "fake-chat-456"), \
         patch("workers.daily_report.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)

        from workers.daily_report import send_daily_report
        send_daily_report()

    assert mock_post.called
    call_args = mock_post.call_args
    url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "api.telegram.org/bot" in url
    assert "fake-token-123" in url
    assert "sendMessage" in url

    # Check payload has chat_id and text
    data = call_args[1].get("data") or call_args[1].get("json") or {}
    assert data.get("chat_id") == "fake-chat-456"
    assert "text" in data


def test_send_daily_report_skips_when_not_configured(fake_db):
    """Without Telegram credentials, should skip gracefully (not crash)."""
    _setup_fake_db(fake_db)

    with patch("workers.daily_report.TELEGRAM_BOT_TOKEN", ""), \
         patch("workers.daily_report.TELEGRAM_CHAT_ID", ""), \
         patch("workers.daily_report.httpx.post") as mock_post:

        from workers.daily_report import send_daily_report
        result = send_daily_report()

    assert not mock_post.called
    assert result == "skipped"  # or similar marker


def test_send_daily_report_survives_telegram_error(fake_db):
    """If Telegram API returns error, task should log and not crash."""
    _setup_fake_db(fake_db)

    with patch("workers.daily_report.TELEGRAM_BOT_TOKEN", "tok"), \
         patch("workers.daily_report.TELEGRAM_CHAT_ID", "chat"), \
         patch("workers.daily_report.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=500, text="Server Error")

        from workers.daily_report import send_daily_report
        # Should not raise
        send_daily_report()


# ── MRR counts PAYING subscribers only (gifts/comp excluded) ──


def test_mrr_counts_only_paying_subscribers(fake_db):
    """THE Ali regression: plan column said 4 starter + 4 pro, but only 3
    starters actually pay (rest = gifts/own accounts). MRR must be 3 × $9."""
    _setup_fake_db(
        fake_db,
        starter=4, paying_starter=3,
        pro=4, paying_pro=0,
        gifts=5,
    )

    from workers.daily_report import build_report
    msg = build_report()

    assert "MRR: $27/mo" in msg
    assert "Starter: 3 × $9 = $27" in msg
    assert "Pro: 0 × $19 = $0" in msg
    assert "Gifts/comp active: 5" in msg


def test_mrr_excludes_owner_accounts(fake_db):
    """Rows whose email is in REPORT_OWNER_EMAILS never count as paying."""
    _setup_fake_db(fake_db, starter=3, paying_starter=3, pro=0, paying_pro=0)

    with patch(
        "workers.daily_report.REPORT_OWNER_EMAILS", ["u-paystarter-0@x.com"]
    ):
        from workers.daily_report import build_report
        msg = build_report()

    assert "Starter: 2 × $9 = $18" in msg
    assert "MRR: $18/mo" in msg


# ── 12h error check (PostHog) + health line ──


def test_report_says_error_check_not_configured_by_default(fake_db):
    """Without a PostHog key (the test env), the report still builds and says
    the check isn't configured — and makes no network call."""
    _setup_fake_db(fake_db)

    from workers.daily_report import build_report
    msg = build_report()

    assert "Errors (12h): check not configured" in msg


def test_error_check_clean_window():
    from workers import daily_report

    with patch("workers.daily_report.POSTHOG_PERSONAL_API_KEY", "phx"), \
         patch("workers.daily_report.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200, json=lambda: {"results": []}
        )
        lines = daily_report._error_check_lines()

    assert lines == ["🩺 Errors (12h): ✅ none"]
    # The HogQL must scan the 12h window and the failure-class events
    q = post.call_args.kwargs["json"]["query"]["query"]
    assert "INTERVAL 12 HOUR" in q
    assert "send_failed" in q and "$exception" in q


def test_error_check_flags_hard_errors_and_marks_info():
    from workers import daily_report

    rows = [["send_failed", 0, 2, 1], ["oauth_failed", 0, 3, 2]]
    with patch("workers.daily_report.POSTHOG_PERSONAL_API_KEY", "phx"), \
         patch("workers.daily_report.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200, json=lambda: {"results": rows}
        )
        lines = daily_report._error_check_lines()

    assert lines[0] == "🩺 Errors (12h): ⚠️"
    assert "send_failed ×2 (1 user)" in lines[1]
    assert "oauth_failed ×3 (2 users) (info)" in lines[2]


def test_error_check_soft_only_is_not_alarming():
    from workers import daily_report

    rows = [["oauth_failed", 1, 1, 1]]
    with patch("workers.daily_report.POSTHOG_PERSONAL_API_KEY", "phx"), \
         patch("workers.daily_report.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200, json=lambda: {"results": rows}
        )
        lines = daily_report._error_check_lines()

    assert lines[0] == "🩺 Errors (12h): ✅ no hard errors"


def test_error_check_paywall_codes_are_info_not_hard():
    """A free user tapping a locked feature emits e.g. send_failed with
    error_code=feature_locked_scheduled_sending. That's working-as-
    designed — it must render as info·paywall and must NOT flip the ⚠️
    flag (bellmed 07-14 / hrcargo 07-17 false alarms)."""
    from workers import daily_report

    rows = [
        ["send_failed", 1, 1, 1],              # paywall touch
        ["ai_email_generate_failed", 1, 1, 1], # paywall touch
    ]
    with patch("workers.daily_report.POSTHOG_PERSONAL_API_KEY", "phx"), \
         patch("workers.daily_report.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200, json=lambda: {"results": rows}
        )
        lines = daily_report._error_check_lines()

    assert lines[0] == "🩺 Errors (12h): ✅ no hard errors"
    assert "(info · paywall)" in lines[1]
    assert "(info · paywall)" in lines[2]


def test_error_check_mixed_paywall_and_real_failures():
    """The same event name can carry both paywall and real rows — the
    real one must still raise ⚠️ and render without the info suffix."""
    from workers import daily_report

    rows = [
        ["send_failed", 0, 2, 1],  # real failures
        ["send_failed", 1, 1, 1],  # paywall touch
    ]
    with patch("workers.daily_report.POSTHOG_PERSONAL_API_KEY", "phx"), \
         patch("workers.daily_report.httpx.post") as post:
        post.return_value = MagicMock(
            status_code=200, json=lambda: {"results": rows}
        )
        lines = daily_report._error_check_lines()

    assert lines[0] == "🩺 Errors (12h): ⚠️"
    assert "send_failed ×2 (1 user)" in lines[1]
    assert lines[1].endswith("(1 user)")
    assert "(info · paywall)" in lines[2]


def test_error_check_survives_posthog_outage():
    from workers import daily_report

    with patch("workers.daily_report.POSTHOG_PERSONAL_API_KEY", "phx"), \
         patch("workers.daily_report.httpx.post", side_effect=Exception("down")):
        lines = daily_report._error_check_lines()

    assert lines == ["🩺 Errors (12h): check unavailable"]


def test_health_line_up_and_down():
    from workers import daily_report

    with patch("workers.daily_report.REPORT_HEALTH_URL", "https://x/"), \
         patch("workers.daily_report.httpx.get") as get:
        get.return_value = MagicMock(status_code=200)
        assert daily_report._health_line() == ["🌐 API: ✅ up"]

    with patch("workers.daily_report.REPORT_HEALTH_URL", "https://x/"), \
         patch("workers.daily_report.httpx.get", side_effect=Exception("net")):
        assert daily_report._health_line() == ["🌐 API: 🔴 unreachable"]

    # Not configured → omitted entirely
    assert daily_report._health_line() == []
