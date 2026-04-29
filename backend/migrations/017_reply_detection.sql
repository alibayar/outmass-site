-- 017: reply tracking — most reliable engagement signal we have.
--
-- Open tracking (pixel) is heavily distorted by Outlook's "block
-- remote images" default and Apple Mail Privacy Protection (which
-- pre-loads pixels and inflates opens to ~95% regardless of real
-- engagement). Click tracking is better but still misses recipients
-- who open the email, read it, and reply without clicking.
--
-- A reply is the strongest possible engagement signal: the recipient
-- saw the message, processed it, and acted. Worth its own column on
-- contacts so we can compute reply_rate alongside open_rate /
-- click_rate / engaged_rate.
--
-- The matching logic (workers/reply_detector.py) scans the user's
-- Outlook Inbox via Microsoft Graph for messages whose sender matches
-- a contact's email and whose conversation arrived AFTER we sent to
-- that contact. We deliberately don't store the reply body itself —
-- the contact's own mailbox keeps that, and we have no business
-- holding a copy of their counterparty's words.

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS replied_at TIMESTAMPTZ;

-- Index for the reply-rate computation in /campaigns/{id}/stats:
-- counts replied contacts per campaign in O(replied) instead of
-- scanning every contact row.
CREATE INDEX IF NOT EXISTS idx_contacts_replied_at
    ON contacts(campaign_id)
    WHERE replied_at IS NOT NULL;
