"""Is it safe to spend money on traffic yet — asked from inside production.

There are two ways to read this report and they must never be two reports:

  * ``send_green_report`` — a daily beat task that builds it in production,
    against the production database, and sends the short form to Telegram.
  * ``scripts/green.py`` — the same builder, printed in full, for when you
    want the detail.

The split exists because the first attempt was a local script, and its first
real run was read against a laptop's .env: the users table came back empty,
every check reported "0 accounts, ok", and it looked like health. Running it
where the credentials already live removes the question of which credentials
it used. Running it from one builder removes the question of whether the two
answers agree.

## What it is for

At fourteen installs, unknowns do not shrink by waiting — they shrink by
traffic. So the useful split is not "is anything unknown" but:

  * things that get WORSE with spend — a checkout writing fictional billing
    state, a sign-in leaking at the top of the funnel, a first email nobody
    has read. Each visitor multiplies them. Those are gates.
  * things that get BETTER with spend — everything you only learn from
    users. Marketing is the instrument that resolves those, not the risk.

## What it deliberately does not do

Reads only: writes nothing, changes nothing, sends no customer email.

It does not answer Gate 1 for the web service. Railway variables are
per-service, this task runs on the beat, and a report that read the beat's
Stripe key and called it "the answer" would be the same confident wrongness
it exists to catch. The per-service answer already has an instrument — the
startup guard alerts on every deploy, naming its service — and this points
at that rather than impersonating it.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from config import STRIPE_SECRET_KEY, SUPABASE_URL, monthly_limit_for_plan
from utils.config_guard import _db_looks_production, _stripe_mode
from workers.celery_app import celery

PASS, CHECK, FAIL, INFO, HEAD = "ok", "check", "FAIL", "", "head"


class EmptyDatabase(RuntimeError):
    """Zero user rows. Not health — the credentials did not reach anybody."""


@dataclass(frozen=True)
class Line:
    mark: str
    text: str
    #: Explanatory prose. Kept in the full report, dropped from Telegram,
    #: which has a hard length limit and is read on a phone.
    detail: bool = False


def _age_days(iso) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


def _rows(db) -> list[dict]:
    res = (
        db.table("users")
        .select(
            "email, plan, created_at, last_login_at, last_activity_at, "
            "last_seen_extension_version, stripe_customer_id, "
            "stripe_subscription_id, month_reset_date, last_cycle_invoice_at, "
            "emails_sent_this_month, emails_sent_total, requires_reauth, "
            "manual_promo_until, preferred_language"
        )
        .limit(1000)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise EmptyDatabase(
            "the users table returned zero rows. We have paying customers, so "
            "this is credentials that did not reach them — most likely "
            "SUPABASE_KEY is the anon key rather than the service role, in "
            "which case row-level security answers with an empty set and no "
            f"error at all. URL in use: {SUPABASE_URL}"
        )
    return rows


def build(db, *, role: str = "beat") -> list[Line]:
    """The whole report, as lines. Raises EmptyDatabase rather than
    describing a population it never saw."""
    rows = _rows(db)
    out: list[Line] = [Line(INFO, f"{len(rows)} user row(s)")]

    # ── Gate 1 ──
    out.append(Line(HEAD, "GATE 1 — Stripe key"))
    mode = _stripe_mode(STRIPE_SECRET_KEY)
    prod_db = _db_looks_production(SUPABASE_URL)
    if mode is None:
        out.append(Line(INFO, f"no Stripe key on the {role} service"))
    elif mode == "test" and prod_db:
        out.append(Line(FAIL, f"{role}: TEST key against the production database"))
    elif mode == "live" and not prod_db:
        out.append(Line(FAIL, f"{role}: LIVE key against a non-production database"))
    else:
        out.append(Line(PASS, f"{role}: {mode} key, production database"))
    out.append(Line(
        INFO,
        "The WEB service is the only one that creates checkouts and its key "
        "is a different variable. That answer arrives as a startup alert on "
        "every deploy, naming its service — this task cannot see it.",
        detail=True,
    ))

    # ── Gate 2 ──
    out.append(Line(HEAD, "GATE 2 — Microsoft consent screen (#48)"))
    out.append(Line(CHECK, "PostHog, by hand: oauth_started -> oauth_completed"))
    out.append(Line(
        INFO,
        "34 people lost between them. It sits above everything else in the "
        "funnel, so every acquired user walks into it. No honest proxy for it "
        "exists in our database, so none is invented here.",
        detail=True,
    ))

    # ── Gate 3 ──
    out.append(Line(HEAD, "GATE 3 — welcome email"))
    try:
        from emails import render

        msg = render(
            "welcome", name="Ada", free_quota=f"{monthly_limit_for_plan('free'):,}"
        )
        ok = bool(msg.subject.strip() and msg.text.strip() and msg.html.strip())
        out.append(Line(PASS if ok else FAIL, "renders in production"))
    except Exception as e:  # noqa: BLE001
        out.append(Line(FAIL, f"the renderer raised: {e}"))
    fresh = [r for r in rows if (_age_days(r.get("created_at")) or 99) <= 3]
    out.append(Line(CHECK, f"{len(fresh)} sign-up(s) in 3 days"))
    out.append(Line(
        INFO,
        "Rendering proves the code, not that MailerSend accepted the two-part "
        "payload or that it looks right in a real inbox. One sign-in with a "
        "throwaway account does.",
        detail=True,
    ))

    # ── Extension actually in use ──
    out.append(Line(HEAD, "Extension in real use"))
    seen: dict[str, int] = {}
    for r in rows:
        seen[r.get("last_seen_extension_version") or "(never called back)"] = (
            seen.get(r.get("last_seen_extension_version") or "(never called back)", 0) + 1
        )
    for v, n in sorted(seen.items(), reverse=True):
        out.append(Line(INFO, f"{v}: {n}"))
    out.append(Line(
        INFO,
        "This column is written only on an authenticated request, so it means "
        "somebody USED it — unlike an auto-update, which fires while nobody "
        "is at the keyboard.",
        detail=True,
    ))

    # ── Renewals ──
    out.append(Line(HEAD, "Quota rollover — is the Stripe event path alive?"))
    subs = [r for r in rows if r.get("stripe_subscription_id")]
    stamped = [r for r in subs if r.get("last_cycle_invoice_at")]
    out.append(Line(INFO, f"{len(subs)} subscriber(s), {len(stamped)} confirmed"))
    for r in subs:
        stamp, anchor = r.get("last_cycle_invoice_at"), r.get("month_reset_date")
        if not stamp:
            out.append(Line(INFO, f"{r.get('email')}: anchor {anchor}, none yet"))
        elif str(stamp)[:10] == str(anchor):
            out.append(Line(PASS, f"{r.get('email')}: Stripe confirmed {str(stamp)[:10]}"))
        else:
            out.append(Line(
                CHECK,
                f"{r.get('email')}: anchor {anchor} but Stripe said "
                f"{str(stamp)[:10]} — the backstop rolled it, webhook late",
            ))
    if subs and not stamped:
        out.append(Line(
            INFO,
            "Expected until the first renewal after 2026-08-14. Still empty a "
            "month from now means the webhook is not arriving and every paid "
            "rollover is running on the backstop.",
            detail=True,
        ))

    # ── Health ──
    out.append(Line(HEAD, "Health"))
    reauth = [r for r in rows if r.get("requires_reauth")]
    out.append(Line(
        PASS if not reauth else CHECK,
        f"{len(reauth)} dead Microsoft connection(s)"
        + ("" if not reauth else ": " + ", ".join(str(r.get("email")) for r in reauth[:5])),
    ))
    capped = [
        r for r in rows
        if (r.get("emails_sent_this_month") or 0)
        >= monthly_limit_for_plan(r.get("plan") or "free")
    ]
    out.append(Line(
        PASS if not capped else CHECK,
        f"{len(capped)} at their monthly cap"
        + ("" if not capped else ": " + ", ".join(str(r.get("email")) for r in capped[:5])),
    ))
    today = date.today()
    rolled = 0
    for r in rows:
        try:
            if 0 <= (today - date.fromisoformat(str(r.get("month_reset_date")))).days <= 2:
                rolled += 1
        except (ValueError, TypeError):
            continue
    out.append(Line(INFO, f"{rolled} rolled over in the last 2 days"))
    known = [r for r in rows if r.get("preferred_language")]
    out.append(Line(INFO, f"{len(known)}/{len(rows)} know their language"))
    return out


def as_text(lines: list[Line]) -> str:
    """Everything, for a terminal."""
    parts = []
    for ln in lines:
        if ln.mark == HEAD:
            parts.append(f"\n{ln.text}\n" + "─" * len(ln.text))
        else:
            parts.append(f"[{ln.mark:^6}] {ln.text}")
    return "\n".join(parts)


def as_telegram(lines: list[Line]) -> str:
    """The short form. Telegram caps a message at 4096 characters and this is
    read on a phone, so the explanatory prose is dropped — it is in the full
    report and in this module's docstring, and neither is going anywhere."""
    icon = {PASS: "✅", CHECK: "🟡", FAIL: "🔴", INFO: "·"}
    parts = ["📊 OutMass — green check", ""]
    for ln in lines:
        if ln.detail:
            continue
        if ln.mark == HEAD:
            parts.append(f"\n*{ln.text}*")
        else:
            parts.append(f"{icon.get(ln.mark, '·')} {ln.text}")
    parts.append("\nFull report: cd backend && python scripts/green.py")
    return "\n".join(parts)


@celery.task
def send_green_report():
    """Daily, from production, to Telegram.

    Never raises. This is a report about health; a report that can take the
    beat down with it would be a poor one.
    """
    from routers.billing import _telegram_alert

    try:
        from database import get_db

        lines = build(get_db(), role="beat")
        _telegram_alert(as_telegram(lines))
        return {"lines": len(lines)}
    except EmptyDatabase as e:
        _telegram_alert(
            "🔴 OutMass — green check could not run\n\n"
            f"{e}\n\n"
            "Nothing else is reported, because every line below would have "
            "been computed over an empty list and printed as though it passed."
        )
        return {"error": "empty_database"}
    except Exception as e:  # noqa: BLE001
        _telegram_alert(f"🔴 OutMass — green check crashed: {e}")
        return {"error": str(e)}


if __name__ == "__main__":  # pragma: no cover
    # Run it now, from a Railway shell, without waiting for 07:00:
    #
    #     cd backend && python -m workers.green_report
    #
    # Prints the full report to the shell AND sends the short form to
    # Telegram, so the on-demand run and the daily one cannot tell different
    # stories about the same morning.
    #
    # WHICH SERVICE you run it in changes exactly one line: Gate 1 reads the
    # Stripe key of the process it is in. Run it on WEB to answer the gate
    # that actually matters — web is the only service that creates checkouts.
    # The scheduled run is on beat, and says so.
    import sys

    try:
        from database import get_db

        lines = build(get_db(), role="this service")
        print(as_text(lines))
    except EmptyDatabase as e:
        print(f"STOP — {e}")
        sys.exit(2)
    except Exception as e:  # noqa: BLE001
        # A raw traceback here would be a stack full of supabase internals
        # ending in "Invalid API key", which says nothing about what to do.
        print(f"could not build the report: {e}")
        print(
            "Run this inside a service that already has SUPABASE_URL and "
            "SUPABASE_KEY — a Railway shell on web, worker or beat. It is "
            "not meant to be run from a laptop; that is the mistake this "
            "whole task exists to remove."
        )
        sys.exit(1)
    send_green_report()
