-- 034 — users.sender_logo_url, so a signature can carry a logo
--
-- Hélène Carpentier asked on 2026-09-01, in the same message as her follow-up
-- text: "add a logo in signature (as my signature below)". The only way to do
-- it was to type an <img> tag by hand, which is not an answer for someone
-- writing an email.
--
-- Ali's scoping, the same evening: a field to type the address into. No
-- hosting — that is a different product, and every logo already lives on the
-- website it belongs to.
--
-- Nullable with no default, so every existing row is untouched and the
-- signature of anyone who does not set one is byte-identical to yesterday.
--
-- Reversible: DROP COLUMN. Nothing reads it unless the user's own template
-- contains {{senderLogo}}, so rolling back leaves that tag rendering as
-- nothing rather than breaking a send.

ALTER TABLE users ADD COLUMN IF NOT EXISTS sender_logo_url TEXT;

COMMENT ON COLUMN users.sender_logo_url IS
  'https URL of the user''s logo image, pasted by them in Settings. Expanded '
  'into a complete <img> tag by build_merge_context() when their template '
  'contains {{senderLogo}}. We never fetch, store or proxy the image.';

-- down:
--   ALTER TABLE users DROP COLUMN IF EXISTS sender_logo_url;
