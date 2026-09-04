"""One account, read-only: did this person actually manage to send?

    cd backend && python scripts/whois.py someone@example.com

Answers the question we keep asking about a new signup — did they get through
the funnel or stall in it — without a round trip through the Supabase editor.
SELECTs only; nothing here writes.

Gate 0 exists because of green.py's own scar, recorded in its docstring: the
first run of that script on a laptop found an empty users table and cheerfully
reported "0 accounts, ok". A local .env can point at the wrong database or
carry a key with no rights, and every count then reads as a clean zero. So the
first thing printed is the size of the users table, and a zero there means
STOP — not "this person did nothing".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_db  # noqa: E402


def _count(table, **eq):
    q = get_db().table(table).select("id", count="exact").limit(1)
    for k, v in eq.items():
        q = q.eq(k, v)
    return q.execute().count or 0


def main(email):
    db = get_db()

    total = _count("users")
    print("users in this database: %d" % total)
    if total == 0:
        print("\nSTOP. An empty users table means the credentials are wrong, "
              "not that the product has no users.")
        return 1
    print()

    rows = (
        db.table("users").select("*").eq("email", email).execute().data or []
    )
    if not rows:
        print("no user row for %s" % email)
        return 0
    u = rows[0]

    print("=" * 68)
    print("%s  (%s)" % (email, u.get("name") or "no name"))
    print("=" * 68)
    for f in ("id", "plan", "comp_plan", "comp_plan_until", "created_at",
              "last_activity_at", "emails_sent_this_month", "emails_sent_total",
              "month_reset_date", "requires_reauth", "reauth_reason",
              "preferred_language", "last_seen_extension_version"):
        if f in u:
            print("  %-26s %s" % (f, u.get(f)))

    camps = (
        db.table("campaigns")
        .select("*")
        .eq("user_id", u["id"])
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    print("\ncampaigns: %d" % len(camps))
    for c in camps:
        cid = c["id"]
        total_c = _count("contacts", campaign_id=cid)
        sent = (
            db.table("contacts")
            .select("id", count="exact")
            .eq("campaign_id", cid)
            .not_.is_("sent_at", "null")
            .limit(1)
            .execute()
            .count
            or 0
        )
        last = (
            db.table("contacts")
            .select("sent_at")
            .eq("campaign_id", cid)
            .not_.is_("sent_at", "null")
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        print("\n  %-28s %s%s" % (
            (c.get("name") or "(unnamed)")[:28],
            c.get("status"),
            "  ARCHIVED" if c.get("archived") else "",
        ))
        print("    created      %s" % c.get("created_at"))
        print("    scheduled_for %s   daily_cap %s   send_days %s" % (
            c.get("scheduled_for"), c.get("daily_send_cap"), c.get("send_days")))
        print("    contacts %d   with sent_at %d   last sent %s" % (
            total_c, sent, last[0]["sent_at"] if last else "never"))
        if "stalled_notice_at" in c:
            print("    stalled_notice_at %s" % c.get("stalled_notice_at"))
        print("    opened %s  clicked %s  replied %s" % (
            c.get("opened_count"), c.get("clicked_count"), c.get("replied_count")))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
