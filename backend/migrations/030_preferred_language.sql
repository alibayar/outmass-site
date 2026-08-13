-- 030: know what language to write to someone in.
--
-- ── Why ──
--
-- The panel speaks 14 languages. Every email we send is English: welcome,
-- reconnect, quota-cap, upgrade thank-you, plan-dropped, account-deleted, and
-- all three inactivity tiers — nine templates in four files.
--
-- The blocker was never the templates. It is that we do not know anyone's
-- language. There is no column for it anywhere in schema.sql, and the team
-- has written down three separate times why Accept-Language is not the
-- answer: the browser header describes the browser, not the person, and this
-- product's own Settings screen lets someone choose a panel language that
-- deliberately overrides it. Guessing from the header would write Turkish to
-- an English-speaking user in Istanbul and English to a Turkish user in
-- London — and an email in the wrong language is worse than an English one,
-- because the first reads as a mistake and the second as a default.
--
-- ── Where the value comes from ──
--
-- The extension already computes it. getActiveLocale() in extension/i18n.js
-- resolves the Settings override first, then Chrome's UI language, then
-- navigator.language, then "en" — the same precedence the panel itself
-- renders with. So the value exists, correctly, on every client; it has just
-- never been sent anywhere.
--
-- It will ride on a call the panel already makes rather than a new endpoint.
-- Older extension builds simply never send it, the column stays NULL, and
-- every email falls back to English exactly as today — the same
-- default-to-English shape routers/ai.py already uses for an unrecognised
-- language. No version gate, no breakage in the field.
--
-- ── NULL means unknown, not English ──
--
-- Deliberately nullable with no default. "We have not been told" and "they
-- chose English" are different facts, and only one of them is worth a
-- follow-up when the localisation work is judged later.
--
-- ── Deploy order ──
--
-- Inert until the extension sends it and the templates read it. Safe to run
-- now and leave empty for weeks.
--
-- Additive and idempotent.
-- Reversal: ALTER TABLE users DROP COLUMN preferred_language;

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS preferred_language TEXT;

-- Length only, not a whitelist. A whitelist here would be a second list of
-- supported locales, and the first one — extension/_locales — is the one that
-- decides. A value we do not recognise falls back to English in code, which
-- is the same thing a rejected write would achieve with more moving parts.
ALTER TABLE users
    ADD CONSTRAINT preferred_language_looks_like_a_locale
    CHECK (preferred_language IS NULL OR char_length(preferred_language) <= 16)
    NOT VALID;

COMMENT ON COLUMN users.preferred_language IS
    'BCP-47 tag the panel is rendering in, as computed by getActiveLocale() '
    'in extension/i18n.js: the Settings override if set, else the browser. '
    'NULL means we have not been told — not that they chose English. Read by '
    'the outgoing-email templates; anything unrecognised falls back to '
    'English in code.';

COMMIT;

-- ── Verification ──
--
-- 1) The column exists and is empty, which is correct until the extension
--    ships the change that fills it:
--      SELECT count(*) FILTER (WHERE preferred_language IS NOT NULL) AS known,
--             count(*)                                               AS total
--      FROM users;
--
-- 2) After it ships, what we actually have — this is the number that decides
--    whether the nine templates are worth translating and into which
--    languages first:
--      SELECT COALESCE(preferred_language, '(not told)') AS lang,
--             count(*) AS users,
--             count(*) FILTER (WHERE plan <> 'free') AS paying
--      FROM users GROUP BY 1 ORDER BY users DESC;
--
-- 3) Validate the length check whenever convenient:
--      ALTER TABLE users VALIDATE CONSTRAINT preferred_language_looks_like_a_locale;
