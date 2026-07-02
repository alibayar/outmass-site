-- 021 — Lifetime sent counter + dual-counter RPC + backfill
--
-- Run BEFORE deploying the matching backend code (the code's RPC fallback
-- writes emails_sent_total, so the column must exist first; old code calling
-- the new RPC is harmless — it just starts maintaining the total early).
--
-- The paid-anchor alignment is deliberately NOT here: it must run AFTER the
-- deploy (see 022) — the old calendar-reset code still running in the
-- migration→deploy window would clobber aligned anchors with 'today' at the
-- user's next login.
--
-- Reversible (down):
--   DROP FUNCTION IF EXISTS increment_user_sent_count(UUID, INT);
--   CREATE OR REPLACE FUNCTION increment_user_sent_count(user_id_input UUID, amount INT)
--   RETURNS void LANGUAGE sql AS $$
--     UPDATE users SET emails_sent_this_month = COALESCE(emails_sent_this_month,0) + amount
--     WHERE id = user_id_input; $$;
--   ALTER TABLE users DROP COLUMN IF EXISTS emails_sent_total;

-- 1. Lifetime counter (never reset; the operator's tracking metric)
ALTER TABLE users ADD COLUMN IF NOT EXISTS emails_sent_total INT DEFAULT 0;

-- 2. Atomic increment maintains both counters.
--    Drop EVERY existing overload first — the original was created ad-hoc in
--    the SQL editor with an unknown signature; a surviving overload would make
--    PostgREST rpc() fail (PGRST203) and silently push every send onto the
--    non-atomic Python fallback.
DO $$
DECLARE fn RECORD;
BEGIN
  FOR fn IN
    SELECT oid::regprocedure AS sig
    FROM pg_proc
    WHERE proname = 'increment_user_sent_count'
  LOOP
    EXECUTE 'DROP FUNCTION ' || fn.sig;
  END LOOP;
END $$;

CREATE FUNCTION increment_user_sent_count(user_id_input UUID, amount INT)
RETURNS void
LANGUAGE sql
AS $$
  UPDATE users
  SET emails_sent_this_month = COALESCE(emails_sent_this_month, 0) + amount,
      emails_sent_total      = COALESCE(emails_sent_total, 0) + amount
  WHERE id = user_id_input;
$$;

-- Verify exactly ONE definition remains (should return a single row):
--   SELECT proname, pg_get_function_identity_arguments(oid)
--   FROM pg_proc WHERE proname = 'increment_user_sent_count';

-- 3. Backfill lifetime totals from surviving 'sent' contact rows.
--    Approximation caveats (documented, acceptable): contacts of DELETED
--    campaigns are cascade-gone, and follow-up re-sends don't create contact
--    rows — so history undercounts slightly. GREATEST() keeps this idempotent
--    and never lowers an existing value.
UPDATE users u
SET emails_sent_total = GREATEST(
  COALESCE((SELECT COUNT(*)
            FROM contacts ct
            JOIN campaigns c ON ct.campaign_id = c.id
            WHERE c.user_id = u.id AND ct.status = 'sent'), 0),
  COALESCE(u.emails_sent_this_month, 0),
  COALESCE(u.emails_sent_total, 0)
);
