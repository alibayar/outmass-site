"""An operator alert that cannot be sent must not disappear quietly.

On 2026-07-29/30 three payment-failure alerts were never delivered while the
twice-daily reports kept arriving on schedule. The reports are sent by the
WORKER service and the alerts by the WEB service, and Railway gives each
service its own environment — so TELEGRAM_* can be present on one and absent
on the other. `_telegram_alert` returned silently in that case, and the loss
was only discovered by comparing the Stripe dashboard against Telegram by
hand, days later and after a sale had already expired.

Two guards: the dropped alert is logged, and the report asks the web service
whether it can alert at all.
"""
from unittest.mock import MagicMock, patch

from workers.daily_report import _health_line


# ── a dropped alert is loud ──


def test_missing_config_logs_the_undelivered_alert(caplog):
    from routers import billing

    with patch("config.TELEGRAM_BOT_TOKEN", ""), \
         patch("config.TELEGRAM_CHAT_ID", ""), \
         caplog.at_level("ERROR"):
        billing._telegram_alert("⚠️ payment failed for someone important")

    assert "OPERATOR ALERT DROPPED" in caplog.text
    # The alert body must survive into the log, so it stays recoverable.
    assert "payment failed for someone important" in caplog.text


def test_configured_channel_posts_and_logs_nothing(caplog):
    from routers import billing

    with patch("config.TELEGRAM_BOT_TOKEN", "tok"), \
         patch("config.TELEGRAM_CHAT_ID", "chat"), \
         patch("httpx.post") as post, \
         caplog.at_level("ERROR"):
        billing._telegram_alert("hello")

    post.assert_called_once()
    assert "OPERATOR ALERT DROPPED" not in caplog.text


# ── the report surfaces a dead alert channel ──


def _health(json_body, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_body
    with patch("workers.daily_report.REPORT_HEALTH_URL", "https://api.example/"), \
         patch("workers.daily_report.httpx.get", return_value=resp):
        return _health_line()


def test_report_flags_a_web_service_that_cannot_alert():
    lines = _health({"status": "ok", "alerts": False})

    assert any("ALERTS OFF" in line for line in lines)
    assert any("TELEGRAM_BOT_TOKEN" in line for line in lines), (
        "the report has to say what to set, not just that something is wrong"
    )


def test_report_stays_quiet_when_alerts_work():
    lines = _health({"status": "ok", "alerts": True})

    assert lines == ["🌐 API: ✅ up"]


def test_report_does_not_invent_a_fault_on_older_deploys():
    """A web build predating the `alerts` field must not read as broken."""
    lines = _health({"status": "ok", "version": "0.1.0"})

    assert lines == ["🌐 API: ✅ up"]


def test_unparseable_health_body_is_not_a_fault():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = ValueError("not json")
    with patch("workers.daily_report.REPORT_HEALTH_URL", "https://api.example/"), \
         patch("workers.daily_report.httpx.get", return_value=resp):
        assert _health_line() == ["🌐 API: ✅ up"]


def test_health_endpoint_reports_alert_capability(client):
    with patch("main.TELEGRAM_BOT_TOKEN", "tok"), patch("main.TELEGRAM_CHAT_ID", "chat"):
        assert client.get("/").json()["alerts"] is True

    with patch("main.TELEGRAM_BOT_TOKEN", ""), patch("main.TELEGRAM_CHAT_ID", ""):
        assert client.get("/").json()["alerts"] is False
