"""A clean send-now campaign must reach 'sent' — and increment quota ONCE.

Regression test for a bug I shipped on 2026-08-06 (commit 9a8153f) and caught
the same day only because a spawned task made me re-examine four "pre-existing"
test failures I had accepted on a review agent's word.

The bug: `_run_campaign_send` carried `import logging` inside two of its except
blocks. A function-local import makes that name local for the ENTIRE function,
so the module-level `import logging` added by the same commit was shadowed and
the new summary-log line raised UnboundLocalError — at the very end of an
otherwise perfect send.

The damage was in the recovery path, not the send. Emails went out fine; then
the function-level handler ran `increment_sent_count` a SECOND time (it had
already run before the log line) and wrote status 'partial'. So a clean
campaign charged the user's monthly quota twice and reported itself as
partially sent. Nobody was hit: zero send_completed events between the deploy
and the fix.

Two lessons pinned here rather than in a comment nobody re-reads:
  - a green suite is the release gate, so a red test must be explained, never
    accepted. "Pre-existing" was asserted by a reviewer and repeated by me
    without either of us bisecting it. `git worktree` + one pytest run found
    the exact commit in two minutes.
  - the quota assertion below matters more than the status one: a wrong status
    is visible in Reports, a double-charged quota is not.
"""
from unittest.mock import AsyncMock, patch

from tests.conftest import FAKE_STARTER_USER


def _contact(cid, email):
    return {"id": cid, "email": email, "unsubscribed": False}


def test_clean_send_lands_on_sent_and_charges_quota_once():
    import asyncio

    from routers import campaigns as campaigns_router

    increments = []
    updates = []

    async def _ok(**kwargs):
        return {"success": True}

    with patch("models.contact.mark_sent"), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.update_campaign",
               side_effect=lambda cid, payload: updates.append(payload)), \
         patch("models.user.increment_sent_count",
               side_effect=lambda uid, n: increments.append(n)), \
         patch("routers.campaigns._send_single_email", new=AsyncMock(side_effect=_ok)), \
         patch("routers.campaigns.SEND_DELAY_SECONDS", 0):
        asyncio.run(campaigns_router._run_campaign_send(
            campaign_id="camp-clean",
            campaign={"id": "camp-clean", "subject": "Hi", "body": "Hello",
                      "attachments": []},
            send_list=[_contact("c1", "a@example.com"), _contact("c2", "b@example.com")],
            ab_test=None,
            half=0,
            ab_remaining=[],
            access_token="tok",
            user=dict(FAKE_STARTER_USER),
            suppressed_emails=set(),
        ))

    assert updates[-1] == {"status": "sent"}, (
        f"a clean send must close as 'sent', got {updates[-1]} — an exception "
        "escaping to the outer handler writes 'partial' and hides a crash"
    )
    assert increments == [2], (
        f"quota must be charged exactly once per recipient, got {increments} — "
        "the outer handler re-increments, so any exception after the first "
        "increment silently double-charges the user's monthly limit"
    )


def test_cancelled_mid_send_still_charges_the_recipients_that_went_out():
    """A deploy during a send must not give the emails away for free.

    asyncio.CancelledError has derived from BaseException since Python 3.8,
    so `except Exception` does not catch it — and uvicorn raises exactly that
    into in-flight background tasks when it shuts down on SIGTERM, which
    happens on every deploy.

    Each recipient is marked 'sent' and counted into campaigns.sent_count as
    the loop runs, but the user's monthly quota is charged once at the end.
    Cancelled in between, the per-contact state was durable and the quota
    charge simply vanished: the emails went out, nothing was counted, and the
    resumed remainder was later charged against a quota that had never seen
    them.
    """
    import asyncio

    from routers import campaigns as campaigns_router

    increments = []
    updates = []
    calls = {"n": 0}

    async def _ok_then_cancelled(**kwargs):
        calls["n"] += 1
        if calls["n"] > 2:
            raise asyncio.CancelledError()
        return {"success": True}

    async def _run():
        await campaigns_router._run_campaign_send(
            campaign_id="camp-cancel",
            campaign={"id": "camp-cancel", "subject": "Hi", "body": "Hello",
                      "attachments": []},
            send_list=[_contact("c%d" % i, "u%d@example.com" % i) for i in range(5)],
            ab_test=None,
            half=0,
            ab_remaining=[],
            access_token="tok",
            user=dict(FAKE_STARTER_USER),
            suppressed_emails=set(),
        )

    with patch("models.contact.mark_sent"), \
         patch("models.contact.mark_failed"), \
         patch("models.campaign.increment_stat"), \
         patch("models.campaign.update_campaign",
               side_effect=lambda cid, payload: updates.append(payload)), \
         patch("models.user.increment_sent_count",
               side_effect=lambda uid, n: increments.append(n)), \
         patch("routers.campaigns._send_single_email",
               new=AsyncMock(side_effect=_ok_then_cancelled)), \
         patch("routers.campaigns.SEND_DELAY_SECONDS", 0):
        try:
            asyncio.run(_run())
        except asyncio.CancelledError:
            cancelled = True
        else:
            cancelled = False

    assert cancelled, (
        "CancelledError must propagate — swallowing it tells the event loop "
        "this task is still alive while it is shutting down"
    )
    assert increments == [2], (
        f"the 2 recipients that actually went out must be charged, got "
        f"{increments} — anything else is either free email or double billing"
    )
    assert updates and updates[-1] == {"status": "partial"}, (
        f"a cancelled send must land on 'partial', got {updates}; 'sending' "
        "waits an hour for the sweep and 'scheduled' is invisible to every "
        "recovery path"
    )


def test_quota_is_charged_in_batches_so_a_kill_cannot_lose_the_lot():
    """A SIGKILL runs no handler, so no except block can rescue the charge.

    The only thing that survives a kill is what was already written. Charging
    once after the loop meant a Railway deploy mid-send left every recipient
    already emailed and marked 'sent' uncharged — durable per-contact state
    saying they went out, a counter saying they never did, and the resumed
    remainder later billed against a quota that had never seen the first half.
    """
    import asyncio

    from routers import campaigns as campaigns_router

    increments = []

    async def _ok(**kwargs):
        return {"success": True}

    with patch("models.contact.mark_sent"),          patch("models.campaign.increment_stat"),          patch("models.campaign.update_campaign"),          patch("models.user.increment_sent_count",
               side_effect=lambda uid, n: increments.append(n)),          patch("routers.campaigns._send_single_email", new=AsyncMock(side_effect=_ok)),          patch("routers.campaigns.QUOTA_CHARGE_BATCH", 10),          patch("routers.campaigns.SEND_DELAY_SECONDS", 0):
        asyncio.run(campaigns_router._run_campaign_send(
            campaign_id="camp-batched",
            campaign={"id": "camp-batched", "subject": "Hi", "body": "Hello",
                      "attachments": []},
            send_list=[_contact("c%d" % i, "u%d@example.com" % i) for i in range(25)],
            ab_test=None,
            half=0,
            ab_remaining=[],
            access_token="tok",
            user=dict(FAKE_STARTER_USER),
            suppressed_emails=set(),
        ))

    assert sum(increments) == 25, (
        f"every recipient must be charged exactly once, got {increments}"
    )
    assert len(increments) > 1, (
        "the whole point is that the charge lands DURING the loop, not only "
        f"after it — got a single write of {increments}"
    )
    assert increments == [10, 10, 5], (
        f"expected two full batches then the remainder, got {increments}"
    )


def test_a_kill_after_the_first_batch_still_leaves_that_batch_charged():
    """The bound, stated as a number: at most QUOTA_CHARGE_BATCH - 1 free."""
    import asyncio

    from routers import campaigns as campaigns_router

    increments = []
    calls = {"n": 0}

    async def _ok_then_die(**kwargs):
        calls["n"] += 1
        if calls["n"] > 12:
            raise asyncio.CancelledError()
        return {"success": True}

    async def _run():
        await campaigns_router._run_campaign_send(
            campaign_id="camp-killed",
            campaign={"id": "camp-killed", "subject": "Hi", "body": "Hello",
                      "attachments": []},
            send_list=[_contact("c%d" % i, "u%d@example.com" % i) for i in range(25)],
            ab_test=None,
            half=0,
            ab_remaining=[],
            access_token="tok",
            user=dict(FAKE_STARTER_USER),
            suppressed_emails=set(),
        )

    with patch("models.contact.mark_sent"),          patch("models.contact.mark_failed"),          patch("models.campaign.increment_stat"),          patch("models.campaign.update_campaign"),          patch("models.user.increment_sent_count",
               side_effect=lambda uid, n: increments.append(n)),          patch("routers.campaigns._send_single_email",
               new=AsyncMock(side_effect=_ok_then_die)),          patch("routers.campaigns.QUOTA_CHARGE_BATCH", 10),          patch("routers.campaigns.SEND_DELAY_SECONDS", 0):
        try:
            asyncio.run(_run())
        except asyncio.CancelledError:
            pass

    assert sum(increments) == 12, (
        f"12 went out, so 12 must be charged — no more (double billing) and "
        f"no fewer (free email). Got {increments}"
    )


def test_logging_is_not_shadowed_inside_the_send_path():
    """The specific trap, pinned by name.

    `import logging` inside any function body makes `logging` local to that
    whole function, so a module-level import stops working there — silently,
    and only on the lines that run BEFORE the local import. Nothing about the
    code looks wrong at the call site.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "routers" / "campaigns.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Import):
                for alias in inner.names:
                    if alias.name == "logging":
                        offenders.append(f"{node.name}:{inner.lineno}")

    assert not offenders, (
        f"function-local 'import logging' at {offenders} shadows the "
        "module-level import for the entire function — this exact pattern "
        "raised UnboundLocalError on every completed send in 9a8153f"
    )
