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
-- Safe to run more than once.
--
-- DO NOT DROP THIS COLUMN. An earlier version of this comment called
-- `ALTER TABLE user_tokens DROP COLUMN has_mail_read_scope` a safe reversal.
-- It is not, and the 2026-08-06 review proved why:
--
--   * Before the flag is ever flipped, dropping it is merely pointless — the
--     code's missing-column guard swallows the error and every user keeps the
--     full scope set, which is what the column would have said anyway.
--   * AFTER the flag has been flipped and narrow users exist, dropping it
--     ERASES the only record of who consented to what. Those users' refresh
--     requests then ask for Mail.Read they never granted, Microsoft answers
--     AADSTS65001, and the ENTIRE refresh fails — every background send stops
--     for them, silently, with the guard hiding the cause.
--
-- The column is one boolean on one row per user. There is no scenario where
-- removing it is worth that. If the feature is abandoned, set
-- FIRST_SIGNIN_INCLUDE_MAIL_READ=true and leave the column in place.

ALTER TABLE user_tokens
    ADD COLUMN IF NOT EXISTS has_mail_read_scope BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN user_tokens.has_mail_read_scope IS
    'True once the user has consented to Mail.Read. Sticky. Existing rows '
    'default TRUE because Mail.Read was part of the first-sign-in ask until '
    '2026-08-06. Drives refresh-token scope matching (AADSTS65001 guard).';
