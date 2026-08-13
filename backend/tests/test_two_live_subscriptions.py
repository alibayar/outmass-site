"""One customer must never end up with two subscriptions billing them.

Two independent routes led there, both found on 2026-08-14 by mapping the
delayed-payment path end to end.

ROUTE ONE — the webhook. The replay guard in _activate_from_checkout_session
asks only "is this the subscription id already on the row", which is a guard
against Stripe redelivering the SAME event. A DIFFERENT subscription reads as
a first-time activation. That is reachable: a bank debit is withheld at
checkout.session.completed (payment_status 'unpaid', nothing written), so the
row still says no subscription; if the customer pays again by card, the card
subscription activates correctly; days later the debit settles and arrives as
an unrecognised id. Overwriting drops the live, actively-billing card
subscription out of our own database and re-zeroes the customer's quota
mid-period on the way past.

ROUTE TWO — create-checkout. A transient StripeError while reading an existing
subscriber's subscription used to set sub = None, which the status check then
read as "no live subscription", falling through to open a brand-new
full-price Checkout Session for someone already paying. A failed read is not
evidence of absence.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeQueryBuilder


class _RecordingUsers(FakeQueryBuilder):
    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(dict(vals))
        return super().update(vals)


@pytest.fixture()
def client():
    from main import app
    return TestClient(app)


def _user_row(stored_sub):
    return {
        "id": "u-two",
        "email": "two@example.com",
        "name": "Two Subs",
        "plan": "starter",
        "stripe_subscription_id": stored_sub,
        "emails_sent_this_month": 1900,
    }


def _completed(subscription_id):
    return {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_second",
            "metadata": {"user_id": "u-two", "plan": "starter"},
            "customer": "cus_two",
            "subscription": subscription_id,
            "payment_status": "paid",
            "amount_total": 900,
            "currency": "usd",
        }},
    }


def _conflict_alerts(alert):
    """Only OUR alert. An unrecognised price id legitimately raises its own,
    and asserting on the call count instead would fail for the wrong reason."""
    return [c.args[0] for c in alert.call_args_list
            if "two live subscriptions" in c.args[0]]


def _post(client, event, stored_status):
    """Drive the webhook with a stored subscription in a given Stripe state."""
    def _retrieve(sub_id):
        if sub_id == "sub_card":          # the one already on the row
            if stored_status == "gone":
                raise RuntimeError("stripe is unreachable")
            return {"id": sub_id, "status": stored_status,
                    "items": {"data": [{"price": {"id": "price_whatever"}}]}}
        return {"id": sub_id, "status": "active",
                "items": {"data": [{"price": {"id": "price_whatever"}}]}}

    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.stripe.Subscription.retrieve", side_effect=_retrieve), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing.welcome_email.send_upgrade_email"), \
         patch("routers.billing._telegram_alert") as alert, \
         patch("routers.billing._capture_billing_event"):
        resp = client.post("/billing/webhook", content=b"{}",
                           headers={"stripe-signature": "sig"})
    return resp, alert


# ── Route one: the webhook ──


@pytest.mark.parametrize("status", ["active", "trialing", "past_due"])
def test_a_second_subscription_never_overwrites_a_live_one(client, fake_db, status):
    """The whole point. Their plan and their counters must survive untouched."""
    users = _RecordingUsers(rows=[_user_row("sub_card")])
    fake_db.set_table("users", users)

    resp, alert = _post(client, _completed("sub_ach"), status)

    assert resp.status_code == 200
    assert users.update_calls == [], (
        f"a second subscription overwrote a {status} one: {users.update_calls}"
    )
    alert.assert_called_once()
    assert "two live subscriptions" in alert.call_args.args[0]


def test_the_alert_carries_both_ids_so_a_human_can_act(client, fake_db):
    users = _RecordingUsers(rows=[_user_row("sub_card")])
    fake_db.set_table("users", users)

    _, alert = _post(client, _completed("sub_ach"), "active")

    sent = alert.call_args.args[0]
    assert "sub_card" in sent and "sub_ach" in sent
    assert "refund" in sent.lower(), "the alert does not say what to do about it"


@pytest.mark.parametrize("dead", ["canceled", "incomplete_expired", "incomplete"])
def test_resubscribing_after_the_old_one_died_still_works(client, fake_db, dead):
    """The common, legitimate case that must not be caught by the guard: they
    cancelled, then came back. A fresh quota period is correct here."""
    users = _RecordingUsers(rows=[_user_row("sub_card")])
    fake_db.set_table("users", users)

    resp, alert = _post(client, _completed("sub_new"), dead)

    assert resp.status_code == 200
    granted = [c for c in users.update_calls if c.get("plan")]
    assert len(granted) == 1
    assert granted[0]["stripe_subscription_id"] == "sub_new"
    assert granted[0]["emails_sent_this_month"] == 0
    assert not _conflict_alerts(alert), _conflict_alerts(alert)


def test_an_unreadable_stored_subscription_is_treated_as_live(client, fake_db):
    """Asymmetric on purpose. Refusing to overwrite a subscription that was
    actually dead delays a plan grant until someone looks; overwriting one
    that was actually live drops a paying customer out of our records. Only
    one of those is a support ticket the customer opens."""
    users = _RecordingUsers(rows=[_user_row("sub_card")])
    fake_db.set_table("users", users)

    resp, alert = _post(client, _completed("sub_ach"), "gone")

    assert resp.status_code == 200
    assert users.update_calls == []
    alert.assert_called_once()


def test_the_first_ever_subscription_is_unaffected(client, fake_db):
    """Nothing stored, so nothing to conflict with — the ordinary purchase."""
    users = _RecordingUsers(rows=[_user_row(None)])
    fake_db.set_table("users", users)

    resp, alert = _post(client, _completed("sub_first"), "active")

    assert resp.status_code == 200
    granted = [c for c in users.update_calls if c.get("plan")]
    assert len(granted) == 1
    assert not _conflict_alerts(alert), _conflict_alerts(alert)


def test_a_redelivery_of_the_same_subscription_is_still_a_no_op_for_quota(client, fake_db):
    """The guard this one was built on must keep working: Stripe retries for
    days, and a replay must not hand out a bonus quota month."""
    users = _RecordingUsers(rows=[_user_row("sub_card")])
    fake_db.set_table("users", users)

    resp, alert = _post(client, _completed("sub_card"), "active")

    assert resp.status_code == 200
    for call in users.update_calls:
        assert "emails_sent_this_month" not in call, (
            "a webhook redelivery re-zeroed the quota"
        )
    assert not _conflict_alerts(alert), _conflict_alerts(alert)


# ── Route two: create-checkout ──


def _upgrade(client, fake_db, retrieve_side_effect):
    import stripe as stripe_sdk
    from main import app
    from routers.auth import get_current_user

    user = {
        "id": "u-up", "email": "up@example.com", "plan": "starter",
        "stripe_subscription_id": "sub_live", "emails_sent_this_month": 0,
    }

    async def _override():
        return user

    fake_db.set_table("users", FakeQueryBuilder([user]))
    app.dependency_overrides[get_current_user] = _override
    try:
        with patch("routers.billing.STRIPE_SECRET_KEY", "sk_test_x"), \
             patch("routers.billing.STRIPE_PRO_PRICE_ID", "price_pro"), \
             patch("routers.billing.STRIPE_STARTER_PRICE_ID", "price_starter"), \
             patch("routers.billing.stripe.Subscription.retrieve",
                   side_effect=retrieve_side_effect), \
             patch("routers.billing.stripe.checkout.Session.create") as create:
            resp = client.post("/billing/create-checkout", json={"plan": "pro"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    return resp, create


def test_a_stripe_blip_during_an_upgrade_does_not_open_a_second_subscription(
    client, fake_db
):
    """The defect: the error was swallowed into sub = None, the status check
    read that as 'not subscribed', and an existing paying customer was handed
    a brand-new full-price Checkout Session."""
    import stripe as stripe_sdk

    resp, create = _upgrade(
        client, fake_db, stripe_sdk.StripeError("connection reset")
    )

    assert resp.status_code == 502
    create.assert_not_called(), "a second Checkout Session was opened for a subscriber"


def test_the_502_tells_the_user_to_try_again_rather_than_naming_stripe(
    client, fake_db
):
    """They pressed Upgrade; what they need is whether to press it again."""
    import stripe as stripe_sdk

    resp, _ = _upgrade(client, fake_db, stripe_sdk.StripeError("connection reset"))

    detail = resp.json().get("detail", "")
    assert "try again" in detail.lower(), detail
