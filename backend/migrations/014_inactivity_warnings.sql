-- 014: two more inactivity warning milestones (Phase 6 minimal).
--
-- Phase 5 shipped a single 30-day "heads up" nudge. Phase 6 adds two
-- firmer reminders at 60 and 90 days for paid users who still haven't
-- logged in. No subscription is auto-paused or auto-cancelled — the
-- manual cancel+refund path is handled by the operator when support@
-- receives a reply, or when the 90-day warning itself prompts the
-- user to act.
--
-- Each milestone uses its own "sent" column for the same reason as
-- the 30-day nudge (migration 013): avoid re-sending once the stamp
-- is more recent than last_activity_at. When the user comes back,
-- the stamps naturally go stale and future inactive streaks trigger
-- fresh emails.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS inactivity_warning_60d_sent_at TIMESTAMPTZ;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS inactivity_warning_90d_sent_at TIMESTAMPTZ;
