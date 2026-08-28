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
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

import httpx

from config import (
    POSTHOG_API_HOST,
    POSTHOG_PERSONAL_API_KEY,
    POSTHOG_PROJECT_ID,
    STRIPE_SECRET_KEY,
    SUPABASE_URL,
    monthly_limit_for_plan,
)
from utils.config_guard import _db_looks_production, _stripe_mode
from workers.celery_app import celery

logger = logging.getLogger(__name__)

PASS, CHECK, FAIL, INFO, HEAD = "ok", "check", "FAIL", "", "head"

# Events that mean a human was at the keyboard: clicks, uploads, sign-ins.
# Deliberately absent: emails_sent / send_completed (the machine finishing
# what a click started — and for scheduled campaigns nobody is there at
# all), ext_updated / ext_installed (the browser's doing), $exception.
USER_PRESENT_EVENTS = [
    "login", "signin_clicked", "oauth_started", "oauth_completed",
    "oauth_retry", "ms_auth_window_opened", "sidebar_opened",
    "compose_view_seen", "outlook_reached", "onboarding_step_viewed",
    "onboarding_completed", "onboarding_skipped", "recipients_uploaded",
    "csv_template_downloaded", "csv_upload_failed", "test_send_clicked",
    "send_clicked", "send_failed", "test_send_failed",
    "email_preview_opened", "merge_tag_chip_inserted", "ai_writer_opened",
    "followup_enabled", "schedule_send_enabled", "ab_test_enabled",
    "settings_updated", "language_changed", "template_saved",
    "template_loaded", "reports_view_changed", "campaign_results_exported",
    "upgrade_button_clicked", "manage_subscription_clicked",
    "checkout_session_created", "onedrive_consent_acknowledged",
    "onedrive_file_selected", "panel_open_failed",
]

# Ours. A rhythm read for deploy timing must not count the operator
# testing at 03:00 as a user being awake at 03:00.
INTERNAL_IDS = [
    "outmassapp@outlook.com",   # support / test inbox
    "bayar_ali@hotmail.com",    # operator's test account
    "mstest404@outlook.com",    # store review account
]

_DAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday", "Sunday",
]


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
            "stripe_subscription_id, month_reset_date, month_reset_anchor_day, "
            "last_cycle_invoice_at, "
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


def _window(totals: list[int], width: int, *, quiet: bool) -> tuple[int, int]:
    """Start hour and sum of the best contiguous `width`-hour window over a
    24h circle — the smallest-sum window when quiet, the largest otherwise.
    Ties go to the earliest start, so the answer is stable day to day."""
    sums = [sum(totals[(s + k) % 24] for k in range(width)) for s in range(24)]
    best = min(sums) if quiet else max(sums)
    start = sums.index(best)
    return start, best


def _rhythm_lines() -> list[Line]:
    """When users are actually at the keyboard, from PostHog — the section
    that answers "when do I deploy, and by when do I answer support". Never
    raises; the report must go out even when this check is broken."""
    out = [Line(HEAD, "Rhythm — when users are actually here (30d)")]
    if not POSTHOG_PERSONAL_API_KEY:
        out.append(Line(INFO, "check not configured (POSTHOG_PERSONAL_API_KEY)"))
        return out

    events = ", ".join(f"'{e}'" for e in USER_PRESENT_EVENTS)
    internal = ", ".join(f"'{i}'" for i in INTERNAL_IDS)
    # Weighted by user-days, not events: one heavy user's fifty clicks in an
    # hour count once, so the busy band is "people were here", not "somebody
    # was busy". Hours are Türkiye time — the operator's clock.
    hogql = (
        "SELECT toDayOfWeek(toTimeZone(timestamp, 'Europe/Istanbul')) AS dow, "
        "toHour(toTimeZone(timestamp, 'Europe/Istanbul')) AS h, "
        "uniq(distinct_id, toDate(toTimeZone(timestamp, 'Europe/Istanbul'))) AS user_days "
        "FROM events WHERE timestamp >= now() - INTERVAL 30 DAY "
        "AND distinct_id LIKE '%@%' "
        f"AND distinct_id NOT IN ({internal}) "
        f"AND event IN ({events}) "
        "GROUP BY dow, h"
    )
    try:
        resp = httpx.post(
            f"{POSTHOG_API_HOST}/api/projects/{POSTHOG_PROJECT_ID}/query/",
            headers={"Authorization": f"Bearer {POSTHOG_PERSONAL_API_KEY}"},
            json={"query": {"kind": "HogQLQuery", "query": hogql}},
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.warning(
                "PostHog rhythm check returned %s: %s",
                resp.status_code, resp.text[:200],
            )
            out.append(Line(INFO, "check unavailable"))
            return out
        rows = resp.json().get("results") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("PostHog rhythm check failed: %s", e)
        out.append(Line(INFO, "check unavailable"))
        return out

    day_totals = [0] * 7
    hour_totals = [0] * 24
    for dow, h, user_days in rows:
        day_totals[int(dow) - 1] += int(user_days)
        hour_totals[int(h)] += int(user_days)
    total = sum(day_totals)
    if not total:
        out.append(Line(INFO, "no user-initiated activity in 30 days"))
        return out

    top_day = max(range(7), key=lambda d: day_totals[d])
    mon_thu = sum(day_totals[:4])
    p_start, p_sum = _window(hour_totals, 6, quiet=False)
    q_start, _ = _window(hour_totals, 4, quiet=True)
    out.append(Line(
        INFO,
        f"busiest: {_DAY_NAMES[top_day]} ({round(100 * day_totals[top_day] / total)}%)"
        f" · Mon–Thu {round(100 * mon_thu / total)}%",
    ))
    out.append(Line(
        INFO,
        f"peak: {p_start:02d}:00–{(p_start + 6) % 24:02d}:00 TSİ carries "
        f"{round(100 * p_sum / total)}% — answer support before it starts",
    ))
    out.append(Line(
        INFO,
        f"quietest: {q_start:02d}:00–{(q_start + 4) % 24:02d}:00 TSİ — the "
        "deploy window",
    ))
    out.append(Line(
        INFO,
        "Measured from user-initiated events only — clicks, uploads, "
        "sign-ins — not sends the worker finished and not auto-updates, "
        "with our own accounts excluded. The bands move as the user base "
        "does; trust this line over any remembered version of it.",
        detail=True,
    ))
    return out


# The renewal path only started stamping invoices on this date (migration 031
# and the invoice.payment_succeeded handler, both 2026-08-15). A subscriber
# whose last renewal happened before it can never carry a stamp, and reading
# their blank as a missed payment costs an hour and a scare - it did on
# 2026-08-27, for a renewal Stripe had collected perfectly on 08-08.
STAMPING_SINCE = date(2026, 8, 15)


def _renewal_dates(anchor: str | None, anchor_day) -> tuple:
    """(most recent renewal that has come due, next one still ahead).

    Two corrections from the 0.2.3 review, both of which made this function
    quietly agree with itself while disagreeing with the quota engine.

    It advanced ONE month and stopped. A subscriber two cycles stale therefore
    had their first missed renewal reported as their next one - and if that
    date happened to precede STAMPING_SINCE, the caller printed a cheerful
    "nothing to see" over a renewal that never arrived. That is the exact
    shape this file exists to refuse: literally true, and read as health.

    And it took the day from month_reset_date, which is the CLAMPED value. A
    31st anchor lands on the 28th in February, and re-deriving from that gives
    the 28th forever after - the drift migration 029 added
    month_reset_anchor_day to stop, reimplemented one layer up. The anchor day
    is now passed in, exactly as models/user.py uses it.
    """
    if not anchor:
        return None, None
    try:
        a = date.fromisoformat(str(anchor)[:10])
    except ValueError:
        return None, None
    try:
        day = int(anchor_day) if anchor_day else a.day
    except (TypeError, ValueError):
        day = a.day

    today = datetime.now(timezone.utc).date()
    last_due = None
    cur = a
    for _ in range(400):  # bounded: ~33 years, and a legacy row cannot exceed it
        nxt = _shift_month(cur, day)
        if nxt is None:
            break
        # `>= today`, not `> today`. check_monthly_reset deliberately holds
        # the rollover all day waiting for Stripe's webhook, and Stripe
        # charges at the subscription's creation TIME - so on the morning of
        # a renewal there is legitimately no invoice yet. Treating today as
        # already missed printed "renewal was due <today> and no invoice
        # arrived" hours before the charge, every month, for every subscriber.
        if nxt >= today:
            return last_due, nxt
        last_due = nxt
        cur = nxt
    return last_due, None


def _shift_month(d: date, anchor_day: int):
    """One month on from `d`, landing on anchor_day when the month is long
    enough and on the last day of the month when it is not."""
    month = d.month + 1
    year = d.year + (month > 12)
    month = month - 12 if month > 12 else month
    day = anchor_day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _no_stamp_line(row: dict, anchor: str | None) -> "Line":
    """Why this subscriber has no confirmed renewal - and whether that is fine.

    Three very different states used to print the same "none yet", which is
    how a paid renewal came to look like a lost one:
      * every renewal so far predates the stamping code - nothing to see
      * the first renewal has not come round yet - nothing to see, for now
      * a renewal has passed since stamping began with no invoice - read this

    The judgement is on the LAST renewal that has come due, not the first.
    Judging the first was the 0.2.3 review's finding: a subscriber stale by
    two cycles had a missed renewal described as an upcoming one.
    """
    email = row.get("email")
    last_due, next_due = _renewal_dates(anchor, row.get("month_reset_anchor_day"))
    if last_due is None and next_due is None:
        return Line(INFO, f"{email}: no anchor to reason from")
    if last_due is None:
        return Line(INFO, f"{email}: next renewal {next_due}, not due yet")
    if last_due < STAMPING_SINCE:
        # Nothing has come due since we started stamping. Name the next date
        # that WILL prove the path - never a date already in the past.
        return Line(
            INFO,
            f"{email}: renewed {last_due}, before stamping began "
            f"{STAMPING_SINCE} — first provable renewal {next_due}",
        )
    return Line(
        CHECK,
        f"{email}: renewal was due {last_due} and no invoice arrived — check "
        "Stripe for this customer before assuming the webhook is at fault",
    )


def _posthog_rows(hogql: str, label: str):
    """One HogQL read, or None. Never raises - the report must go out even
    when a check cannot run."""
    try:
        resp = httpx.post(
            f"{POSTHOG_API_HOST}/api/projects/{POSTHOG_PROJECT_ID}/query/",
            headers={"Authorization": f"Bearer {POSTHOG_PERSONAL_API_KEY}"},
            json={"query": {"kind": "HogQLQuery", "query": hogql}},
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.warning(
                "PostHog %s returned %s: %s", label, resp.status_code,
                resp.text[:200],
            )
            return None
        return resp.json().get("results") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("PostHog %s failed: %s", label, e)
        return None


def _signin_gate_lines() -> list["Line"]:
    """GATE 2, counting PEOPLE rather than OAuth calls.

    The first automated version of this line counted `oauth_started` against
    server `login`, and the 0.2.3 review found both halves measuring the wrong
    population under a heading that names the consent screen:

      * `oauth_started` fires for the OneDrive picker and the Mail.Read banner
        as well as for sign-in, and `login` fires on every re-auth - flows
        Microsoft passes WITHOUT showing a consent screen at all. They almost
        never fail, so they inflated numerator and denominator together and
        dragged the ratio toward a green tick. That is the same confound
        config.py records having already been burned by once, this time
        automated and stamped PASS.
      * a `tenant_provisioning_race` the extension auto-retries produces one
        failure and one login for one attempt, so the old arithmetic printed
        "1 attempt, 1 completed (100%)" AND "lost: 1" beside it - a loss count
        larger than the shortfall it was derived from.

    Counting people removes both. PostHog keeps the original distinct_id on
    each event, so one person appears under an anonymous id before sign-in and
    under their email after; `$identify` carries `$anon_distinct_id`, which is
    the only thread between the halves. A person who retried and got in is
    linked, so they cannot be counted as lost - the recovery is invisible to
    this line, which is exactly right: it asks who ended up with an account.

    Thirty days, not seven. At roughly one sign-in a day a week is not a
    reading, it is a rumour.
    """
    out = [Line(HEAD, "GATE 2 — Microsoft consent screen (#48)")]
    if not POSTHOG_PERSONAL_API_KEY:
        out.append(Line(CHECK, "not configured (POSTHOG_PERSONAL_API_KEY)"))
        return out

    tried = _posthog_rows(
        "SELECT DISTINCT distinct_id FROM events WHERE event='oauth_started' "
        "AND timestamp >= now() - INTERVAL 30 DAY",
        "sign-in gate (attempts)",
    )
    linked = _posthog_rows(
        "SELECT DISTINCT toString(properties.$anon_distinct_id) AS a "
        "FROM events WHERE event='$identify' "
        "AND timestamp >= now() - INTERVAL 30 DAY",
        "sign-in gate (identities)",
    )
    if tried is None or linked is None:
        out.append(Line(CHECK, "check unavailable"))
        return out

    # An id that is already an email is a returning user signing in again;
    # they have an account, so they are not part of this question.
    anon = {r[0] for r in tried if r and r[0] and "@" not in str(r[0])}
    known = {str(r[0]) for r in linked if r and r[0] and r[0] != "None"}
    got_in = anon & known
    lost = anon - known

    # NOT an early return. A window with no anonymous starts can still
    # contain Microsoft-side failures, and returning here would have hidden
    # exactly the failures this gate exists to surface.
    no_starts = not anon
    if no_starts:
        out.append(Line(INFO, "nobody started a sign-in in the last 30 days"))

    pct = round(100 * len(got_in) / len(anon)) if anon else 0
    if anon:
        out.append(Line(
        PASS if not lost else CHECK,
            f"30d: {len(anon)} people started a sign-in, {len(got_in)} reached "
            f"an account ({pct}%)",
        ))
    if lost:
        out.append(Line(
            INFO,
            f"{len(lost)} never did — anyone who uninstalled and reinstalled "
            "gets a new anonymous id, so this is a floor",
        ))

    # The failure classes are reported separately and NOT as a ratio: most of
    # the people above never produce a failure event at all. Microsoft's window
    # opens and nothing comes back, which is the bucket it never explains.
    blame = _posthog_rows(
        "SELECT coalesce(toString(properties.attributed_to), 'unknown') AS who, "
        "count() AS n FROM events WHERE event='ms_auth_failed' "
        "AND timestamp >= now() - INTERVAL 30 DAY GROUP BY who",
        "sign-in gate (attribution)",
    )
    if blame:
        counts = {str(w): int(n) for w, n in blame}
        out.append(Line(
            INFO,
            "failure classes (30d): "
            + ", ".join(f"{n} {w}" for w, n in sorted(counts.items(), key=lambda kv: -kv[1])),
        ))
        ours = counts.get("app", 0) + counts.get("microsoft", 0)
        if ours:
            out.append(Line(
                CHECK,
                f"{ours} of those were on our side of the line — the ones "
                "worth chasing; a decline is a person choosing",
            ))
    return out


def build(db, *, role: str = "beat") -> list[Line]:
    """The whole report, as lines. Raises EmptyDatabase rather than
    describing a population it never saw."""
    rows = _rows(db)
    out: list[Line] = [Line(INFO, f"{len(rows)} user row(s)")]

    # ── Freshness canary ──
    # On 2026-08-17 and 08-18 the 07:00 UTC scheduled run reported a world
    # ~14-17 hours old — lucia's confirmed renewal, a new subscriber and a
    # 0.2.2 sighting all sat in the database while the morning report denied
    # them. Every ad-hoc run read fresh. A report that can quietly describe
    # yesterday must say how old its newest evidence is, for the same reason
    # it refuses to describe an empty table: wrongness must be visible.
    newest = None
    for r in rows:
        age = _age_days(r.get("last_activity_at"))
        if age is not None and (newest is None or age < newest):
            newest = age
    if newest is None:
        out.append(Line(CHECK, "freshness: no activity timestamps at all"))
    else:
        hours = newest * 24
        out.append(Line(
            INFO if hours <= 24 else CHECK,
            f"freshest activity in this read: {hours:.1f}h ago"
            + ("" if hours <= 24 else " — this read may be STALE"),
        ))

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
    out.extend(_signin_gate_lines())

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
        "is at the keyboard. It also LAGS: it only moves when they next make "
        "a request after the update reached them, so a recent release leaves "
        "active users still recorded on the previous one for days.",
        detail=True,
    ))
    out.append(Line(
        INFO,
        "Which means this list cannot tell 'stopped using it' from 'has not "
        "been back since the update landed', and no amount of squinting at "
        "it will. Read the next section instead.",
        detail=True,
    ))

    # Because the version spread was read as churn twice on 2026-08-15, and
    # was wrong twice: first as "only 8 of 54 are active" (the measure said
    # 14 in 7 days, 30 in 30), then as an Edge-store lag (Edge users were on
    # 0.2.0 too, and Chrome had the same tail). Both readings were inference
    # from a column that answers a different question. This one is measured.
    out.append(Line(HEAD, "Actually still here"))
    for window in (7, 30):
        n = sum(
            1 for r in rows
            if (_age_days(r.get("last_activity_at")) or 1e9) <= window
        )
        out.append(Line(
            PASS if n else CHECK,
            f"{n}/{len(rows)} active in the last {window} days",
        ))
    out.append(Line(
        INFO,
        "The number that decides whether more traffic helps. Signups arriving "
        "faster than they stick is a leak being fed, not growth.",
        detail=True,
    ))

    # ── Rhythm ──
    out.extend(_rhythm_lines())

    # ── Renewals ──
    out.append(Line(HEAD, "Quota rollover — is the Stripe event path alive?"))
    subs = [r for r in rows if r.get("stripe_subscription_id")]
    stamped = [r for r in subs if r.get("last_cycle_invoice_at")]
    out.append(Line(INFO, f"{len(subs)} subscriber(s), {len(stamped)} confirmed"))
    for r in subs:
        stamp, anchor = r.get("last_cycle_invoice_at"), r.get("month_reset_date")
        if not stamp:
            out.append(_no_stamp_line(r, anchor))
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
            "No confirmed renewal on any subscriber yet. Each row above says "
            "whether that is expected; a CHECK among them is the one to read.",
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
    # The command as it works WHERE THIS IS READ: on a phone, and pasted into
    # a Railway shell whose working directory is already /app. A footer
    # telling you to cd into a directory that does not exist there is worse
    # than no footer.
    parts.append("\nFull report: python -m workers.green_report")
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
    # Run it now, from a Railway shell, without waiting for 07:00.
    #
    # Bare `python` in that shell is NOT the interpreter the service runs
    # with. Nixpacks installs the dependencies into a virtualenv and puts it
    # on PATH for the start command only, so an interactive shell gets the
    # system Python and `import dotenv` fails on config.py line 7 — which
    # looks alarmingly like a missing dependency and is not one.
    #
    # Ask the image where its interpreter is, rather than guessing a path:
    #
    #     /opt/venv/bin/python -m workers.green_report
    #
    # That path is MEASURED, not guessed — it is what worked on the web
    # service on 2026-08-15. `command -v uvicorn` finds nothing there either:
    # the venv is not on the shell's PATH at all, which is why the earlier
    # "ask the image where its interpreter is" trick also failed. If a
    # builder change ever moves it:
    #
    #     ls -l /opt/venv/bin/python || find / -maxdepth 5 -name uvicorn -type f
    #
    # Or dispatch it as a task, which resolves `celery` off the same PATH the
    # service uses and needs no interpreter hunting — at the cost of running
    # on the WORKER, so Gate 1 reports the worker's Stripe key:
    #
    #     celery -A workers.celery_app call workers.green_report.send_green_report
    #
    # No `cd backend` on Railway: the image's WORKDIR is /app and /app IS
    # this directory — Procfile, main.py and workers/ all sit in it. The
    # first attempt said `cd backend &&` and got "No such file or directory",
    # which is a small thing to get wrong in a comment and an annoying one to
    # get wrong in a message somebody pastes at 7am. Locally, where the repo
    # root has a backend/ folder, `cd backend` first.
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
