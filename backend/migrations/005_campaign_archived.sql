-- 005: campaign archive flag
-- Adds `archived` column so old campaigns can be hidden from the default
-- Reports view without being deleted.

ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS campaigns_user_archived_idx
    ON campaigns (user_id, archived);
