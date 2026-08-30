"""
OutMass — User model helpers
"""

import calendar
import logging
from datetime import date, datetime, timedelta, timezone

from database import get_db
from utils import send_telemetry

logger = logging.getLogger(__name__)

# last_activity_at is written at most once per ACTIVITY_TOUCH_INTERVAL
# to avoid a DB write on every single authenticated request. The
# inactivity-detection beat task (Phase 5+) only cares about
# day-level freshness, so a 15-minute resolution is plenty.
_ACTIVITY_TOUCH_INTERVAL = timedelta(minutes=15)


def find_by_microsoft_id(microsoft_id: str) -> dict | None:
    """Find a user by their Microsoft account ID."""
    result = (
        get_db()
        .table("users")
        .select("*")
        .eq("microsoft_id", microsoft_id)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def upsert_user(microsoft_id: str, email: str, name: str) -> tuple[dict, bool]:
    """Create or update a user. Returns (user_row, created).

    `created` is True only on the first-ever sign-in (row inserted), so
    callers can trigger one-time onboarding side effects — the welcome
    email — exactly once, never on later logins.
    """
    existing = find_by_microsoft_id(microsoft_id)

    if existing:
        result = (
            get_db()
            .table("users")
            .update({"email": email, "name": name})
            .eq("microsoft_id", microsoft_id)
            .execute()
        )
        return result.data[0], False

    # The quota anchor is born HERE, explicitly — both halves of it. The
    # date used to come from the schema's DEFAULT CURRENT_DATE and the
    # anchor DAY from nowhere at all: migration 029 backfilled existing
    # rows once and no application code ever wrote the column again, so
    # every user created after the backfill carried NULL and fell back to
    # the clamped-day arithmetic the column exists to end.
    today = datetime.now(timezone.utc).date()
    result = (
        get_db()
        .table("users")
        .insert(
            {
                "microsoft_id": microsoft_id,
                "email": email,
                "name": name,
                "plan": "free",
                "emails_sent_this_month": 0,
                "month_reset_date": today.isoformat(),
                "month_reset_anchor_day": today.day,
            }
        )
        .execute()
    )
    return result.data[0], True


def get_by_id(user_id: str) -> dict | None:
    result = (
        get_db()
        .table("users")
        .select("*")
        .eq("id", user_id)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def touch_login(user_id: str) -> None:
    """Record a fresh JWT issue on the users row. Called once per login,
    so it's cheap to write unconditionally. Never raises — a failure
    here must not block the actual login.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        get_db().table("users").update({
            "last_login_at": now,
            "last_activity_at": now,
        }).eq("id", user_id).execute()
    except Exception:  # noqa: BLE001
        logger.exception("touch_login failed for user %s", user_id)


def _is_activity_fresh(last_activity_iso: str | None) -> bool:
    """True if last_activity_at is recent enough to skip a DB write.

    Malformed / missing timestamps count as stale so we err on the side
    of writing — the beat task that consumes this field would otherwise
    never see new activity.
    """
    if not last_activity_iso:
        return False
    try:
        last = datetime.fromisoformat(last_activity_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return (datetime.now(timezone.utc) - last) < _ACTIVITY_TOUCH_INTERVAL


_MAX_VERSION_LEN = 32  # semver + suffix is well under this; defensive cap


def _is_valid_version(v: str | None) -> str | None:
    """Sanitize a version string: must be non-empty, ASCII semver charset
    (alphanumerics + ``.-+_``), capped at 32 chars. Returns the cleaned
    value or None.

    Charset is checked on the full input BEFORE truncation, so a 50-char
    input ending in a bad character is rejected entirely (not silently
    truncated to a clean-looking prefix)."""
    if not v or not isinstance(v, str):
        return None
    candidate = v.strip()
    if not candidate:
        return None
    if not all(c.isalnum() or c in ".-+_" for c in candidate):
        return None
    return candidate[:_MAX_VERSION_LEN]


_MAX_LANGUAGE_LEN = 16  # matches the CHECK added by migration 030


def _is_valid_language(v: str | None) -> str | None:
    """Sanitize a BCP-47 tag: letters, digits and hyphens, 2–16 chars.

    Rejects rather than truncates, for the same reason _is_valid_version
    does: a truncated tag is a tag that looks fine and means something else.
    The database has its own 16-char CHECK, and a write it rejects would
    surface as an exception inside the auth dependency on every request from
    that user — so the guard has to be here too, not only there.

    Deliberately NOT a whitelist of supported locales. That list lives in
    extension/_locales, and a tag we do not recognise falls back to English
    in emails/__init__.py, which is the same outcome a rejected write gives
    with fewer moving parts — and this way we can SEE that somebody wants a
    language we do not have.
    """
    if not v or not isinstance(v, str):
        return None
    candidate = v.strip()
    if not 2 <= len(candidate) <= _MAX_LANGUAGE_LEN:
        return None
    if not all(c.isascii() and (c.isalnum() or c == "-") for c in candidate):
        return None
    return candidate


def maybe_touch_activity(
    user: dict,
    extension_version: str | None = None,
    preferred_language: str | None = None,
) -> None:
    """Bump last_activity_at if stale, and/or update
    last_seen_extension_version and preferred_language if they changed.

    Called from the auth dependency on every authenticated request. Mutates
    the passed-in dict so downstream handlers see the fresh values without
    a re-fetch.

    Language rides the changed-value path rather than the 15-minute timer,
    like the version does: it changes approximately never, so a write costs
    nothing, and gating it on the timer would mean somebody who switched
    language in Settings could get an email in the old one for another
    quarter of an hour.
    """
    activity_fresh = _is_activity_fresh(user.get("last_activity_at"))
    cleaned_version = _is_valid_version(extension_version)
    version_changed = (
        cleaned_version is not None
        and cleaned_version != user.get("last_seen_extension_version")
    )
    cleaned_language = _is_valid_language(preferred_language)
    language_changed = (
        cleaned_language is not None
        and cleaned_language != user.get("preferred_language")
    )

    if activity_fresh and not version_changed and not language_changed:
        return

    updates: dict = {}
    if not activity_fresh:
        now = datetime.now(timezone.utc).isoformat()
        updates["last_activity_at"] = now
        user["last_activity_at"] = now  # mutate so downstream sees fresh
    if version_changed:
        updates["last_seen_extension_version"] = cleaned_version
        user["last_seen_extension_version"] = cleaned_version
    if language_changed:
        updates["preferred_language"] = cleaned_language
        user["preferred_language"] = cleaned_language

    if not updates:
        return
    try:
        get_db().table("users").update(updates).eq("id", user["id"]).execute()
    except Exception:  # noqa: BLE001
        logger.exception("maybe_touch_activity failed for user %s", user.get("id"))


def increment_sent_count(
    user_id: str,
    count: int = 1,
    *,
    reason: str = "unspecified",
    email: str | None = None,
    extra: dict | None = None,
):
    """Increment the user's sent counters atomically, and say so out loud.

    Maintains TWO counters: emails_sent_this_month (the quota counter,
    reset each billing-anchored month) and emails_sent_total (lifetime,
    never reset — the operator's tracking metric).

    It is also the one function every send path in this codebase passes
    through, which is why the send telemetry lives here rather than at the
    eleven call sites. Instrumenting the call sites would mean the next send
    path someone adds is invisible until they remember — and "invisible until
    someone remembers" is the whole defect this reporting exists to close.

    `reason` and `email` are keyword-only so that no existing positional call
    breaks. A caller that omits `reason` still produces an event, logged as
    unlabelled rather than dropped: a send we cannot categorise beats a send
    we cannot see.
    """
    # C-05: Use RPC for atomic increment to prevent race conditions.
    # Migration 021 makes the RPC bump both counters.
    try:
        get_db().rpc(
            "increment_user_sent_count",
            {"user_id_input": user_id, "amount": count},
        ).execute()
    except Exception:
        # Fallback to non-atomic if the RPC doesn't exist / errors. Log it —
        # a permanently-failing RPC (e.g. a signature-mismatch overload after
        # a migration) would otherwise silently reintroduce the C-05 race.
        logger.warning(
            "increment_user_sent_count RPC failed; using non-atomic fallback",
            exc_info=True,
        )
        user = get_by_id(user_id)
        if not user:
            return
        try:
            get_db().table("users").update(
                {
                    "emails_sent_this_month": user.get("emails_sent_this_month", 0) + count,
                    "emails_sent_total": user.get("emails_sent_total", 0) + count,
                }
            ).eq("id", user_id).execute()
        except Exception:
            # emails_sent_total may not exist yet (migration 021 not applied).
            # NEVER lose the quota increment over the lifetime counter.
            get_db().table("users").update(
                {"emails_sent_this_month": user.get("emails_sent_this_month", 0) + count}
            ).eq("id", user_id).execute()

    # Last, and unable to raise. Every caller wraps this function in a try
    # whose except deliberately leaves `quota_charged` unadvanced so a later
    # flush recharges it (workers/scheduled_worker.py:189-199). A telemetry
    # error thrown AFTER the counter has been written would therefore charge
    # the same emails to the customer's quota twice.
    send_telemetry.report_emails_sent(user_id, count, reason, email, extra)


def _month_shift(base: date, months: int, day: int) -> date:
    """`base`'s month plus N months, on `day`, clamped to that month's length.

    The clamp is right — Jan 31 + 1 month has to be Feb 28 — and it is also
    lossy, which is the whole reason `day` is a separate argument rather than
    read off `base`. See _anchor_day.
    """
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _add_months(d: date, months: int) -> date:
    """`d` plus N calendar months, clamping the day to the target month's
    length (Jan 31 + 1mo → Feb 28/29) — mirrors how Stripe anchors monthly
    billing. Always call with the ORIGINAL anchor date so the day doesn't
    drift after a clamp (Jan 31 + 2mo = Mar 31, not Mar 28)."""
    return _month_shift(d, months, d.day)


def _anchor_day(user: dict, reset_date: date) -> int:
    """The calendar day this user's quota month really starts on.

    month_reset_date holds the CLAMPED date for the current period, and
    check_monthly_reset used to compute the next one from it — so a 31st
    anchor became a 28th in February and stayed a 28th forever after, costing
    that customer three days of quota month every year. The docstring on
    _add_months warns to "always call with the ORIGINAL anchor date"; its
    caller was the one place that could not, because the original was not
    stored anywhere.

    Migration 029 stores it. NULL means a row written before that migration
    or by an older code path, and falling back to the clamped day is exactly
    the pre-029 behaviour — no worse than it already was.
    """
    stored = user.get("month_reset_anchor_day")
    try:
        day = int(stored)
    except (TypeError, ValueError):
        return reset_date.day
    return day if 1 <= day <= 31 else reset_date.day


def next_reset_date(user: dict) -> date | None:
    """First day of the NEXT quota period (rolling anchor + 1 month).

    Callers should run check_monthly_reset first so the anchor is
    current. Used by the quota-cap email to tell the user when their
    pending recipients will auto-resume.
    """
    reset_date = user.get("month_reset_date")
    if not reset_date:
        return None
    if isinstance(reset_date, str):
        reset_date = date.fromisoformat(reset_date)
    # The real anchor, not the clamped one. This date is quoted to the user
    # in the quota-cap email; telling a 31st-anchor customer their sends
    # resume on the 28th and then not resuming them is worse than saying
    # nothing.
    return _month_shift(reset_date, 1, _anchor_day(user, reset_date))


def effective_plan(user: dict) -> str:
    """The plan whose FEATURES this user may use right now.

    users.plan is the billing truth and Stripe owns it — the
    customer.subscription.updated handler rewrites it from the price on every
    renewal. A complimentary upgrade written there is therefore reverted
    within the month, silently. So a comp lives in comp_plan /
    comp_plan_until (migration 032) and only this function merges the two.

    The split is the point. Everything that decides what someone may DO calls
    this; everything that reports what they PAY keeps reading users.plan. That
    is why daily_report still counts a comped Starter as a paying Starter, and
    why MRR does not move when we give one away.

    Expires by arithmetic — no beat task, nothing to undo, no half-applied
    state. A missing or unparseable comp_plan_until reads as expired, which
    fails toward the plan they actually pay for.
    """
    until = user.get("comp_plan_until")
    comp = user.get("comp_plan")
    if not until or not comp:
        return user.get("plan") or "free"
    try:
        expires = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
    except ValueError:
        logger.warning(
            "effective_plan: unreadable comp_plan_until %r for user %s",
            until, user.get("id"),
        )
        return user.get("plan") or "free"
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= expires:
        return user.get("plan") or "free"
    return comp


def check_monthly_reset(
    user: dict,
    today: date | None = None,
    *,
    paid_cycle_confirmed: bool = False,
):
    """Reset the quota counters when the user's billing-anchored month rolls
    over.

    ``paid_cycle_confirmed`` is set by exactly one caller: the Stripe webhook
    for invoice.payment_succeeded with billing_reason subscription_cycle. It
    means "this customer has just paid for a new month", which is the only
    thing that can start a paid month on time — see the hold below.

    The quota period is a ROLLING month from month_reset_date (set at signup
    and re-anchored at each paid checkout) — NOT the calendar month. A Starter
    who pays on the 25th gets exactly one quota-month per billed month; the
    old calendar rule handed out a bonus reset every 1st.

    Mutates the passed-in dict so callers (login, /send gate, workers) see the
    fresh values without a re-fetch. emails_sent_total is deliberately NEVER
    touched here. `today` is injectable for tests only.
    """
    reset_date = user.get("month_reset_date")
    if not reset_date:
        return
    if isinstance(reset_date, str):
        reset_date = date.fromisoformat(reset_date)
    if today is None:
        today = datetime.now(timezone.utc).date()

    anchor_day = _anchor_day(user, reset_date)
    due = _month_shift(reset_date, 1, anchor_day)
    if today < due:
        return  # still inside the current quota month

    # A subscription Stripe is about to end today must not roll over first.
    #
    # This function compares DATES and runs from the scheduled-campaign beat,
    # so on the anniversary it fires within minutes of 00:00 UTC. Stripe ends
    # a cancelling subscription at the subscription's creation TIME that day —
    # usually hours later. Rolling over in the gap hands a full bonus quota
    # month to the one person we already know is leaving.
    #
    # Bounded to the due day alone, deliberately. If customer.subscription
    # .deleted never arrives — a lost webhook, or they un-cancelled in the
    # portal and we were not told — then tomorrow this rolls over as usual.
    # Withholding for a few hours is the fix; withholding forever would be a
    # paying customer stuck at zero quota with no way to see why.
    if today == due and user.get("cancel_at_period_end"):
        logger.info(
            "user %s reaches their anchor today with a cancelling "
            "subscription; holding the rollover until it ends",
            user.get("id"),
        )
        return

    # A paying customer's month starts when they pay for it, not at midnight.
    #
    # Same clock mismatch as above, pointing the other way. We reset on a DATE
    # match minutes after 00:00 UTC; Stripe charges the renewal at the
    # subscription's creation TIME — for the customer that prompted this,
    # 20:20 UTC. So the new month's quota went live about twenty hours before
    # the month was paid for, every month, for every subscriber.
    #
    # So the renewal is no longer something we predict. Stripe tells us it
    # happened — invoice.payment_succeeded with billing_reason
    # subscription_cycle — and that handler calls this function with
    # paid_cycle_confirmed=True. No clock of ours is involved, which also
    # means no timezone of ours can be wrong about it.
    #
    # Bounded to the due day alone, exactly like the cancellation hold: if the
    # webhook is lost or Stripe's retries run long, tomorrow this rolls over
    # anyway. Waiting a few hours is the fix; waiting forever would strand a
    # paying customer at zero quota, which is a worse bug than the one being
    # closed. Anything capped in the gap is not lost either — the auto-resume
    # beat sends it as soon as the headroom lands.
    #
    # Free users have no subscription and are untouched: for them the anchor
    # is not an approximation of anything, it IS the rule.
    if (
        today == due
        and not paid_cycle_confirmed
        and user.get("stripe_subscription_id")
    ):
        logger.info(
            "user %s reaches their anchor today on a paid plan; holding the "
            "rollover until Stripe confirms the renewal",
            user.get("id"),
        )
        return

    # Advance in whole months FROM THE ORIGINAL anchor (day preserved even
    # across a long absence): anchor the 25th + first login two periods later
    # → new anchor is still a 25th, of the most recent elapsed period.
    months = 1
    while _month_shift(reset_date, months + 1, anchor_day) <= today:
        months += 1
    new_anchor = _month_shift(reset_date, months, anchor_day)

    get_db().table("users").update(
        {
            "emails_sent_this_month": 0,
            "ai_generations_this_month": 0,
            "month_reset_date": new_anchor.isoformat(),
            # Written unconditionally, on purpose. For a row that has one,
            # this rewrites the same value — a no-op. For a legacy row that
            # never got an anchor day (created in the gap after migration
            # 029's one-time backfill, before creation started writing it),
            # this persists the fallback the period was just computed from,
            # so the row heals on its first rollover instead of falling
            # back forever. It also keeps the invariant a source-scan test
            # can enforce: no write of month_reset_date without its anchor.
            "month_reset_anchor_day": anchor_day,
        }
    ).eq("id", user["id"]).execute()
    user["emails_sent_this_month"] = 0
    user["ai_generations_this_month"] = 0
    user["month_reset_date"] = new_anchor.isoformat()
    user["month_reset_anchor_day"] = anchor_day
