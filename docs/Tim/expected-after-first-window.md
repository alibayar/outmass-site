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

---

## What actually happened, and his reply (2026-09-01 11:26)

The first window ran correctly as a *send*: exactly 15 at 08:05:27 UTC, the cap
held, and the campaign went back to scheduled. The close-out change from
`01e18bb` did what it was supposed to.

The formatting did not. Tim wrote:

> "I sent the first 15 emails this morning via OutMass, but the layout came out
> completely wrong. The layout was correct in the first two test emails. How is
> this possible? I'd like to prevent the rest of the emails from being sent
> because the layout is incorrect. How do I stop a campaign?"

His two test sends were correct and his scheduled send was not, which is the
diagnosis stated back to us by a customer who could not have known it: test
sends go through `routers/campaigns.py`, which converted plain text to HTML;
scheduled sends go through `scheduled_worker.py`, which did not. Second
independent confirmation on the same morning, after Helene's.

Timing, which decides what to tell him: his 15 went out **08:05:27 UTC**, and
`0252d0b` deployed after that. Backend is on `0280451` now, verified. So his
remaining 93 go out tomorrow at 08:00 UTC with the formatting correct, and
stopping is not something he needs — though it is his call, not ours.

## Reply

Kept short on purpose: the customer does not need the mechanism, only what
happened, whether it is fixed, and what happens next.

Subject: **Layout problem — found and fixed this morning**

> Hi Tim,
>
> Thanks for flagging it, and sorry. This was a bug on our side: campaigns
> sent on a schedule lost their line breaks, while test emails kept them —
> which is why your two tests looked right. We found it this morning and it
> is fixed.
>
> The 15 that went out earlier had the wrong layout and I cannot undo those.
> **The remaining 93 go out tomorrow morning as planned, and will look
> correct.** So there is no need to stop the campaign — though if you would
> rather stop it anyway, just say so and I will do it within minutes.
>
> On how to stop one: you could not, and you are the second person to ask
> today. There is now a Stop button on the campaign report, coming with the
> next update.
>
> If you would like the 15 addresses so you can follow up with them yourself,
> just ask.
>
> Your follow-up from yesterday is still waiting on your wording whenever you
> want it — no rush.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.
No compensation offered: he already has a month of Pro, and stacking another
gesture on top reads as buying him off rather than fixing it.

## The one claim in this that must stay true

"The remaining 93 will be formatted correctly." Verify after 08:00 UTC tomorrow
by looking at what a recipient actually received — not at `emails_sent`, which
only counts. If it is wrong again the fix did not reach the worker, and that
needs re-opening before the third batch.
