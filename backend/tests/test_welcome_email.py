"""Welcome email (first sign-in) tests.

New users used to get total silence after signup (only Stripe's receipt if
they paid — a paying customer literally asked "will I receive any other
confirmation?"). These lock in:

- upsert_user reports created=True only on first-ever sign-in.
- send_welcome_email: correct payload, never raises, skips without API key.
- The auth endpoint schedules the welcome exactly once (new users only).
"""

from unittest.mock import MagicMock, patch

from tests.conftest import FAKE_USER, FakeQueryBuilder


# ── upsert_user created flag ──


def test_upsert_returns_created_true_for_new_user(fake_db):
    from models.user import upsert_user

    fake_db.set_table("users", FakeQueryBuilder(data=[]))  # no existing row
    user, created = upsert_user("ms-new", "new@example.com", "New User")
    assert created is True
    assert user["email"] == "new@example.com"


def test_upsert_returns_created_false_for_existing_user(fake_db):
    from models.user import upsert_user

    fake_db.set_table("users", FakeQueryBuilder(data=[dict(FAKE_USER)]))
    _user, created = upsert_user("ms-test-123", "test@example.com", "Test User")
    assert created is False


# ── send_welcome_email ──


def test_send_welcome_skips_without_api_key():
    from utils import welcome_email

    with patch("utils.welcome_email.MAILERSEND_API_KEY", ""), \
         patch("utils.welcome_email.httpx.post") as post:
        assert welcome_email.send_welcome_email("x@y.com", "X") is False
        post.assert_not_called()


def test_send_welcome_payload_shape():
    from utils import welcome_email

    with patch("utils.welcome_email.MAILERSEND_API_KEY", "key"), \
         patch("utils.welcome_email.httpx.post") as post:
        post.return_value = MagicMock(status_code=202, text="")
        ok = welcome_email.send_welcome_email("mary@example.com", "Mary Bass")

    assert ok is True
    payload = post.call_args.kwargs["json"]
    assert payload["to"] == [{"email": "mary@example.com"}]
    assert payload["reply_to"]["email"] == "support@getoutmass.com"
    assert "Welcome" in payload["subject"]
    # Greeting uses the first name only
    assert "Hi Mary," in payload["text"]
    # The merge-tag example must survive as literal text
    assert "{{firstName}}" in payload["text"]


def test_send_welcome_never_raises():
    from utils import welcome_email

    with patch("utils.welcome_email.MAILERSEND_API_KEY", "key"), \
         patch("utils.welcome_email.httpx.post", side_effect=Exception("boom")):
        assert welcome_email.send_welcome_email("x@y.com", "X") is False


def test_first_name_fallback():
    from utils.welcome_email import _first_name

    assert _first_name("Mary Bass") == "Mary"
    assert _first_name(None) == "there"
    assert _first_name("   ") == "there"


# ── send_upgrade_email ──


def test_upgrade_email_starter_quota_and_label():
    from utils import welcome_email

    with patch("utils.welcome_email.MAILERSEND_API_KEY", "key"), \
         patch("utils.welcome_email.httpx.post") as post:
        post.return_value = MagicMock(status_code=202, text="")
        ok = welcome_email.send_upgrade_email("p@x.com", "Pay Er", "starter")

    assert ok is True
    payload = post.call_args.kwargs["json"]
    assert "Starter" in payload["subject"]
    assert "2,500" in payload["text"]


def test_upgrade_email_pro_quota_and_label():
    from utils import welcome_email

    with patch("utils.welcome_email.MAILERSEND_API_KEY", "key"), \
         patch("utils.welcome_email.httpx.post") as post:
        post.return_value = MagicMock(status_code=202, text="")
        welcome_email.send_upgrade_email("p@x.com", None, "pro")

    payload = post.call_args.kwargs["json"]
    assert "Pro" in payload["subject"]
    assert "10,000" in payload["text"]
    assert "Hi there," in payload["text"]  # missing name falls back


def test_quota_capped_email_content():
    from utils import welcome_email

    with patch("utils.welcome_email.MAILERSEND_API_KEY", "key"), \
         patch("utils.welcome_email.httpx.post") as post:
        post.return_value = MagicMock(status_code=202, text="")
        welcome_email.send_quota_capped_email(
            "f@x.com", "Faisal K", 250, 2500, "2026-07-25"
        )

    payload = post.call_args.kwargs["json"]
    assert "250 recipients saved" in payload["subject"]
    assert "automatically" in payload["text"]
    assert "July 25" in payload["text"]      # human-readable reset date
    assert "2,500" in payload["text"]        # formatted limit
    assert "Hi Faisal," in payload["text"]
    assert "nothing you need to do" in payload["text"]


def test_quota_capped_email_survives_missing_reset_date():
    from utils import welcome_email

    with patch("utils.welcome_email.MAILERSEND_API_KEY", "key"), \
         patch("utils.welcome_email.httpx.post") as post:
        post.return_value = MagicMock(status_code=202, text="")
        welcome_email.send_quota_capped_email("f@x.com", None, 10, 250, None)

    payload = post.call_args.kwargs["json"]
    assert "when your monthly quota resets" in payload["text"]
    assert "Hi there," in payload["text"]


# ── webhook wiring: upgrade email once, replay-guarded ──


def _post_checkout(client, users_tbl, subscription):
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {"user_id": "u-42"},
                "customer": "cus_x",
                "subscription": subscription,
            }
        },
    }
    fake_sub = {"items": {"data": [{"price": {"id": "price_whatever"}}]}}
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.stripe.Subscription.retrieve", return_value=fake_sub), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing.welcome_email.send_upgrade_email") as send:
        resp = client.post(
            "/billing/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig"},
        )
    return resp, send


def test_first_checkout_sends_upgrade_email(client, fake_db):
    users_tbl = FakeQueryBuilder(
        data=[{"id": "u-42", "email": "payer@x.com", "name": "Pay Er"}]
    )  # no stored subscription id → first processing
    fake_db.set_table("users", users_tbl)

    resp, send = _post_checkout(client, users_tbl, subscription="sub_new")

    assert resp.status_code == 200
    send.assert_called_once_with("payer@x.com", "Pay Er", "pro")


def test_checkout_replay_does_not_resend_upgrade_email(client, fake_db):
    users_tbl = FakeQueryBuilder(
        data=[{
            "id": "u-42",
            "email": "payer@x.com",
            "stripe_subscription_id": "sub_dup",
        }]
    )
    fake_db.set_table("users", users_tbl)

    resp, send = _post_checkout(client, users_tbl, subscription="sub_dup")

    assert resp.status_code == 200
    send.assert_not_called()


# ── endpoint wiring: welcome scheduled exactly once, for NEW users only ──


class _FakeAsyncClient:
    """Async-context httpx.AsyncClient stub returning a fixed Graph /me."""

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **kw):
        return MagicMock(
            status_code=200,
            json=lambda: {
                "id": "ms-test-123",
                "mail": "test@example.com",
                "displayName": "Test User",
            },
        )


def _post_auth(client, created):
    with patch("routers.auth.httpx.AsyncClient", _FakeAsyncClient), \
         patch(
             "routers.auth.user_model.upsert_user",
             return_value=(dict(FAKE_USER), created),
         ), \
         patch("routers.auth.welcome_email.send_welcome_email") as send:
        resp = client.post(
            "/auth/microsoft",
            json={
                "access_token": "tok",
                "microsoft_id": "ms-test-123",
                "email": "test@example.com",
                "name": "Test User",
            },
        )
    return resp, send


def test_new_user_gets_welcome_email(client, fake_db):
    resp, send = _post_auth(client, created=True)
    assert resp.status_code == 200
    send.assert_called_once_with("test@example.com", "Test User")


def test_existing_user_gets_no_welcome_email(client, fake_db):
    resp, send = _post_auth(client, created=False)
    assert resp.status_code == 200
    send.assert_not_called()
