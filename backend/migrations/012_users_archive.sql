-- 012: users_archive — anonymised tombstone for deleted accounts.
--
-- When a user exercises their GDPR right to erasure, we delete their
-- users row (cascades through campaigns, contacts, tokens, etc. via
-- migration 010). But deleting EVERY trace breaks three real needs:
--
--   1. Chargeback dispute: "I never had an account." Stripe retains
--      their customer_id and invoice history for 7+ years; we need a
--      stub on our side to prove we processed a real relationship.
--   2. Fraud detection: spotting the same email creating + deleting +
--      recreating accounts to abuse free-tier limits.
--   3. Turkish VUK + UK/EU tax law: transactional records retained 5-10y.
--
-- The trade-off is: store the absolute minimum. No name, no raw email,
-- no campaign content, no recipient addresses. Just:
--   * A UUID that was previously users.id (non-identifying on its own).
--   * A SHA-256 email hash (matches audit_log.email_hash for continuity).
--   * Aggregate counters (how many emails/campaigns lifetime).
--   * Stripe customer_id (a reference to Stripe's own retained records).
--   * Timestamps and a reason code for why the row landed here.
--
-- Under GDPR Art. 6(1)(f) legitimate interest + Art. 17(3)(b) legal
-- obligation, this processing is lawful.

BEGIN;

CREATE TABLE IF NOT EXISTS users_archive (
    archive_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_user_id    UUID NOT NULL,
    email_hash          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL,
    deleted_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    plan_at_deletion    TEXT,
    total_emails_sent   BIGINT DEFAULT 0,
    total_campaigns     INT DEFAULT 0,
    stripe_customer_id  TEXT,
    deletion_reason     TEXT NOT NULL  -- 'user_requested' | 'admin' | 'inactivity' | 'chargeback'
);

-- Deliberately NO FK to users. The point of this table is to exist
-- after the users row is gone.

CREATE INDEX IF NOT EXISTS idx_users_archive_email_hash
    ON users_archive(email_hash);

CREATE INDEX IF NOT EXISTS idx_users_archive_stripe_customer
    ON users_archive(stripe_customer_id)
    WHERE stripe_customer_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_users_archive_deleted_at
    ON users_archive(deleted_at);

-- Atomic archive-then-delete RPC.
--
-- Supabase's REST client can't open a multi-statement transaction, so
-- we wrap the two writes in a plpgsql function. Either both succeed
-- (archive row inserted + user cascade-deleted) or neither does.
--
-- Parameters:
--   p_user_id          — users.id to delete.
--   p_deletion_reason  — one of the four reason codes above.
--
-- Returns the new archive_id so the caller can reference it in the
-- confirmation email / audit log.
CREATE OR REPLACE FUNCTION archive_and_delete_user(
    p_user_id UUID,
    p_deletion_reason TEXT
)
RETURNS UUID AS $$
DECLARE
    v_archive_id UUID;
    v_email_hash TEXT;
    v_created_at TIMESTAMPTZ;
    v_plan TEXT;
    v_stripe_customer TEXT;
    v_total_sent BIGINT;
    v_total_campaigns INT;
BEGIN
    -- Pull the fields we want to preserve. If the user doesn't exist
    -- (double-delete), raise so the caller sees an explicit error
    -- rather than a silent no-op.
    SELECT
        encode(digest(lower(trim(email)), 'sha256'), 'hex'),
        created_at,
        plan,
        stripe_customer_id
    INTO
        v_email_hash,
        v_created_at,
        v_plan,
        v_stripe_customer
    FROM users
    WHERE id = p_user_id;

    IF v_email_hash IS NULL THEN
        RAISE EXCEPTION 'user % not found', p_user_id;
    END IF;

    -- Aggregate the lifetime counters BEFORE cascade delete wipes them.
    SELECT COALESCE(SUM(sent_count), 0), COUNT(*)
    INTO v_total_sent, v_total_campaigns
    FROM campaigns
    WHERE user_id = p_user_id;

    INSERT INTO users_archive (
        original_user_id,
        email_hash,
        created_at,
        plan_at_deletion,
        total_emails_sent,
        total_campaigns,
        stripe_customer_id,
        deletion_reason
    ) VALUES (
        p_user_id,
        v_email_hash,
        v_created_at,
        v_plan,
        v_total_sent,
        v_total_campaigns,
        v_stripe_customer,
        p_deletion_reason
    ) RETURNING archive_id INTO v_archive_id;

    -- CASCADE (migration 010) handles campaigns → contacts → events,
    -- suppression_list, follow_ups, user_tokens, templates, ab_tests.
    DELETE FROM users WHERE id = p_user_id;

    RETURN v_archive_id;
END;
$$ LANGUAGE plpgsql;

-- pgcrypto is used for the digest(...) call. Supabase enables it by
-- default, but be explicit in case anyone runs this on a vanilla PG.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

COMMIT;

-- ── Verification ──
--
-- 1) Table exists:
--    \d users_archive
--
-- 2) Function callable (on a throwaway test user):
--    SELECT archive_and_delete_user('<uuid>'::uuid, 'user_requested');
--    -- returns a UUID (the new archive row's archive_id)
--
-- 3) Confirm deletion cascaded:
--    SELECT count(*) FROM campaigns WHERE user_id = '<uuid>';  -- 0
--    SELECT count(*) FROM user_tokens WHERE user_id = '<uuid>';  -- 0
--    SELECT * FROM users_archive WHERE original_user_id = '<uuid>';  -- 1 row
