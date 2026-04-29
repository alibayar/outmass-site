"""
OutMass — Microsoft Graph send retry helper.

Wraps a single sendMail POST with a small, bounded retry loop for
classes of failure that are usually transient:

  * httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, etc.
  * Microsoft Graph 5xx (server-side / regional incident)
  * 429 with Retry-After (rate limit — handled separately by callers
    in some paths, but normalised here for paths that don't)

Permanent errors (4xx other than 429) are NOT retried — they indicate
a problem with the request itself (e.g. invalid recipient, body too
large, auth scope) that another retry won't fix.

Idempotency: Microsoft Graph's /me/sendMail accepts an optional
internetMessageId, but absent that, a 5xx after the message was
actually queued can produce a duplicate send on retry. Microsoft's own
documentation says the API is "best effort" idempotent on 5xx;
empirically we've seen no duplicates in OutMass's own send history
across thousands of messages. The trade-off favours retry: a missed
send is a more user-visible failure than a rare duplicate.

The retry budget is intentionally small (3 attempts total, including
the original) and uses exponential backoff capped at the configured
RATE_LIMIT_WAIT_SECONDS. We don't want to hold a worker hostage if
Microsoft is genuinely down.
"""

import logging
import time
from typing import Callable

import httpx

from config import RATE_LIMIT_WAIT_SECONDS

logger = logging.getLogger(__name__)


# Total attempts (including the original) before giving up.
MAX_ATTEMPTS = 3
# Base for exponential backoff in seconds: 1s, 4s, 16s, ... capped.
_BACKOFF_BASE = 4
_BACKOFF_CAP = RATE_LIMIT_WAIT_SECONDS  # never wait longer than the rate-limit wait


def _is_retryable_response(resp: httpx.Response) -> bool:
    """5xx server errors are retryable. 4xx (except 429) are not."""
    if resp.status_code == 429:
        return True
    return 500 <= resp.status_code < 600


def _backoff_seconds(attempt: int) -> int:
    """attempt 1 → 1s, attempt 2 → 4s, attempt 3 → 16s (capped at cap)."""
    delay = _BACKOFF_BASE ** (attempt - 1)
    return min(delay, _BACKOFF_CAP)


def post_with_retry(
    client: httpx.Client | httpx.AsyncClient,
    url: str,
    *,
    headers: dict,
    json: dict,
) -> httpx.Response:
    """Synchronous retry wrapper around a single POST.

    Returns the final httpx.Response (which may still be an error if
    retries didn't help). Network errors raise the underlying httpx
    exception only AFTER the last attempt; intermediate ones are
    swallowed and trigger a backoff sleep.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.post(url, headers=headers, json=json)
        except (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.ConnectTimeout,
            httpx.RemoteProtocolError,
        ) as e:
            last_exc = e
            if attempt < MAX_ATTEMPTS:
                wait = _backoff_seconds(attempt)
                logger.info(
                    "send_with_retry: network error attempt %s, sleeping %ss: %s",
                    attempt, wait, e,
                )
                time.sleep(wait)
                continue
            raise

        # 429 honours Retry-After; other retryables use exponential backoff
        if _is_retryable_response(resp) and attempt < MAX_ATTEMPTS:
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", _BACKOFF_CAP))
            else:
                wait = _backoff_seconds(attempt)
            logger.info(
                "send_with_retry: %s on attempt %s, sleeping %ss",
                resp.status_code, attempt, wait,
            )
            time.sleep(wait)
            continue

        return resp

    # Final attempt produced a response (or we exited due to non-retryable
    # status that didn't fall through to the return above — paranoia).
    return resp  # type: ignore[possibly-unbound]


async def async_post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict,
    json: dict,
) -> httpx.Response:
    """Async variant of post_with_retry. Same behaviour, async sleeps."""
    import asyncio

    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = await client.post(url, headers=headers, json=json)
        except (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.ConnectTimeout,
            httpx.RemoteProtocolError,
        ) as e:
            last_exc = e
            if attempt < MAX_ATTEMPTS:
                wait = _backoff_seconds(attempt)
                logger.info(
                    "async_post_with_retry: network error attempt %s, "
                    "sleeping %ss: %s",
                    attempt, wait, e,
                )
                await asyncio.sleep(wait)
                continue
            raise

        if _is_retryable_response(resp) and attempt < MAX_ATTEMPTS:
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", _BACKOFF_CAP))
            else:
                wait = _backoff_seconds(attempt)
            logger.info(
                "async_post_with_retry: %s on attempt %s, sleeping %ss",
                resp.status_code, attempt, wait,
            )
            await asyncio.sleep(wait)
            continue

        return resp

    return resp  # type: ignore[possibly-unbound]
