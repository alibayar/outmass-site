"""Classify a Graph send failure into a contact status.

Shared by the immediate send loop (routers.campaigns) and the scheduled
worker (workers.scheduled_worker) so both record the same 4-state semantics
without duplicating the mapping logic.
"""


def _classify_failure(status_code: int | None) -> str:
    """Map a Graph send failure to a contact status.

    Permanent (failed): 4xx except the retryable ones below — bad recipient,
        forbidden, payload too large, unprocessable.
    Transient (deferred): 408 (timeout), 409 (conflict), 429 (rate limit),
        5xx, or no status (network/timeout) — retryable on the next Resume.
    """
    if status_code is None:
        return "deferred"
    if status_code in (408, 409, 429):
        return "deferred"
    if 400 <= status_code < 500:
        return "failed"
    return "deferred"  # 5xx and anything else
