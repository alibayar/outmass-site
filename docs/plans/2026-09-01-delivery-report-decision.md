# Delivery Report — the decision (2026-09-01)

Written for Ali to decide today. Prepared by reading the code, not the
proposal. Backend baseline at time of writing: `1321 passed, 1 skipped`.
Extension 0.3.2 is in review at both stores.

---

## 1. The question, and what the two incidents actually cost

The proposal is a per-campaign delivery breakdown in Reports. The strategy
doc (`2026-08-31-post-microsoft-strategy.md` §8) split it into a **truth
layer** (delivered / failed / never-attempted from columns we already have,
"one day") and a **bounce layer** (NDR reading, "five to eight days"), and
ordered them truth-first, on the stated grounds that "the product currently
misreports delivery in **both** directions" — faisal told `sent` while 110
were never attempted, miriam told `failed` while her mail went out. This memo
checks that sentence against the code and finds it half true and stale on the
other half, which changes the order. The cost side is: **faisal** —
110 recipients silently unsent across two campaigns, found by Ali querying
Supabase nine weeks late, customer has not opened the product since
2026-08-10, apology email still unsent
(`2026-08-31-faisal-missed-recipients.md`). **miriam** — bought Pro at
13:06:13 on 24 June, sent at 13:08, complained at 13:52, wrote three times
that afternoon, refunded. Forty-six minutes from paying to complaining
(§8, `2026-08-31-post-microsoft-strategy.md`). Between them that is the only
documented Pro sale in the product's history and its most valuable
non-churned paying account.

---

## 2. What is true today

### 2.1 Three things the strategy doc assumed that turn out otherwise

**(a) The truth layer would not have helped miriam. It would have lied to
her.** Her 244 failures were non-delivery reports arriving in her own mailbox
after Microsoft had accepted the sends. `backend/routers/campaigns.py:1909`
is the whole of what the database ever learns:

```python
if resp.status_code in (200, 202):
```

202 means accepted for delivery. `mark_sent` then writes
`{"status": "sent", ...}` (`backend/models/contact.py:189`). Nothing anywhere
ingests an NDR. So a delivered/failed/never-attempted panel built from
`contacts.status` would have shown miriam **417 delivered, 0 failed** while
her inbox filled with 244 bounces. The diagnosed cause was sender-side, not
bad addresses: `docs/plans/handoff-2026-06-24.md:85` records the remedy we
gave her — "ask IT admin to lift the **'Restricted entities' block in
Microsoft Defender**". The product also never told her "failed" about
delivery: there is no per-recipient delivery-failure string in any locale, in
any era, and `extension/sidebar.html:313-355` has only Sent / Opened /
Clicked / Engaged / Replied tiles.

**What §8's sentence is actually about, and it is real:** the 502. Her
417-recipient send ran synchronously inside the HTTP request, Railway timed
it out, the UI said "Send failed!" while the loop kept sending. Commit
`c1b3889`, 2026-06-24 17:48 +0300 — "the request 502'd even though the send
itself was fine". She sent at 13:08 UTC = 16:08 TRT; that was fixed **100
minutes later**, and the pacing fix `35eff3c` landed at 18:29 the same day.
That leg cannot recur — `/send` returns `{queued, status:"sending"}`
immediately now (`campaigns.py:889`).

Consequence for the decision: **the truth layer's justification rests on
faisal alone.** miriam needs the bounce layer or nothing.

**(b) "From columns the database already has" is true for five of six
buckets, not six.** `contacts.status` is a genuinely closed set — `pending`
(`contact.py:100`), `sent` (`:189`), `failed`/`deferred` (`:199`, guarded by
`_FAILABLE_STATUSES`), `suppressed` (`:226`) — and those are the only writers
outside tests. But faisal's headline number depends on the sixth split: of
his 91 pending, "exactly **one** is on his suppression list — correctly held,
not a miss. So the honest figure is **110 never attempted**"
(`2026-08-31-faisal-missed-recipients.md`). That contact reads `pending`, not
`suppressed`; the fact lives in `suppression_list`, which has no foreign key
to `contacts`, so PostgREST cannot express the join in one request. It needs
a SQL function or a second query. Also: `mark_suppressed` shipped 2026-08-04
(`cf20251`), so **no row sent before August can carry `suppressed` at all** —
any historical report must do the join or it is wrong by construction.

**(c) Mail.Read is not currently requested separately.**
`backend/config.py:131-134` defaults `FIRST_SIGNIN_INCLUDE_MAIL_READ` to
`true` and the flip has never been made; `backend/workers/reply_detector.py:26-31`
states it outright — "every live user has the scope and the 403 branch below
is unreachable in production". The separate-ask constraint describes the
**planned** post-flip state (`2026-08-28-closing-the-consent-leak.md`,
decision line: Ali, 2026-08-28, "kesinlikle kapatmaya çalışalım"). The gate is
client-version 0.3.0+ (`config.py:389 FIRST_SIGNIN_MIN_CLIENT = (0, 3, 0)`),
so after the flip existing users and pre-0.3.0 clients keep the scope; only
new 0.3.0+ installs lose it, and they get the one-click banner
(`sidebar.js`, `updateRepliesBanner`). So the bounce layer's scope cost is
lower than §8 charges — but it makes a paid feature depend on the exact
permission line the 44%-loss plan exists to delete (39 started, 22 reached an
account, 17 never did, 30 days).

### 2.2 What the Reports panel actually shows

Nine numbers, **no denominator anywhere**. List row: name, date,
`sent_count + " sent"` (`sidebar.js:3190`, `reportsSentSuffix` = `" sent"`),
open rate, click rate; the only status ever rendered is `failed_auth`
(`sidebar.js:3181-3184`). Detail: `stat-sent` binds `stats.sent_count`
(`sidebar.js:3293`) and nothing binds `total_contacts` — which **is already
on the wire** (`campaigns.py:336` returns it, and `list_campaigns` selects
`*`). `total_contacts` appears **exactly once in the entire extension**:
`sidebar.js:2071`, inside the 60-second post-send watcher.

That watcher is the strongest independent argument for a customer-facing
panel, and it has nothing to do with either incident. When it gives up it
says (`sendStillGoingLine`):

> "Still sending. You can close this — Reports will show the result."

Reports cannot show the result. It shows a numerator.

`total_contacts` is trustworthy as a denominator: it is written once at
upload from `get_campaign_contacts_count` (`contact.py:378`), a
`count="exact"` aggregate, which is not row-capped. One caveat — a contact
who unsubscribes *after* upload stays in `total_contacts` and stays `pending`
forever (every send read filters `unsubscribed=False`, `contact.py:262`), so
the buckets will not sum to the denominator unless that is its own line.

### 2.3 Three live misreports on the exact surface the panel would sit on

1. **CSV export truncates at 1000 rows, silently, for the user.**
   `campaigns.py:395` → `get_all_contacts` → `.limit(SUPABASE_MAX_ROWS)`
   (`contact.py:361-376`). Its own docstring: "a silently short export hands
   the user a file that looks complete and is not." It logs; the user is told
   nothing. Faisal's 1210-contact campaign exports 1000 rows. This is the
   **only** self-serve route to per-recipient status that exists today, and it
   is broken by the same row cap that caused his incident.
2. **Engaged / Replied are capped and fail to a confident zero.**
   `campaigns.py:307-325` pulls contact rows with `.limit(SUPABASE_MAX_ROWS)`
   and counts in Python, wrapped in `except Exception: engaged_count = 0;
   replied_count = 0`. Under a hint that calls Engaged "More reliable than raw
   open rate".
3. **Click rate can exceed 100%.** The open path guards on first open
   (`tracking.py:83-90`, `if not contact.get("opened_at")`). The click path
   does not (`tracking.py:132-138`) — `increment_stat("click_count")` runs on
   every hit. The comment at `campaigns.py:290-293` claims the opposite ("a
   recipient who opens five times bumps open_count five times"); it is wrong
   about opens and silent about clicks.

Building the panel on `/stats` as it stands inherits all three, at exactly
the list sizes the panel exists for.

### 2.4 Nothing in the product looks for a shortfall

`grep -c campaign backend/workers/daily_report.py` → **0**. The twice-daily
Telegram report covers users, plans, MRR and event counts and has never
mentioned a campaign. All three silent misreports in this product's history
were found by Ali reading Supabase by hand, weeks late: `c1705f2`
(2026-07-26, six days late), `01e18bb` (2026-08-31, nine weeks late —
"nobody noticed for two months").

The demonstrated user of a delivery truth signal is **Ali**, not the
customer. Faisal was shown 1020 at upload and 1000 at send minutes apart on
campaign 1 and did not notice — though on campaign 2, which carries 91 of the
110, he was *scheduled* and shown only the upload count, so no discrepancy
was ever on his screen at all.

### 2.5 Two smaller facts that price things

- **No failure reason is stored, ever.** `mark_failed` writes one column
  (`contact.py:199-223`). There is no `failed_at`, no code, no text. A
  "refused" bucket can say "120" and never why — which is the shape of
  miriam's complaint, and the faisal draft already has to concede it: "Our
  records do not distinguish a bad address from a temporary refusal."
- **`increment_campaign_stat` has no definition in this repository.**
  `models/campaign.py:200` calls it inside a bare `try` that falls back to a
  non-atomic read-modify-write. A repo-wide grep across `*.py`, `*.sql`,
  `*.md` returns that one call site. Also `sent_count` is bumped by the
  follow-up worker (`followup_worker.py:197-199`), so it is *emails*, not
  *recipients* — putting "Delivered 999 / 1210" next to "Sent 1,040" would
  manufacture a fresh contradiction on the panel built to end one.

### 2.6 The fixed cost of any user-visible string

14 locale directories (`ar de en es fr hi ja pt_BR pt_PT ru tr zh zh_CN
zh_TW`), 383 keys in `en`, parity enforced by
`extension/tests/locale-consistency.test.js`. Calibration anchor, not a
guess: `0280451` ("a running campaign can be stopped") is the same shape —
6 strings × 14 files (18 lines each), 68 lines of `sidebar.js`, 184 lines of
test, 913 insertions — and shipped in one day.

---

## 3. The options

Prices are Ali-days. "Store cycle" means it cannot reach a user until a new
extension review clears; 0.3.2 went in today.

### Option 0 — Do nothing

**Fixes:** nothing. **Costs:** 0 days. **Does not fix:** the root cause is
already fixed (`01e18bb`), so no new recipients are being lost. What remains
unfixed is that nobody would find out if they were, and the CSV export still
hands a truncated file to a paying customer. **Commits us to:** finding
incident #4 the same way we found #1–#3 — by hand, weeks late.
**Honest case for it:** faisal's bug is fixed, miriam's two causes were fixed
in June, and September may have a better use for two days.

### Option A — Operator alarm, no UI (recommended core)

One extra line in the existing twice-daily Telegram report: campaigns whose
status is terminal while `count_resumable_contacts` > 0, plus any campaign
where `sent_count < total_contacts`. This is the query that found faisal,
running by itself.

**Fixes:** the class of failure that has actually happened three times.
Detection goes from nine weeks to twelve hours. **Costs:** **0.5 day.**
Backend-only, Ali-facing, zero locale strings, no store cycle, no customer
notification, falls under CLAUDE.md §5 (invisible, trivially reversible) —
**no approval needed**. **Does not fix:** anything a customer can see. A user
still cannot check the product themselves. **Commits us to:** nothing. It is
deletable in one commit. **Free bonus:** its first run re-answers the
blast-radius question against the post-`01e18bb` table.

### Option B — Support-only tool, no UI

A `backend/scripts/` read-only query Ali runs on demand for one campaign or
one user: rows in `contacts`, sent, failed, deferred, suppressed, pending,
pending-but-on-the-suppression-list, unsubscribed, plus a canary bucket for
`NULL`/unknown status.

**Fixes:** answering a support email accurately in two minutes instead of
hand-writing SQL. It is what produced the faisal table. **Costs:** **0.25
day** on top of A (they share the SQL); **0.5 day** standalone. **Does not
fix:** detection (it is pull, not push) or anything customer-visible.
**Commits us to:** nothing; a script is not an interface. **Note:** the
suppression split needs the lateral join described in 2.1(b), which is also
the thing PostgREST cannot do — writing it once here is what makes a panel
version cheap later.

### Option C — Fix the three live misreports (2.3)

**Fixes:** a paying customer's CSV export silently missing rows; Engaged /
Replied understating above 1000 contacts and reading 0 on any DB error; a
click rate that can print over 100%. **Costs:** **0.5–1 day.** Two are
invisible fixes. **The CSV one and the click one are user-visible** — some
users' click rates will drop, and stored inflated `click_count` values are
not repaired — so both need approval and one release-note line.
**Does not fix:** anything about never-attempted recipients. **Commits us
to:** nothing new, and it is a prerequisite for any panel built on `/stats`,
because otherwise the truth panel ships on top of three untruths.

### Option D — Denominator only, in the panel ("1,000 / 1,020" + a status word)

**Fixes:** the broken promise in `sendStillGoingLine`. Puts the two numbers
faisal never saw together on one line, permanently, on the pull surface.
**Costs:** **0.5 day** — zero backend work (`total_contacts` and `status` are
already in both responses), ~3 locale keys × 14 files, plus a store cycle.
**Does not fix:** *why* a campaign came up short — on faisal's second
campaign the 211-row gap is 90 never-attempted + 120 refused + 1 held, and
undifferentiated it reads as 211 of our failures, which is worse for us than
the truth. **Commits us to:** a store submission, and to keeping the
denominator honest thereafter (see the post-upload unsubscribe caveat in
2.2).

### Option E — Full breakdown panel (the strategy doc's truth layer)

D plus per-bucket counts using `count="exact"` aggregates, guarded so a clean
campaign renders nothing new.

**Fixes:** the full faisal story, self-serve. **Costs:** **+1 day on top of
D** — ~5 count queries or one SQL function, 4–5 more locale keys × 14 files,
plus the `sent_count` semantics decision from 2.5 which must be made *before*
coding or it eats the day. Realistic total for D+E: **1.5–2 days**, not the
one day §8 priced, and that price assumes C is already done. **Does not
fix:** miriam's failure mode at all; and it can label a bucket "120 refused"
with no reason attached, forever, because we store none. **Commits us to:**
a public per-recipient failure vocabulary in 14 languages, and to a support
wave — every user with a dirty list suddenly sees "120 refused" where they
previously saw nothing. That is correct behaviour and a real cost.

### Option F — Bounce layer

**Fixes:** miriam's failure mode — the loudest complaint in the product's
history — and nothing else does. **Costs:** **6–10 days**, not 5–8. Half-day
Graph spike, +0.25 day to repeat it on a consumer `outlook.live.com` mailbox
(half our base; `manifest.json` includes it), 2–3 days for attribution *if*
the spike finds a route, and **+0.5–1 day of claims rewrite** if any body
field is read — `docs/pricing.html:219` ("message bodies are never
downloaded"), `docs/store-listing/certification-notes.txt:36` ("never message
content"), `docs/store-listing/softonic-en.txt:34`, `docs/privacy.html`, and
`popupConsentExplainer` in all 14 locale files. A certification-notes edit
while 0.3.2 is in review invites a fresh look at the permission story.
**Commits us to:** Mail.Read being load-bearing for a paid feature, at the
moment the consent-leak plan intends to remove it from first sign-in.
**Do not build suppression in September:** the feature is named after an
incident whose failures were sender-side, so invalid-address auto-suppression
would have suppressed up to 244 *good* addresses on our only Pro account.

---

## 4. Recommendation

**A + C now (1–1.5 days), D bundled with whatever release ships next
(0.5 day), E deferred, F not in September.**

**The evidence does not support "truth layer first" as §8 scoped it.** §8
ordered it first because the product misreports in both directions; it
misreports in one direction, and the panel it proposes would have reproduced
miriam's misreport rather than fixed it (2.1a). Stripped of her, the truth
layer's entire case is one customer who was shown the discrepant numbers on
campaign 1 and did not notice, and was never shown them at all on campaign 2.
Meanwhile every instance of this failure class was caught by a query Ali ran
by hand — so the instrument that has demonstrably worked, three times out of
three, costs half a day, ships today, needs no approval and no store review.

The reason A beats D as the *first* thing: D is a promise to the customer
that Reports tells the truth, shipped on top of `/stats`, which today
truncates the CSV, undercounts Engaged above 1000 contacts, and can print a
click rate over 100%. A costs less, ships sooner, and is aimed at the
incident that actually happened. D is still worth doing — the
`sendStillGoingLine` promise is a live defect in shipped code and the data is
already in the client's hands — but it is a bug fix riding a release, not a
project.

Send faisal's email **before** any panel ships. Once a denominator is on
screen his two campaigns display their own shortfall, and an honest admission
on Ali's terms becomes a customer discovery.

---

## 5. What Ali has to decide

Reply one word per line. Defaults in brackets are what happens if he says
nothing.

1. **Alarm in the daily report — build it?** [yes]
2. **Support-only script (Option B) alongside it?** [yes — +0.25 day, shares
   the SQL, and it is what a support reply needs]
3. **Fix the CSV export truncation?** [yes] — and if yes, **page it or refuse
   with an honest message?** [page]
4. **Fix the click double-count?** [yes] — user-visible, some click rates
   drop, needs a release-note line
5. **Denominator in Reports (Option D) — in the next release?** [yes]
6. **Full breakdown (Option E) — now?** [no — wait for the
   `campaign_detail_opened` number below]
7. **Bounce layer (Option F) — start the spike this month?** [no]
8. **Correct faisal's two `sent` rows in the DB?** [no — a contacts-derived
   report is retroactive with no migration, and flipping them to `partial`
   puts a Resume button in front of campaigns we have decided must never send]
9. **Send faisal's email this week?** [yes — before anything ships]

---

### Unknowns, and what settles each

| Unknown | Experiment | Cost |
|---|---|---|
| Does anyone open the Reports detail view? Decides whether E is worth a day. | Add `track("campaign_detail_opened")` to the next release; read it in two weeks. | 15 min |
| How many existing campaigns would suddenly display a gap, and to whom — i.e. the size of the support wave E creates. | One SQL query grouping every campaign by contact status where `sent_count < total_contacts`. | 5 min |
| Does `increment_campaign_stat` exist in production, or has every stat increment been a non-atomic fallback? | `SELECT proname FROM pg_proc WHERE proname = 'increment_campaign_stat';` | 2 min |
| Are there rows with `NULL` or unknown `contacts.status`? `schema.sql` has no CHECK constraint. | `SELECT status, count(*) FROM contacts GROUP BY status;` | 2 min |
| Has `FIRST_SIGNIN_INCLUDE_MAIL_READ` been flipped on Railway? Moves F's price by days. | Railway → web → Variables. | 1 min |
| Whether an NDR's failed address is readable without a body field. Gates all of F. | The half-day Graph spike, on both an M365 and a consumer mailbox. | 0.75 day |
| miriam's exact wording, and what the app told her. | PostHog: `user_feedback` and `send_failed` events for her account, 24 June. | 10 min |

---

## 6. Refuted during this review — not reasons to build anything

- **"The product told miriam 'failed' while her mail was going out"** — true
  of the 502 (`c1b3889`), which was fixed 100 minutes after her send and
  cannot recur. Not true of delivery reporting: no OutMass string has ever
  reported a per-recipient delivery failure. **miriam is not a justification
  for the truth layer.** She is a justification for the bounce layer, which is
  6–10 days.
- **"The product currently misreports delivery in both directions"** — stale
  in both directions as of today. faisal's direction was fixed by `01e18bb`
  on 2026-09-01; miriam's by `c1b3889` on 2026-06-24. The honest case is "has
  misreported, and has no surface where a user could check", not "does".
- **"One day, from columns the database already has"** — one day prices the
  backend happy path only, and only with a SQL function. The
  never-attempted-vs-held split is not expressible in PostgREST, the test
  double (`tests/conftest.py`, `FakeQueryBuilder` ignores every filter) cannot
  distinguish six differently-filtered counts against one table, and the
  panel half needs 14 locale files and a store review. D+E is 1.5–2 days on
  top of C.
- **"The bounce layer needs a new Mail.Read consent"** — it does not, today
  (2.1c). Every live user already granted it. What it needs is a *purpose*
  consent rewrite across five published sentences and 14 locale files, which
  §8 did not price separately.
- **"Faisal already had the numbers and did not look"** — true for the 20 on
  campaign 1 only. Campaign 2 carries 90 of the 110, was scheduled, and the
  only number he was ever shown was the upload count; the shortfall appeared
  on no screen. This is a real argument *for* D, and the only one that
  survives.
- **"Correct the statuses"** — a contacts-derived report displays the truth
  retroactively with no migration. Nothing needs correcting.
- **"Auto-suppress bounced addresses"** — the incident that motivates it was
  a Microsoft Defender sender-side block. This feature would have suppressed
  up to 244 good addresses on our only documented Pro account. If it is ever
  built, it proposes and the user confirms, and it is reversible.
