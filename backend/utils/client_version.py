"""How old is the extension asking us this?

Two settings have been waiting on "both stores have published, and enough
people have updated": UPLOAD_LIMIT_FOLLOWS_QUOTA and
FIRST_SIGNIN_INCLUDE_MAIL_READ. Both are global switches whose safety
depends on what the CLIENT can do, and a global switch cannot express that.
The cost is not the flip itself — it is remembering that the flip is owed,
weeks later, after two store reviews on someone else's schedule.

The version is already here. backendFetch sends X-Extension-Version on every
authenticated request (extension/background.js:910), and /auth/login can
carry it as a query parameter the same way it already carries `ext` and
`aid`. So a behaviour that a newer panel understands and an older one does
not can simply ask, per request, instead of being switched on for everyone
at a moment we have to remember.

WHAT "OLD" MEANS HERE. Absent, empty, unparseable, or lower than the
minimum: all old. That is deliberate and one-directional — every caller uses
this to decide whether to give a client something NEW, so an unknown version
gets today's behaviour rather than tomorrow's. A missing header is a client
we cannot vouch for, and there is no version of that argument where guessing
"probably new" is the safe half.
"""
from __future__ import annotations

import re

# Chrome and Edge both accept up to four dot-separated integers. We ship
# three; the fourth is parsed rather than rejected so a hotfix build like
# 0.2.3.1 does not read as older than 0.2.3.
_VERSION = re.compile(r"^\s*(\d{1,5})(?:\.(\d{1,5})){0,3}\s*$")


def parse_version(raw: str | None) -> tuple[int, ...] | None:
    """A version string as a tuple of ints, or None if it is not one.

    None rather than a zero tuple: "unparseable" and "0.0.0" are different
    facts, and only one of them means someone sent us something strange.
    """
    if not raw or not isinstance(raw, str):
        return None
    if not _VERSION.match(raw):
        return None
    try:
        return tuple(int(part) for part in raw.strip().split("."))
    except ValueError:  # pragma: no cover — the regex already guarantees it
        return None


def client_at_least(raw: str | None, minimum: tuple[int, ...]) -> bool:
    """True when the calling extension is at least `minimum`.

    Compared as integers, not as text: "0.2.10" is newer than "0.2.9", and
    string comparison says the opposite. That mistake has a long history in
    software that ships version numbers, and it becomes reachable here the
    day a patch number passes nine.

    Shorter tuples compare as if zero-padded, so "0.2" is below (0, 2, 3)
    and "0.2.3.1" is above it.
    """
    parsed = parse_version(raw)
    if parsed is None:
        return False
    width = max(len(parsed), len(minimum))
    padded = parsed + (0,) * (width - len(parsed))
    wanted = tuple(minimum) + (0,) * (width - len(minimum))
    return padded >= wanted
