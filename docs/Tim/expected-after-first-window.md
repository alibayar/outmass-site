# Tim's campaign — what the first daily window should look like

Snapshot before it ran is in `query_results.txt`, taken 2026-09-01 ~07:10 UTC,
about fifty minutes before the campaign was due.

Campaign `c813f366-d407-45c6-95cc-8a2a93016f16`, owner
`TimHaverkamp@improve4all.nl`. This is the first customer campaign to run on
the close-out changes in `01e18bb`, so it is worth checking rather than
assuming.

## Before

| | |
|---|---|
| campaign status | `scheduled`, `scheduled_for` 2026-09-01 08:00:00+00 |
| contacts | 108, all `pending`, none unsubscribed, no `sent_at` |
| follow_ups | none — he was refused on 08-31, before saving existed |
| daily_send_cap | 15 |
| owner | `starter` + `comp_plan` `pro` until 2026-10-01, `requires_reauth` false |
| emails_sent_this_month | 0 (Starter allows 2,500) |

## Expected after the first window

Re-run the same four queries and compare:

| | expected |
|---|---|
| contacts `sent` | **15**, each with a `sent_at` on 2026-09-01 |
| contacts `pending` | **93** |
| campaign status | **`scheduled`** again, `scheduled_for` about 24h later |
| `sent_count` | **15** |
| `emails_sent_this_month` | **15** |

Roughly eight windows to finish, so 1–8 September.

## The one thing that would mean a regression

**The campaign must come back as `scheduled`, not `sent`.**

The daily-cap branch (`scheduled_worker.py:284`) is the one place that already
re-queried the database before deciding, and `01e18bb` changed what it asks:
it now calls `has_resumable_contacts()` — a COUNT — instead of pulling a whole
page of contacts. If that change is wrong, this campaign closes as `sent` with
93 people still `pending`, and nothing in the product reopens `sent`.

That is exactly the failure that cost faisal 110 recipients, so it is the thing
to look for first. `test_scheduled_capped_pass_still_reschedules_rather_than_closing`
covers it, but a test is not a customer.

Two softer signals worth a glance:

- **`sent_count` above 15 in one window** would mean the cap is not holding.
- **Nothing at all by ~08:30 UTC** means the beat did not pick it up. The
  campaign is not lost — it stays `scheduled` and the next tick takes it — but
  it would be worth knowing why.

## Quick check without the DB

```
cd backend && python scripts/ask.py "SELECT timestamp, distinct_id, properties.count AS adet FROM events WHERE event='emails_sent' AND timestamp >= now() - INTERVAL 6 HOUR ORDER BY timestamp DESC LIMIT 10"
```

Server-side `emails_sent` is the truth; the client's `send_completed` only
means the request was accepted. Tim's should appear shortly after 08:00 UTC.
