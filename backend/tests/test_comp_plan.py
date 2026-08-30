"""A complimentary plan that Stripe cannot silently take back.

Five paying customers configured follow-ups that were never created, and the
remedy chosen was a free month of Pro. Writing 'pro' into users.plan does not
survive: billing.py's customer.subscription.updated handler rewrites plan from
the Stripe price whenever the status is active, and that fires on every
renewal — so the gift would die within the month, silently, which is the same
shape of failure we are apologising for.

users.manual_promo_until does not fit either. grant_manual_promo refuses to run
over a live subscription because it clears stripe_subscription_id, and
daily_report counts a real payer by that column — the four affected customers
would have vanished from MRR and reappeared as gifts.

So the comp lives in its own two columns (migration 032). users.plan stays
exactly what Stripe says; only the readers that decide what someone may DO
consult effective_plan.

The separation is the whole design, so it is what most of this file tests.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from models.user import effective_plan
from tests.conftest import FAKE_USER


def _until(days_from_now: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days_from_now)).isoformat()


def _user(**over):
    return {**FAKE_USER, **over}


# ── the merge itself ──


@pytest.mark.parametrize("plan", ["free", "starter", "pro"])
def test_no_comp_is_the_plan_they_pay_for(plan):
    assert effective_plan(_user(plan=plan)) == plan


def test_a_live_comp_wins():
    user = _user(plan="starter", comp_plan="pro", comp_plan_until=_until(30))
    assert effective_plan(user) == "pro"


def test_an_expired_comp_falls_back_to_the_subscription():
    user = _user(plan="starter", comp_plan="pro", comp_plan_until=_until(-1))
    assert effective_plan(user) == "starter"


def test_it_expires_by_arithmetic_with_nothing_to_undo():
    """No beat task ends a comp, so the same row reads differently either side
    of the boundary and no state can be left half-applied."""
    boundary = datetime.now(timezone.utc) + timedelta(seconds=1)
    user = _user(plan="starter", comp_plan="pro", comp_plan_until=boundary.isoformat())
    assert effective_plan(user) == "pro"

    user["comp_plan_until"] = (boundary - timedelta(seconds=2)).isoformat()
    assert effective_plan(user) == "starter"


@pytest.mark.parametrize(
    "comp,until",
    [
        ("pro", None),          # half-written grant
        (None, _until(30)),     # date with no plan
        ("pro", ""),            # blank
    ],
)
def test_a_half_written_comp_grants_nothing(comp, until):
    """Both columns or neither. A grant that only half-landed must not
    silently open Pro features with no end date."""
    user = _user(plan="starter", comp_plan=comp, comp_plan_until=until)
    assert effective_plan(user) == "starter"


def test_an_unreadable_date_falls_back_to_the_subscription():
    """Fails toward the plan they actually pay for, which is the safe
    direction: too little access is visible and fixable, too much is neither.
    """
    user = _user(plan="starter", comp_plan="pro", comp_plan_until="next tuesday")
    assert effective_plan(user) == "starter"


def test_a_naive_timestamp_is_read_as_utc():
    """Postgres can return a timestamp with no offset; treating it as
    naive-local would raise on the comparison and quietly revoke the comp."""
    naive = (datetime.now(timezone.utc) + timedelta(days=5)).replace(tzinfo=None)
    user = _user(plan="starter", comp_plan="pro", comp_plan_until=naive.isoformat())
    assert effective_plan(user) == "pro"


def test_a_comp_never_takes_anything_away():
    """A comp is an upgrade, never a downgrade — but nothing in the merge says
    so, and a mis-typed grant could hand a Pro subscriber 'starter'. If this
    ever needs to be true, it has to be enforced here rather than assumed."""
    user = _user(plan="pro", comp_plan="starter", comp_plan_until=_until(30))
    assert effective_plan(user) == "starter", (
        "documenting today's behaviour: the comp column wins outright. Grant "
        "only upgrades, or teach effective_plan to take the better of the two"
    )


# ── the separation from money ──


def test_the_money_reports_do_not_consult_it():
    """MRR must move when someone PAYS differently, never when we give
    something away. daily_report filters on the raw column in the query
    itself (`.eq("plan", plan_name)`), which is what makes that structural
    rather than a convention — this test keeps it structural."""
    import inspect

    from workers import daily_report, green_report

    for module in (daily_report, green_report):
        src = inspect.getsource(module)
        assert "effective_plan" not in src, (
            f"{module.__name__} now reads effective_plan; a comped Starter "
            "would be reported as revenue nobody pays"
        )
        assert "comp_plan" not in src, (
            f"{module.__name__} now reads comp_plan directly, which is the "
            "same mistake wearing a different name"
        )


def test_billing_does_not_consult_it():
    """Stripe owns users.plan. If the checkout or webhook paths ever resolved
    through the comp, a comped user's next renewal would write the COMP back
    as their subscription — turning a gift into a price change."""
    import inspect

    from routers import billing

    assert "effective_plan" not in inspect.getsource(billing)


# ── and the gates that should open ──


def _override_user(user):
    from main import app
    from routers.auth import get_current_user

    async def _u():
        return user

    app.dependency_overrides[get_current_user] = _u
    return lambda: app.dependency_overrides.pop(get_current_user, None)


def test_a_comped_starter_gets_past_the_followup_gate(client, fake_db):
    """The gate that started all of this. On Starter it answers 402; with a
    live Pro comp the request must reach the model."""
    user = _user(plan="starter", comp_plan="pro", comp_plan_until=_until(30))
    undo = _override_user(user)
    try:
        with patch(
            "models.campaign.get_campaign",
            return_value={"id": "camp-1", "user_id": user["id"]},
        ), patch(
            "models.followup.create_followup", return_value={"id": "fu-1"}
        ) as create:
            resp = client.post(
                "/campaigns/camp-1/followups",
                json={"delay_days": 3, "subject": "s", "body": "b"},
            )
    finally:
        undo()

    assert resp.status_code != 402, resp.text
    assert create.called, "the comp opened the gate but nothing was created"


def test_a_plain_starter_is_still_refused(client, fake_db):
    """The other half: the gate has to still be a gate."""
    user = _user(plan="starter", comp_plan=None, comp_plan_until=None)
    undo = _override_user(user)
    try:
        with patch(
            "models.campaign.get_campaign",
            return_value={"id": "camp-1", "user_id": user["id"]},
        ):
            resp = client.post(
                "/campaigns/camp-1/followups",
                json={"delay_days": 3, "subject": "s", "body": "b"},
            )
    finally:
        undo()

    assert resp.status_code == 402


def test_an_expired_comp_is_refused_again(client, fake_db):
    user = _user(plan="starter", comp_plan="pro", comp_plan_until=_until(-1))
    undo = _override_user(user)
    try:
        with patch(
            "models.campaign.get_campaign",
            return_value={"id": "camp-1", "user_id": user["id"]},
        ):
            resp = client.post(
                "/campaigns/camp-1/followups",
                json={"delay_days": 3, "subject": "s", "body": "b"},
            )
    finally:
        undo()

    assert resp.status_code == 402


# ── what the panel is told ──


def test_settings_reports_the_comp_as_the_plan_and_the_truth_beside_it(
    client, fake_db
):
    """The panel has drawn its plan label and quota bar from `plan` since
    0.1.x, so a comped user must see the plan whose limits actually apply.
    billing_plan carries the subscription for anything that talks about money.
    """
    from config import PRO_PLAN_MONTHLY_LIMIT

    user = _user(plan="starter", comp_plan="pro", comp_plan_until=_until(30))
    undo = _override_user(user)
    try:
        resp = client.get("/settings")
    finally:
        undo()

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["plan"] == "pro"
    assert data["billing_plan"] == "starter"
    assert data["monthly_limit"] == PRO_PLAN_MONTHLY_LIMIT
