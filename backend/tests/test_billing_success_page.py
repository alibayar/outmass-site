"""The page after checkout has to say what actually happened.

Until 2026-08-14 /billing/success took no parameters — it ignored the
session_id its own success_url passes — and told every visitor "Your plan
upgrade is now active".

For a card that is true within a second. For a bank debit, live since
2026-08-08, it is false for several days: checkout.session.completed arrives
with payment_status 'unpaid', the account stays Free with no subscription id,
and the money lands later via async_payment_succeeded. So the person read
"active", opened the panel, saw Free, and had every reason to pay a second
time with a card — landing us with two subscriptions and them with a quota
that the replay guard re-zeroes mid-period.

Nobody would have complained. They would have paid twice.
"""
from unittest.mock import patch

import pytest

SETTLED = {"payment_status": "paid"}
PENDING = {"payment_status": "unpaid"}


def _get(client, **params):
    return client.get("/billing/success", params=params)


@pytest.fixture
def stripe_key():
    with patch("routers.billing.STRIPE_SECRET_KEY", "sk_test_success_page"):
        yield


# ── The common case is unchanged ──


def test_a_settled_card_payment_still_says_active(client, stripe_key):
    with patch("routers.billing.stripe.checkout.Session.retrieve",
               return_value=SETTLED):
        resp = _get(client, session_id="cs_test_paid")

    assert resp.status_code == 200
    assert "now active" in resp.text


# ── The case it was built for ──


def test_a_pending_bank_debit_does_not_claim_the_plan_is_active(client, stripe_key):
    with patch("routers.billing.stripe.checkout.Session.retrieve",
               return_value=PENDING):
        resp = _get(client, session_id="cs_test_ach")

    assert resp.status_code == 200
    assert "now active" not in resp.text
    assert "few business days" in resp.text


def test_a_pending_payment_is_told_not_to_pay_again(client, stripe_key):
    """The sentence the whole change exists for. Without it the reader's next
    move is a card payment, and the second subscription is ours to unpick."""
    with patch("routers.billing.stripe.checkout.Session.retrieve",
               return_value=PENDING):
        resp = _get(client, session_id="cs_test_ach")

    assert "don't need to pay again" in resp.text


# ── When we cannot tell ──


@pytest.mark.parametrize("params", [{}, {"session_id": ""}])
def test_no_session_id_falls_back_to_wording_true_either_way(client, stripe_key, params):
    """An old link or a bookmark. The fallback must not be the old text: a
    guess of 'active' is exactly the wrong guess, because it is only wrong in
    the case that costs money."""
    resp = _get(client, **params)

    assert resp.status_code == 200
    assert "now active" not in resp.text
    assert "don't need to pay again" in resp.text


def test_a_stripe_outage_does_not_break_the_page(client, stripe_key):
    """The customer has just paid. Whatever else happens, they must not get a
    500 on the page that tells them it worked."""
    with patch("routers.billing.stripe.checkout.Session.retrieve",
               side_effect=RuntimeError("stripe is down")):
        resp = _get(client, session_id="cs_test_boom")

    assert resp.status_code == 200
    assert "now active" not in resp.text
    assert "don't need to pay again" in resp.text


def test_no_stripe_key_configured_is_not_an_error(client):
    with patch("routers.billing.STRIPE_SECRET_KEY", ""):
        resp = _get(client, session_id="cs_test_whatever")

    assert resp.status_code == 200
    assert "now active" not in resp.text


# ── The invariant, stated once ──


@pytest.mark.parametrize("status", [
    "unpaid", "pending", "no_payment_required", "paid", "", None, "something_new",
])
def test_active_is_claimed_only_for_a_settled_status(client, stripe_key, status):
    """One rule rather than four branches: the page may say the plan is active
    only when Stripe says the money is ours. A payment_status Stripe invents
    next year lands in the cautious branch by default, which is the direction
    that cannot cost a customer a second charge."""
    from routers.billing import _SETTLED_PAYMENT_STATUSES

    with patch("routers.billing.stripe.checkout.Session.retrieve",
               return_value={"payment_status": status}):
        resp = _get(client, session_id="cs_test_x")

    claims_active = "now active" in resp.text
    assert claims_active == (status in _SETTLED_PAYMENT_STATUSES), (
        f"payment_status={status!r} produced claims_active={claims_active}"
    )
