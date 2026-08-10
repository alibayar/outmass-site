-- 027: grant_manual_promo must not pick a row at random.
--
-- A NEW file rather than an edit to 026, because 026 has already been run
-- against production — editing it would change a document of what happened
-- without changing the function that exists in the database. CREATE OR
-- REPLACE FUNCTION carries the correction forward.
--
-- ── Why ──
--
-- 026 selects the target user by email:
--
--     SELECT * INTO u FROM users WHERE email = p_email;
--
-- and users.email carries NO unique constraint (schema.sql: `email TEXT NOT
-- NULL`; only microsoft_id is UNIQUE). In PL/pgSQL, SELECT ... INTO with
-- several matching rows does not raise — it takes an arbitrary one and
-- continues. So on a duplicated address the function would gift one row,
-- report success, and leave the user signing into the other.
--
-- Two rows for one address is not hypothetical: microsoft_id is the Entra
-- object id, and a tenant migration or a personal-plus-work pair with the
-- same address mints a second row through upsert_user's insert path.
--
-- The 2026-08-08 adversarial review of 026 raised exactly this question. The
-- agent examining it died on a session limit and the finding was never
-- checked. It was not the cause of the Faisal incident two days later — that
-- was a deploy-order gap — but the hazard is real and was found by looking
-- for the cause of something else.
--
-- ── Also: a warning the incident earned ──
--
-- Granting is a DATABASE write; keeping the grant alive is APPLICATION
-- behaviour (the promo shield in billing.py, which stops a Stripe
-- cancellation from clearing the plan). On 2026-08-08 a promo was granted
-- eleven minutes after the shield was committed and about six hours before
-- it was deployed. That afternoon Stripe cancelled the customer's failed
-- subscription, the still-old handler wrote plan='free', and a gift promised
-- in writing quietly evaporated. Nothing in the database was wrong; the code
-- that was meant to defend it simply was not running yet.
--
-- So the function now says so, in the one place someone reads at the moment
-- they are about to grant.
--
-- Additive and idempotent. Reversal: re-run 026's function body.

BEGIN;

CREATE OR REPLACE FUNCTION grant_manual_promo(
    p_email                TEXT,
    p_plan                 TEXT,
    p_days                 INT,
    p_reason               TEXT,
    p_dead_subscription_id TEXT DEFAULT NULL
) RETURNS manual_promo_grants AS $$
DECLARE
    u            users%ROWTYPE;
    grant_row    manual_promo_grants;
    match_count  INT;
BEGIN
    -- Count first, select second. users.email is not unique, and a silent
    -- arbitrary pick would gift the wrong row while reporting success.
    SELECT count(*) INTO match_count FROM users WHERE email = p_email;

    IF match_count = 0 THEN
        RAISE EXCEPTION 'grant_manual_promo: no user with email %', p_email;
    END IF;

    IF match_count > 1 THEN
        RAISE EXCEPTION
            'grant_manual_promo: % rows share the email %. Pick the right one '
            'by id — the one whose microsoft_id matches the account they '
            'actually sign in with — and grant it by hand. Guessing here '
            'gifts one row while they use the other.',
            match_count, p_email;
    END IF;

    SELECT * INTO u FROM users WHERE email = p_email;

    IF p_plan NOT IN ('starter', 'pro') THEN
        RAISE EXCEPTION 'grant_manual_promo: plan must be starter or pro, got %', p_plan;
    END IF;

    IF p_days IS NULL OR p_days < 1 THEN
        RAISE EXCEPTION 'grant_manual_promo: promo length must be >= 1 day, got %', p_days;
    END IF;

    -- Never grant over a LIVE subscription. See 026 for the full reasoning:
    -- the plan column and Stripe would disagree, and every way that
    -- disagreement resolves costs us or the customer.
    IF u.stripe_subscription_id IS NOT NULL
       AND u.stripe_subscription_id IS DISTINCT FROM p_dead_subscription_id THEN
        RAISE EXCEPTION
            'grant_manual_promo: % still carries subscription %. Check it in '
            'Stripe. If it is dead, pass it as p_dead_subscription_id to '
            'confirm. If it is LIVE, do not grant a promo — use a Stripe '
            'coupon instead.',
            p_email, u.stripe_subscription_id;
    END IF;

    INSERT INTO manual_promo_grants (
        user_id, email, granted_plan, previous_plan,
        previous_stripe_subscription_id, reason, expires_at
    ) VALUES (
        u.id,
        u.email,
        p_plan,
        COALESCE(u.plan, 'free'),
        u.stripe_subscription_id,
        p_reason,
        now() + make_interval(days => p_days)
    )
    RETURNING * INTO grant_row;

    UPDATE users
    SET plan                   = p_plan,
        manual_promo_until     = grant_row.expires_at,
        stripe_subscription_id = NULL,
        plan_updated_at        = now()
    WHERE id = u.id;

    -- The grant is safe in the database from this moment. It is NOT safe
    -- from the billing webhooks until the promo shield is deployed, and a
    -- Stripe cancellation arriving in that window silently reverts it.
    RAISE NOTICE
        'Promo granted to % until %. This gift survives a Stripe '
        'cancellation ONLY while the promo shield in billing.py is deployed '
        '— confirm the backend is running current code before relying on it.',
        p_email, grant_row.expires_at;

    RETURN grant_row;
END;
$$ LANGUAGE plpgsql;

COMMIT;

-- ── Verification ──
--
-- 1) The ambiguity guard, without needing a duplicate to exist:
--      SELECT email, count(*) FROM users GROUP BY email HAVING count(*) > 1;
--    Any row here is an address the old function could have gifted blindly.
--
-- 2) The other guards still fire (each should RAISE, changing nothing):
--      SELECT grant_manual_promo('nobody@example.com', 'starter', 60, 'x');
--      SELECT grant_manual_promo('<real email>', 'startre', 60, 'x');
--      SELECT grant_manual_promo('<real email>', 'starter', 0, 'x');
--
-- 3) Live grants and what they will restore:
--      SELECT email, granted_plan, previous_plan, expires_at, status
--      FROM manual_promo_grants ORDER BY granted_at DESC;
