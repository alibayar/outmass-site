-- 006: cross-campaign dedup (Pro feature)
-- Adds two user-level settings:
--   cross_campaign_dedup_enabled  – on/off (default TRUE; only effective for Pro plan)
--   cross_campaign_dedup_days     – lookback window in days (default 60)
-- When enabled, a CSV upload skips email addresses the user has already sent
-- (or queued as pending) within the window across all previous campaigns.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS cross_campaign_dedup_enabled BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS cross_campaign_dedup_days INTEGER NOT NULL DEFAULT 60;

-- Index helps the upload-time dedup query: "find all my contacts since T"
CREATE INDEX IF NOT EXISTS contacts_campaign_status_sent_idx
    ON contacts (campaign_id, status, sent_at);
