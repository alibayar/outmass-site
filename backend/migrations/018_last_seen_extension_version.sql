-- 018: track last extension version each user signed in / made an authenticated request from.
--
-- Purpose: feed analytics queries like "what % of paid users are still
-- on v0.1.5?" and enable future stale-version nudge emails. Updated on
-- every authenticated request, gated by the same 15-minute rate-limiter
-- that protects last_activity_at, so this is essentially free.
--
-- Safety: nullable, additive. Reversible with `ALTER TABLE users DROP COLUMN`.
-- Existing rows treated as "unknown" (NULL) until their next signed-in request.

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_seen_extension_version TEXT;

COMMIT;

-- Verification:
--   SELECT column_name FROM information_schema.columns
--   WHERE table_name='users' AND column_name='last_seen_extension_version';
