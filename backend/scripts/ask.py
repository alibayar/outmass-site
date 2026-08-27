"""Ask PostHog a question from the terminal.

    cd backend && python scripts/ask.py --signups 3
    cd backend && python scripts/ask.py --trail someone@example.com
    cd backend && python scripts/ask.py --errors 24
    cd backend && python scripts/ask.py "SELECT event, count() FROM events
                                         WHERE timestamp >= now() - INTERVAL 1 DAY
                                         GROUP BY event ORDER BY 2 DESC"

Why this file exists
--------------------

The funnel answers — where a new user stopped, whether a send failed, how long
install-to-first-campaign took — were only ever reachable through an editor
integration. On 2026-08-27 that connection dropped mid-session and every one of
those questions became unanswerable, on a day two new users had signed up. The
data was fine; the only road to it had a gate on it.

So this is the road we own. Same endpoint the daily report and green check
already use (`/api/projects/{id}/query/` with a personal API key), no plugin in
the path, and it runs anywhere the key does.

What it needs
-------------

`POSTHOG_PERSONAL_API_KEY` in the environment (backend/.env is gitignored and
is the right home for it). Create it at

    PostHog → Settings → Personal API keys → New key

and give it READ scopes only — "Query: read" plus project read is enough for
everything here. This script never writes, and a read-only key means a leaked
key cannot change anything either.

Project id and host already default to the live EU project, so the key is the
only thing to add.

Identity note: server-side events use the user's EMAIL as distinct_id, and the
extension identifies by email too once someone signs in. Events from before
sign-in carry an anonymous id, so `--trail` will not show them — that gap is
the consent-screen leak, not a bug in this script.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from config import (  # noqa: E402
    POSTHOG_API_HOST,
    POSTHOG_PERSONAL_API_KEY,
    POSTHOG_PROJECT_ID,
)

TIMEOUT = 60.0


def run(hogql: str) -> tuple[list[str], list[list]]:
    """Execute one HogQL query. Raises with the server's own words on failure —
    a truncated error here would send the reader looking in the wrong place."""
    resp = httpx.post(
        f"{POSTHOG_API_HOST}/api/projects/{POSTHOG_PROJECT_ID}/query/",
        headers={"Authorization": f"Bearer {POSTHOG_PERSONAL_API_KEY}"},
        json={"query": {"kind": "HogQLQuery", "query": hogql}},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise SystemExit(
            f"PostHog returned {resp.status_code}\n\n{resp.text[:1500]}"
        )
    payload = resp.json()
    return payload.get("columns") or [], payload.get("results") or []


def show(hogql: str) -> None:
    print(hogql.strip())
    print()
    columns, rows = run(hogql)
    if not rows:
        print("(no rows)")
        return
    widths = [len(str(c)) for c in columns]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))
    line = "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(columns))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(
            str(cell).ljust(widths[i]) if i < len(widths) else str(cell)
            for i, cell in enumerate(row)
        ))
    print(f"\n{len(rows)} row(s)")


# ── Presets: the questions actually asked, so they are not re-typed ──

def q_signups(days: str) -> str:
    """Everyone whose FIRST EVER event falls in the window, and what they did.

    Deliberately no WHERE on timestamp. With one, min(timestamp) is only the
    first event inside the window, so every returning user looks new — the
    first run of this preset reported bellmed and a two-week-old account as
    fresh sign-ups. The aggregate has to see all of history to know what is
    actually first.

    Ordered newest first, with the event count and the last thing they did:
    enough to tell "signed in and left" from "signed in and got somewhere".
    """
    return (
        "SELECT distinct_id, min(timestamp) AS first_seen, "
        "max(timestamp) AS last_seen, count() AS events, "
        "count(DISTINCT event) AS kinds, "
        "argMax(event, timestamp) AS last_event "
        "FROM events "
        "GROUP BY distinct_id "
        f"HAVING first_seen >= now() - INTERVAL {int(days)} DAY "
        "ORDER BY first_seen DESC"
    )


def q_trail(who: str) -> str:
    """One person's events in order. The answer to "where did they stop"."""
    safe = who.replace("'", "''")
    return (
        "SELECT timestamp, event, "
        "coalesce(properties.error_code, '') AS error_code, "
        "coalesce(toString(properties.recipient_count), '') AS recipients "
        "FROM events "
        f"WHERE distinct_id = '{safe}' "
        "AND timestamp >= now() - INTERVAL 90 DAY "
        "ORDER BY timestamp"
    )


def q_errors(hours: str) -> str:
    """Failures in the window, split by code, with how many people hit each."""
    return (
        "SELECT event, coalesce(properties.error_code, '') AS error_code, "
        "count() AS n, count(DISTINCT distinct_id) AS users, "
        "max(timestamp) AS latest "
        "FROM events "
        f"WHERE timestamp >= now() - INTERVAL {int(hours)} HOUR "
        "AND (event LIKE '%failed%' OR event LIKE '%error%') "
        "GROUP BY event, error_code ORDER BY n DESC"
    )


PRESETS = {
    "--signups": (q_signups, "3", "new distinct_ids and what they did"),
    "--trail": (q_trail, None, "one person's events in order (pass an email)"),
    "--errors": (q_errors, "24", "failures by code"),
}


def main() -> None:
    if not POSTHOG_PERSONAL_API_KEY:
        raise SystemExit(
            "POSTHOG_PERSONAL_API_KEY is not set, so there is nothing to ask "
            "with.\n\n"
            "Create one at PostHog -> Settings -> Personal API keys -> New "
            "key, with READ scopes only (Query: read + project read), then "
            "put it in backend/.env as:\n\n"
            "    POSTHOG_PERSONAL_API_KEY=phx_...\n\n"
            "backend/.env is gitignored. Project id and host already default "
            "to the live EU project, so the key is the only thing missing."
        )

    args = sys.argv[1:]
    if not args:
        print(__doc__)
        print("Presets:")
        for flag, (_, default, what) in PRESETS.items():
            suffix = f" (default {default})" if default else ""
            print(f"  {flag:<12} {what}{suffix}")
        return

    if args[0] in PRESETS:
        builder, default, _ = PRESETS[args[0]]
        arg = args[1] if len(args) > 1 else default
        if arg is None:
            raise SystemExit(f"{args[0]} needs an argument")
        show(builder(arg))
        return

    show(" ".join(args))


if __name__ == "__main__":
    main()
