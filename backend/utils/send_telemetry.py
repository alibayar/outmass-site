"""Report a send from wherever it happened, not only from the panel.

Until 2026-08-13 `send_completed` was emitted by extension/sidebar.js and by
nothing else, and no Celery worker emitted any PostHog event at all. So a send
was only visible if the user happened to have the panel open while it went
out. Everything the server does on its own — scheduled campaigns, daily-cap
continuations, follow-ups, the A/B winner pass, quota auto-resume — moved the
Supabase counter and left no trace in analytics.

What that cost, concretely: marketing@bellmed.com read as a customer about to
churn (last send 2026-07-27, six sign-ins since with nothing after them) while
their `emails_sent_this_month` was 2243 and climbing that same day. They were
running a paced campaign that sends itself, and the daily send cap was built
for them, so they were the single user most certain to be misread. The
operator nearly acted on the wrong story.

It also means `send_completed` cannot carry a funnel: the 2026-08-13 read of
119 installs -> 18 senders undercounts senders by an unknown amount, the same
way `sidebar_opened` did before 0.1.28.

This module is deliberately small and deliberately unable to fail. It is
called from inside models.user.increment_sent_count — the one function every
send path already passes through — so a send path added later is instrumented
without anyone remembering to.
"""
import logging

logger = logging.getLogger(__name__)

# The closed set of ways email leaves this system. An unknown value is still
# reported — a send we cannot label is far better than a send we cannot see —
# but it is logged, because it means a new send path appeared and nobody
# taught this module about it.
REASONS = frozenset({
    "send_now",   # routers/campaigns.py::_run_campaign_send — the user pressed Send
    "scheduled",  # workers/scheduled_worker.py::process_scheduled_campaigns
    "ab_winner",  # workers/scheduled_worker.py::evaluate_ab_tests
    "followup",   # workers/followup_worker.py::process_followups
})

# Four, not six. Two paths that feel separate are not:
#
#   * the next day's slice of a daily-capped campaign is the SAME scheduled
#     loop running again, so it reports as "scheduled" and is told apart by
#     the daily_capped property instead of by a reason of its own
#   * auto_resume_partial_campaigns (scheduled_worker.py:1314) does not send
#     anything — it flips a partial campaign back to 'scheduled' and the
#     scheduled loop does the sending, so those emails are "scheduled" too
#
# Inventing reasons for paths that do not exist would be its own kind of
# wrong number: a dashboard slice that can never be non-zero reads as a
# feature nobody uses rather than a category that was never real.


def report_emails_sent(
    user_id: str,
    count: int,
    reason: str,
    email: str | None = None,
    extra: dict | None = None,
) -> None:
    """Record that `count` emails actually went out. Never raises.

    The no-raise guarantee is load-bearing rather than defensive. Every caller
    of increment_sent_count sits in a try/except that, on failure, deliberately
    leaves `quota_charged` unadvanced so an end-of-loop flush can recharge it
    (see workers/scheduled_worker.py:189-199 for the reasoning). If telemetry
    could raise AFTER the counter has been written, that flush would charge the
    same emails a second time and eat a paying customer's quota. So this
    swallows everything, and the send loop cannot tell whether it worked.
    """
    try:
        # Imported here, not at module scope: config reads POSTHOG_API_KEY at
        # import time and conftest.py blanks it before importing anything, so
        # a late read is what lets the test suite stay silent.
        from config import POSTHOG_API_KEY

        if not POSTHOG_API_KEY:
            return
        if not count or count <= 0:
            # A zero or negative charge is a correction, not a send.
            return

        if reason not in REASONS:
            logger.warning(
                "emails_sent reported with an unknown reason %r — a new send "
                "path exists that utils/send_telemetry.py has not been told "
                "about. The event is still sent, unlabelled.",
                reason,
            )

        import posthog

        posthog.capture(
            # Email, to land on the SAME PostHog person as the login event,
            # which uses it as distinct_id (routers/auth.py). A user id here
            # would create a second person and reproduce the exact problem
            # this module exists to fix — the sends would be recorded and
            # still not show up against the customer who made them.
            distinct_id=email or user_id,
            event="emails_sent",
            properties={
                "count": count,
                "reason": reason,
                # False means the caller had only an id, so this event is
                # stranded on a person of its own. Visible rather than
                # guessed at.
                "identified": bool(email),
                # Distinguishes these from the panel's send_completed, which
                # keeps its own meaning: "a human watched this go out".
                "surface": "server",
                **(extra or {}),
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning("emails_sent capture failed", exc_info=True)
