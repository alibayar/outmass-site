# One CSV row limit for every plan — the quota does the gating

**Decision:** Ali, 2026-08-25. Option B from the free-tier discussion, plus his
own extension of it: stop varying the CSV row limit by plan. One limit of
**10,000 rows** for everyone; whichever monthly quota the user is on does the
actual work.

**Status:** IMPLEMENTED 2026-08-25 and shipping DARK behind
`UPLOAD_LIMIT_FOLLOWS_QUOTA` (default off) — see §8. Backend
suite 1143 passed / 1 skipped; `node extension/tests/run-all.js` green across
all eleven suites. Ships with 0.2.3 — no separate deploy, no migration.

**Release-notes line, since this is user-visible:** free and Starter users can
now upload their whole list; what sends each month is unchanged. Nobody loses
a capability, so no proactive email is warranted — release notes only.

---

## 1. Why

Two gates exist today and they are easy to confuse:

| Gate | What it protects | When it bites |
|---|---|---|
| Monthly quota (250 / 2,500 / 10,000) | revenue | after the user has used the product |
| Per-upload row limit (250 / 2,500 / 10,000) | nothing revenue-related | before the user has seen it work |

The row limit currently rejects the list at the door. A school with 800 parents
creates the campaign, writes the subject, uploads the CSV and receives
`413 CSV has 800 rows; plan limit is 250` — raw English from the API, with no
translation, no upgrade path and no next step. They never see the product work.
That is the audience we measured on 08-24 as our dominant real user.

The quota already does the right thing on its own: the send path caps to the
remaining allowance, reports `quota_capped` and `quota_skipped`, emails the
user, and leaves the remainder `pending` for the next month
(`backend/routers/campaigns.py:773-862`). None of that needs the row limit.

## 2. What changes

**`backend/config.py`**

- `UPLOAD_LIMIT_FOLLOWS_QUOTA` (default **false**) and
  `CSV_UPLOAD_ROW_LIMIT` (default 10000).
- The three per-plan limits stay exactly as they were, read from the same env
  vars as before. They are what answers while the flag is off — confirmed
  unset in Railway by Ali on 2026-08-25, so the defaults are live.
- `upload_limit_for_plan(plan)` branches on the flag at CALL time, so one
  switch moves the upload endpoint and `/settings` together and neither can
  answer differently from the other.

**`backend/routers/campaigns.py`**

- `upload_contacts` currently re-implements the plan→limit dict inline instead
  of calling `upload_limit_for_plan`. Replace it with the helper. That
  duplication is exactly how the two could have drifted.

**The 10,000 ceiling stays a real ceiling.** It is also the abuse guard: a free
account can upload 10,000 rows, not 10,000,000. `MAX_CSV_SIZE_BYTES` (5 MB)
remains the second bound.

## 3. What the user sees

| | Flag off (today) | Flag on |
|---|---|---|
| Free, 800-row list | 413, raw English, dead end | Uploads. Merge preview works. 250 send now, 550 stay pending. |
| Free, 10,001-row list | 413 | 413 — the ceiling is real for everyone |
| Starter, 3,000-row list | 413 | Uploads. 2,500 send now, 500 pending. |
| Pro, 10,000-row list | uploads | uploads |

Nobody loses a capability in either state. Nobody gains send volume: the
quota is untouched. Verified by running both states:

```
flag off  free 250   starter 2500   pro 10000   unknown 250
flag on   free 10000 starter 10000  pro 10000   unknown 10000
```

## 4. The message that had to change with it (approved)

Making big lists uploadable exposes a message that is already slightly wrong
and would become badly wrong. After a quota-capped send the sidebar says:

> "They stay saved and will be sent automatically after your monthly reset. To
> send them sooner, upgrade your plan."

For a 1,000-row list on Free that is three more resets, not one. For a
10,000-row list it is thirty-nine. The sentence implies the next reset finishes
the job. Today the row limit keeps most users away from that sentence; after
this change it becomes the normal path, and we would be shipping a promise we
do not keep — the exact rule we spent this week enforcing on the store copy.

Proposed: when the remainder needs more than one reset, say how many months it
takes on the current plan, and put the upgrade next to it. Same for
`alertPartialCsvQuota`, which today says "only the first N will be sent" and
stops there.

**Shipped as a new key, `alertQuotaHorizon`, in all 14 locale files:**

> Your plan sends $1 emails a month, so the remaining $2 recipients would take
> about $3 more months. Upgrade to send them sooner.

It is appended to BOTH quota alerts - the pre-send "only the first N will be
sent" and the post-send "they stay saved until your monthly reset" - by
`quotaHorizonSuffix` in `extension/sidebar.js`.

Three decisions inside that helper worth keeping:

1. **Only when the remainder outlives one reset.** If the leftovers fit in a
   single month, the existing sentence is already true and nothing is added.
2. **Only from a fresh limit.** The month count comes from the same live read
   that guards the send; if that read was stale the line is omitted entirely.
   A confidently wrong "39 months" is worse than silence, and this file already
   made that call once (the comment above `alertPartialCsvQuota`).
3. **No other plan's numbers in the string.** The draft named Starter's 2,500
   and Pro's 10,000. Plan numbers living in 14 translated files is how the free
   quota came to be mis-stated in July - the string says "your plan sends $1"
   and stops.

## 4b. The promise the message makes is now one the code keeps (2026-08-28)

The 0.2.3 release review found `alertQuotaHorizon` unshippable, and it was
right: `auto_resume_partial_campaigns` only resumed campaigns created inside
the user's current or previous quota cycle, so a 10,000-row list on the free
plan received two of the forty batches the sentence promised. Worse, the
suffix only appears when the remainder exceeds one month's quota — so it was
false at the smallest number it could ever print.

Two ways out: soften the sentence, or make it true. Ali chose the second —
"kaç ay sürerse sürsün otomatik biz handle edelim."

So the age rule is gone. What guards the surprise-send it existed to prevent:

- **archiving**, which the user can reach from Reports, and which the query
  now respects — an age window stopped campaigns nobody had abandoned, and
  archiving stops exactly the ones somebody did;
- **an email on every capped batch**, so a campaign that runs for a year
  announces itself twelve times instead of arriving as a surprise on month
  nine;
- **a dead Microsoft connection**, which already skips the account until it
  is reconnected.

Sequencing is automatic and in the right order: the backend deploys on push,
the message ships with 0.2.3 through two store reviews. The behaviour is true
before the sentence claiming it is ever seen.

## 5. Tests

- `backend/tests/test_settings.py:42` asserts `FREE_UPLOAD_ROW_LIMIT == 250` —
  update to assert the single limit and that all three aliases agree.
- Add: free-plan upload of 800 rows succeeds; 10,001 rows still 413.
- Add: `upload_limit_for_plan` returns the same number for free / starter / pro
  / unknown.
- `node extension/tests/run-all.js` must stay green if the locale strings change
  (key parity across 14 files, placeholder consistency).

## 6. Rollback

Delete `UPLOAD_LIMIT_FOLLOWS_QUOTA` (or set it to `false`) on the Railway web
service and every plan is back to its old limit without a deploy. Existing
pending contacts are unaffected either way — nothing is migrated, no schema
changes.

A contact list uploaded while the flag was on stays uploaded if the flag goes
off; the limit is checked at upload, not at send. That is the intended
behaviour — a rollback should not strand a campaign someone already built.

## 7. Notes for whoever implements

- No published claim mentions row limits: the pricing page, the store listings
  and the site say nothing about CSV size. Checked 2026-08-25. So no claims
  cleanup rides along with this.
- The sidebar has no client-side row check; the server value is authoritative
  and `/settings` already exposes it as `upload_limit`.

## 8. Deploy sequencing

The two halves ship on different clocks. The backend takes effect on the next
Railway deploy of the web service; the message needs a store release and days
of review. Deploy the backend live and every user would get the relaxed limit
while their installed extension still says the leftovers go out "after your
monthly reset" — exactly the pairing §4 exists to prevent, for however long
0.2.3 sits in review.

So the change ships **dark**, the way `INACTIVITY_NUDGE_ENABLED` does. Nothing
to set before deploying: the flag defaults to false, so forgetting it changes
nothing, which is the safe direction to forget in.

**On the day 0.2.3 is published on BOTH stores**, set on the Railway **web**
service:

```
UPLOAD_LIMIT_FOLLOWS_QUOTA=true
```

### Why it is a switch and not a number

The first version of this plan said to hold the change back by setting
`CSV_UPLOAD_ROW_LIMIT=250`. **Ali caught that it would have capped Starter and
Pro at 250 rows too** — that single value had replaced all three per-plan
limits, so the "rollback" would have taken 9,750 rows away from every paying
customer. It was one command away from being deployed.

The lesson is in the shape, not the number: a flag that changes behaviour must
be a switch between two known-good states. A magic value that happens to equal
the old default for one plan is not a rollback, it is a coincidence that
expires the moment the plans differ.

Ali owns Railway; nothing here touches it.
