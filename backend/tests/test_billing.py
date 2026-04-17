"""Billing router tests — checkout creation + subscription modification."""

from unittest.mock import patch, MagicMock

from tests.conftest import FAKE_USER, FAKE_STARTER_USER, FakeQueryBuilder


# ── Free user → new checkout session ──


def test_create_checkout_free_user_returns_url(client, fake_db):
    """A Free user gets a Stripe Checkout URL (new subscription)."""
    from routers.auth import get_current_user
    from main import app

    async def _override():
        return FAKE_USER  # plan = "free"

    fake_session = MagicMock(url="https://checkout.stripe.com/c/pay/cs_test_xxx")

    app.dependency_overrides[get_current_user] = _override
    try:
        with patch("routers.billing.STRIPE_SECRET_KEY", "sk_test_xxx"), \
             patch("routers.billing.STRIPE_STARTER_PRICE_ID", "price_starter_test"), \
             patch("routers.billing.stripe.checkout.Session.create", return_value=fake_session):
            resp = client.post("/billing/create-checkout", json={"plan": "starter"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    body = resp.json()
    assert "checkout_url" in body
    assert body["checkout_url"].startswith("https://checkout.stripe.com")


# ── Starter user → modify subscription with proration ──


def test_starter_user_upgrades_to_pro_via_modify(client, fake_db):
    """A Starter user upgrading to Pro should modify their existing subscription."""
    from routers.auth import get_current_user
    from main import app

    user_starter = {
        **FAKE_STARTER_USER,
        "stripe_subscription_id": "sub_test_existing_123",
    }

    async def _override():
        return user_starter

    fake_sub = {
        "id": "sub_test_existing_123",
        "status": "active",
        "items": {"data": [{"id": "si_test_456"}]},
    }

    modify_calls = []

    def fake_modify(sub_id, **kwargs):
        modify_calls.append({"sub_id": sub_id, **kwargs})
        return MagicMock()

    fake_db.set_table("users", FakeQueryBuilder([user_starter]))

    app.dependency_overrides[get_current_user] = _override
    try:
        with patch("routers.billing.STRIPE_SECRET_KEY", "sk_test_xxx"), \
             patch("routers.billing.STRIPE_PRO_PRICE_ID", "price_pro_test"), \
             patch("routers.billing.stripe.Subscription.retrieve", return_value=fake_sub), \
             patch("routers.billing.stripe.Subscription.modify", side_effect=fake_modify) as mock_modify:
            resp = client.post("/billing/create-checkout", json={"plan": "pro"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    body = resp.json()
    # Should NOT return a checkout URL — should signal modify happened
    assert body.get("modified") is True
    assert body.get("plan") == "pro"

    # Stripe.Subscription.modify should have been called with proration
    assert mock_modify.called
    call_kwargs = mock_modify.call_args.kwargs
    assert call_kwargs["proration_behavior"] == "create_prorations"
    assert call_kwargs["items"][0]["price"] == "price_pro_test"
    assert call_kwargs["items"][0]["id"] == "si_test_456"


def test_modify_uses_existing_subscription_item_id(client, fake_db):
    """The modify call should use the actual subscription item ID, not the sub ID."""
    from routers.auth import get_current_user
    from main import app

    user_starter = {
        **FAKE_STARTER_USER,
        "stripe_subscription_id": "sub_abc",
    }

    async def _override():
        return user_starter

    fake_sub = {
        "id": "sub_abc",
        "status": "active",
        "items": {"data": [{"id": "si_real_item_xyz"}]},
    }

    fake_db.set_table("users", FakeQueryBuilder([user_starter]))

    app.dependency_overrides[get_current_user] = _override
    try:
        with patch("routers.billing.STRIPE_SECRET_KEY", "sk_test_xxx"), \
             patch("routers.billing.STRIPE_PRO_PRICE_ID", "price_pro_test"), \
             patch("routers.billing.stripe.Subscription.retrieve", return_value=fake_sub), \
             patch("routers.billing.stripe.Subscription.modify") as mock_modify:
            client.post("/billing/create-checkout", json={"plan": "pro"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    items_passed = mock_modify.call_args.kwargs["items"]
    assert items_passed[0]["id"] == "si_real_item_xyz"


# ── Validation tests ──


def test_already_on_target_plan_returns_400(client, fake_db):
    """Trying to upgrade to your current plan should fail."""
    from routers.auth import get_current_user
    from main import app

    async def _override():
        return FAKE_STARTER_USER

    app.dependency_overrides[get_current_user] = _override
    try:
        with patch("routers.billing.STRIPE_SECRET_KEY", "sk_test_xxx"), \
             patch("routers.billing.STRIPE_STARTER_PRICE_ID", "price_starter_test"):
            resp = client.post("/billing/create-checkout", json={"plan": "starter"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 400


def test_pro_user_cannot_upgrade(client, fake_db):
    """Pro user trying to 'upgrade' should be blocked (no plan above Pro)."""
    from routers.auth import get_current_user
    from main import app

    pro_user = {**FAKE_USER, "plan": "pro"}

    async def _override():
        return pro_user

    app.dependency_overrides[get_current_user] = _override
    try:
        with patch("routers.billing.STRIPE_SECRET_KEY", "sk_test_xxx"), \
             patch("routers.billing.STRIPE_PRO_PRICE_ID", "price_pro_test"):
            resp = client.post("/billing/create-checkout", json={"plan": "pro"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 400


def test_canceled_subscription_falls_back_to_new_checkout(client, fake_db):
    """If existing subscription is canceled, treat user as new (not modify)."""
    from routers.auth import get_current_user
    from main import app

    user_with_canceled_sub = {
        **FAKE_USER,
        "plan": "free",  # Plan reset to free after cancel
        "stripe_subscription_id": "sub_canceled_old",
    }

    async def _override():
        return user_with_canceled_sub

    fake_canceled = {
        "id": "sub_canceled_old",
        "status": "canceled",
        "items": {"data": [{"id": "si_old"}]},
    }
    fake_session = MagicMock(url="https://checkout.stripe.com/c/pay/new_cs_xxx")

    app.dependency_overrides[get_current_user] = _override
    try:
        with patch("routers.billing.STRIPE_SECRET_KEY", "sk_test_xxx"), \
             patch("routers.billing.STRIPE_STARTER_PRICE_ID", "price_starter_test"), \
             patch("routers.billing.stripe.Subscription.retrieve", return_value=fake_canceled), \
             patch("routers.billing.stripe.Subscription.modify") as mock_modify, \
             patch("routers.billing.stripe.checkout.Session.create", return_value=fake_session):
            resp = client.post("/billing/create-checkout", json={"plan": "starter"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    # Should fall through to checkout, NOT modify
    assert "checkout_url" in resp.json()
    assert not mock_modify.called
