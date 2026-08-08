-- 026: manual promo grants — a plan gift that undoes itself exactly.
--
-- WHY THIS EXISTS
--
-- Granting a free plan by hand used to be four separate UPDATEs done from
-- memory, and one of them was destructive: to make the expiry beat able to
-- see the row at all, we had to NULL users.stripe_subscription_id. That
-- column is the ONLY link back to the customer's dead Stripe subscription,
-- and once overwritten it is gone. The plan was to "write it down somewhere
-- and put it back later" — which is another way of saying it would not have
-- been put back.
--
-- NOTE the stash is an ARCHIVE, not something the expiry writes back. The
-- column means "this user's CURRENT subscription", and since this function
-- refuses to run over a live one (see the guard below), every stashed id is
-- one an operator confirmed dead. Putting a dead id back would be a false
-- value in a live field — and account.py blocks account deletion on (paid
-- plan AND a subscription id), so it could stop someone deleting their own
-- account over a subscription that does not exist. The id is preserved
-- here, stripe_customer_id is never cleared, and Stripe stays one query
-- away; that is what "do not lose it" needed.
--
-- The load-bearing detail is in scheduled_worker.expire_manual_promos:
--
--     # Never touch a real paying customer.
--     if user.get("stripe_subscription_id"):
--         continue
--
-- So a promo granted to someone who still carries a (dead) subscription id
-- NEVER expires — the gift silently becomes permanent. And daily_report
-- counts a real payer as "paid plan + live subscription id", so that same
-- row would also be reported as paying revenue that does not exist.
--
-- This migration makes the grant a transaction with a record: what we gave,
-- what we took, and what to put back. Expiry reads that record instead of
-- guessing.
--
-- ADDITIVE AND SAFE ON A LIVE DB: one new table, one new function, no
-- existing table or column is altered. Nothing reads the new table until
-- the matching worker change deploys, so this may be run BEFORE the code.
--
-- REVERSAL IS NOT FREE. `DROP TABLE manual_promo_grants` removes the
-- restore data along with the table, so any promo still active at that
-- moment can no longer be undone correctly — its users would keep the
-- granted plan and lose their stashed subscription id permanently. To roll
-- back safely: first let every active grant expire (or restore them by
-- hand from the table), confirm `SELECT count(*) FROM manual_promo_grants
-- WHERE status = 'active'` is 0, and only then drop.

BEGIN;

CREATE TABLE IF NOT EXISTS manual_promo_grants (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                         UUID NOT NULL,
    email                           TEXT,
    granted_plan                    TEXT NOT NULL,
    -- What to put back when the promo ends. Captured at grant time, but
    -- deliberately mutable: if the customer's Stripe subscription dies
    -- DURING the promo, the webhook retargets this to 'free' so we don't
    -- restore a paid plan they are no longer paying for.
    previous_plan                   TEXT NOT NULL,
    -- The stash. NULL is a legitimate value (a user who never subscribed),
    -- which is why the restore decision keys off the grant row's existence
    -- and status, never off this column being non-NULL.
    previous_stripe_subscription_id TEXT,
    reason                          TEXT,
    granted_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at                      TIMESTAMPTZ NOT NULL,
    -- active     — running; the user is on granted_plan
    -- restored   — expired and undone; user back on previous_plan
    -- superseded — the user became a real paying subscriber during the
    --              promo, so there was nothing to undo. Never downgrade a
    --              paying customer.
    status                          TEXT NOT NULL DEFAULT 'active',
    resolved_at                     TIMESTAMPTZ
);

-- One active grant per user. A second grant while one is running raises a
-- unique violation instead of silently overwriting the first grant's
-- restore data — which would strand the user on a paid plan forever.
CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_grants_one_active
    ON manual_promo_grants (user_id) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_promo_grants_due
    ON manual_promo_grants (expires_at) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_promo_grants_user
    ON manual_promo_grants (user_id);


-- ── The whole grant, as one call ──
--
--   SELECT grant_manual_promo('someone@example.com', 'starter', 60, 'why');
--
-- Atomic: either the record and the plan change both land, or neither
-- does. That is the point — the previous procedure could half-apply, and
-- a half-applied grant is the permanent-gift bug above.
CREATE OR REPLACE FUNCTION grant_manual_promo(
    p_email                TEXT,
    p_plan                 TEXT,
    p_days                 INT,
    p_reason               TEXT,
    -- Required ONLY when the user still carries a subscription id. See the
    -- guard below: passing it is how the operator proves they looked at
    -- Stripe and the subscription is genuinely dead.
    p_dead_subscription_id TEXT DEFAULT NULL
) RETURNS manual_promo_grants AS $$
DECLARE
    u          users%ROWTYPE;
    grant_row  manual_promo_grants;
BEGIN
    SELECT * INTO u FROM users WHERE email = p_email;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'grant_manual_promo: no user with email %', p_email;
    END IF;

    -- ── Never grant over a LIVE subscription ──
    --
    -- A promo overrides users.plan while Stripe keeps its own state. If the
    -- subscription is still alive, those two disagree and every disagreement
    -- resolves against us:
    --
    --   * the next renewal fires customer.subscription.updated(active),
    --     which is deliberately unshielded, so the plan silently snaps back
    --     to whatever they were paying for — the gift dies within days and
    --     nothing looks broken;
    --   * create_checkout decides "existing subscriber vs new" purely from
    --     users.stripe_subscription_id, which this function clears, so an
    --     upgrade click can open a SECOND live subscription and double-bill
    --     a real customer;
    --   * a payment blip on the live subscription retargets the grant's
    --     restore plan to 'free', and if the retry then succeeds nothing
    --     undoes that — expiry later downgrades someone who is paying.
    --
    -- The database cannot tell a dead subscription id from a live one; only
    -- Stripe knows. So we refuse, and the way to proceed is to pass the id
    -- back in — which requires having opened Stripe and looked at it.
    --
    -- If the subscription really is alive and the customer should get
    -- something free, the instrument is a Stripe coupon or credit, not a
    -- plan override.
    IF u.stripe_subscription_id IS NOT NULL
       AND u.stripe_subscription_id IS DISTINCT FROM p_dead_subscription_id THEN
        RAISE EXCEPTION
            'grant_manual_promo: % still carries subscription %. Check it in '
            'Stripe. If it is dead, pass it as p_dead_subscription_id to '
            'confirm. If it is LIVE, do not grant a promo — use a Stripe '
            'coupon instead.',
            p_email, u.stripe_subscription_id;
    END IF;

    -- Fail loudly on a typo rather than write a plan name the quota
    -- lookup does not know: monthly_limit_for_plan() falls back to the
    -- FREE limit for anything unrecognised, so 'startre' would look like
    -- a successful grant and deliver 250 sends a month.
    IF p_plan NOT IN ('starter', 'pro') THEN
        RAISE EXCEPTION 'grant_manual_promo: plan must be starter or pro, got %', p_plan;
    END IF;

    IF p_days IS NULL OR p_days < 1 THEN
        RAISE EXCEPTION 'grant_manual_promo: promo length must be >= 1 day, got %', p_days;
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
        -- Cleared so the expiry beat can see this row (see the comment at
        -- the top). The original value is archived in the grant record
        -- above and stays there — expiry does NOT write it back, because
        -- by then it is a confirmed-dead id and the column means "current".
        stripe_subscription_id = NULL,
        plan_updated_at        = now()
    WHERE id = u.id;

    RETURN grant_row;
END;
$$ LANGUAGE plpgsql;

COMMIT;

-- ── Verification ──
--
-- 1) Nothing granted yet:
--      SELECT count(*) FROM manual_promo_grants;   -- 0
--
-- 2) The guards fire (each should RAISE, and change nothing):
--      SELECT grant_manual_promo('nobody@example.com', 'starter', 60, 'x');
--      SELECT grant_manual_promo('<real email>', 'startre', 60, 'x');
--      SELECT grant_manual_promo('<real email>', 'starter', 0, 'x');
--      -- and, for anyone still carrying a subscription id:
--      SELECT grant_manual_promo('<that email>', 'starter', 60, 'x');
--      -- → refuses, and names the subscription to go check in Stripe.
--
-- 2b) Granting over a subscription you have CONFIRMED dead in Stripe:
--      SELECT grant_manual_promo(
--        '<email>', 'starter', 60, '<reason>',
--        p_dead_subscription_id := '<the exact id the error named>'
--      );
--     If the subscription turns out to be LIVE, do not do this — the plan
--     column and Stripe would disagree, and every way that resolves costs
--     us or the customer. Use a Stripe coupon instead.
--
-- 3) Live grants and what they will restore:
--      SELECT email, granted_plan, previous_plan,
--             previous_stripe_subscription_id, expires_at, status
--      FROM manual_promo_grants ORDER BY granted_at DESC;
