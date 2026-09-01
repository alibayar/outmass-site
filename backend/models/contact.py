"""
OutMass — Contact model helpers
"""

import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from config import SUPABASE_MAX_ROWS
from database import get_db
from utils.email_classifier import is_role_account, is_disposable

logger = logging.getLogger(__name__)

# Simple email regex for validation
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _is_uuid(value: str) -> bool:
    """True if `value` is a well-formed UUID string.

    contacts.id is a Postgres UUID column. Public tracking routes take the
    id straight from the URL, so scanners / link-truncating clients send
    garbage. Querying with a non-UUID raises 22P02 (invalid input syntax
    for type uuid) → unhandled 500. Callers use this to short-circuit
    before the query.
    """
    if not value or not isinstance(value, str):
        return False
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def bulk_insert(
    campaign_id: str,
    contacts: list[dict],
    suppressed: set[str] | None = None,
) -> dict:
    """Insert contacts for a campaign.

    Normalizes email to lowercase, deduplicates within the input list,
    skips invalid emails, and skips addresses present in `suppressed`.

    Returns a dict with counts:
        {"inserted": int, "skipped_invalid": int,
         "skipped_duplicate": int, "skipped_suppressed": int}
    """
    suppressed = {s.lower() for s in (suppressed or set())}
    seen: set[str] = set()
    rows: list[dict] = []
    skipped_invalid = 0
    skipped_duplicate = 0
    skipped_suppressed = 0
    warn_role = 0
    warn_disposable = 0

    for c in contacts:
        raw = (c.get("email") or "").strip().lower()
        if not raw or not EMAIL_REGEX.match(raw):
            skipped_invalid += 1
            continue
        if raw in suppressed:
            skipped_suppressed += 1
            continue
        if raw in seen:
            skipped_duplicate += 1
            continue
        # A.4: role-account + disposable warnings (counted, not skipped)
        if is_role_account(raw):
            warn_role += 1
        if is_disposable(raw):
            warn_disposable += 1
        seen.add(raw)
        rows.append(
            {
                "campaign_id": campaign_id,
                "email": raw,
                "first_name": c.get("firstName", c.get("first_name", "")),
                "last_name": c.get("lastName", c.get("last_name", "")),
                "company": c.get("company", ""),
                "position": c.get("position", ""),
                "custom_fields": {
                    k: v
                    for k, v in c.items()
                    if k
                    not in (
                        "email",
                        "firstName",
                        "first_name",
                        "lastName",
                        "last_name",
                        "company",
                        "position",
                    )
                },
                "status": "pending",
            }
        )

    if not rows:
        return {
            "inserted": 0,
            "skipped_invalid": skipped_invalid,
            "skipped_duplicate": skipped_duplicate,
            "skipped_suppressed": skipped_suppressed,
            "warn_role": warn_role,
            "warn_disposable": warn_disposable,
        }

    result = get_db().table("contacts").insert(rows).execute()
    inserted = len(result.data) if result.data else len(rows)
    return {
        "inserted": inserted,
        "skipped_invalid": skipped_invalid,
        "skipped_duplicate": skipped_duplicate,
        "skipped_suppressed": skipped_suppressed,
        "warn_role": warn_role,
        "warn_disposable": warn_disposable,
    }


def _warn_if_truncated(rows: list, what: str, campaign_id: str) -> list:
    """Say so when a read came back exactly at the server ceiling.

    PostgREST returns a short list and no error, so a truncated read is
    indistinguishable from a complete one unless something checks the length.
    Nothing did, and campaign 91e7ce08 sent 1000 of 1020 recipients and then
    reported itself finished.

    This only makes the loss audible. It cannot make the read complete — the
    caller must never decide "there is nothing left" from a list.
    """
    if len(rows) >= SUPABASE_MAX_ROWS:
        logger.error(
            "%s for campaign %s came back at the %s-row server ceiling and is "
            "almost certainly truncated. Do NOT treat this list as the whole "
            "population; count_resumable_contacts is the honest answer.",
            what, campaign_id, SUPABASE_MAX_ROWS,
        )
    return rows


def get_pending_contacts(campaign_id: str) -> list[dict]:
    """Get all pending (unsent) contacts for a campaign.

    Bounded explicitly at the server ceiling so the bound is visible here
    rather than applied invisibly by PostgREST.
    """
    result = (
        get_db()
        .table("contacts")
        .select("*")
        .eq("campaign_id", campaign_id)
        .eq("status", "pending")
        .eq("unsubscribed", False)
        .limit(SUPABASE_MAX_ROWS)
        .execute()
    )
    return _warn_if_truncated(result.data or [], "get_pending_contacts", campaign_id)


def get_contact(contact_id: str) -> dict | None:
    # contacts.id is a UUID column — a non-UUID id (truncated tracking link,
    # scanner garbage) can never match a real contact and would otherwise
    # crash the query with 22P02. Treat it as "not found".
    if not _is_uuid(contact_id):
        return None
    result = (
        get_db()
        .table("contacts")
        .select("*")
        .eq("id", contact_id)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def _now_iso() -> str:
    """Return current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def mark_sent(contact_id: str):
    # M-02: Use proper ISO timestamp instead of string "now()"
    get_db().table("contacts").update(
        {"status": "sent", "sent_at": _now_iso()}
    ).eq("id", contact_id).execute()


_FAILABLE_STATUSES = ("deferred", "failed")


def mark_failed(contact_id: str, status: str = "failed"):
    """Mark a contact as failed (permanent) or deferred (transient/retryable).

    deferred → retryable later (rate-limit, 5xx, network); included by Resume.
    failed   → permanent (4xx invalid recipient); excluded from Resume.
    Any other status is ignored defensively.
    """
    if status not in _FAILABLE_STATUSES:
        return
    (
        get_db()
        .table("contacts")
        .update({"status": status})
        .eq("id", contact_id)
        # A contact Graph has already accepted must never be rewound. Every
        # send loop marks the contact 'sent' and then does more work — stats,
        # quota — inside the same try, so a failure in that later work lands
        # in an except that calls this function for a recipient who HAS been
        # emailed. Rewinding them to 'deferred' puts them back in
        # get_resumable_contacts, and the auto-resume beat then mails them a
        # second time with no user action. The status filter makes that
        # impossible at the one place all four loops funnel through.
        .neq("status", "sent")
        .execute()
    )


def mark_suppressed(contact_id: str):
    """Record that a send loop skipped this contact for the suppression list.

    Addresses on the list are normally filtered at upload time, so this only
    catches the ones added AFTER the CSV went in (including anyone who
    unsubscribed from an earlier campaign — that adds them to the list).
    Those contacts used to be skipped with a bare `continue`, leaving them
    'pending' forever: they stayed in every resumable set, inflating what
    Resume and the auto-resume beat thought was left to do, and a campaign
    whose only remaining "pending" were suppressed would churn
    scheduled → sent on each pass.

    Deliberately NOT reversible: if the user later removes the address from
    the suppression list, this contact stays skipped rather than quietly
    becoming sendable again. Re-emailing someone who was on a do-not-email
    list has to be a deliberate act (upload them again), not a side effect.
    """
    get_db().table("contacts").update(
        {"status": "suppressed"}
    ).eq("id", contact_id).execute()


def get_resumable_contacts(campaign_id: str) -> list[dict]:
    """Contacts eligible for (re)sending: never-attempted + transiently-failed.

    Excludes permanently `failed` (retry is futile), `suppressed` (the user
    asked us not to email them) and already `sent`. Used by the send loop,
    the scheduled worker, and the Resume endpoint so a partial campaign's
    recoverable contacts go out on the next run.
    """
    result = (
        get_db()
        .table("contacts")
        .select("*")
        .eq("campaign_id", campaign_id)
        .in_("status", ["pending", "deferred"])
        .eq("unsubscribed", False)
        .limit(SUPABASE_MAX_ROWS)
        .execute()
    )
    return _warn_if_truncated(
        result.data or [], "get_resumable_contacts", campaign_id
    )


def count_resumable_contacts(campaign_id: str) -> int:
    """How many recipients this campaign could still be sent to.

    A COUNT, and that is the entire point. Every list read above is capped at
    SUPABASE_MAX_ROWS, so len(get_resumable_contacts(...)) answers "how big was
    the page", not "how many are there". A count aggregate is computed
    server-side and is not paged, so it is the only honest answer to the one
    question the close-out asks: is this campaign actually finished.
    """
    result = (
        get_db()
        .table("contacts")
        .select("id", count="exact")
        .eq("campaign_id", campaign_id)
        .in_("status", ["pending", "deferred"])
        .eq("unsubscribed", False)
        .limit(1)
        .execute()
    )
    return result.count or 0


def has_resumable_contacts(campaign_id: str) -> bool:
    """count_resumable_contacts, failing CLOSED.

    Every caller is deciding whether to write 'sent', and 'sent' is terminal:
    no beat, sweep or endpoint in this product selects a 'sent' campaign, and
    nothing compares sent_count to total_contacts. 'partial' is recoverable —
    auto-resume picks it up and closes it properly once a later count comes
    back zero. So when the count cannot be taken, the safe answer is "yes,
    there is more", not "no".
    """
    try:
        return count_resumable_contacts(campaign_id) > 0
    except Exception:  # noqa: BLE001
        logger.warning(
            "could not count resumable contacts for campaign %s — treating the "
            "campaign as unfinished, which auto-resume will correct",
            campaign_id, exc_info=True,
        )
        return True


def get_last_sent_at(campaign_id: str) -> str | None:
    """When the LAST recipient of this campaign received it, or None.

    A campaign is not an instant. A daily-capped one delivers over days or
    weeks, and "follow up three days later" has to mean three days after the
    recipient got it — not three days after the campaign row was created,
    which for a paced send can fall before a single email has gone out.
    """
    result = (
        get_db()
        .table("contacts")
        .select("sent_at")
        .eq("campaign_id", campaign_id)
        .not_.is_("sent_at", "null")
        .order("sent_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0].get("sent_at") if rows else None


def mark_opened(contact_id: str):
    get_db().table("contacts").update(
        {"opened_at": _now_iso()}
    ).eq("id", contact_id).is_("opened_at", "null").execute()


def mark_clicked(contact_id: str):
    get_db().table("contacts").update(
        {"clicked_at": _now_iso()}
    ).eq("id", contact_id).is_("clicked_at", "null").execute()


def set_ab_variant(contact_id: str, variant: str):
    """Set the A/B test variant for a contact."""
    get_db().table("contacts").update(
        {"ab_variant": variant}
    ).eq("id", contact_id).execute()


def mark_unsubscribed(contact_id: str):
    get_db().table("contacts").update({"unsubscribed": True}).eq(
        "id", contact_id
    ).execute()


# A hard ceiling on the export, far above any real campaign (the largest send
# in 90 days was 1,876 recipients). It exists so a corrupt campaign_id or a
# runaway row count cannot pull an unbounded result into memory, not as a
# product limit.
EXPORT_MAX_ROWS = 50_000


def get_all_contacts(campaign_id: str) -> list[dict]:
    """Every contact on a campaign, for CSV export. Paged, not truncated.

    This used to be one bounded read, and the bound was PostgREST's server-side
    max-rows. The docstring said "a silently short export hands the user a file
    that looks complete and is not" and then handed them exactly that: the
    warning went to a server log, and the user got 1,000 rows of a 1,210-row
    campaign with nothing to indicate the difference. An export is the one
    place a short answer is indistinguishable from a complete one, because the
    file has no idea what it is missing.

    Two round trips for a campaign of 1,210 and one for everything smaller.
    """
    db = get_db()
    rows: list[dict] = []
    start = 0
    while start < EXPORT_MAX_ROWS:
        page = (
            db.table("contacts")
            .select("*")
            .eq("campaign_id", campaign_id)
            .order("id")           # a stable order, or paging can skip or repeat
            .range(start, start + SUPABASE_MAX_ROWS - 1)
            .execute()
        )
        batch = page.data or []
        rows.extend(batch)
        if len(batch) < SUPABASE_MAX_ROWS:
            return rows
        start += SUPABASE_MAX_ROWS

    logger.error(
        "campaign %s export hit the %s-row ceiling; the file is short",
        campaign_id, EXPORT_MAX_ROWS,
    )
    return rows


def count_delivered_contacts(campaign_id: str) -> int:
    """How many distinct recipients actually received this campaign.

    The honest denominator for every engagement rate, and NOT the same number
    as campaigns.sent_count, for two reasons:

      1. A follow-up bumps sent_count (followup_worker.py, the increment_stat
         after its loop) but never touches contacts.status — a follow-up goes
         to someone already marked 'sent'. So a 100-person campaign whose
         follow-up reached 80 has sent_count 180, and every rate divided by it
         reads roughly half what it should. Invisible today only because no
         real user has received a follow-up yet; it appears on the first one.
      2. It is a COUNT. The stats endpoint used to walk a page of contacts to
         work out engagement, and that page is capped at SUPABASE_MAX_ROWS, so
         above a thousand recipients the numerator was short while the
         denominator was not.

    A COUNT aggregate is computed server-side and is not paged.
    """
    result = (
        get_db()
        .table("contacts")
        .select("id", count="exact")
        .eq("campaign_id", campaign_id)
        .eq("status", "sent")
        .limit(1)
        .execute()
    )
    return result.count or 0


def get_campaign_contacts_count(campaign_id: str) -> int:
    result = (
        get_db()
        .table("contacts")
        .select("id", count="exact")
        .eq("campaign_id", campaign_id)
        .execute()
    )
    return result.count or 0
