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
| **scanner-open backfill** (not a numbered migration — a manual UPDATE) | 2026-09-02, Ali, in the Supabase editor | ✅ 2026-09-03 — `tara.white@cbre.com`: `opened_at` NULL with `open_events` = 1, sent 09:41:47 UTC and fetched 11 seconds later, ~8 hours BEFORE the classifier deployed. A contact with an open event and no `opened_at` cannot be produced by the write path. See below. |
| 035_send_days | 2026-09-02, Ali (in chat) | ✅ 2026-09-02 — `select id, name, send_days from campaigns limit 1;` answered in the Supabase editor with `send_days` NULL. A named SELECT: a missing column errors rather than returning NULL. |
| 034_sender_logo_url | 2026-09-01, Ali (in chat) | ✅ 2026-09-02 — `SELECT email, sender_logo_url FROM users WHERE email = 'bayar_ali@hotmail.com';` answered in the Supabase editor with one row, `sender_logo_url` NULL. A named SELECT: a missing column errors rather than returning NULL, so the answer itself is the proof. Not yet proven to accept WRITES — the second query below covers that once a logo has been saved from Settings. |
| 033_follow_up_sends | 2026-08-30, Ali (in chat) | ✅ 2026-08-30 — `SELECT count(*) FROM follow_up_sends;` returned 0 in the Supabase editor. A named SELECT on the table itself: if it did not exist the statement would have errored rather than answered. |
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

## The scanner-open backfill — the one this ledger nearly lost

Not a numbered migration, which is exactly why it nearly went unrecorded: a
manual UPDATE run in the Supabase editor on 2026-09-02, clearing
`contacts.opened_at` and lowering `campaigns.open_count` for opens the new
`looks_automated()` classifier calls automated. **The SQL text was never
captured.** The rule at the top of this file exists for migrations; this was
the same act by another name, and the ledger should hold it too.

Found missing on 2026-09-03 by an adversarial review of the announcement that
was about to tell every user "we've corrected your past campaigns as well".
The reviewer could find no migration, no script and no ledger row, and was
right on every one of those. What it could not see was production.

**Why we believe it ran** — from Hélène Carpentier's CBRE campaign, queried
2026-09-03:

- 15 contacts sent; all 15 have at least one `open` event.
- `tara.white@cbre.com`'s only open is 11 seconds after her send, from a
  generic desktop user-agent — automated under `looks_automated()`.
- The classifier deployed at ~17:30 UTC on 2026-09-02 (`ee904ca`, committed
  19:59 +0300). Her fetch was **09:41 UTC the same day**, ~7 hours earlier, so
  the live filter cannot have been what excluded her.
- Under the old write path her fetch set `opened_at` and incremented
  `open_count`, so the campaign would read 15.
- It reads **14**, and `count(contacts WHERE opened_at IS NOT NULL)` is also
  14.

One row was cleared retroactively, and it is precisely the row the classifier
names. That is a strong inference, not a proof.

**The named SELECT that would make it a proof** — run this and record the
answer here:

```sql
SELECT ct.email, ct.opened_at, ct.sent_at,
       (SELECT count(*) FROM events e
         WHERE e.contact_id = ct.id AND e.event_type = 'open') AS open_events
FROM contacts ct
WHERE ct.email = 'tara.white@cbre.com';
```

Expected if the backfill ran: `opened_at` NULL **and** `open_events` ≥ 1. A
contact with an open event and no `opened_at` cannot be explained by the write
path — only by something that went back and cleared it.

**Answer, 2026-09-03:**

| email | opened_at | sent_at | open_events |
|---|---|---|---|
| tara.white@cbre.com | null | 2026-09-02 09:41:47+00 | 1 |

Proven. She was sent at 09:41:47 and fetched 11 seconds later, roughly eight
hours before `ee904ca` reached production, so the live guard cannot be what
spared her. Her `opened_at` was cleared afterwards. The backfill ran.

That also makes three public statements true rather than merely believed: this
ledger row, the v0.3.3 CHANGELOG line ("we have corrected the history so past
campaigns read correctly too"), and the sentence sent to Hélène on 2026-09-03.

**The lesson is the process, not the outcome.** The backfill was real and the
copy was accurate — and for a day the only record of either lived in a chat
log. A review found the gap by looking for an artifact and finding none, which
is what anyone would find, including us in a month. An unnumbered manual
UPDATE against live customer data belongs in this file the moment it runs,
with its SQL. We could not record the SQL here because nobody kept it.

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

---

## 034_sender_logo_url — verification (2026-09-01)

A named SELECT, not `information_schema`, and not a `.get()` path: the settings
endpoint reads this column with `user.get("sender_logo_url")`, which returns
None for a missing column exactly as it does for an empty one. That path can
never tell us whether the migration ran.

```sql
SELECT email, sender_logo_url
FROM users
WHERE email = 'alibayar@gmail.com';
```

Expected: one row, `sender_logo_url` NULL. If the column were missing the
statement would ERROR rather than answer, which is the whole point of naming it.

Then, once a logo has been saved from Settings at least once, the stronger
check — that it exists AND accepts writes:

```sql
SELECT email, sender_logo_url
FROM users
WHERE sender_logo_url IS NOT NULL;
```
