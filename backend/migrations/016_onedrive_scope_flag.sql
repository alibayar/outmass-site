-- 016: track whether the user has consented to OneDrive scopes.
--
-- Why this column exists: refresh-token requests in OAuth must ask
-- for a scope set the user has already granted. If we always request
-- Mail+Files but the user only ever consented to Mail, Microsoft
-- returns AADSTS65001 and the refresh fails — knocking the user out
-- of every scheduled-send / follow-up / inactivity-check loop.
--
-- We set this flag the first time a callback succeeds with
-- include_onedrive=true (the user explicitly went through the OneDrive
-- consent flow). All subsequent refreshes for that user request both
-- scope sets. Mail-only users keep refreshing with Mail only.
--
-- Default FALSE: every existing token row pre-dates the OneDrive
-- feature, so none of them have the scope. Backfill not required.

ALTER TABLE user_tokens
    ADD COLUMN IF NOT EXISTS has_onedrive_scope BOOLEAN NOT NULL DEFAULT FALSE;
