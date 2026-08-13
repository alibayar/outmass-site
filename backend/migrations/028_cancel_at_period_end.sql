-- 028: remember that a subscription is already on its way out.
--
-- ── Why ──
--
-- check_monthly_reset (models/user.py) compares plain DATES:
--
--     if today < _add_months(reset_date, 1): return
--
-- and it runs from seven places, one of which is the scheduled-campaign beat
-- (workers/scheduled_worker.py:68) — unattended, every tick, no user action
-- required. So on the anniversary DAY it fires within minutes of 00:00 UTC.
--
-- Stripe ends a cancelling subscription at the subscription's creation TIME
-- that same day, which is almost always hours later. In the gap the customer
-- is still on a paid plan with a counter we have just re-zeroed: one full
-- bonus quota month, handed to the one person we already know is leaving.
--
-- Nothing in the codebase currently persists cancel_at_period_end, so the
-- rollover has no way to know the difference between "renewing tomorrow" and
-- "ending in six hours".
--
-- ── What the code will do with it ──
--
-- customer.subscription.updated (routers/billing.py) writes this flag; it
-- already receives it on every portal toggle and touches no quota fields, so
-- it stays consistent with the comment there about why that handler must
-- never refill. check_monthly_reset then skips the rollover while the flag is
-- true, and customer.subscription.deleted clears it when the plan actually
-- drops to free — after which the ordinary reset resumes for a user who comes
-- back later.
--
-- ── Deploy order ──
--
-- This column is INERT until that code ships. Running it early is safe and
-- changes nothing. Running the code before the column exists is not: the
-- write would fail with 42703. Column first, then deploy.
--
-- Additive and idempotent.
-- Reversal: ALTER TABLE users DROP COLUMN cancel_at_period_end;

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS cancel_at_period_end BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN users.cancel_at_period_end IS
    'Stripe says this subscription ends at the end of the current period. '
    'Set from customer.subscription.updated, cleared on '
    'customer.subscription.deleted. Read by check_monthly_reset so the '
    'date-granularity rollover does not hand a departing customer one last '
    'free quota month in the hours between 00:00 UTC and the subscription '
    'actually ending.';

COMMIT;

-- ── Verification ──
--
-- 1) The column exists and defaults false for everyone:
--      SELECT count(*) FILTER (WHERE cancel_at_period_end) AS cancelling,
--             count(*)                                     AS total
--      FROM users;
--    Expect cancelling = 0 immediately after this migration — nothing writes
--    it yet.
--
-- 2) After the code ships, the rows it should be true for are exactly those
--    with a live subscription the customer has switched off in the portal:
--      SELECT email, plan, cancel_at_period_end, month_reset_date
--      FROM users
--      WHERE stripe_subscription_id IS NOT NULL
--      ORDER BY month_reset_date;
--
-- 3) The case this exists for, if you want to watch one: a customer whose
--    month_reset_date is today AND cancel_at_period_end is true should still
--    be showing their USED counter, not a fresh zero.
