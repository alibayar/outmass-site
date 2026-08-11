"""past_due is Stripe still collecting, not a cancellation.

Until 2026-08-11 customer.subscription.updated put past_due in the same
bucket as canceled and unpaid and wrote plan='free'. It cost us twice:

  * business@solutionsweekly.info dropped to free on 08-10 11:02 UTC with a
    live subscription and an invoice due 09-08. Capped at 250 emails while
    believing they were a subscriber.
  * faisal@samaed.com spent the last fourteen days of his subscription on
    the free tier while Stripe ran ten collection attempts against his card.

Two things in the same file said it was wrong. invoice.payment_failed
carries the comment "Don't immediately downgrade — mark as past_due", and
the upgrade path treats past_due as a live subscription it can modify. And
nothing in tests/ touched past_due at all, which is why it survived.

The safety argument for holding the plan is that retry exhaustion ends the
subscription rather than parking it: Faisal's final attempt at 08-08 17:17
UTC produced customer.subscription.deleted at the same second. So every
past_due either recovers (-> active) or dies (-> deleted/unpaid), and both
of those are handled.
"""
from unittest.mock import patch

import pytest

from tests.conftest import FakeQueryBuilder


class _RecordingUsers(FakeQueryBuilder):
    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []

    def update(self, vals):
        self.update_calls.append(dict(vals))
        return super().update(vals)


def _subscriber(**over):
    row = {
        "id": "u-pd",
        "email": "pd@example.com",
        "plan": "starter",
        "manual_promo_until": None,
        "stripe_customer_id": "cus_pd",
        "stripe_subscription_id": "sub_pd",
    }
    row.update(over)
    return row


def _send(client, status, items=None):
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "customer": "cus_pd",
            "status": status,
            "items": items or {"data": []},
        }},
    }
    with patch("routers.billing.stripe.Webhook.construct_event",
               return_value=event), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing.STRIPE_STARTER_PRICE_ID", "price_starter"), \
         patch("routers.billing.STRIPE_PRO_PRICE_ID", "price_pro"), \
         patch("routers.billing.STRIPE_TEAM_PRICE_ID", ""), \
         patch("routers.billing._telegram_alert"):
        return client.post("/billing/webhook", content=b"{}",
                           headers={"stripe-signature": "sig"})


def _plans_written(users):
    return [c["plan"] for c in users.update_calls if "plan" in c]


def test_past_due_does_not_touch_the_plan(fake_db):
    """The regression itself."""
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[_subscriber()])
    fake_db.set_table("users", users)

    resp = _send(TestClient(app), "past_due")

    assert resp.status_code == 200
    assert _plans_written(users) == [], (
        "past_due wrote a plan — the customer is mid-retry and Stripe still "
        "counts them as a subscriber"
    )


def test_past_due_still_moves_plan_updated_at(fake_db):
    """It is the marker an operator reads to tell "the handler ran" from
    "the event never arrived" — that check is what proved on 07-31 that
    Stripe was not delivering invoice.payment_failed at all. Holding the
    plan must not also make the event invisible."""
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[_subscriber()])
    fake_db.set_table("users", users)

    _send(TestClient(app), "past_due")

    assert any("plan_updated_at" in c for c in users.update_calls)


@pytest.mark.parametrize("status", ["canceled", "unpaid"])
def test_a_dead_subscription_still_downgrades(status, fake_db):
    """The other half. Removing past_due from the bucket is only safe while
    these two still fall through to free — otherwise a failed customer keeps
    the plan for ever."""
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[_subscriber()])
    fake_db.set_table("users", users)

    _send(TestClient(app), status)

    assert _plans_written(users) == ["free"]


def test_deleted_is_the_path_that_actually_ends_it(fake_db):
    """Faisal's subscription was CANCELLED when retries ran out — the final
    blocked attempt and customer.subscription.deleted share a timestamp. That
    is the whole safety argument for holding the plan during past_due, so it
    gets a test rather than a comment."""
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[_subscriber()])
    fake_db.set_table("users", users)

    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_pd"}},
    }
    with patch("routers.billing.stripe.Webhook.construct_event",
               return_value=event), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing._telegram_alert"):
        resp = TestClient(app).post("/billing/webhook", content=b"{}",
                                    headers={"stripe-signature": "sig"})

    assert resp.status_code == 200
    assert _plans_written(users) == ["free"]
    assert any(c.get("stripe_subscription_id") is None
               for c in users.update_calls)


def test_recovery_restores_the_plan_from_the_price(fake_db):
    """When the card finally works the subscription goes past_due -> active
    and the plan is re-resolved. Under the old code this was a RESTORE; now
    it is a no-op for anyone who never lost the plan. Both have to work,
    because a customer who was already downgraded by the old behaviour still
    depends on this path."""
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[_subscriber(plan="free")])
    fake_db.set_table("users", users)

    _send(TestClient(app), "active",
          items={"data": [{"price": {"id": "price_starter"}}]})

    assert _plans_written(users) == ["starter"]


def test_the_promo_shield_still_covers_the_downgrade_paths(fake_db):
    """A gifted plan must survive a cancellation for the subscription that
    died before it. past_due leaving the bucket must not take the shield
    with it on the paths that still downgrade."""
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[_subscriber(
        plan="starter",
        manual_promo_until="2099-01-01T00:00:00+00:00",
        stripe_subscription_id=None,
    )])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", FakeQueryBuilder(data=[]))

    _send(TestClient(app), "canceled")

    assert _plans_written(users) == [], (
        "a manual promo was revoked by a cancellation it outranks"
    )
