-- 032: a complimentary plan that Stripe cannot silently take back.
--
-- WHY THIS EXISTS
--
-- Five paying customers configured follow-ups that were never created: the
-- endpoint is Pro-only and answered 402, and the panel logged that answer to
-- a debug channel nobody has on. The remedy chosen was a free month of Pro.
--
-- Writing 'pro' into users.plan does not survive. billing.py's
-- customer.subscription.updated handler rewrites plan from the Stripe price
-- whenever the status is active, and that fires on every renewal — so the
-- gift dies within the month, silently, which is the same shape of failure
-- we are apologising for.
--
-- users.manual_promo_until does not fit either. grant_manual_promo REFUSES to
-- run over a live subscription, and correctly: it clears
-- stripe_subscription_id, and six readers treat that column as "this user's
-- current subscription" — daily_report counts a real payer by it, so the four
-- affected customers would vanish from MRR and reappear as gifts.
--
-- So the comp lives in its own two columns. users.plan stays exactly what
-- Stripe says it is, every report that answers "what do they pay" keeps
-- reading it, and only the readers that answer "what may they DO" consult
-- effective_plan() in models/user.py.
--
-- It expires by arithmetic. The gate compares comp_plan_until to now(), so
-- there is no beat task to run, nothing to undo, and no state that can be
-- left half-applied the way a plan swap can.
--
-- ADDITIVE AND SAFE ON A LIVE DB: two nullable columns, no existing column
-- or row touched. NULL everywhere means today's behaviour exactly, so this
-- may be run before the code that reads it.
--
-- REVERSAL: the columns can be dropped once no row has a live comp —
--   SELECT count(*) FROM users WHERE comp_plan_until > now();   -- expect 0
-- Dropping them while a comp is live silently ends it, so check first.

BEGIN;

ALTER TABLE users
    -- 'starter' or 'pro'. NULL means no comp, which is almost everyone.
    ADD COLUMN IF NOT EXISTS comp_plan       TEXT,
    -- When it lapses. Past or NULL means the comp is over; nothing has to
    -- clean up after it.
    ADD COLUMN IF NOT EXISTS comp_plan_until TIMESTAMPTZ;

-- Small table, and the predicate is only ever read per-user by primary key,
-- so no index. Named here so the next person does not wonder.

COMMIT;

-- ── Verification ──
--
-- 1) The columns exist and nobody has one yet:
--      SELECT count(*) FILTER (WHERE comp_plan IS NOT NULL) AS comped,
--             count(*) AS total
--      FROM users;                                  -- comped = 0
--
-- 2) Granting one (the four follow-up cases, 30 days):
--      UPDATE users
--         SET comp_plan = 'pro',
--             comp_plan_until = now() + INTERVAL '30 days'
--       WHERE email = 'someone@example.com';
--
--    Note what is NOT touched: plan, stripe_subscription_id,
--    manual_promo_until. Their subscription and their MRR line are unchanged.
--
-- 3) Who is on one, and until when:
--      SELECT email, plan, comp_plan, comp_plan_until
--      FROM users WHERE comp_plan_until > now() ORDER BY comp_plan_until;
--
-- 4) Ending one early:
--      UPDATE users SET comp_plan = NULL, comp_plan_until = NULL
--       WHERE email = 'someone@example.com';
