"""A plan the user did not choose to lose must not vanish in silence.

Until 2026-08-13 the only way to learn your plan had gone back to Free was
to hit the free cap mid-send. past_due stopped downgrading on 08-11, which
left two silent paths: a subscription that really ended, and a manual promo
running out.

The distinction these tests exist to protect is WHY it dropped:

  * The customer asked to cancel — they know, and a "your plan has gone back
    to Free" message minutes after their own confirmation is noise. Mary Bass
    would have received exactly that on 2026-08-12.
  * The card never recovered — Stripe spent about two weeks on it and they
    have had its dunning emails, so ours is the end of a chain rather than
    news, and it carries what Stripe cannot know: the new quota, and that
    nothing was deleted.
  * A gift ran out — nothing failed, and mentioning a card would be wrong.

Stripe tells the first two apart in cancellation_details.reason, a field
this codebase did not read until now.
"""
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks

from tests.conftest import FakeQueryBuilder


def _deleted(reason=None, customer="cus_1"):
    obj = {"customer": customer}
    if reason is not None:
        obj["cancellation_details"] = {"reason": reason}
    return {"type": "customer.subscription.deleted", "data": {"object": obj}}


class _Queued:
    """What the handler DECIDED to send, not what FastAPI later ran.

    TestClient does not execute background tasks in this suite — no existing
    test relies on it — and whether Starlette runs a queued task is not our
    code. What IS ours is the decision: send or stay quiet, and with which
    reason. So the assertion belongs on add_task.
    """

    def __init__(self):
        self.calls = []

    def names(self):
        return [c[0] for c in self.calls]

    def args_for(self, name):
        return next((c[1] for c in self.calls if c[0] == name), None)


def _post(client, event):
    queued = _Queued()
    real = BackgroundTasks.add_task

    def _capture(self, func, *args, **kwargs):
        queued.calls.append((getattr(func, "__name__", str(func)), args, kwargs))
        return real(self, func, *args, **kwargs)

    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("routers.billing._telegram_alert"), \
         patch.object(BackgroundTasks, "add_task", _capture):
        resp = client.post(
            "/billing/webhook",
            content=b"{}",
            headers={"stripe-signature": "sig", "host": "api.getoutmass.com"},
        )
    return resp, queued


def _users(**over):
    row = {
        "id": "u-1", "email": "drop@example.com", "name": "Dana",
        "plan": "starter", "manual_promo_until": None,
        "stripe_customer_id": "cus_1", "stripe_subscription_id": "sub_1",
    }
    row.update(over)
    return FakeQueryBuilder(data=[row])


# ── The subscription really ended ──


def test_a_card_that_never_recovered_gets_a_message(client, fake_db):
    fake_db.set_table("users", _users())

    resp, queued = _post(client, _deleted(reason="payment_failed"))

    assert resp.status_code == 200
    args = queued.args_for("send_plan_dropped_email")
    assert args is not None, f"nothing queued; saw {queued.names()}"
    assert args[0] == "drop@example.com"
    assert args[2] == "payment_failed"


def test_a_missing_reason_is_treated_as_not_their_choice(client, fake_db):
    """Stripe does not always populate cancellation_details. Staying silent
    on an unknown reason would recreate the exact gap this closes; the cost
    of guessing wrong here is one extra email."""
    fake_db.set_table("users", _users())

    _, queued = _post(client, _deleted(reason=None))

    assert queued.args_for("send_plan_dropped_email") is not None


# ── They asked ──


def test_a_requested_cancellation_stays_quiet(client, fake_db):
    """Mary Bass cancelled on 2026-08-12 and had her confirmation within the
    hour. A second message telling her what she had just asked for is noise,
    not service."""
    fake_db.set_table("users", _users())

    _, queued = _post(client, _deleted(reason="cancellation_requested"))

    assert queued.args_for("send_plan_dropped_email") is None, (
        f"queued anyway: {queued.names()}"
    )


# ── The promo shield ──


def test_a_shielded_user_is_not_told_they_lost_anything(client, fake_db):
    """Inside a manual promo the plan does NOT drop — the gift holds. Saying
    otherwise would contradict what they were promised in writing."""
    fake_db.set_table("users", _users(
        plan="starter",
        manual_promo_until="2099-01-01T00:00:00+00:00",
        stripe_subscription_id=None,
    ))
    fake_db.set_table("manual_promo_grants", FakeQueryBuilder(data=[]))

    _, queued = _post(client, _deleted(reason="payment_failed"))

    assert queued.args_for("send_plan_dropped_email") is None


# ── The copy itself ──


@pytest.mark.parametrize("reason", ["payment_failed", "promo_ended"])
def test_the_message_says_what_to_do_and_never_types_a_number(reason):
    """Two rules from the same day: a message the reader cannot act on is
    the same as no message, and docs/terms.html spent months promising a
    50-email free tier because somebody wrote a number into copy."""
    from utils import welcome_email

    captured = {}

    def _fake(email, subject, text, html):
        captured.update(subject=subject, text=text, html=html)
        return True

    # A value the free tier has never had. Asserting the REAL limit would
    # pass against a hardcoded "250" — it is the current answer, so the test
    # could not tell a read from a literal. Mutation testing caught exactly
    # that on the first run.
    with patch.object(welcome_email, "_dispatch", _fake), \
         patch.object(welcome_email, "monthly_limit_for_plan", lambda p: 4321):
        welcome_email.send_plan_dropped_email("x@y.com", "Dana", reason)

    body = captured["text"]
    assert "Dana" in body
    assert "4,321" in body, "the quota is typed into the copy, not read"
    # Something to do, and a way to answer.
    assert "pick a plan" in body
    assert "reply" in body.lower()
    # Nothing was deleted is the reassurance that matters most here.
    assert "Nothing was deleted" in body


def test_the_promo_message_never_mentions_a_payment_problem():
    """Nothing failed when a gift runs out. Blaming a card would be a lie
    the reader can check against their own bank."""
    from utils import welcome_email

    captured = {}
    with patch.object(welcome_email, "_dispatch",
                      lambda e, s, t, h: captured.update(text=t) or True):
        welcome_email.send_plan_dropped_email("x@y.com", "Dana", "promo_ended")

    lowered = captured["text"].lower()
    for word in ("card", "stripe", "payment", "failed"):
        assert word not in lowered, f"the promo message mentions {word!r}"


def test_the_payment_message_does_not_pretend_to_be_news():
    """They have had Stripe's dunning emails for a fortnight — every
    customer-email toggle was switched on 2026-08-10. Announcing it as a
    surprise would read as though we had not been watching."""
    from utils import welcome_email

    captured = {}
    with patch.object(welcome_email, "_dispatch",
                      lambda e, s, t, h: captured.update(text=t) or True):
        welcome_email.send_plan_dropped_email("x@y.com", "Dana", "payment_failed")

    assert "you'll have had its emails" in captured["text"]


def test_the_welcome_email_reads_the_free_limit_too():
    """Found while writing this: send_welcome_email had 250 typed into it in
    two places, in a file that already imports monthly_limit_for_plan."""
    from utils import welcome_email

    captured = {}
    with patch.object(welcome_email, "_dispatch",
                      lambda e, s, t, h: captured.update(text=t, html=h) or True), \
         patch.object(welcome_email, "monthly_limit_for_plan", lambda p: 4321):
        welcome_email.send_welcome_email("x@y.com", "Dana")

    # Same trick as above: a value the free tier has never had, so a
    # reinstated literal cannot coincide with the assertion.
    assert "4,321" in captured["text"]
    assert "4,321" in captured["html"]
