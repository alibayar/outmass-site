-- 029: keep the real anchor day, not the last clamped one.
--
-- ── Why ──
--
-- _add_months (models/user.py) clamps the day to the target month's length,
-- which is correct — Jan 31 + 1 month has to be Feb 28. The bug is that
-- check_monthly_reset then stores the CLAMPED result back into
-- month_reset_date, the only anchor there is:
--
--     new_anchor = _add_months(reset_date, months)   -- Jan 31 -> Feb 28
--     ... "month_reset_date": new_anchor.isoformat()
--
-- so the next period computes from the 28th, and the 31st is gone for good.
-- A customer who subscribes on the 31st loses three days of quota month every
-- year, silently and permanently, after the first short month.
--
-- The docstring in _add_months already warns about this — "Always call with
-- the ORIGINAL anchor date so the day doesn't drift after a clamp" — and the
-- caller is the one place that cannot honour it, because the original day is
-- not stored anywhere.
--
-- ── Not urgent, and worth saying why ──
--
-- No current customer is affected: every live anchor is the 23rd-25th, which
-- exists in all twelve months. This is a migration to run BEFORE someone
-- checks out on the 29th, not after. Which is also why the backfill below is
-- safe today and would not be in a year — it reads the current
-- month_reset_date, and for anyone already decayed that value is the damage
-- rather than the truth. Verification query 2 checks that nobody is.
--
-- ── What the code will do with it ──
--
-- Each period's stored date is computed by clamping FROM this day + the
-- target month, every time, instead of from the previously-clamped date. NULL
-- keeps today's behaviour exactly, so the column can sit unused indefinitely.
--
-- ── Deploy order ──
--
-- Inert until the code ships. Column first.
--
-- Additive and idempotent.
-- Reversal: NO LONGER a bare DROP COLUMN. Since 2026-08-15 the column is
-- WRITTEN on the two hottest paths — the signup INSERT (upsert_user) and the
-- quota-rollover UPDATE (check_monthly_reset) — so dropping it under live
-- code turns every signup and every rollover into an error. Roll the code
-- back first, then: ALTER TABLE users DROP COLUMN month_reset_anchor_day;

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS month_reset_anchor_day SMALLINT;

-- Backfill from the current anchor. Correct as long as nobody has already
-- decayed — see verification 2, which is the check that makes this line
-- honest rather than hopeful.
UPDATE users
SET month_reset_anchor_day = EXTRACT(DAY FROM month_reset_date)::SMALLINT
WHERE month_reset_date IS NOT NULL
  AND month_reset_anchor_day IS NULL;

ALTER TABLE users
    ADD CONSTRAINT month_reset_anchor_day_is_a_day
    CHECK (month_reset_anchor_day IS NULL
           OR month_reset_anchor_day BETWEEN 1 AND 31)
    NOT VALID;

COMMENT ON COLUMN users.month_reset_anchor_day IS
    'The calendar day the billing-anchored quota month starts on, preserved '
    'across short months. month_reset_date holds the CLAMPED date for the '
    'current period (Feb 28 for a 31st anchor); this holds 31 so the next '
    'period returns to it instead of decaying. NULL = derive from '
    'month_reset_date, which is the pre-029 behaviour.';

COMMIT;

-- ── Verification ──
--
-- 1) Every user with an anchor now has a day:
--      SELECT count(*) FROM users
--      WHERE month_reset_date IS NOT NULL AND month_reset_anchor_day IS NULL;
--    Expect 0.
--
-- 2) THE ONE THAT MATTERS — has anyone already decayed? Compare the anchor
--    day against the day they actually started paying:
--      SELECT email, plan, month_reset_date, month_reset_anchor_day,
--             EXTRACT(DAY FROM plan_updated_at) AS paid_on_day
--      FROM users
--      WHERE plan <> 'free' AND month_reset_date IS NOT NULL
--      ORDER BY month_reset_anchor_day DESC;
--    A row where month_reset_anchor_day is 28 but paid_on_day is 29/30/31 has
--    already lost its anchor, and the backfill above just made that
--    permanent. Fix those by hand:
--      UPDATE users SET month_reset_anchor_day = <the real day> WHERE id = ...
--    Expect none today: every live anchor is the 23rd-25th.
--
-- 3) The constraint is NOT VALID on purpose — it applies to new writes
--    without scanning the table. Validate it whenever convenient:
--      ALTER TABLE users VALIDATE CONSTRAINT month_reset_anchor_day_is_a_day;
