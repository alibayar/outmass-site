-- 023: per-campaign daily send cap (multi-day spread).
--
-- A campaign with daily_send_cap = N sends at most N contacts per day: the
-- scheduled worker sends today's batch, then advances scheduled_for by one
-- day and leaves the campaign 'scheduled' — the same beat loop continues
-- tomorrow until no resumable contacts remain.
--
-- Why now: a Starter customer (bellmed) upgraded for exactly this after one
-- of our blog posts promised it prematurely (corrected 2026-07-15); the
-- capability was already on the roadmap as pacing Phase 2.
--
-- Additive + reversible. NULL/0 = no cap (existing behavior unchanged).

ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS daily_send_cap INT;

-- Down (manual):
--   ALTER TABLE campaigns DROP COLUMN IF EXISTS daily_send_cap;

-- Verification:
--   SELECT column_name FROM information_schema.columns
--   WHERE table_name = 'campaigns' AND column_name = 'daily_send_cap';
