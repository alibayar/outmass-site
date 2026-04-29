-- 015: campaigns.attachments — list of OneDrive sharing links to
--      include in each email.
--
-- Why JSONB instead of a separate table: attachments here are tiny —
-- just {name, url} pairs, never more than a handful per campaign. A
-- JSONB column avoids a join on every send and keeps the schema
-- simple. If a future feature needs per-attachment metadata
-- (open count, click count, removal date) we can promote to a table
-- without disrupting existing campaigns.
--
-- Shape:
--   [
--     {"name": "brochure.pdf", "url": "https://onedrive.live.com/..."},
--     {"name": "case-study.docx", "url": "https://1drv.ms/..."}
--   ]
--
-- Empty array '[]' is the default and is treated as "no attachments"
-- by the send pipeline. Existing rows get this default for free.

ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb;
