-- 013: track whether we've already nudged an inactive paid user.
--
-- Without this column, a daily "haven't seen you in 30 days" beat task
-- would spam the same user every day once they crossed the threshold.
-- We store the timestamp of the last nudge we sent, and re-send only
-- when the user has been active again in the meantime (new streak).
--
-- Query used by the beat task (see workers/inactivity_nudge.py):
--
--   WHERE plan != 'free'
--     AND stripe_subscription_id IS NOT NULL
--     AND last_activity_at IS NOT NULL
--     AND last_activity_at < NOW() - INTERVAL '30 days'
--     AND (inactivity_nudge_sent_at IS NULL
--          OR inactivity_nudge_sent_at < last_activity_at)
--
-- Nullable — any row with NULL is a user who's either never been active
-- or has never been nudged. Both are fine.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS inactivity_nudge_sent_at TIMESTAMPTZ;

-- Partial index: we only ever read this column alongside the WHERE
-- conditions above, which narrow to paid-active-and-inactive users.
-- Scanning the full users table each day is fine at current scale
-- but the index keeps the beat task O(1) as we grow.
CREATE INDEX IF NOT EXISTS idx_users_inactivity_check
    ON users(last_activity_at, inactivity_nudge_sent_at)
    WHERE stripe_subscription_id IS NOT NULL AND plan != 'free';
