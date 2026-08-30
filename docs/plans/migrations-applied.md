# Applied migrations — the ledger

The rule (Ali, 2026-08-15): **when Ali says a migration has been run, it gets
written HERE, in the same sitting.** A migration whose applied-status lives
only in chat history is a migration whose status is lost by Monday — the
handoffs carried "028-031 all run by Ali" as prose, which is exactly the kind
of sentence that goes stale without anyone editing it.

One line per migration, newest first. "verified" means a query or a
production code path *proved* it — not that somebody remembers it.

| migration | applied | verified |
|---|---|---|
| 032_comp_plan | 2026-08-30, Ali (in chat) | ✅ 2026-08-30 — a named SELECT in the Supabase editor returned `comp_plan` and `comp_plan_until` WITH VALUES for Helene@circularworkplaces.com (`pro`, `2026-09-28`), which proves both columns exist and accept writes. Stronger than information_schema: a `.get()` path could not have produced that row. |
| 024_mail_read_scope_flag | before 2026-08-28, Ali (date unrecorded) | ✅ 2026-08-28 — information_schema query on `user_tokens.has_mail_read_scope` run by Ali in the Supabase SQL editor: `true` |
| 031_last_cycle_invoice_at | 2026-08-15, Ali (in chat) | ✅ 2026-08-15 — the green report ran in prod SELECTing the column by name; also the information_schema query below, all four true |
| 030_preferred_language | by 2026-08-15, Ali (in chat) | ✅ 2026-08-15 — green report's "know their language" line read it; query confirms |
| 029_month_reset_anchor_day | by 2026-08-15, Ali (in chat) | ✅ 2026-08-15 — information_schema query run by Ali in the Supabase SQL editor: `applied = true` |
| 028_cancel_at_period_end | by 2026-08-14, Ali (in chat) | ✅ 2026-08-15 — same query run, `applied = true` |

All four verified 2026-08-15. The backfill-sanity query below is now
OPTIONAL: since commit ad68d01 the write path self-heals — creation writes
the anchor and each row's first rollover fills a NULL — so its answer only
says how many rows are still waiting for their first rollover, not whether
anything is wrong.

## 024, and the gap it exposed

024 was applied at some unrecorded point and only *checked* on 2026-08-28,
because the sign-in leak review needed to know whether the column existed
before proposing anything that depends on it. The code has always been guarded
against its absence (`ms_token.py` selects columns defensively so an unrun 024
returns a row WITHOUT the field rather than raising), which is good engineering
and is also exactly why nobody noticed the status was unknown for two weeks.

The lesson is the one this file already states, arriving from a new direction:
a guard that makes a missing migration invisible makes the ledger the ONLY
place its status can live. Migrations with guards need the row here more than
the ones that would crash.

**Why it matters now:** `has_mail_read_scope` is the precondition for task #24
- moving the "Read your mail" permission off the first consent screen. The
panel has to be able to tell a user that reply detection is off before we make
declining it easy, and it cannot do that without this column. That half is now
confirmed present.

## Why "the code runs fine" is NOT proof for 028/029

030 and 031 are verified because production code SELECTs those columns **by
name** and ran clean. 028 and 029 are read via `.get()` with fallbacks off
`select("*")` rows: if either column were missing, nothing would crash — the
feature would silently not run (the cancellation hold never fires; the
anchor falls back to the clamped day). That is the silent-zero shape this
project keeps refinding, so these two need one query in the Supabase SQL
editor:

```sql
SELECT m.migration, m.col,
       EXISTS (SELECT 1 FROM information_schema.columns c
               WHERE c.table_name = 'users' AND c.column_name = m.col) AS applied
FROM (VALUES
  ('028', 'cancel_at_period_end'),
  ('029', 'month_reset_anchor_day'),
  ('030', 'preferred_language'),
  ('031', 'last_cycle_invoice_at')
) AS m(migration, col)
ORDER BY m.migration;
```

Expected: four rows, all `applied = true`. Then 029's backfill sanity:

```sql
SELECT count(*) AS rows_missing_anchor
FROM users
WHERE month_reset_date IS NOT NULL AND month_reset_anchor_day IS NULL;
```

Expected: a small number — exactly the signups between 029's backfill and the
2026-08-15 deploy (creation writes the anchor from then on, and each row's
first quota rollover heals its NULL). A LARGE number would mean the backfill
did not run.

Paste the query results (or just "all true / N rows") back into this file's
table when run.
