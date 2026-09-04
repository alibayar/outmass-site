-- 036 — campaigns.stalled_notice_at, so a long-dead campaign asks before it wakes
--
-- faisal@samaed.com, 2026-08-11. His `Wave 6 SYC Jeddah` sent 154 on 27 June
-- and stopped partway, leaving 208 people never written to. Those 208 sat for
-- six weeks and nothing told him. He signed in on 10 August at 15:15, did
-- nothing else — no send, no schedule, sidebar opened and closed — and at
-- 06:04 the next morning 204 emails went out to his customers. He called it
-- embarrassing and said he had been ready to stop using OutMass over it.
--
-- The trigger was auto_resume_partial_campaigns' dormancy hold, whose
-- docstring says what happens next in as many words: "It self-heals: one
-- sign-in writes the column and the next run resumes." He was punished for
-- opening the app.
--
-- The fix is not to stop resuming. Four live places promise that a campaign
-- capped on quota carries on by itself — the store listing in twelve
-- languages, the quota-capped email, the panel's alertQuotaCapped in fourteen,
-- and a message owed to a customer this week — and every one of them is about
-- QUOTA, a wait bounded by construction at one cycle. What is unbounded is the
-- DORMANCY hold. So the beat now asks first, but only past a threshold no
-- quota wait can reach, and the campaign waits on the Resume button it already
-- has.
--
-- This column is what keeps that ask to ONE email. The beat runs every two
-- hours; without a persistent marker the same campaign would be announced
-- twelve times a day for as long as its owner ignored it. That is not a
-- hypothetical: the quota-capped notification added two days ago was gated on
-- a condition that auto-resume re-armed every six hours, and would have sent
-- one customer about fifty-two identical emails over thirteen days. It was
-- caught by Ali asking what would happen on push, not by a test.
--
-- NULL means "not asked yet", which is what every existing row is and what the
-- Resume endpoint writes back, so a campaign that stalls again a year from now
-- gets a fresh notice rather than silence.
--
-- FORWARD is safe in either order. The worker and the Resume endpoint both
-- look for the key on the row itself (they read `select *`) and treat its
-- absence as "this migration has not been applied" — the guard goes inert and
-- auto-resume behaves exactly as it did yesterday. So the code may land before
-- the migration without producing a single surprise email.
--
-- BACKWARD is not symmetric, and the first draft of this file said it was.
-- Once campaigns have been held, every one of their owners has been told in
-- writing: "Nothing is sent until you do." Dropping the column makes
-- `stalled_notice_at IN campaign` false, which does not decline the idle
-- guard — it skips it entirely — so on the next beat every held campaign is
-- flipped to 'scheduled' and delivered. That is faisal's morning replayed for
-- all of them at once, after an explicit promise. Reverting the CODE alone
-- does exactly the same thing, for the same reason.
--
-- So a rollback has to neutralise the held rows first. Archiving is the right
-- neutraliser rather than a status change: it is the user's own stop switch,
-- it keeps auto-resume off the row, and POST /campaigns/{id}/resume clears
-- `archived` itself — so the Resume button we promised still works from the
-- Archived tab, and the promise survives the rollback.
--
-- Reversal, in this order:
--     UPDATE campaigns SET archived = true
--      WHERE status = 'partial' AND stalled_notice_at IS NOT NULL;
--     ALTER TABLE campaigns DROP COLUMN IF EXISTS stalled_notice_at;
--
-- Before any held rows exist — which is the case the day this ships, because
-- nothing is backfilled — the UPDATE matches nothing and the DROP alone is
-- genuinely enough. Run it anyway; it costs one statement and it is the step
-- nobody will remember to add later.
--
-- And do NOT backfill this column to skip the notifications. A row with
-- stalled_notice_at set leaves the beat at the top of the loop, BEFORE the
-- idle-days test and before the quota test, so backfilling every partial
-- campaign would freeze the ones legitimately waiting on a quota reset —
-- including the thirty-eight recipients marketing@hrds.com is expecting on
-- 16 September — held forever, never emailed, waiting on a button nobody was
-- told to press.

ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS stalled_notice_at TIMESTAMPTZ;

COMMENT ON COLUMN campaigns.stalled_notice_at IS
    'When we emailed this campaign''s owner to say it had been silent too long '
    'to resume on its own. NULL = never asked. Written by '
    'auto_resume_partial_campaigns before it sends that email, so the ask '
    'happens once; cleared by POST /campaigns/{id}/resume, so a later stall '
    'can ask again.';
