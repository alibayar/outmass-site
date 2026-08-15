-- 031: when Stripe last told us a subscriber paid for a new month.
--
-- ── Why ──
--
-- check_monthly_reset compares DATES and runs from the scheduled beat, so on
-- a subscriber's anniversary it fires within minutes of 00:00 UTC. Stripe
-- charges the renewal at the subscription's CREATION TIME. For the customer
-- that surfaced this on 2026-08-14 that is 20:20 UTC — so the new month's
-- quota was live for about twenty hours before the month was paid for, every
-- month, for every subscriber.
--
-- The fix is not to compute the moment more precisely. It is to stop
-- computing it: Stripe already sends invoice.payment_succeeded with
-- billing_reason 'subscription_cycle', the webhook already receives and
-- resolves it, and that event IS the fact we were approximating. The handler
-- now rolls the quota over, and the date anchor becomes a bounded backstop
-- that fires the next day if the webhook never arrives.
--
-- ── What this column is for ──
--
-- Not the logic — the logic needs no column, it reads the event. This is the
-- evidence trail. Without it there is no way to tell a rollover that Stripe
-- confirmed from one the backstop performed a day late, and "the event path
-- silently stopped working" is precisely the class of failure that let a
-- worker's sends go unreported for weeks (task #53).
--
--   SELECT count(*) FILTER (WHERE last_cycle_invoice_at IS NOT NULL)
--   FROM users WHERE stripe_subscription_id IS NOT NULL;
--
-- If that stays at zero a month from now, the webhook is not arriving and
-- every paid rollover is running on the backstop.
--
-- ── Deploy order ──
--
-- Additive, nullable, idempotent. Safe to run before or after the code: the
-- writer uses a plain UPDATE that simply has nothing to write until it
-- exists, and nothing reads it.
--
-- Reversal: ALTER TABLE users DROP COLUMN last_cycle_invoice_at;

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_cycle_invoice_at TIMESTAMPTZ;

COMMENT ON COLUMN users.last_cycle_invoice_at IS
    'When Stripe last confirmed a renewal invoice (billing_reason '
    '''subscription_cycle'') for this subscriber. Written by the '
    'invoice.payment_succeeded webhook, which also rolls the quota month '
    'over. NULL means we have never seen one — expected for free users and '
    'for anyone still inside their first billing period, and a signal worth '
    'investigating for a long-standing subscriber.';

COMMIT;

-- ── Verification ──
--
-- 1) The column exists and is empty, which is correct until the first
--    renewal lands after deploy:
--      SELECT count(*) AS subscribers,
--             count(last_cycle_invoice_at) AS confirmed
--      FROM users WHERE stripe_subscription_id IS NOT NULL;
--
-- 2) After a renewal, the stamp and the anchor should agree to the day:
--      SELECT email, month_reset_date, last_cycle_invoice_at,
--             date(last_cycle_invoice_at) = month_reset_date AS agree
--      FROM users
--      WHERE last_cycle_invoice_at IS NOT NULL
--      ORDER BY last_cycle_invoice_at DESC;
--
--    `agree = false` means the backstop rolled it over before Stripe
--    confirmed — check whether the webhook is being delivered.
