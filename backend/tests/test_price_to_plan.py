"""An unknown Stripe price must not become the top tier.

Both plan lookups defaulted to "pro" until 2026-08-10. Any price id that was
not byte-identical to STRIPE_STARTER_PRICE_ID resolved to Pro — 10,000 emails
a month for Starter money. That includes every case where a second price
appears, and prices appear from the DASHBOARD:

  * a second currency, which is exactly what local pricing would require
  * an annual tier
  * a NEW starter price after a price change — Stripe prices are immutable,
    so raising the price mints a new id
  * the Team price, configured in env and compared nowhere

None of those need a deploy, so the trigger sat entirely outside code review.
And the failure favours the customer, so nobody would ever report it; it
would surface, if ever, in a revenue reconciliation.

The replacement default is the LOWEST paid tier plus an operator alert.
Between two failures, prefer the one the customer will tell you about.
"""
from unittest.mock import patch

import pytest

from routers import billing
from tests.conftest import FakeQueryBuilder


@pytest.fixture()
def prices():
    with patch.object(billing, "STRIPE_STARTER_PRICE_ID", "price_starter"), \
         patch.object(billing, "STRIPE_PRO_PRICE_ID", "price_pro"), \
         patch.object(billing, "STRIPE_TEAM_PRICE_ID", "price_team"), \
         patch.object(billing, "_telegram_alert") as alert:
        yield alert


def test_known_prices_resolve(prices):
    assert billing._plan_for_price("price_starter", "t") == "starter"
    assert billing._plan_for_price("price_pro", "t") == "pro"
    prices.assert_not_called()


def test_team_price_delivers_pro(prices):
    """There is no "team" tier in monthly_limit_for_plan, so a Team
    subscription can only be delivered as Pro. Mapping it explicitly beats
    alerting on something that was done deliberately."""
    assert billing._plan_for_price("price_team", "t") == "pro"
    prices.assert_not_called()


@pytest.mark.parametrize("unknown", [
    "price_starter_eur",     # the same plan in another currency
    "price_starter_annual",  # the same plan, another interval
    "price_starter_v2",      # what a price RISE mints
    "price_something_else",
])
def test_an_unknown_price_does_not_become_pro(prices, unknown):
    assert billing._plan_for_price(unknown, "t") == "starter"
    prices.assert_called_once()
    assert "unknown Stripe price" in prices.call_args.args[0]


def test_an_unknown_price_is_loud(prices):
    """It is triggered by a dashboard action with no deploy, so silence would
    mean nobody ever learns it happened."""
    billing._plan_for_price("price_mystery", "checkout session cs_1")
    body = prices.call_args.args[0]
    assert "price_mystery" in body
    assert "cs_1" in body


def test_empty_price_id_never_resolves(prices):
    """A price we failed to read arrives as "". If an unset env var were
    allowed into the mapping as a key, that blank would resolve to whatever
    it mapped to — so empties are dropped when the map is built."""
    assert billing._plan_for_price("", "t") == "starter"
    prices.assert_called_once()


def test_unset_env_vars_do_not_create_a_blank_key():
    with patch.object(billing, "STRIPE_STARTER_PRICE_ID", "price_starter"), \
         patch.object(billing, "STRIPE_PRO_PRICE_ID", ""), \
         patch.object(billing, "STRIPE_TEAM_PRICE_ID", ""):
        mapping = billing._price_to_plan()
    assert "" not in mapping
    assert mapping == {"price_starter": "starter"}


# ── the call sites must actually use it ──
#
# The unit tests above prove _plan_for_price is correct. They say nothing
# about whether anything CALLS it — mutation testing found all three sites
# could be reverted to a hardcoded "pro" with every test above still green.


class _RecordingUsers(FakeQueryBuilder):
    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(dict(vals))
        return super().update(vals)


def _webhook(client, event, fake_sub=None, retrieve_raises=False):
    retrieve = (
        patch("routers.billing.stripe.Subscription.retrieve",
              side_effect=RuntimeError("stripe down"))
        if retrieve_raises
        else patch("routers.billing.stripe.Subscription.retrieve",
                   return_value=fake_sub or {"items": {"data": []}})
    )
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         retrieve, \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing.STRIPE_STARTER_PRICE_ID", "price_starter"), \
         patch("routers.billing.STRIPE_PRO_PRICE_ID", "price_pro"), \
         patch("routers.billing.STRIPE_TEAM_PRICE_ID", ""), \
         patch("routers.billing.welcome_email.send_upgrade_email"), \
         patch("routers.billing._telegram_alert") as alert:
        resp = client.post("/billing/webhook", content=b"{}",
                           headers={"stripe-signature": "sig"})
    return resp, alert


def _plans_written(users):
    return [c["plan"] for c in users.update_calls if "plan" in c]


def test_checkout_with_an_unknown_price_does_not_grant_pro(fake_db):
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[{"id": "u-1", "email": "u1@example.com",
                                   "stripe_subscription_id": None}])
    fake_db.set_table("users", users)

    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_unknown", "metadata": {"user_id": "u-1"},
            "customer": "cus_1", "subscription": "sub_1",
            "payment_status": "paid",
        }},
    }
    resp, alert = _webhook(
        TestClient(app), event,
        fake_sub={"items": {"data": [{"price": {"id": "price_mystery"}}]}},
    )

    assert resp.status_code == 200
    assert _plans_written(users) == ["starter"]
    # Two alerts since 2026-08-19: the unknown-price warning AND the
    # operator payment ping (every activation pings, this one included).
    msgs = [c.args[0] for c in alert.call_args_list]
    assert len(msgs) == 2
    assert any("unknown Stripe price" in m for m in msgs)
    assert any("New subscription" in m for m in msgs)


def test_checkout_when_stripe_cannot_be_read_does_not_grant_pro(fake_db):
    """A Stripe outage used to hand out the top tier: the old code caught the
    exception with a bare `pass` onto a "pro" default."""
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[{"id": "u-2", "email": "u2@example.com",
                                   "stripe_subscription_id": None}])
    fake_db.set_table("users", users)

    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_down", "metadata": {"user_id": "u-2"},
            "customer": "cus_2", "subscription": "sub_2",
            "payment_status": "paid",
        }},
    }
    resp, alert = _webhook(TestClient(app), event, retrieve_raises=True)

    assert resp.status_code == 200
    assert _plans_written(users) == ["starter"]
    # The guard's warning plus the payment ping (2026-08-19) — the outage
    # alert must survive the new ping, not be replaced by it.
    msgs = [c.args[0] for c in alert.call_args_list]
    assert len(msgs) == 2
    assert any("New subscription" in m for m in msgs)
    assert any("New subscription" not in m for m in msgs)


def test_subscription_updated_with_an_unknown_price_does_not_grant_pro(fake_db):
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[{"id": "u-3", "email": "u3@example.com",
                                   "plan": "free", "manual_promo_until": None,
                                   "stripe_customer_id": "cus_3",
                                   "stripe_subscription_id": "sub_3"}])
    fake_db.set_table("users", users)

    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "customer": "cus_3", "status": "active",
            "items": {"data": [{"price": {"id": "price_mystery"}}]},
        }},
    }
    resp, alert = _webhook(TestClient(app), event)

    assert resp.status_code == 200
    assert _plans_written(users) == ["starter"]
    alert.assert_called_once()


def test_subscription_updated_with_the_real_pro_price_still_grants_pro(fake_db):
    """The guard must not become a ceiling: a genuine Pro subscriber still
    gets Pro, and nobody is alerted about it."""
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[{"id": "u-4", "email": "u4@example.com",
                                   "plan": "free", "manual_promo_until": None,
                                   "stripe_customer_id": "cus_4",
                                   "stripe_subscription_id": "sub_4"}])
    fake_db.set_table("users", users)

    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "customer": "cus_4", "status": "active",
            "items": {"data": [{"price": {"id": "price_pro"}}]},
        }},
    }
    resp, alert = _webhook(TestClient(app), event)

    assert resp.status_code == 200
    assert _plans_written(users) == ["pro"]
    alert.assert_not_called()


def test_the_fallback_is_the_lowest_paid_tier_not_free():
    """Not "free" either: they paid. Leaving a payer on the free tier is a
    different silent failure, and this one they would notice immediately —
    but only after being blocked mid-campaign."""
    assert billing._UNKNOWN_PRICE_PLAN == "starter"
    from config import monthly_limit_for_plan
    assert monthly_limit_for_plan("starter") < monthly_limit_for_plan("pro")
    assert monthly_limit_for_plan("starter") > monthly_limit_for_plan("free")
