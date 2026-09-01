"""
OutMass — Reply Detector

Daily beat task that scans each connected user's Outlook Inbox for
replies to OutMass-sent campaigns and stamps the matching contact
row with replied_at.

Why this matters:
  * Open tracking is unreliable (Outlook image-block + Apple MPP).
  * Click tracking only fires when the recipient clicks a link —
    plenty of recipients reply without clicking anything.
  * A reply is the strongest possible engagement signal.

Matching strategy (deliberately conservative — false negatives are
fine, false positives would be embarrassing):
  1. List messages from Inbox where receivedDateTime >= the
     earliest sent_at among the user's contacts that haven't
     already been marked replied_at, capped at the last 30 days.
  2. For each candidate message, compare its sender email
     (case-insensitive) against the campaign contacts whose
     sent_at is BEFORE the message's receivedDateTime.
  3. First match wins; we mark replied_at and move on. We never
     attempt to associate one inbound message with multiple
     contacts.

Mail.Read is NOT guaranteed by design — but as of 2026-08-08 it IS
guaranteed in fact, because the narrow ask has never been switched
on. MS_GRAPH_FIRST_SIGNIN_SCOPES exists and works;
FIRST_SIGNIN_INCLUDE_MAIL_READ still defaults to true, so every
live user has the scope and the 403 branch below is unreachable in
production.

That was deliberate, and the precondition it waited on is now
built. The reason "Read your mail" should leave the first consent
screen is real: it is the most alarming line shown to someone who
has not sent anything yet. The reason to wait was that a user who
declines it would lose reply detection SILENTLY - follow-ups
chasing people who already replied, and Reports showing a 0.0%
reply rate that reads as a result rather than a missing
permission.

That gap closed in 0.2.0. The panel polls has_mail_read_scope and
raises a banner offering one-click re-consent when it is false
(extension/sidebar.js, updateRepliesBanner), migration 024 is
applied and verified in production (docs/plans/migrations-applied
.md, 2026-08-28), and the 403 branch below degrades to a skip
rather than corrupting anything.

This paragraph said "nothing in the panel reads it" for twenty
days after the panel started reading it, and was quoted twice on
2026-08-28 as a live blocker. Nothing depends on this file being
right about the client - which is exactly how it stayed wrong.

Privacy: we ask Microsoft for three fields per message - the sender
address, the time it arrived, and the conversation id - and keep only
what a match needs. Bodies are never downloaded; subjects are no
longer even requested (they were, until 2026-08-28, and were thrown
away unread). The only thing written back is a replied_at stamp on
the contact row.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from config import GRAPH_API_BASE, OUTBOUND_HTTP_TIMEOUT, SUPABASE_MAX_ROWS

# How many campaign ids go into one `in_` filter. PostgREST puts the whole
# list in the query string, and a user with hundreds of campaigns would
# otherwise build a URL long enough to be refused by something in the middle.
CAMPAIGN_ID_CHUNK = 100
from models import audit
from models.ms_token import get_fresh_access_token
from workers.celery_app import celery

logger = logging.getLogger(__name__)


# How far back to look on each run. 30 days catches typical reply
# windows without trying to backfill ancient history.
REPLY_LOOKBACK_DAYS = 30

# Per-user request cap. We page through up to this many messages on
# each daily run; anything beyond this gets caught on subsequent days
# (replied_at is sticky, so re-counting is a no-op).
PER_USER_MESSAGE_CAP = 200


def _list_recent_messages(
    client: httpx.Client, access_token: str, since_iso: str
) -> list[dict]:
    """Page through Inbox messages from the last N days, returning a
    flat list of {from_email, received_at, conversation_id} dicts.

    $select carries exactly the three fields that leave this function, and
    the reason is not payload size. Until 2026-08-28 it also asked for
    `subject`, which nothing here read - Microsoft returned every subject
    line in the user's inbox for a value we dropped on the floor. Asking for
    less is the only version of "we do not read your mail" that survives
    somebody reading this file, and the user-facing sentence now says so.
    """
    url = (
        f"{GRAPH_API_BASE}/me/mailFolders/Inbox/messages"
        f"?$select=from,receivedDateTime,conversationId"
        f"&$filter=receivedDateTime ge {since_iso}"
        f"&$orderby=receivedDateTime desc"
        f"&$top=50"
    )

    out: list[dict] = []
    while url and len(out) < PER_USER_MESSAGE_CAP:
        try:
            resp = client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError as e:
            logger.warning("reply detector: list-messages network error: %s", e)
            break
        if resp.status_code != 200:
            if resp.status_code == 403:
                # Mail.Read not granted. Unreachable while
                # FIRST_SIGNIN_INCLUDE_MAIL_READ is true, which it still
                # is; it becomes the normal state for new users the day
                # that flips. Nothing for the beat task to do but skip —
                # and note that skipping is invisible to the user until
                # the panel learns to read has_mail_read_scope.
                logger.info(
                    "reply detector: 403 — user lacks Mail.Read scope"
                )
            else:
                logger.info(
                    "reply detector: messages list returned %s: %s",
                    resp.status_code, resp.text[:200],
                )
            break
        data = resp.json()
        for msg in data.get("value", []):
            sender = (msg.get("from") or {}).get("emailAddress") or {}
            email_addr = (sender.get("address") or "").lower().strip()
            received_at = msg.get("receivedDateTime")
            if email_addr and received_at:
                out.append({
                    "from_email": email_addr,
                    "received_at": received_at,
                    "conversation_id": msg.get("conversationId"),
                })
        url = data.get("@odata.nextLink")
    return out


def _find_replies_for_user(
    db,
    user_id: str,
    user_email: str | None,
    access_token: str,
) -> int:
    """Per-user reply scan. Returns the count of contacts newly stamped
    with replied_at on this run."""
    since_dt = datetime.now(timezone.utc) - timedelta(days=REPLY_LOOKBACK_DAYS)
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # The user's own campaigns FIRST, then the contacts inside them.
    #
    # This used to run the other way round: contacts were pulled with no user
    # filter and no limit, so PostgREST returned the first SUPABASE_MAX_ROWS
    # rows of the entire table and the loop below filtered them down to this
    # user afterwards. Every user therefore scanned the same global page, and
    # anyone whose contacts fell outside it was invisible to reply detection —
    # which, across 2,795 recipients emailed in a recent 30-day window, was
    # most of them.
    #
    # It is not only a wrong number in Reports. followup_worker excludes
    # contacts by replied_at, so a missed reply means we chase somebody who
    # already answered, from their correspondent's own mailbox.
    try:
        camps_resp = (
            db.table("campaigns")
            .select("id")
            .eq("user_id", user_id)
            .limit(SUPABASE_MAX_ROWS)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("reply detector: campaigns query failed for %s: %s", user_id, e)
        return 0

    user_camp_ids = [c["id"] for c in camps_resp.data or []]
    if not user_camp_ids:
        return 0
    if len(user_camp_ids) >= SUPABASE_MAX_ROWS:
        logger.error(
            "reply detector: user %s has at least %s campaigns — the campaign "
            "read is at the server ceiling and the scan below will miss the "
            "rest", user_id, SUPABASE_MAX_ROWS,
        )

    # Chunked so a user with many campaigns cannot overflow the request URL.
    contacts: list[dict] = []
    try:
        for i in range(0, len(user_camp_ids), CAMPAIGN_ID_CHUNK):
            chunk = user_camp_ids[i:i + CAMPAIGN_ID_CHUNK]
            resp = (
                db.table("contacts")
                .select("id, email, sent_at, campaign_id")
                .in_("campaign_id", chunk)
                .gte("sent_at", since_iso)
                .is_("replied_at", "null")
                .limit(SUPABASE_MAX_ROWS)
                .execute()
            )
            rows = resp.data or []
            if len(rows) >= SUPABASE_MAX_ROWS:
                logger.error(
                    "reply detector: contact read for user %s came back at the "
                    "%s-row ceiling and is probably truncated — some replies "
                    "will be missed this run",
                    user_id, SUPABASE_MAX_ROWS,
                )
            contacts.extend(rows)
    except Exception as e:  # noqa: BLE001
        logger.warning("reply detector: contact query failed for %s: %s", user_id, e)
        return 0

    if not contacts:
        return 0

    # Build a lookup: lowercased email → list of (contact_id, sent_at)
    # ordered earliest-first. A user campaigning the same recipient
    # twice (different campaigns) gets BOTH stamped if the reply
    # arrives after both sent_at's.
    #
    # No user filter here any more: the query above is already scoped to this
    # user's campaigns, which is what makes it fit in a page at all.
    by_email: dict[str, list[dict]] = {}
    for c in contacts:
        email = (c.get("email") or "").lower().strip()
        if not email or not c.get("sent_at"):
            continue
        by_email.setdefault(email, []).append({
            "id": c["id"],
            "sent_at": c["sent_at"],
            "campaign_id": c["campaign_id"],
        })

    if not by_email:
        return 0

    # Walk the user's Inbox.
    with httpx.Client(timeout=OUTBOUND_HTTP_TIMEOUT) as client:
        messages = _list_recent_messages(client, access_token, since_iso)
    if not messages:
        return 0

    stamped = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for msg in messages:
        candidates = by_email.get(msg["from_email"])
        if not candidates:
            continue
        # Don't count the user replying to themselves as a reply.
        if user_email and msg["from_email"] == user_email.lower().strip():
            continue
        # Match: any contact whose sent_at is BEFORE the message's
        # receivedDateTime. A recipient who happened to email us BEFORE
        # we sent isn't replying.
        for c in candidates:
            if c["sent_at"] < msg["received_at"]:
                try:
                    db.table("contacts").update(
                        {"replied_at": now_iso}
                    ).eq("id", c["id"]).execute()
                    stamped += 1
                except Exception:  # noqa: BLE001
                    continue
                # Remove this contact from future matching so a single
                # reply doesn't double-stamp via another iteration.
                candidates.remove(c)
                break

    if stamped:
        audit.emit(
            "replies_detected",
            user_id=user_id,
            metadata={"count": stamped},
        )
    return stamped


@celery.task
def detect_replies():
    """Beat task. Reply detection for every user who has actually sent
    something.

    Cadence went from once a day to four times on 2026-09-01, because the gap
    is the window in which a follow-up can reach somebody who already replied
    — the one thing users expect follow-ups never to do. Daily meant that
    window was up to 24 hours; six-hourly makes it at most six.

    Narrowing the population came first, and had to. This scanned every user
    holding a refreshable token, which meant reading the inbox of somebody who
    signed up and never sent an email, looking for replies to messages that do
    not exist. Multiplying that by four would have multiplied the waste, not
    the value: a Graph read and a token check each time, for an answer that
    cannot change.

    A user qualifies when they have at least one non-archived campaign that
    has sent something. No time bound — a follow-up delay can legitimately be
    a year, and a reply to a campaign from months ago still must stop it.
    """
    from database import get_db

    db = get_db()
    try:
        tokens = (
            db.table("user_tokens")
            .select("user_id")
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("reply detector: token list failed: %s", e)
        return {"checked": 0, "stamped": 0}

    user_ids = [t["user_id"] for t in (tokens.data or []) if t.get("user_id")]
    if not user_ids:
        return {"checked": 0, "stamped": 0}

    # Whose mail could contain a reply at all.
    try:
        senders = (
            db.table("campaigns")
            .select("user_id")
            .gt("sent_count", 0)
            .eq("archived", False)
            .limit(SUPABASE_MAX_ROWS)
            .execute()
        ).data or []
        with_sends = {r["user_id"] for r in senders if r.get("user_id")}
        # A short read here would silently stop scanning real senders, so say
        # so and scan everyone rather than quietly narrowing.
        if len(senders) >= SUPABASE_MAX_ROWS:
            logger.error(
                "reply detector: the sender query hit its %s-row ceiling; "
                "scanning every token holder instead of narrowing",
                SUPABASE_MAX_ROWS,
            )
        else:
            skipped = len(user_ids) - len([u for u in user_ids if u in with_sends])
            user_ids = [u for u in user_ids if u in with_sends]
            if skipped:
                logger.info(
                    "reply detector: skipped %s user(s) who have never sent",
                    skipped,
                )
    except Exception as e:  # noqa: BLE001
        # Never let the narrowing break the scan. Reading one inbox too many
        # is waste; reading one too few is a follow-up chasing somebody who
        # already wrote back.
        logger.warning("reply detector: sender narrowing failed: %s", e)

    if not user_ids:
        return {"checked": 0, "stamped": 0}

    total_stamped = 0
    checked = 0
    for user_id in user_ids:
        access_token = get_fresh_access_token(user_id)
        if not access_token:
            # Skipped users will eventually re-auth or be cleaned up by
            # the inactivity flow.
            continue
        # Pull user.email so we can ignore the user's own messages.
        try:
            user_resp = (
                db.table("users")
                .select("email")
                .eq("id", user_id)
                .execute()
            )
            user_email = (
                user_resp.data[0].get("email") if user_resp.data else None
            )
        except Exception:  # noqa: BLE001
            user_email = None
        try:
            stamped = _find_replies_for_user(db, user_id, user_email, access_token)
        except Exception:  # noqa: BLE001
            logger.exception("reply detector: unhandled error for %s", user_id)
            continue
        total_stamped += stamped
        checked += 1

    return {"checked": checked, "stamped": total_stamped}
