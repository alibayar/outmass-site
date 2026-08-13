"""The panel must never invent a price.

Before 2026-08-13 the Account tab had one "Upgrade Plan" button that opened
Stripe Checkout for a hardcoded 'starter'. Nobody could see what it cost
without landing on a payment form, and Pro could not be bought from the panel
at all. Two people reached Checkout in the first half of August and left
without entering a card — the expected result of a control that reads "show
me the plans" and behaves like "pay now".

The catalogue that replaces it holds no numbers of its own: the price comes
from Stripe and the limit from config.py. Writing either a second time is
how docs/terms.html spent months promising a 50-email free tier while the
code gave 250.

The rule these tests encode: a WRONG price is worse than no price. When
Stripe cannot be read, the endpoint serves the last good answer or nothing,
and the panel falls back to its old single button.
"""
from unittest.mock import patch

import pytest

from config import PRO_PLAN_MONTHLY_LIMIT, STARTER_PLAN_MONTHLY_LIMIT
from routers import billing


@pytest.fixture(autouse=True)
def _clear_cache():
    billing._PLAN_CACHE["plans"] = None
    billing._PLAN_CACHE["at"] = None
    yield
    billing._PLAN_CACHE["plans"] = None
    billing._PLAN_CACHE["at"] = None


def _price(amount, currency="usd"):
    return {"unit_amount": amount, "currency": currency,
            "recurring": {"interval": "month"}}


def _prices(**over):
    table = {"price_starter": _price(900), "price_pro": _price(1900)}
    table.update(over)
    return lambda pid: table[pid]


def _with_stripe(side_effect):
    return patch.multiple(
        billing,
        STRIPE_STARTER_PRICE_ID="price_starter",
        STRIPE_PRO_PRICE_ID="price_pro",
    ), patch("routers.billing.stripe.Price.retrieve", side_effect=side_effect)


def test_both_plans_come_back_with_live_prices():
    ids, retrieve = _with_stripe(_prices())
    with ids, retrieve:
        plans = billing._purchasable_plans()

    assert [p["key"] for p in plans] == ["starter", "pro"]
    assert plans[0]["amount"] == 900
    assert plans[1]["amount"] == 1900


def test_the_limits_come_from_config_not_from_this_module():
    """If a limit is ever raised in config.py, the panel must follow without
    anyone editing a second copy."""
    ids, retrieve = _with_stripe(_prices())
    with ids, retrieve:
        plans = {p["key"]: p for p in billing._purchasable_plans()}

    assert plans["starter"]["limit"] == STARTER_PLAN_MONTHLY_LIMIT
    assert plans["pro"]["limit"] == PRO_PLAN_MONTHLY_LIMIT


def test_a_stripe_outage_serves_the_last_good_answer():
    ids, retrieve = _with_stripe(_prices())
    with ids, retrieve:
        good = billing._purchasable_plans()
    assert len(good) == 2

    # Force a refresh, and make Stripe fail during it.
    billing._PLAN_CACHE["at"] = None
    ids, broken = _with_stripe(RuntimeError("stripe down"))
    with ids, broken:
        served = billing._purchasable_plans()

    assert served == good, "a Stripe outage must not blank the pricing"


def test_a_stripe_outage_with_no_cache_returns_nothing_rather_than_a_guess():
    ids, broken = _with_stripe(RuntimeError("stripe down"))
    with ids, broken:
        assert billing._purchasable_plans() == []


def test_one_broken_price_does_not_ship_half_a_catalogue():
    """A pricing list missing a product is its own kind of wrong — the user
    would conclude Pro does not exist."""
    def _half(pid):
        if pid == "price_pro":
            raise RuntimeError("no such price")
        return _price(900)

    ids, retrieve = _with_stripe(_half)
    with ids, retrieve:
        assert billing._purchasable_plans() == []


def test_an_unconfigured_price_id_is_not_silently_skipped():
    with patch.multiple(billing, STRIPE_STARTER_PRICE_ID="price_starter",
                        STRIPE_PRO_PRICE_ID=""), \
         patch("routers.billing.stripe.Price.retrieve",
               side_effect=_prices()):
        assert billing._purchasable_plans() == []


def test_a_price_with_no_amount_is_refused():
    """Stripe can return a price whose unit_amount is null (tiered pricing).
    Rendering that as a blank or a zero is exactly the wrong price."""
    def _null_amount(pid):
        return {"unit_amount": None, "currency": "usd"}

    ids, retrieve = _with_stripe(_null_amount)
    with ids, retrieve:
        assert billing._purchasable_plans() == []


def test_the_catalogue_is_cached_rather_than_hit_per_request():
    calls = {"n": 0}

    def _counting(pid):
        calls["n"] += 1
        return _price(900)

    ids, retrieve = _with_stripe(_counting)
    with ids, retrieve:
        billing._purchasable_plans()
        first = calls["n"]
        billing._purchasable_plans()

    assert calls["n"] == first, "every /billing/status hit Stripe"


def test_status_carries_the_catalogue(client, fake_db, auth_bypass):
    """Additive on purpose: an older extension ignores the key and keeps its
    single button, so shipping the backend first is safe."""
    from tests.conftest import FakeQueryBuilder, FAKE_USER

    fake_db.set_table("users", FakeQueryBuilder(data=[dict(FAKE_USER)]))
    ids, retrieve = _with_stripe(_prices())
    with ids, retrieve:
        resp = client.get("/billing/status")

    assert resp.status_code == 200
    body = resp.json()
    assert {"plan", "emails_sent_this_month", "limit", "plans"} <= set(body)
    assert [p["key"] for p in body["plans"]] == ["starter", "pro"]


# ── "Your plan ended" — context at the moment of use ──
#
# The notification is the email sent when the plan drops. This flag decides
# whether the panel ALSO explains why the account is capped when the user
# next comes back. Bounded, because the underlying condition never stops
# being true: someone who paid once in June and has been happily on Free
# since does not need a banner about it in December.


def _dropped(days_ago, **over):
    from datetime import datetime, timedelta, timezone

    row = {
        "plan": "free",
        "stripe_customer_id": "cus_1",
        "plan_updated_at": (
            datetime.now(timezone.utc) - timedelta(days=days_ago)
        ).isoformat(),
    }
    row.update(over)
    return row


def test_a_recent_drop_is_explained():
    assert billing._plan_ended_recently(_dropped(2)) is True


def test_an_old_drop_is_not():
    """Past the window it is not news, it is just their plan — and a banner
    that never clears is furniture rather than information."""
    from config import PLAN_DROP_NOTICE_DAYS

    assert billing._plan_ended_recently(_dropped(PLAN_DROP_NOTICE_DAYS + 1)) is False


def test_someone_who_never_paid_is_never_told_a_plan_ended():
    """stripe_customer_id is written only on a completed checkout, so its
    absence means they have never had a plan to lose."""
    assert billing._plan_ended_recently(_dropped(1, stripe_customer_id=None)) is False


def test_a_paying_customer_is_not_told_their_plan_ended():
    assert billing._plan_ended_recently(_dropped(1, plan="starter")) is False


def test_a_missing_timestamp_says_nothing_rather_than_guessing():
    assert billing._plan_ended_recently(_dropped(1, plan_updated_at=None)) is False


def test_a_malformed_timestamp_cannot_break_the_status_call():
    """The whole panel reads this endpoint. A bad row must cost an
    explanation, not the account tab."""
    assert billing._plan_ended_recently(_dropped(1, plan_updated_at="not-a-date")) is False


def test_the_window_is_read_from_config():
    """Patched to a value the default has never had, so a reinstated literal
    cannot coincide with the assertion."""
    with patch.object(billing, "PLAN_DROP_NOTICE_DAYS", 3):
        assert billing._plan_ended_recently(_dropped(2)) is True
        assert billing._plan_ended_recently(_dropped(5)) is False


def test_status_carries_the_flag(client, fake_db, auth_bypass):
    from tests.conftest import FakeQueryBuilder, FAKE_USER

    row = dict(FAKE_USER)
    row.update(_dropped(1))
    fake_db.set_table("users", FakeQueryBuilder(data=[row]))
    ids, retrieve = _with_stripe(_prices())
    with ids, retrieve:
        body = client.get("/billing/status").json()

    assert body["plan_ended_recently"] is True
