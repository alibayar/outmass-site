"""Every scheduled beat entry must name a task the worker actually knows.

On 2026-08-08 a helper function was inserted directly beneath the
`@celery.task` line belonging to `reset_stuck_sending_campaigns` (5e912d8).
The decorator transferred to the helper. The beat entry kept dispatching
`workers.scheduled_worker.reset_stuck_sending_campaigns`, no worker had it
registered, and Celery answered `NotRegistered` — every hour, for 24 days,
into a log nobody reads.

Nothing else noticed, because the sweep's job is to clean up after a rare
crash: its absence looks exactly like nothing having gone wrong. It surfaced
on 2026-09-01 only because a deploy landed while campaigns were in flight and
someone went looking for what would rescue them.

This is a whole class of bug — a beat entry is a STRING, so a rename, a move
between modules, or a decorator that walks off is not a NameError anywhere.
The check costs one import.
"""


def test_every_beat_entry_names_a_registered_task():
    from workers.celery_app import celery

    # Import exactly what the worker process imports, in the same way.
    for module in celery.conf.include:
        __import__(module)

    registered = set(celery.tasks.keys())
    missing = {
        name: cfg["task"]
        for name, cfg in celery.conf.beat_schedule.items()
        if cfg["task"] not in registered
    }

    assert not missing, (
        f"beat schedules a task nothing registers: {missing}. Celery dispatches "
        f"the name on every tick and gets NotRegistered back, silently — which "
        f"is how the stuck-'sending' sweep was dead from 2026-08-08 to 09-01. "
        f"Usual cause: a @celery.task decorator that now sits on the function "
        f"above the one it belongs to."
    )


def test_the_stuck_sending_sweep_in_particular_is_registered():
    """Named on its own because of what it costs when it is not.

    It is the only path that recovers a campaign left in 'sending' by a worker
    that died mid-loop. Nothing else queries that status: the send beat wants
    'scheduled', Resume 409s on anything but 'partial', auto-resume wants
    'partial'. Without this task those recipients are reachable by nothing.
    """
    from workers import scheduled_worker  # noqa: F401
    from workers.celery_app import celery

    assert (
        "workers.scheduled_worker.reset_stuck_sending_campaigns" in celery.tasks
    ), "the stuck-'sending' sweep is not a registered task"


def test_mark_partial_is_not_dispatchable():
    """Its first argument is a live Supabase client.

    It cannot be serialised onto a broker, so registering it as a task can
    only ever produce a runtime failure — and the decorator being on it is
    the exact mistake that took the sweep off the air.
    """
    from workers import scheduled_worker  # noqa: F401
    from workers.celery_app import celery

    assert "workers.scheduled_worker._mark_partial" not in celery.tasks, (
        "_mark_partial is registered as a Celery task; it takes a database "
        "client as its first argument and is called in-process"
    )
