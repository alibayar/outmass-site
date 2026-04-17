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
    emails_sent=1847,
    opens=743,
    clicks=128,
):
    """Wire up fake_db tables so the report queries return expected counts."""
    # users table: we use multiple selects with .eq(plan, ...) so
    # counts come from len(data). We set up different builders per context
    # by using a stateful wrapper that tracks .eq() calls.

    class UsersBuilder(FakeQueryBuilder):
        def __init__(self):
            super().__init__([])
            self._plan_filter = None
            self._after_filter = None

        def eq(self, field, value):
            if field == "plan":
                self._plan_filter = value
            return self

        def gte(self, field, value):
            if field == "created_at":
                self._after_filter = value
            return self

        def execute(self):
            if self._plan_filter == "free":
                data = [{"id": f"u-free-{i}"} for i in range(free)]
            elif self._plan_filter == "starter":
                data = [{"id": f"u-starter-{i}"} for i in range(starter)]
            elif self._plan_filter == "pro":
                data = [{"id": f"u-pro-{i}"} for i in range(pro)]
            elif self._after_filter:
                data = [{"id": f"u-new-{i}"} for i in range(new_today)]
            else:
                data = [{"id": f"u-{i}"} for i in range(total_users)]
            # Reset so same builder can be reused
            self._plan_filter = None
            self._after_filter = None
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
