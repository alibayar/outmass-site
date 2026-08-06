-- 024 — track whether a user has granted Mail.Read
--
-- Mail.Read is moving out of the first sign-in ask. Microsoft renders it as
-- "Read your mail", which is the scariest line on a consent screen shown to
-- someone who has not sent a single email with OutMass yet, and it exists
-- only for reply detection — a feature that cannot matter before the first
-- campaign. Measured 2026-08-06: ~31% of first-time Chrome users and ~54% of
-- first-time Edge users never finish the consent screen, and publisher
-- verification (2026-06-24) did not move that number.
--
-- The flag is what keeps the refresh-token request scope-matched. If we ask
-- for a scope the user never granted, Microsoft answers AADSTS65001 and the
-- WHOLE refresh fails — knocking that user out of every background send. Same
-- reason 016 added has_onedrive_scope.
--
-- DEFAULT TRUE is the load-bearing part: every row that exists today belongs
-- to a user who granted Mail.Read at sign-in, so backfill is automatic and
-- correct. New rows get their value written explicitly by _persist_ms_tokens.
--
-- Safe to run more than once. Reversible:
--   ALTER TABLE user_tokens DROP COLUMN has_mail_read_scope;
-- (Dropping it while the code still reads it makes refreshes fall back to the
-- full scope set — the current behaviour — so a rollback is not destructive.)

ALTER TABLE user_tokens
    ADD COLUMN IF NOT EXISTS has_mail_read_scope BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN user_tokens.has_mail_read_scope IS
    'True once the user has consented to Mail.Read. Sticky. Existing rows '
    'default TRUE because Mail.Read was part of the first-sign-in ask until '
    '2026-08-06. Drives refresh-token scope matching (AADSTS65001 guard).';
