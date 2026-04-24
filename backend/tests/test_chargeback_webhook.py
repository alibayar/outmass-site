"""Stripe chargeback webhook tests.

When Stripe delivers charge.dispute.created, our handler must:
  1. Resolve the charge → customer → user row
  2. Cancel the subscription in Stripe (if one exists)
  3. Drop the user's plan to free in our DB
  4. Write an audit_log row tagged reason=chargeback
  5. Ping Telegram so the operator sees it immediately

charge.dispute.closed just logs + alerts; we do NOT auto-restore plan.
"""
from unittest.mock import MagicMock, patch

from tests.conftest import FakeQueryBuilder


def _dispute_event(dispute: dict) -> dict:
    return {
        "type": "charge.dispute.created",
        "data": {"object": dispute},
    }


def _dispute_closed_event(dispute: dict) -> dict:
    return {
        "type": "charge.dispute.closed",
        "data": {"object": dispute},
    }


class _RecordingUsers(FakeQueryBuilder):
    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(vals)
        return super().update(vals)


def _stub_charge_to_customer(customer_id: str):
    """Mock stripe.Charge.retrieve to return {"customer": customer_id}."""
    def fake_retrieve(charge_id):
        return {"customer": customer_id}
    return fake_retrieve


# ── dispute.created ──


def test_dispute_created_cancels_subscription_and_downgrades(fake_db):
    from routers import billing

    users = _RecordingUsers(rows=[{
        "id": "u-disputer",
        "email": "disputer@example.com",
        "stripe_subscription_id": "sub_abc",
        "plan": "pro",
    }])
    fake_db.set_table("users", users)

    dispute = {
        "id": "dp_123",
        "charge": "ch_xyz",
        "customer": "cus_abc",
        "amount": 1900,
        "reason": "fraudulent",
    }

    with patch("stripe.Charge.retrieve", side_effect=_stub_charge_to_customer("cus_abc")), \
         patch("stripe.Subscription.delete") as mock_cancel, \
         patch("routers.billing._telegram_alert") as mock_alert:
        billing._handle_dispute_created(fake_db, dispute)

    # Stripe cancel was attempted with the right sub id
    mock_cancel.assert_called_once_with("sub_abc")

    # User row downgraded
    plan_updates = [u for u in users.update_calls if u.get("plan") == "free"]
    assert len(plan_updates) == 1
    # stripe_subscription_id cleared
    assert plan_updates[0].get("stripe_subscription_id") is None

    # Operator was alerted
    mock_alert.assert_called_once()
    alert_text = mock_alert.call_args.args[0]
    assert "CHARGEBACK" in alert_text.upper()
    assert "dp_123" in alert_text


def test_dispute_created_emits_audit_event(fake_db):
    from routers import billing

    fake_db.set_table("users", FakeQueryBuilder(data=[{
        "id": "u1",
        "email": "u1@example.com",
        "stripe_subscription_id": "sub_x",
        "plan": "starter",
    }]))

    with patch("stripe.Charge.retrieve", side_effect=_stub_charge_to_customer("cus_x")), \
         patch("stripe.Subscription.delete"), \
         patch("routers.billing._telegram_alert"), \
         patch("models.audit.emit") as mock_emit:
        billing._handle_dispute_created(fake_db, {
            "id": "dp_aud",
            "charge": "ch_a",
            "amount": 900,
            "reason": "product_not_received",
        })

    mock_emit.assert_called_once()
    event_type, kwargs = mock_emit.call_args.args[0], mock_emit.call_args.kwargs
    assert event_type == "subscription_canceled"
    meta = kwargs["metadata"]
    assert meta["reason"] == "chargeback"
    assert meta["dispute_id"] == "dp_aud"
    assert meta["dispute_reason"] == "product_not_received"
    assert meta["amount"] == 900


def test_dispute_created_handles_missing_user_gracefully(fake_db):
    """Dispute for a charge we don't recognise shouldn't 500. We still
    alert the operator so they can investigate manually."""
    from routers import billing

    fake_db.set_table("users", FakeQueryBuilder(data=[]))  # no matching user

    with patch("stripe.Charge.retrieve", side_effect=_stub_charge_to_customer("cus_ghost")), \
         patch("stripe.Subscription.delete") as mock_cancel, \
         patch("routers.billing._telegram_alert") as mock_alert:
        billing._handle_dispute_created(fake_db, {
            "id": "dp_ghost",
            "charge": "ch_ghost",
            "amount": 100,
            "reason": "unrecognized",
        })

    # No subscription cancel since we couldn't find the user
    mock_cancel.assert_not_called()
    # Operator still pinged so they can trace it
    mock_alert.assert_called_once()
    assert "unresolved" in mock_alert.call_args.args[0]


def test_dispute_created_swallows_stripe_cancel_errors(fake_db):
    """A failing Stripe cancel must not break DB update + alert."""
    from routers import billing

    users = _RecordingUsers(rows=[{
        "id": "u2",
        "email": "u2@example.com",
        "stripe_subscription_id": "sub_fail",
        "plan": "pro",
    }])
    fake_db.set_table("users", users)

    with patch("stripe.Charge.retrieve", side_effect=_stub_charge_to_customer("cus_2")), \
         patch("stripe.Subscription.delete",
               side_effect=Exception("subscription already canceled")), \
         patch("routers.billing._telegram_alert"):
        # Must not raise
        billing._handle_dispute_created(fake_db, {
            "id": "dp_race",
            "charge": "ch_r",
            "amount": 1900,
            "reason": "duplicate",
        })

    # DB still updated
    assert any(u.get("plan") == "free" for u in users.update_calls)


# ── dispute.closed ──


def test_dispute_closed_only_logs(fake_db):
    from routers import billing

    fake_db.set_table("users", FakeQueryBuilder(data=[{
        "id": "u-closed",
        "email": "c@example.com",
    }]))

    with patch("stripe.Charge.retrieve", side_effect=_stub_charge_to_customer("cus_c")), \
         patch("routers.billing._telegram_alert") as mock_alert, \
         patch("models.audit.emit") as mock_emit:
        billing._handle_dispute_closed(fake_db, {
            "id": "dp_done",
            "charge": "ch_c",
            "status": "won",
        })

    # One audit event, one telegram alert, no DB updates
    mock_emit.assert_called_once()
    event_type = mock_emit.call_args.args[0]
    assert event_type == "dispute_closed"
    assert mock_emit.call_args.kwargs["metadata"]["status"] == "won"

    mock_alert.assert_called_once()


# ── End-to-end through the webhook endpoint ──


def test_webhook_routes_dispute_created_to_handler(client, fake_db):
    """Signature verification is patched; we're validating the routing
    from the webhook endpoint into _handle_dispute_created."""
    from routers import billing

    dispute = {
        "id": "dp_e2e",
        "charge": "ch_e2e",
        "amount": 1900,
        "reason": "fraudulent",
    }

    with patch("stripe.Webhook.construct_event",
               return_value=_dispute_event(dispute)), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing._handle_dispute_created") as mock_handler:
        resp = client.post(
            "/billing/webhook",
            content=b"{}",
            headers={"stripe-signature": "t=0,v1=fake"},
        )

    assert resp.status_code == 200
    mock_handler.assert_called_once()
    passed_dispute = mock_handler.call_args.args[1]
    assert passed_dispute["id"] == "dp_e2e"


def test_webhook_routes_dispute_closed_to_handler(client, fake_db):
    dispute = {"id": "dp_close", "charge": "ch_close", "status": "lost"}

    with patch("stripe.Webhook.construct_event",
               return_value=_dispute_closed_event(dispute)), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing._handle_dispute_closed") as mock_handler:
        resp = client.post(
            "/billing/webhook",
            content=b"{}",
            headers={"stripe-signature": "t=0,v1=fake"},
        )

    assert resp.status_code == 200
    mock_handler.assert_called_once()
