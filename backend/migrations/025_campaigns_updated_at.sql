-- 025 — campaigns.updated_at, so the stuck-campaign sweep stops guessing
--
-- reset_stuck_sending_campaigns has to answer one question: is this campaign
-- still delivering, or did the process die mid-loop? It has never had a way
-- to know, and every proxy tried so far has been wrong in a way that costs
-- someone a duplicate email:
--
--   * scheduled_for (until 2026-08-08). NULL for every campaign started with
--     Send now, because only the scheduler writes it — so the guard
--     `if scheduled_for and scheduled_for > cutoff` short-circuited on the
--     falsy NULL and the 30-minute window was skipped ENTIRELY for exactly
--     those campaigns. Any list still sending when the hourly beat fired was
--     flipped to 'partial' mid-flight, after which Resume or
--     auto_resume_partial_campaigns could start a SECOND loop over contacts
--     the first had not reached, and email those people twice.
--
--   * the newest contacts.sent_at (2026-08-08, the interim fix). Correct for
--     a first run and wrong for a resumed one: a campaign resumed after a
--     quota reset has its newest sent_at from the PREVIOUS run, days ago, so
--     it reads as stale from the moment it starts and the same mid-flight
--     flip is reachable during its first 30 minutes.
--
-- A column the database maintains itself has neither problem. The trigger is
-- the load-bearing half: without it every write path would have to remember
-- to touch the column, and the one that forgets is the one that matters —
-- increment_stat, called once per delivered recipient, which IS the progress
-- signal the sweep needs.
--
-- Safe to run more than once.
--
-- Reversal: dropping this column is genuinely safe, unlike 024's. It stores
-- no user decision and nothing is derived from it that cannot be recomputed;
-- the sweep falls back to its sent_at logic when the column is absent, which
-- is the behaviour shipped on 2026-08-08. Reverse with:
--     DROP TRIGGER IF EXISTS campaigns_set_updated_at ON campaigns;
--     ALTER TABLE campaigns DROP COLUMN IF EXISTS updated_at;

ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

COMMENT ON COLUMN campaigns.updated_at IS
    'Last time this row changed, maintained by the campaigns_set_updated_at '
    'trigger. Read by reset_stuck_sending_campaigns to tell a campaign that '
    'is still delivering from one whose process died mid-loop.';

CREATE OR REPLACE FUNCTION set_campaigns_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS campaigns_set_updated_at ON campaigns;

CREATE TRIGGER campaigns_set_updated_at
    BEFORE UPDATE ON campaigns
    FOR EACH ROW
    EXECUTE FUNCTION set_campaigns_updated_at();

-- Existing rows get now() from the DEFAULT, which reads as "just touched".
-- That is the safe direction: for one hour after the migration the sweep
-- treats every in-flight campaign as fresh and recovers nothing, rather than
-- treating a live one as dead and flipping it.
