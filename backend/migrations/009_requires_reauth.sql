-- 009: surface Microsoft OAuth re-auth requirement to the user.
--
-- When a refresh_token exchange fails (401 invalid_grant / invalid_client),
-- the user's Microsoft session is effectively broken: scheduled campaigns,
-- follow-ups, and AI sends will all silently no-op. Before this migration
-- we had no way to tell the user their authorization needs renewing.
--
-- `requires_reauth` flags the user so the sidebar can display a
-- prominent "Reconnect to Outlook" banner. `reauth_reason` stores the
-- short reason (e.g. 'refresh_failed', 'revoked') for future analytics.
-- `reauth_flagged_at` captures when we first noticed, useful for
-- post-incident triage.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS requires_reauth BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS reauth_reason TEXT;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS reauth_flagged_at TIMESTAMPTZ;
