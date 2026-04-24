-- 010: user activity tracking + FK ON DELETE CASCADE chain.
--
-- Two independent concerns bundled into one migration because they share
-- the same risk profile (schema-only, reversible, zero user impact):
--
-- 1. Two nullable timestamps on users:
--    * last_login_at       — set on every JWT issue (auth callback success)
--    * last_activity_at    — set on every authenticated request (batched)
--
--    These power the "is this paid user still using OutMass?" inactivity
--    detection we're adding in later phases (nudge email at 30d, pause
--    at 60d, cancel at 90d). Nullable so existing rows don't need a
--    backfill — treated as "unknown" by the beat task.
--
-- 2. Convert the foreign-key chain from the default NO ACTION behaviour
--    to ON DELETE CASCADE. Today, deleting a users row fails with a
--    constraint violation because campaigns/contacts/etc. reference it.
--    That makes the GDPR "delete my account" endpoint we're shipping
--    next a painful SQL puzzle with a specific deletion order. CASCADE
--    lets us just DELETE FROM users WHERE id=? and the database cleans
--    up every dependent row transactionally.
--
-- Safety: all FK constraints are dropped and recreated inside a single
-- transaction. If anything fails, Postgres rolls back the whole thing.
-- No rows are touched — only constraint metadata.
--
-- Reversal: to undo, re-add each FK without ON DELETE CASCADE. The
-- activity columns can be dropped with ALTER TABLE DROP COLUMN.

BEGIN;

-- ── Part 1: activity tracking columns ──

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ;

-- Index to make the inactivity-detection beat task fast. Partial index
-- skips NULLs so we only scan users who have at least one login.
CREATE INDEX IF NOT EXISTS idx_users_last_activity
    ON users(last_activity_at)
    WHERE last_activity_at IS NOT NULL;

-- ── Part 2: FK ON DELETE CASCADE ──
--
-- Postgres default FK naming is {table}_{column}_fkey. If a prior
-- migration renamed any of these, the DROP CONSTRAINT will fail and
-- the whole transaction rolls back — safe to retry after fixing the
-- name.

-- campaigns.user_id → users
ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_user_id_fkey;
ALTER TABLE campaigns
    ADD CONSTRAINT campaigns_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- contacts.campaign_id → campaigns
ALTER TABLE contacts DROP CONSTRAINT IF EXISTS contacts_campaign_id_fkey;
ALTER TABLE contacts
    ADD CONSTRAINT contacts_campaign_id_fkey
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE;

-- events.contact_id → contacts
ALTER TABLE events DROP CONSTRAINT IF EXISTS events_contact_id_fkey;
ALTER TABLE events
    ADD CONSTRAINT events_contact_id_fkey
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE;

-- events.campaign_id → campaigns
ALTER TABLE events DROP CONSTRAINT IF EXISTS events_campaign_id_fkey;
ALTER TABLE events
    ADD CONSTRAINT events_campaign_id_fkey
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE;

-- suppression_list.user_id → users
ALTER TABLE suppression_list DROP CONSTRAINT IF EXISTS suppression_list_user_id_fkey;
ALTER TABLE suppression_list
    ADD CONSTRAINT suppression_list_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- follow_ups.campaign_id → campaigns
ALTER TABLE follow_ups DROP CONSTRAINT IF EXISTS follow_ups_campaign_id_fkey;
ALTER TABLE follow_ups
    ADD CONSTRAINT follow_ups_campaign_id_fkey
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE;

-- follow_ups.user_id → users
ALTER TABLE follow_ups DROP CONSTRAINT IF EXISTS follow_ups_user_id_fkey;
ALTER TABLE follow_ups
    ADD CONSTRAINT follow_ups_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- user_tokens.user_id → users (UNIQUE constraint stays)
ALTER TABLE user_tokens DROP CONSTRAINT IF EXISTS user_tokens_user_id_fkey;
ALTER TABLE user_tokens
    ADD CONSTRAINT user_tokens_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- templates.user_id → users
ALTER TABLE templates DROP CONSTRAINT IF EXISTS templates_user_id_fkey;
ALTER TABLE templates
    ADD CONSTRAINT templates_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- ab_tests.campaign_id → campaigns
ALTER TABLE ab_tests DROP CONSTRAINT IF EXISTS ab_tests_campaign_id_fkey;
ALTER TABLE ab_tests
    ADD CONSTRAINT ab_tests_campaign_id_fkey
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE;

-- ab_tests.user_id → users
ALTER TABLE ab_tests DROP CONSTRAINT IF EXISTS ab_tests_user_id_fkey;
ALTER TABLE ab_tests
    ADD CONSTRAINT ab_tests_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

COMMIT;

-- ── Verification queries (run manually to confirm) ──
--
-- 1) Confirm new columns exist:
--    SELECT column_name FROM information_schema.columns
--    WHERE table_name='users' AND column_name IN ('last_login_at','last_activity_at');
--
-- 2) Confirm ON DELETE CASCADE is set on every dependent FK:
--    SELECT conrelid::regclass AS table, conname, confdeltype
--    FROM pg_constraint
--    WHERE contype = 'f'
--      AND conrelid::regclass::text IN (
--        'campaigns','contacts','events','suppression_list',
--        'follow_ups','user_tokens','templates','ab_tests'
--      );
--    -- confdeltype should be 'c' (cascade) for every row.
