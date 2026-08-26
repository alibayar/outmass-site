# One CSV row limit for every plan — the quota does the gating

**Decision:** Ali, 2026-08-25. Option B from the free-tier discussion, plus his
own extension of it: stop varying the CSV row limit by plan. One limit of
**10,000 rows** for everyone; whichever monthly quota the user is on does the
actual work.

**Status:** IMPLEMENTED 2026-08-25, both halves approved by Ali. Backend
suite 1141 passed / 1 skipped; `node extension/tests/run-all.js` green across
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

- Add `CSV_UPLOAD_ROW_LIMIT = int(os.getenv("CSV_UPLOAD_ROW_LIMIT", "10000"))`.
- `FREE_UPLOAD_ROW_LIMIT` / `STARTER_UPLOAD_ROW_LIMIT` / `PRO_UPLOAD_ROW_LIMIT`
  keep existing as deprecated aliases of the new value, so any deployment that
  reads them keeps working. `railway-env.md` lists all three as optional with
  defaults, so nothing should be set today — worth confirming before deploy.
- `upload_limit_for_plan(plan)` returns `CSV_UPLOAD_ROW_LIMIT` regardless of
  plan. The function keeps its signature so `/settings` (`upload_limit`) does
  not change shape for older clients.

**`backend/routers/campaigns.py`**

- `upload_contacts` currently re-implements the plan→limit dict inline instead
  of calling `upload_limit_for_plan`. Replace it with the helper. That
  duplication is exactly how the two could have drifted.

**The 10,000 ceiling stays a real ceiling.** It is also the abuse guard: a free
account can upload 10,000 rows, not 10,000,000. `MAX_CSV_SIZE_BYTES` (5 MB)
remains the second bound.

## 3. What the user sees

| | Before | After |
|---|---|---|
| Free, 800-row list | 413, raw English, dead end | Uploads. Merge preview works. 250 send now, 550 stay pending. |
| Free, 10,001-row list | 413 | 413 (unchanged — the ceiling is now the same for everyone) |
| Starter, 3,000-row list | 413 | Uploads. 2,500 send now, 500 pending. |
| Pro | unchanged | unchanged |

Nobody loses a capability. Nobody gains send volume: the quota is untouched.

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

## 5. Tests

- `backend/tests/test_settings.py:42` asserts `FREE_UPLOAD_ROW_LIMIT == 250` —
  update to assert the single limit and that all three aliases agree.
- Add: free-plan upload of 800 rows succeeds; 10,001 rows still 413.
- Add: `upload_limit_for_plan` returns the same number for free / starter / pro
  / unknown.
- `node extension/tests/run-all.js` must stay green if the locale strings change
  (key parity across 14 files, placeholder consistency).

## 6. Rollback

Set `CSV_UPLOAD_ROW_LIMIT=250` in Railway (web service) and the old free
behaviour returns without a deploy. Existing pending contacts are unaffected
either way — nothing is migrated, no schema changes.

## 7. Notes for whoever implements

- No published claim mentions row limits: the pricing page, the store listings
  and the site say nothing about CSV size. Checked 2026-08-25. So no claims
  cleanup rides along with this.
- The sidebar has no client-side row check; the server value is authoritative
  and `/settings` already exposes it as `upload_limit`.
