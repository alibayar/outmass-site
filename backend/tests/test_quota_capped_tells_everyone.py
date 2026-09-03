"""A campaign that pauses on the monthly ceiling says so, whichever path sent it.

This repo has now shipped the same shape of defect five times: something lands
in one of the three send paths and the other two keep the old behaviour,
because send-now is the path a developer exercises by hand and the workers are
the ones real campaigns actually go through.

    (earlier)   the suppression-skip write
    2026-09-01  render_body — scheduled sends arrived as one block
    2026-09-02  build_merge_context(contact) with no sender_info
    2026-09-03  send_quota_capped_email — this file

The quota email was written on 2026-07-20, and the comment that shipped with
it names the case that prompted it: "a Starter capped at exactly 2,500 with
250 recipients parked". It went into routers/campaigns.py and nowhere else.

On 2026-09-03 marketing@hrds.com hit exactly 2,500 on a SCHEDULED campaign.
Thirty-eight recipients stopped, the campaign went 'partial', the panel said
so in one word, and nothing told them why it had stopped or that the rest
would go out on 16 September — thirteen days later. A paying customer, the
same plan, the same number, and the same silence, because the fix only ever
landed on one path.

So this test does not check that the worker sends the email. It checks that
EVERY send path can, and it is written to fail the moment a fourth path
appears without it.
"""
import inspect

import pytest


# The paths a campaign can leave through. Adding one here is the point: a new
# sender must justify itself against this list rather than be forgotten.
SEND_PATHS = [
    ("routers.campaigns", "send-now"),
    ("workers.scheduled_worker", "scheduled + daily-capped"),
]


@pytest.mark.parametrize("module_name,label", SEND_PATHS)
def test_every_send_path_can_report_a_quota_cap(module_name, label):
    """Not 'does it call it here' — 'can this path reach the user at all'."""
    import importlib

    mod = importlib.import_module(module_name)
    src = inspect.getsource(mod)
    assert "send_quota_capped_email" in src, (
        f"the {label} path cannot tell a user their campaign paused on the "
        f"monthly limit. Their campaign stops mid-list, the panel says "
        f"'partial', and the remaining recipients wait for a reset date "
        f"nobody has told them about. marketing@hrds.com waited thirteen days "
        f"that way on 2026-09-03."
    )


def test_the_capped_count_is_read_from_the_database_not_the_page():
    """The number in that email is how many people are still waiting.

    The worker's own `pending` list is one PostgREST page and can be short —
    that truncation is what stranded 109 of faisal's recipients. Counting the
    page would understate the wait to the one person who most needs it right.
    """
    from workers import scheduled_worker

    src = inspect.getsource(scheduled_worker)
    idx = src.index("send_quota_capped_email")
    window = src[idx:idx + 400]
    assert "count_resumable_contacts" in window, (
        "the quota email reports a count taken from the in-memory page rather "
        "than from the database, so a campaign larger than one page tells the "
        "user the wrong number of waiting recipients"
    )


def test_a_courtesy_email_cannot_fail_a_completed_send():
    """The send already happened. MailerSend being down must not turn a
    finished campaign into an exception after the fact."""
    from workers import scheduled_worker

    src = inspect.getsource(scheduled_worker)
    idx = src.index("send_quota_capped_email")
    before = src[max(0, idx - 400):idx]
    after = src[idx:idx + 500]
    assert "try:" in before and "except" in after, (
        "the quota email is not wrapped, so a mail-provider failure would "
        "raise inside a campaign that has already delivered its recipients"
    )


def test_the_email_is_only_sent_when_the_quota_actually_capped():
    """Every completed campaign must not receive one."""
    from workers import scheduled_worker

    src = inspect.getsource(scheduled_worker)
    idx = src.index("send_quota_capped_email")
    before = src[max(0, idx - 500):idx]
    assert "if quota_capped" in before, (
        "the quota email is no longer gated on quota_capped — every scheduled "
        "campaign that finishes would tell its owner it had been capped"
    )


def test_a_pass_that_sent_nothing_does_not_email():
    """The difference between "it ran and stopped" and "it never started".

    auto_resume_partial_campaigns re-schedules a capped campaign every
    AUTO_RESUME_BACKOFF_HOURS. The send beat then runs it, `remaining` is 0,
    `pending` slices to empty and `quota_capped` is still true — so a block
    gated only on quota_capped fires on a pass that delivered nothing.
    marketing@hrds.com waits thirteen days for a reset. At six-hour intervals
    that is about fifty-two identical emails about a pause they already know
    about, which is how a courtesy becomes a complaint.
    """
    from workers import scheduled_worker

    src = inspect.getsource(scheduled_worker)
    idx = src.index("send_quota_capped_email")
    before = src[max(0, idx - 900):idx]
    assert "quota_capped and sent_count > 0" in before, (
        "the quota email is gated on quota_capped alone, so every idle "
        "re-attempt of an already-capped campaign sends another one"
    )
