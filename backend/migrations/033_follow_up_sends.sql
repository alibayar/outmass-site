-- 033: remember who has already been followed up, so the bump can trail the
-- send instead of arriving all at once at the end.
--
-- WHY THIS EXISTS
--
-- "Follow up 3 days later" meant 3 days after the CAMPAIGN, not 3 days after
-- the recipient got it. For a campaign that goes out at once those are the
-- same moment. For one paced by daily_send_cap they are not: a customer
-- sending 66 recipients at 5 a day takes a fortnight, and until now everyone
-- was bumped together at the end — 16 days late for the people who received
-- the original on day one, and exactly 3 for the last five.
--
-- The reason it could not simply send in batches is that follow_ups.status is
-- a single row-level flag. The worker sent to whoever matched, then marked
-- the whole follow-up 'sent'. To bump some recipients today and the rest on
-- Thursday, it has to remember which is which — and remembering wrongly
-- means emailing someone twice, from their own mailbox, which is the worst
-- outcome available here.
--
-- WHY A TABLE AND NOT A COLUMN
--
-- A flag on `contacts` would be wrong: a campaign may carry more than one
-- follow-up (models/followup.get_campaign_followups returns a list, and
-- nothing stops a second one), and a single boolean cannot say which of them
-- has already been sent.
--
-- A high-water timestamp on follow_ups was the cheaper idea and was rejected.
-- It assumes contacts.sent_at only ever moves forward within a campaign, and
-- it loses anyone whose sent_at ties with the mark. The composite primary key
-- below makes a double bump impossible at the database rather than probable-
-- ly-impossible in the application, and that is worth one small table.
--
-- ADDITIVE AND SAFE ON A LIVE DB: one new table, nothing existing altered.
-- Empty means "nobody has been bumped yet", which is true of every follow-up
-- that has already closed, so this may be run before the code that writes it.
--
-- REVERSAL: DROP TABLE follow_up_sends. The cost is that any follow-up still
-- open at that moment forgets who it has already emailed, and its next run
-- would bump them again. Check first:
--   SELECT count(*) FROM follow_ups WHERE status = 'scheduled';   -- expect 0

BEGIN;

CREATE TABLE IF NOT EXISTS follow_up_sends (
    follow_up_id UUID NOT NULL REFERENCES follow_ups(id) ON DELETE CASCADE,
    contact_id   UUID NOT NULL REFERENCES contacts(id)   ON DELETE CASCADE,
    -- When the bump actually left, not when it was due. Only ever read by a
    -- human asking "when did this person hear from us"; the worker cares
    -- about the row existing, nothing more.
    sent_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- The whole point. A second insert for the same pair raises instead of
    -- quietly adding a duplicate, so "have we already emailed them" cannot
    -- drift from the truth even if the worker is interrupted and re-run.
    PRIMARY KEY (follow_up_id, contact_id)
);

-- The worker's only query: every contact this follow-up has covered.
CREATE INDEX IF NOT EXISTS idx_follow_up_sends_followup
    ON follow_up_sends (follow_up_id);

COMMIT;

-- ── Verification ──
--
-- 1) The table exists and is empty:
--      SELECT count(*) FROM follow_up_sends;             -- 0
--
-- 2) The double-bump guard is real (both statements, second must RAISE):
--      -- pick any follow-up and contact ids, then:
--      INSERT INTO follow_up_sends (follow_up_id, contact_id) VALUES (<f>, <c>);
--      INSERT INTO follow_up_sends (follow_up_id, contact_id) VALUES (<f>, <c>);
--      -- expect: duplicate key value violates unique constraint
--      DELETE FROM follow_up_sends WHERE follow_up_id = <f>;
--
-- 3) Once a paced campaign is running, the trail is readable:
--      SELECT f.campaign_id, count(*) AS bumped, min(s.sent_at), max(s.sent_at)
--      FROM follow_up_sends s JOIN follow_ups f ON f.id = s.follow_up_id
--      GROUP BY f.campaign_id;
