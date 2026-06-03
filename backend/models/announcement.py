"""
OutMass — Announcement model helpers.

In-app one-way announcements. Visibility, read/dismiss merging, and the
settings summary are computed in Python (the table is tiny) so the logic
is unit-testable with the fake Supabase client.
"""

from datetime import datetime, timezone

from database import get_db


def _parse_ts(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _now():
    return datetime.now(timezone.utc)


def _list_active() -> list[dict]:
    result = (
        get_db()
        .table("announcements")
        .select("*")
        .eq("active", True)
        .limit(200)
        .execute()
    )
    return result.data or []


def _reads_for_user(user_id: str) -> dict:
    result = (
        get_db()
        .table("announcement_reads")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    out = {}
    for r in (result.data or []):
        out[r["announcement_id"]] = r
    return out


def _is_within_window(row: dict, now: datetime) -> bool:
    starts = _parse_ts(row.get("starts_at"))
    if starts and starts > now:
        return False
    expires = _parse_ts(row.get("expires_at"))
    if expires and expires <= now:
        return False
    return True


def _is_for_user(row: dict, user_id: str) -> bool:
    if row.get("audience") == "broadcast":
        return True
    return row.get("audience") == "targeted" and row.get("user_id") == user_id


def _is_visible(row: dict, user_id: str, now: datetime) -> bool:
    # FakeSupabase ignores .eq filters, so enforce everything in Python.
    if not row.get("active"):
        return False
    if not _is_within_window(row, now):
        return False
    return _is_for_user(row, user_id)


def get_user_announcements(user_id: str) -> list[dict]:
    """Active, in-window, audience-matching, non-dismissed announcements
    with per-user read/dismissed flags. Sorted: high priority first, then
    newest first.

    NOTE: the `version` field is intentionally NOT filtered here — the
    client suppresses version-tagged items until its running version
    reaches that version (it has the manifest; the server does not)."""
    now = _now()
    reads = _reads_for_user(user_id)
    out = []
    for row in _list_active():
        if not _is_visible(row, user_id, now):
            continue
        rd = reads.get(row["id"], {})
        if rd.get("dismissed_at"):
            continue
        out.append({
            "id": row["id"],
            "audience": row["audience"],
            "priority": row.get("priority", "normal"),
            "title": row["title"],
            "body": row["body"],
            "cta_label": row.get("cta_label"),
            "cta_url": row.get("cta_url"),
            "version": row.get("version"),
            "created_at": row.get("created_at"),
            "read": bool(rd.get("read_at")),
            "dismissed": False,
        })
    # Two stable sorts compose to: high-priority group first, newest-first
    # within each group. (Sort by recency first, then a stable sort by
    # priority preserves that recency order inside each priority bucket.)
    out.sort(key=lambda a: a.get("created_at") or "", reverse=True)
    out.sort(key=lambda a: 0 if a["priority"] == "high" else 1)
    return out


def get_summary_for_user(user_id: str) -> dict:
    """Compact signal for GET /settings: unread count + the single
    highest-priority unread item to render as the top strip."""
    items = get_user_announcements(user_id)
    unread = [a for a in items if not a["read"]]
    banner = None
    high_unread = [a for a in unread if a["priority"] == "high"]
    if high_unread:
        b = high_unread[0]
        banner = {
            "id": b["id"], "priority": b["priority"], "title": b["title"],
            "cta_label": b["cta_label"], "cta_url": b["cta_url"],
            "version": b["version"],
        }
    return {"unread": len(unread), "banner": banner}


def _exists(announcement_id: str, user_id: str) -> bool:
    now = _now()
    for row in _list_active():
        if row["id"] == announcement_id and _is_visible(row, user_id, now):
            return True
    return False


def mark_read(announcement_id: str, user_id: str) -> bool:
    if not _exists(announcement_id, user_id):
        return False
    # Partial upsert: we deliberately omit dismissed_at so a `read` arriving
    # AFTER a dismiss (e.g. bell-open marks all unread read) can't un-dismiss.
    # Supabase upsert only writes the supplied columns, so an existing
    # dismissed_at on the conflicting row is preserved.
    get_db().table("announcement_reads").upsert(
        {"announcement_id": announcement_id, "user_id": user_id,
         "read_at": _now().isoformat()},
        on_conflict="announcement_id,user_id",
    ).execute()
    return True


def mark_dismissed(announcement_id: str, user_id: str) -> bool:
    if not _exists(announcement_id, user_id):
        return False
    get_db().table("announcement_reads").upsert(
        {"announcement_id": announcement_id, "user_id": user_id,
         "read_at": _now().isoformat(), "dismissed_at": _now().isoformat()},
        on_conflict="announcement_id,user_id",
    ).execute()
    return True
