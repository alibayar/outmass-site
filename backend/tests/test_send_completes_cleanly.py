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
