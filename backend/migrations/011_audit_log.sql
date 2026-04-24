-- 011: Audit log for legal defensibility + fraud prevention + dispute resolution.
--
-- Why we need this:
--
-- Every email OutMass "sends" actually originates from Microsoft's servers,
-- authenticated with the user's own OAuth token. Microsoft is the source
-- of truth for delivery evidence. But if a user (or their recipient)
-- disputes a send — "OutMass sent without my consent", "I was spammed,
-- I never signed up" — we need OUR side of the evidence chain: who
-- logged in, from where, who clicked Send, what CSV they uploaded,
-- when Graph API returned 202 Accepted.
--
-- This table is the immutable ledger of user actions. It survives
-- account deletion: GDPR Art. 17(3) explicitly exempts legitimate
-- interest (fraud prevention, legal claims) from the right to erasure.
-- Turkish Tax Procedure Law (VUK) requires 5-year retention of
-- transactional records. We anonymize IP addresses after 1 year as
-- an additional GDPR data-minimization measure.
--
-- What we store per event:
--   user_id       — links to users; NULL after deletion (row survives)
--   email_hash    — SHA256 of user's email; lets us thread an audit
--                   trail across account deletion without re-storing PII
--   event_type    — see backend/models/audit.py for the enum
--   ip_address    — INET; raw for 1 year, then /24-masked for v4 / /48 for v6
--   user_agent    — browser/client string (truncated to 500 chars)
--   metadata      — event-specific JSONB; no raw recipient emails, only hashes
--   created_at    — UTC timestamp of the event
--
-- This migration is additive — no existing tables are touched. Safe
-- to run on a live DB.

BEGIN;

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    email_hash TEXT,
    event_type TEXT NOT NULL,
    ip_address INET,
    user_agent TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Deliberately NOT a FK to users(id) — we want audit_log rows to
-- outlive the user row. If we used a FK with CASCADE (migration 010's
-- pattern) the audit trail would vanish on account deletion, which
-- defeats the whole point.

-- Indexes matching the common read patterns:
--   * "pull everything for this user in date range X" (dispute defense)
--   * "find all events tied to this email hash" (post-deletion lookup)
--   * "all login events in the last hour" (fraud investigation)
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id
    ON audit_log(user_id) WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_audit_log_email_hash
    ON audit_log(email_hash) WHERE email_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_audit_log_event_type_created
    ON audit_log(event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_created_at
    ON audit_log(created_at);


-- IP anonymization helper function — run daily by Celery beat.
--
-- For IPv4: keep the /24 (first three octets), zero the last octet.
--   1.2.3.4 → 1.2.3.0
-- For IPv6: keep the /48, zero the rest.
--   2001:db8:abcd:1234::1 → 2001:db8:abcd::
--
-- Operates on rows older than 1 year with still-unanonymized IPs.
-- Returns counts for observability (beat task logs them).
CREATE OR REPLACE FUNCTION anonymize_old_audit_ips()
RETURNS TABLE(v4_updated INT, v6_updated INT) AS $$
DECLARE
    v4_count INT := 0;
    v6_count INT := 0;
BEGIN
    UPDATE audit_log
    SET ip_address = (host(set_masklen(ip_address, 24))::inet)
    WHERE ip_address IS NOT NULL
      AND family(ip_address) = 4
      -- Skip already-anonymized rows (last octet is zero). `host()`
      -- returns the address as text without the /prefix suffix.
      AND host(ip_address) NOT LIKE '%.0'
      AND created_at < NOW() - INTERVAL '1 year';
    GET DIAGNOSTICS v4_count = ROW_COUNT;

    UPDATE audit_log
    SET ip_address = (host(set_masklen(ip_address, 48))::inet)
    WHERE ip_address IS NOT NULL
      AND family(ip_address) = 6
      AND created_at < NOW() - INTERVAL '1 year';
    GET DIAGNOSTICS v6_count = ROW_COUNT;

    RETURN QUERY SELECT v4_count, v6_count;
END;
$$ LANGUAGE plpgsql;

COMMIT;

-- ── Verification ──
--
-- 1) Table + indexes:
--    \d audit_log
--
-- 2) Anonymization function:
--    SELECT * FROM anonymize_old_audit_ips();
--    -- returns two INT columns; both 0 on a fresh install.
--
-- 3) Insert sanity check:
--    INSERT INTO audit_log(event_type, metadata) VALUES ('test', '{}');
--    SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 1;
--    DELETE FROM audit_log WHERE event_type = 'test';
