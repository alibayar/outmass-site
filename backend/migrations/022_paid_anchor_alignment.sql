-- 022 — One-time paid-anchor alignment (run AFTER the code deploy)
--
-- Aligns current paid users' month_reset_date to their billing anniversary so
-- the new rolling reset keeps quota month == billed month. Must run AFTER the
-- backend deploy: the old calendar-reset code would clobber these anchors
-- with 'today' at the user's next login.
--
-- ⚠️ STEP 0 — VERIFY THE ANCHOR SOURCE FIRST (manual, ~1 minute):
-- plan_updated_at is "last plan-row touch", not necessarily the billing
-- anniversary — it is also bumped by portal edits (customer.subscription.
-- updated), failed-payment retries (invoice.payment_failed), and the in-app
-- modify path (which KEEPS the original Stripe billing day). Before running
-- the UPDATE, compare each paid user against the Stripe dashboard
-- (subscription → current_period_start):
--
--   SELECT email, plan, plan_updated_at::date AS assumed_anchor,
--          month_reset_date, emails_sent_this_month
--   FROM users WHERE plan IN ('starter','pro');
--
-- If a user's Stripe current_period_start DAY differs from assumed_anchor's
-- day, hand-correct with:
--   UPDATE users SET month_reset_date = '<stripe_period_start_date>'
--   WHERE email = '<email>';
-- ...and skip them in the bulk UPDATE below (add: AND email != '<email>').
--
-- Counter policy (both directions safe-for-the-user):
--   * anchor moves FORWARD past the last reset → the counter still contains
--     PRE-period usage → zero it (otherwise a paying user is blocked with
--     last period's sends counted against the new period).
--   * anchor moves BACKWARD (or equal) → the old calendar rule already reset
--     recently → keep the counter (the bonus is grandfathered; NEVER claw
--     back a paying user's remaining quota mid-period).

WITH anchors AS (
  SELECT id,
         ((plan_updated_at AT TIME ZONE 'UTC')::date
          + make_interval(months => (
              EXTRACT(YEAR FROM AGE(now(), plan_updated_at)) * 12
              + EXTRACT(MONTH FROM AGE(now(), plan_updated_at))
            )::int))::date AS anchor
  FROM users
  WHERE plan IN ('starter', 'pro') AND plan_updated_at IS NOT NULL
)
UPDATE users u
SET month_reset_date = a.anchor,
    emails_sent_this_month = CASE
      WHEN a.anchor > u.month_reset_date THEN 0
      ELSE u.emails_sent_this_month END,
    ai_generations_this_month = CASE
      WHEN a.anchor > u.month_reset_date THEN 0
      ELSE u.ai_generations_this_month END
FROM anchors a
WHERE u.id = a.id;

-- Post-check (eyeball: anchors should match each user's Stripe billing day):
--   SELECT email, plan, month_reset_date, emails_sent_this_month
--   FROM users WHERE plan IN ('starter','pro');
