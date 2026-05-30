-- 019: auto-expiring manual plan promos.
--
-- When we grant a user a free promo (e.g. a 30-day Starter as an apology),
-- we set manual_promo_until. A daily beat task reverts them to free once it
-- passes — UNLESS they became a real Stripe subscriber in the meantime.
-- Nullable + additive + reversible (DROP COLUMN). No backfill of existing
-- rows except the one documented promo below.

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS manual_promo_until TIMESTAMPTZ;

-- Backfill the one active manual promo (Abid, granted 2026-05-13 for 30 days).
-- This replaces the manual calendar reminder — the beat task will revert him.
UPDATE users
SET manual_promo_until = '2026-06-12T00:00:00Z'
WHERE email = 'abidalibalospura@outlook.com'
  AND plan = 'starter'
  AND stripe_subscription_id IS NULL;

COMMIT;

-- Verification:
--   SELECT email, plan, manual_promo_until, stripe_subscription_id
--   FROM users WHERE manual_promo_until IS NOT NULL;
