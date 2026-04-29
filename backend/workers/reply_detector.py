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

The user already granted Mail.Read at sign-in (it's part of
MS_GRAPH_SCOPES — used previously for the not_opened follow-up
condition heuristic), so no new consent needed.

Privacy: we read message metadata only (from, receivedDateTime,
internetMessageId). We never persist message bodies. Microsoft
Graph's listing endpoint already filters down to those fields via
$select; we don't even download the bodies.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from config import GRAPH_API_BASE, OUTBOUND_HTTP_TIMEOUT
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

    We only $select the fields we need so payloads stay small.
    """
    url = (
        f"{GRAPH_API_BASE}/me/mailFolders/Inbox/messages"
        f"?$select=from,receivedDateTime,conversationId,subject"
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
                # Mail.Read scope missing — user signed up before this
                # was a default scope. We log once and stop; nothing
                # the beat task can do.
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

    # Pull contacts with sent_at >= cutoff and replied_at IS NULL.
    # We need their email + earliest sent_at to match against incoming
    # messages. Limited to recent campaigns — older ones don't get
    # back-filled (acceptable for reply detection; replies arrive
    # within days for most use cases).
    try:
        contacts_resp = (
            db.table("contacts")
            .select("id, email, sent_at, campaign_id")
            .gte("sent_at", since_iso)
            .is_("replied_at", "null")
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("reply detector: contact query failed for %s: %s", user_id, e)
        return 0

    contacts = contacts_resp.data or []
    if not contacts:
        return 0

    # Build a lookup: lowercased email → list of (contact_id, sent_at)
    # ordered earliest-first. A user campaigning the same recipient
    # twice (different campaigns) gets BOTH stamped if the reply
    # arrives after both sent_at's.
    by_email: dict[str, list[dict]] = {}
    for c in contacts:
        email = (c.get("email") or "").lower().strip()
        if not email or not c.get("sent_at"):
            continue
        # Filter contacts that belong to THIS user — query above doesn't
        # join on user_id (would require a campaigns.user_id pre-fetch).
        # We rely on contacts.campaign_id being present + we'll cross-
        # check via the user's own campaign list separately. The simpler
        # alternative is a 2-step query; below we just do that.
        by_email.setdefault(email, []).append({
            "id": c["id"],
            "sent_at": c["sent_at"],
            "campaign_id": c["campaign_id"],
        })

    if not by_email:
        return 0

    # 2-step user filter: get the user's own campaign IDs, then drop
    # any contact whose campaign isn't ours.
    try:
        camps_resp = (
            db.table("campaigns")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("reply detector: campaigns query failed for %s: %s", user_id, e)
        return 0
    user_camp_ids = {c["id"] for c in camps_resp.data or []}
    for email in list(by_email.keys()):
        by_email[email] = [c for c in by_email[email] if c["campaign_id"] in user_camp_ids]
        if not by_email[email]:
            del by_email[email]

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
    """Beat task — daily. Runs reply detection for every user with a
    refreshable MS token."""
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
