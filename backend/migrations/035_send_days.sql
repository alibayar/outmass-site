-- 035 — campaigns.send_days, so a paced campaign can skip the weekend
--
-- Hélène Carpentier, 2026-09-02: "with the scheduling it would be great to
-- have the option to pick the days on which it sends - like for example I do
-- not need to send emails on saturdays and sundays."
--
-- Her campaign is cold outreach to workplace leads at large corporates. A
-- Sunday-morning send reads as machinery, which is the one impression a
-- personal note cannot afford.
--
-- ISO weekday numbers: 1 = Monday … 7 = Sunday. An array rather than a bit
-- mask so the value is readable in a query result and orderable in a UI
-- without decoding.
--
-- NULL means every day, which is what every existing campaign does today, so
-- no row changes behaviour and no backfill is needed. An empty array would
-- mean "never send", which is not a thing anyone wants and which the check
-- constraint below refuses.
--
-- Reversible: DROP COLUMN. The worker treats NULL and a missing column the
-- same way, so a rollback simply restores every-day sending.

ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS send_days SMALLINT[];

ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_send_days_valid;
ALTER TABLE campaigns ADD CONSTRAINT campaigns_send_days_valid CHECK (
  send_days IS NULL
  OR (
    array_length(send_days, 1) BETWEEN 1 AND 7
    AND send_days <@ ARRAY[1,2,3,4,5,6,7]::SMALLINT[]
  )
);

COMMENT ON COLUMN campaigns.send_days IS
  'ISO weekdays (1=Mon..7=Sun) this campaign may send on, in UTC. NULL means '
  'every day. Enforced in workers/scheduled_worker.py, which rolls '
  'scheduled_for forward to the next permitted day rather than sending.';

-- down:
--   ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_send_days_valid;
--   ALTER TABLE campaigns DROP COLUMN IF EXISTS send_days;
