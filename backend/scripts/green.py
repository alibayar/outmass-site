"""Are we green enough to spend money on traffic?

    cd backend && python scripts/green.py

Run it with the PRODUCTION env (the same SUPABASE_URL / STRIPE_SECRET_KEY the
web service uses), because that is the only environment whose answers matter.

## Why this exists

On 2026-08-14 the question was "when do our unknowns shrink enough to market
hard?" and the honest answer was that unknowns do not shrink by waiting — at
fourteen installs and one event an hour, they shrink by traffic. Every defect
found that day came from looking, not from a user reporting one.

So the useful split is not "is anything unknown" but:

  * things that get WORSE with spend — a broken checkout, a leaking sign-in,
    a first email nobody has read. Each new visitor multiplies them. These
    are gates.
  * things that get BETTER with spend — everything you only learn from
    users. Marketing is the instrument that resolves those, not the risk.

This prints the first list, plus the readouts that answer themselves over the
next few days, so the decision is made on numbers instead of nerve.

## What it deliberately does not do

It changes nothing, writes nothing, and sends nothing. It also does not
pretend to know things it cannot see: the Microsoft consent-screen leak lives
in PostHog, not in our database, and is printed as a manual gate rather than
guessed at from a proxy that would agree with us for the wrong reason.
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import STRIPE_SECRET_KEY, SUPABASE_URL, monthly_limit_for_plan  # noqa: E402
from database import get_db  # noqa: E402
from utils.config_guard import _db_looks_production, _stripe_mode  # noqa: E402

PASS, CHECK, FAIL, INFO = "  ok  ", " CHECK", " FAIL ", "      "


def line(mark: str, text: str) -> None:
    print(f"[{mark}] {text}")


def head(text: str) -> None:
    print(f"\n{text}\n" + "─" * len(text))


def _rows() -> list[dict]:
    """Every user row, or an abort.

    An empty list is NOT a clean bill of health, and the first real run of
    this script proved how badly it reads as one: zero rows produced
    "0 accounts with a dead Microsoft connection [ok]", "0 sitting at their
    cap [ok]", and a quota section reporting nothing to confirm. Every line
    was true and every line was meaningless, because there was nothing behind
    them.

    We have paying customers. Zero rows means the credentials did not reach
    them, not that they are fine — so the caller stops here rather than
    printing a page of reassuring nothing.
    """
    return (
        get_db()
        .table("users")
        .select(
            "email, plan, created_at, last_login_at, last_activity_at, "
            "last_seen_extension_version, stripe_customer_id, "
            "stripe_subscription_id, month_reset_date, last_cycle_invoice_at, "
            "emails_sent_this_month, emails_sent_total, requires_reauth, "
            "manual_promo_until, preferred_language"
        )
        .limit(1000)
        .execute()
    ).data or []


def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


# ── The three that get worse with spend ──


def gate_stripe_key() -> None:
    head("GATE 1 — the Stripe key, in THIS environment")
    mode = _stripe_mode(STRIPE_SECRET_KEY)
    prod_db = _db_looks_production(SUPABASE_URL)

    if mode is None:
        line(CHECK, "no Stripe key set here — this is not the web service")
    elif mode == "test" and prod_db:
        line(FAIL, "TEST key against the PRODUCTION database.")
        line(INFO, "Checkouts write customer and subscription ids that exist")
        line(INFO, "in no live Stripe account, and daily_report counts those")
        line(INFO, "rows as paying subscribers. This happened on 2026-04-17")
        line(INFO, "and went unnoticed for four months.")
    elif mode == "live" and not prod_db:
        line(FAIL, "LIVE key against a non-production database.")
    else:
        line(PASS, f"{mode} key, {'production' if prod_db else 'non-production'} database")

    line(INFO, "Railway variables are PER SERVICE, and this reads the process")
    line(INFO, "you started — so if you ran it on your own machine, it is")
    line(INFO, "describing YOUR .env and says nothing about what the web")
    line(INFO, "service has. Web is the only service that creates checkouts;")
    line(INFO, "the worker and beat never call Stripe at all (verified 08-14).")
    line(INFO, "The web service's own answer arrives as a startup alert.")


def gate_consent_screen() -> None:
    head("GATE 2 — the Microsoft consent screen (#48)")
    line(CHECK, "not in our database — this one is PostHog, by hand")
    line(INFO, "Funnel: oauth_started → oauth_completed. 34 people were lost")
    line(INFO, "between them. It sits ABOVE everything else in the funnel, so")
    line(INFO, "every acquired user walks into it. Acquisition spend before")
    line(INFO, "this is paying to fill a bucket with a hole at the top.")


def gate_welcome_email(rows: list[dict]) -> None:
    head("GATE 3 — the welcome email, rebuilt 2026-08-14")
    try:
        from emails import render

        msg = render("welcome", name="Ada", free_quota=f"{monthly_limit_for_plan('free'):,}")
        ok = bool(msg.subject.strip() and msg.text.strip() and msg.html.strip())
        line(PASS if ok else FAIL, f"renders here: {msg.subject!r}")
        line(INFO, f"text {len(msg.text)} chars, html {len(msg.html)} chars")
    except Exception as e:  # noqa: BLE001
        line(FAIL, f"the renderer raised: {e}")

    fresh = [r for r in rows if (_age_days(r.get("created_at")) or 99) <= 3]
    if fresh:
        line(CHECK, f"{len(fresh)} sign-up(s) in the last 3 days — one of them")
        line(INFO, "received the first welcome email from the new renderer:")
        for r in fresh[:5]:
            line(INFO, f"  {r.get('email')}  ({_age_days(r.get('created_at')):.1f}d ago)")
    else:
        line(CHECK, "no sign-ups in 3 days, so nobody has received one yet")
    line(INFO, "Rendering here proves the code. It does not prove MailerSend")
    line(INFO, "accepted the new two-part payload or that it looks right in a")
    line(INFO, "real inbox. Signing in once with a throwaway account does.")


# ── The readouts that answer themselves ──


def readout_extension(rows: list[dict]) -> None:
    head("Extension actually in use")
    seen: dict[str, int] = {}
    for r in rows:
        v = r.get("last_seen_extension_version") or "(never called back)"
        seen[v] = seen.get(v, 0) + 1
    for v, n in sorted(seen.items(), reverse=True):
        line(INFO, f"{v:<24} {n}")
    line(INFO, "This column is written only when the extension makes an")
    line(INFO, "authenticated request, so it means REAL USE — unlike an")
    line(INFO, "auto-update, which fires while nobody is at the keyboard.")


def readout_renewals(rows: list[dict]) -> None:
    head("Quota rollover — is the Stripe event path alive?")
    subs = [r for r in rows if r.get("stripe_subscription_id")]
    stamped = [r for r in subs if r.get("last_cycle_invoice_at")]
    line(INFO, f"{len(subs)} subscriber(s), {len(stamped)} with a confirmed renewal")

    if not subs:
        line(INFO, "nothing to confirm yet")
        return
    for r in subs:
        stamp = r.get("last_cycle_invoice_at")
        anchor = r.get("month_reset_date")
        if not stamp:
            line(INFO, f"{r.get('email')}: anchor {anchor}, no renewal seen yet")
            continue
        agree = str(stamp)[:10] == str(anchor)
        line(
            PASS if agree else CHECK,
            f"{r.get('email')}: anchor {anchor}, Stripe confirmed {str(stamp)[:10]}"
            + ("" if agree else "  ← backstop rolled it, webhook late or lost"),
        )
    if subs and not stamped:
        line(INFO, "Expected until the first renewal AFTER 2026-08-14. If this")
        line(INFO, "is still empty a month from now, the webhook is not")
        line(INFO, "arriving and every paid rollover is running on the backstop.")


def readout_health(rows: list[dict]) -> None:
    head("Health")
    reauth = [r for r in rows if r.get("requires_reauth")]
    line(
        PASS if not reauth else CHECK,
        f"{len(reauth)} account(s) with a dead Microsoft connection",
    )
    for r in reauth[:5]:
        line(INFO, f"  {r.get('email')}")

    today = date.today()
    due_soon = []
    for r in rows:
        anchor = r.get("month_reset_date")
        if not anchor:
            continue
        try:
            d = date.fromisoformat(str(anchor))
        except ValueError:
            continue
        if 0 <= (today - d).days <= 2:
            due_soon.append(r)
    line(INFO, f"{len(due_soon)} account(s) rolled over in the last 2 days")

    capped = [
        r for r in rows
        if (r.get("emails_sent_this_month") or 0)
        >= monthly_limit_for_plan(r.get("plan") or "free")
    ]
    line(
        PASS if not capped else CHECK,
        f"{len(capped)} account(s) sitting at their monthly cap",
    )
    for r in capped[:5]:
        line(INFO, f"  {r.get('email')} — {r.get('emails_sent_this_month')} sent on {r.get('plan')}")

    known_lang = [r for r in rows if r.get("preferred_language")]
    line(INFO, f"{len(known_lang)}/{len(rows)} know their language (fills with 0.2.2)")


def main() -> None:
    print("OutMass — green check")
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    try:
        rows = _rows()
    except Exception as e:  # noqa: BLE001
        print(f"\ncould not read the users table: {e}")
        print("Run this from backend/ with the production SUPABASE_URL/KEY.")
        raise SystemExit(1)

    if not rows:
        head("STOP — the users table came back empty")
        line(FAIL, "zero rows. That is not a healthy database, it is the")
        line(INFO, "wrong credentials: we have paying customers.")
        line(INFO, "")
        line(INFO, "Three things do this, in order of likelihood:")
        line(INFO, "")
        line(INFO, "1. SUPABASE_KEY is the ANON key, not the service role.")
        line(INFO, "   Row-level security then returns an empty set instead")
        line(INFO, "   of an error — no exception, no warning, no rows.")
        line(INFO, "2. SUPABASE_URL points at a different Supabase project")
        line(INFO, "   (a dev one) that genuinely has no users.")
        line(INFO, "3. You ran it with a local .env rather than the values")
        line(INFO, "   the web service actually has in Railway.")
        line(INFO, "")
        line(INFO, f"URL in this environment: {SUPABASE_URL}")
        line(INFO, "")
        line(INFO, "Everything below this point would have been computed over")
        line(INFO, "an empty list and printed as though it passed, so it is")
        line(INFO, "not printed at all.")
        raise SystemExit(2)

    line(INFO, f"{len(rows)} user row(s) read")
    gate_stripe_key()
    gate_consent_screen()
    gate_welcome_email(rows)
    readout_extension(rows)
    readout_renewals(rows)
    readout_health(rows)

    print(
        "\nThe gates get WORSE with traffic — close them first.\n"
        "Everything below them gets BETTER with traffic: they are the things\n"
        "you only learn from users, and marketing is how you learn them."
    )


if __name__ == "__main__":
    main()
