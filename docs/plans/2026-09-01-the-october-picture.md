# The October Picture — what the product looks like after the defects are closed

Internal. `docs/plans/` is excluded from the public Jekyll site.
Written 2026-09-01, 15:36 Istanbul, from three adversarial lenses (parity,
wedge, buyer), each load-bearing claim cross-examined by a skeptic told to
refute it. Three claims were refuted and are recorded in §7.

**The question this answers, in Ali's words:** *the missing delivery is a
momentary defect we are fixing — look at the situation AFTER it is fixed.*

Every claim below is marked:

| mark | meaning |
|---|---|
| **[V]** | verified from this repo, file:line given |
| **[V-comp]** | verified from the repo's own dated read of a competitor page (31 Aug 2026) — competitor pages drift |
| **[I]** | inference, stated as such |
| **[U]** | unverified; the check that would settle it is named |

---

## 1. What "fixed" buys us, and what it does not

### Ali is right about the boundary he drew

The delivery defect really is momentary, and the closures are in the code, not
in a changelog promise:

- **Stop button** — `backend/routers/campaigns.py:1456` (`POST /{id}/stop`),
  `STOPPABLE_STATUSES` at `:1447`, panel wiring at `extension/sidebar.js:3351`,
  test at `extension/tests/stop-campaign.test.js`. **[V]**
- **Worker formatting** — `render_body` now called on both worker paths;
  `backend/workers/followup_worker.py:358` carries the reason in comment
  ("Same omission as the scheduled worker had"). A real scheduled send was
  verified at 09:35 UTC, not just unit-tested
  (`docs/plans/2026-09-01-helene-stop-and-formatting.md`). **[V]**
- **Paywall offers a path** — both follow-up 402 branches route through
  `showUpgradeModal` (`extension/sidebar.js:3080`, `:3102`). **[V]**
- **The discarded follow-up** — `campaigns.py:1592-1616` now saves a `locked`
  row for clients ≥ 0.3.1 instead of throwing the user's subject and body away;
  `sidebar.js:3370 renderLockedFollowup` gives it an Activate button. **[V]**

After that lands, a paying user can send, pace, schedule, stop, and receive a
follow-up. That is a real change of state and the premise holds for it.

### Momentary gaps: the backend already does the work, the panel never asks

These are days, not quarters. Every one is wiring, not architecture.

| gap | why it is momentary | evidence |
|---|---|---|
| No follow-up **condition** selector | The worker already implements the fall-through that means "sent, not unsubscribed, **not replied**" — Mailmeteor's advertised trigger. The panel hardcodes `condition: "not_opened"`, the only occurrence of the word in 4,960 lines. | `followup_worker.py:313-316` + `:304-311`; `sidebar.js:3067`; API takes a bare `str` with no enum, `campaigns.py:95` **[V]** |
| Cannot **attach a follow-up** to a running/finished campaign | `POST /{id}/followups` checks ownership and plan and **nothing about campaign status** — the server would accept it today. Helene asked for this on 2026-09-01. | `campaigns.py:1581-1625` **[V]**; `2026-09-01-helene-stop-and-formatting.md` §4 **[V]** |
| Cannot **cancel** a pending follow-up | `DELETE /{id}/followups/{fid}` exists at `campaigns.py:1734`; no message type in `background.js` reaches it. Today the only lever is Stop, which archives the campaign and cancels the follow-up as a side effect. | `campaigns.py:1734`; `followup_worker.py:83-88` **[V]** |
| **One stage only** | Everything is keyed per follow-up, not per campaign — `get_pending_followups()` loops all scheduled rows, dedup is `(follow_up_id, contact_id)`, no uniqueness constraint on campaign. A second stage would run today if anything created one. | `models/followup.py:87`, `:100`, `:145`; `schema.sql:71-82` **[V]** |
| `repliedAt` missing from CSV export | Column is populated (`reply_detector.py:262`), header row omits it. | `campaigns.py:400-403` **[V]** |

### The one defect the sprint's **success** switches on

**Follow-up sends are added to the campaign's `sent_count`, and `sent_count` is
the denominator of every engagement rate. [V]**

- `followup_worker.py:197` — `increment_stat(campaign_id, "sent_count", sent_count)`
- `campaigns.py:284-287, 326-327` — `open_rate`, `click_rate`, `engaged_rate`,
  `reply_rate` all divide by that same `sent`
- The numerators cannot follow: `tracking.py:83` increments `open_count` only
  when `opened_at` is null (once per contact ever); `replied_count` is distinct
  contacts.

So a 100-recipient campaign that bumps 80 people will report **Sent: 180** and
divide four rates by 180. The panel renders `stats.sent_count` as the headline
"Sent" (`sidebar.js:3293`) and never renders `total_contacts` in the report
detail — there is no denominator on screen to make it legible. **[V]**

This has been invisible for exactly the reason the strategy doc gives: no real
user has ever received a follow-up. It becomes a wrong number on a customer's
screen on the **first campaign where the sprint succeeds**. After miriam
("failed" while mail was going out) and faisal ("sent" while 110 were never
attempted), this is the third direction in which the product misreports
delivery. **[V — `2026-08-31-post-microsoft-strategy.md` §8]**

### Structural, not momentary — say so plainly

1. **The default follow-up trigger is built on the signal our own code documents
   as unreliable in this client.** `reply_detector.py:8-11` says open tracking is
   unreliable because of "Outlook image-block + Apple MPP" — that is the stated
   reason reply detection exists. `sidebar.html:337` tells users the same thing.
   The follow-up trigger ignores both, and the user cannot change it. **[V]**
   *Correction from the skeptic pass, and it matters:* repliers are **always**
   excluded regardless of condition (`followup_worker.py:310`, shipped
   2026-07-18), so the real gap against Mailmeteor is only the
   opened-but-didn't-reply segment — not reply-safety. **[V]**
2. **Reply detection is a once-daily, Inbox-folder-only, sender-address match.**
   `celery_app.py:248-253` — `crontab(hour=5, minute=0)`. Follow-ups run hourly
   (`:153-156`). A reply at 06:00 UTC is unstamped for 23 hours while up to 23
   follow-up passes run. `reply_detector.py:104` reads
   `/me/mailFolders/Inbox/messages` only; `conversationId` is fetched (`:105`)
   and stored (`:147`) and never used for matching (`:255` matches on sender
   address). **[V]** Mailmeteor's page says "real-time". **[V-comp]**
3. **Delivery truth is still not reported.** The stats response carries
   sent/open/click/engaged/replied and four rates and **no failed count, no
   never-attempted count** (`campaigns.py:336-372`). The statuses exist and are
   never surfaced: `pending`, `deferred`, `sent`, `failed`, `suppressed`
   (`models/contact.py:261,285`), and `count_resumable_contacts` (`:271`) is
   already used by the new Stop handler at `campaigns.py:1497`. **[V]**
4. **Retention.** 8% July→August, longest relationship 25 days, 2 of 24 accounts
   active in more than one calendar month. **[V — §2.5]** The premise does not
   touch this. Fixed delivery is necessary for retention and is not evidence of
   it. The read that survives: the September cohort is the first to use a
   product that works, so **October's return rate is the measurement**, and it
   costs nothing but waiting.
5. **Two category walls, both chosen deliberately.** Per-recipient file
   attachments (Alan → SecureMailMerge; we render OneDrive links,
   `campaigns.py:1872-1885`) and inbox rotation + warmup (Mary Bass → QuickMail
   at $49/mo). The backlog's own read: "entering it is a category change, not a
   feature." **[V — `backlog.md:1015-1016`, `:1036-1041`]**

**The honest boundary of the premise:** Ali is right that delivery is momentary,
and right that the situation after the fix is the one to reason about. He is
wrong if "fixed" is read as "then the differentiator sells" — because one
defect (the `sent_count` denominator) is *created* by the fix landing, and the
number that decides October (retention) is untouched by it.

---

## 2. The October board

Three columns. Microsoft = new Outlook after roadmap 423047 GA. Mailmeteor =
the AppSource Outlook add-in, Premium $17.99. OutMass = $19 Pro / $9 Starter.

| capability | Microsoft built-in | Mailmeteor $17.99 | OutMass $19 |
|---|---|---|---|
| Per-recipient merge fields | **Yes** [V — roadmap text quoted in `2026-08-24-microsoft-qa-answers.md:49-55`] | Yes [V-comp] | Yes [V] |
| Contact source (CSV/spreadsheet) | **[U]** — the roadmap entry never says where the values come from. Would verify: release-communications API `423047` at "Rolling out" + one hands-on pass | Spreadsheet or CSV [V-comp] | CSV upload [V] |
| Where it runs | Native, everywhere Outlook runs [I] | Add-in + web dashboard — desktop, Mac, web [V-comp] | Chrome/Edge extension, Outlook **on the web only** [V] |
| Open & click tracking | **Not in the entry** [V] | Yes, paid tier [V-comp] | Yes, **on every plan incl. Free** — no plan gate anywhere in `routers/tracking.py` [V] |
| Reply detection | **Not in the entry** [V] | Yes, **from a paid tier** [V-comp] | Yes, **not gated** — `reply_detector.py` iterates all `user_tokens`, no plan filter [V]. Daily, not real-time [V] |
| Auto follow-ups | **Not in the entry** [V] | **Multi-stage ("1, 2, 3 or more")**, trigger incl. "no reply in 3 days" [V-comp] | **One stage**, Pro, trigger hardcoded to non-openers [V] |
| Scheduled sending | Not in the entry [V] | Yes [V-comp] | Yes, Starter+ (`campaigns.py:191-202`) [V] |
| Daily pacing / N-per-day continuation | Not in the entry [V] | **[U]** — no pacing row in our own comparison table; would verify from their pricing/feature pages | Yes — `daily-send-cap`, worker continues next day (`sidebar.html:225-227`, `scheduled_worker.py:116-120`), Starter+ [V] |
| Delivery / failure reporting | [U] | [U] | **No** — no failed or never-attempted field in the stats response [V] |
| Subject A/B | Not in the entry [V] | Not advertised [V-comp] | Yes, Pro [V] |
| AI writing | Not in the entry [V] | Yes, paid tier [V-comp] | Yes, Pro [V] |
| Real per-recipient attachments | [U] | **Yes** [V-comp] | **No** — OneDrive links only [V] |
| CSV encoding recovery (GBK/Big5/cp1251/1254/1256…) | [U] | [U] — their Gmail heritage is Sheets, already Unicode [I] | Yes — `decodeCsvBuffer` run against 10 encoding fixtures by `extension/tests/csv-decode.test.js`, plus an ask-don't-guess picker with live preview (`sidebar.html:54-64`) [V] |
| UI languages | Inherits Outlook's localisation, ~100 [I] | **"Multiple"** — which is what you write when you did not check [V, of our own table] | 13 languages / 14 locale files, 383 keys each, equality enforced by test; RTL for ar/he/fa [V] |
| Free tier | Free within Exchange Online's unchanged 10,000/24h, 1,000/msg, 30/min [V — §1] | [U] | 250 emails/month forever, no footer [V — `config.py:313`] |
| Price | $0 | $17.99 | **$19** — we are $1.01 more [V — §5] |

Two rows on this board are the whole strategic picture: **the entire "after
Send" block is empty in Microsoft's column** [V], and **the reply-detection row
is the only one where we are free and Mailmeteor is paid** [V-comp].

---

## 3. The wedge — what is absent from BOTH rivals and true of us

Three bars: absent from both rivals, a buyer would switch for it, demonstrable
in a store screenshot.

**1. Tracking and reply detection on the free plan.** Microsoft does not build
tracking at all [V]; Mailmeteor gates reply detection to a paid tier [V-comp].
What is absent from both is not the capability — it is the price shape. Already
true; needs nothing built. *Demonstrable in one image:* a free-plan campaign
report showing Engaged and Replied. *Cost to make it sellable:* 1 day, and it is
mostly a claims fix — see §6 item 2 — because the listing currently sells this
feature with a sentence that is false.
*Fragility, stated:* a competitor can erase a price-shape difference in an
afternoon. **[I]**

**2. Tracked outbound in Arabic, Chinese and Russian, with the CSV Excel
actually wrote.** Neither half wedges alone — Microsoft inherits Outlook's ~100
languages [I], and the encoding decoder is invisible at purchase. Fused, the
claim is "this tool will take my file and show me who replied, in my language".
*Demonstrable:* an RTL Arabic panel showing a report with opens, clicks and
replies; and the encoding picker with a live preview of decoded names — the only
screenshot-able half of the encoding work. *Cost:* 1 day of localized
screenshots for the zh-CN / zh-TW / ar Edge listings; the pipeline
(`frame-screenshots.py`, `render.js`, `promo-tile.html`) is built and has never
been pointed at a non-English UI. **Gated on a 1-hour lookup** — our own
comparison table writes "Multiple" for Mailmeteor's languages, which is an
admission we never checked. **[V/I/U]**

**3. Daily pacing that continues by itself.** Not in Microsoft's entry [V]; not
recorded either way for Mailmeteor [U]. Six independent repo datapoints say this
is what people actually pay for — see §4. *Demonstrable:* the send screen with
"15/day, finishes 8 September". *Cost:* see #63 in §6.

**Do not use, and strike from the October pitch:**

- **Own-mailbox Graph sending.** Table stakes. Our own comparison table records
  Mailmeteor as "Your own Microsoft account" [V-comp], and Microsoft is
  Microsoft. It differentiates only against relay tools (Mailchimp, Lemlist),
  which are not on this board. Our Mailmeteor FAQ copy still implies the
  contrast ("via Microsoft Graph rather than a separate sending server",
  `mailmeteor-alternative-for-outlook.html:35, :266`) and should be reworded
  when that page is next touched. **[V]**
- **Price.** $19 > $17.99, and Microsoft gives merge away. Unavailable as a
  differentiator. *Not* an anti-differentiator — see §7. **[V]**
- **Privacy.** Two false sentences are live in 12 languages today (§6 item 2),
  and SecureMailMerge owns honest privacy in a way we structurally cannot match:
  our workers must read the stored campaign to send it later
  (`scheduled_worker.py:116-120`). **[V]**

---

## 4. Who is left to sell to

**The measured job.** "The dominant job is an organization emailing its own
list, not cold outbound prospecting" — 120-day recipients: samaed 5,599,
bellmed 2,816, personal accounts 607/36 sends, skylineprp 519, hrds 375,
overdeliverinc 260, mercedesscientific 83. **[V —
`2026-08-24-practitioner-channels.md:64-76`]** The store and site copy target
"founders and SDRs doing outbound", which the same file calls wrong against
measured usage. **[V]**

**Six datapoints say people pay for pacing and scheduling. [V]**

1. bellmed upgraded to Starter *because of* daily-cap spreading (`handoff-2026-07-15.md:60-63`)
2. Tim: refused at `feature_locked_scheduled_sending` 18:07:27, paid $9 at 18:09:35 — **2 min 3 s**, and the only feature-wall conversion in the product's history (`2026-08-31-tim-followup-email.md:17-41`)
3. Tim's campaign is running right now at `daily_send_cap` 15 over 1–8 September (same file)
4. Helene: 66 recipients at 5/day, a number she named herself (`2026-09-01-helene-stop-and-formatting.md`)
5. 5 users fired 17 sends of 300+, max 1,876 in one sitting; nobody heeds the large-send warning (`backlog.md:1017-1019`)
6. faisal's 1,020 and 1,210-recipient campaigns; the daily-capped ones were immune to the truncation bug by accident (`2026-08-31-faisal-missed-recipients.md`)

Against that: ≤8 follow-up attempts, ≤9 A/B, 6 AI — zero delivered, zero
retained revenue. **[V — §2]**

**Where Microsoft actually bites.** Not "only the free tier". The commoditised
segment is bounded by **Exchange's 10,000/24h**, not by our 250/month — the
250 is our pricing artifact, not Microsoft's. The one documented Pro purchase
with a recorded motive on that axis — miriam, 417 recipients, paid 13:06, sent
13:08 — was a **volume basic-merge** purchase, and under the fixed-product
premise that sale stays. And with 8% monthly retention, the paying base is
regenerated from the free funnel every cycle — a threat to the top of the funnel
reaches the base within a month. **[V + I; this refutes a claim made in the
buyer lens, see §7]**

**The band that survives.** Roughly 250–2,500 recipients paced over days:
above Microsoft's free personalisation and our free quota, below the point where
the purchase criterion becomes rotation and warmup. That is the **$9 Starter**
tier — the only tier that has ever held money. In the 120-day table it contains
skylineprp, hrds, overdeliverinc: **three domains of the 24 accounts that ever
created a campaign.** **[I, from V boundaries]**

**Two things this section does not let us pretend.** The band is small, and the
job is episodic — a hiring round, a term, a launch — which is the worst shape for
a monthly subscription, and the product has no annual or per-campaign option
(`routers/billing.py:438, :494` mention an annual tier only as a hypothetical).
**[V]** And one payer bought for a reason nobody has established:
mercedesscientific paid 08-18, first campaign 08-20, 83 recipients in 120 days —
never near the free quota. That is the only positive purchase signal in the
dataset that has never been explained. **[V — `handoff-2026-08-24.md:259-260`]**

---

## 5. THE ANSWER — the smallest true sentence

**For the install decision, the sentence exists. Here it is:**

> **OutMass shows you who opened, clicked and replied — on the free plan, 250
> emails a month, forever.**

Every clause verified: tracking has no plan gate anywhere in
`routers/tracking.py` [V]; `reply_detector.detect_replies` iterates every user
in `user_tokens` with no plan filter [V]; 250 is `config.py:313` [V]; Mailmeteor
gates reply detection to a paid tier [V-comp]; Microsoft's entry does not mention
tracking at all [V].

It works because the install decision is made **before** anyone pays, and the
free tier is the only surface where we are unambiguously ahead of both rivals.

Three conditions on saying it, all cheap and all mandatory:

1. The listing sentence *"stop automatically as soon as someone replies"*
   (`listings.json:5`, `descriptions/en.txt:23`) is false — replies are detected
   once a day at 05:00 UTC. The **same listing** already says honestly
   *"Reply detection — daily Inbox scan"* five bullets later
   (`descriptions/en.txt:28`). The listing contradicts itself in 12 languages.
   Fix it, or make it true (§6 item 4). **[V]**
2. *"We never store the content of your emails on our servers"*
   (`listings.json:5`, `en.txt:47`) is false — `models/campaign.py:66-83`
   inserts subject and body. Corrected wording already written at
   `softonic-en.txt:34` and never propagated. **[V]**
3. Do not add the word "only" until Mailmeteor's free tier is actually read. Our
   own comparison table says "Check their current pricing", which means we do
   not know. **[U]**

**And the sentence that does not exist yet.** There is no verified sentence that
makes someone buy **Pro at $19 over Mailmeteor Premium at $17.99**. On that
comparison we are $1.01 more expensive, one follow-up stage against their
multi-stage, no per-recipient attachments, and a daily reply scan against their
"real-time" claim — all four from our own dated read of their pages [V-comp].
What would have to become true, in order of cost: the condition selector (1d) +
delivery truth (1d) + multi-stage follow-ups (2d) closes three of the four; the
fourth is a pricing decision this repo has never taken.

---

## 6. What September should build — ranked, with day costs

This is the recommendation, stated once. **Do 1–6 (about 4.5 days), then stop
and look at the October return rate before spending anything on 7–11.**

| # | item | days | why here |
|---|---|---|---|
| **1** | **Stop follow-up sends inflating `sent_count`.** Compute `sent` in the stats handler from the contacts read it already performs (`campaigns.py:305-313`), or add a `followup_sent_count` column. | **0.5–1** | The only item that gets *worse* when the sprint succeeds. Ship it in the same commit as the first working follow-up, or the first delivered bump becomes the next support incident. **[V]** |
| **2** | **Fix the two false store-listing sentences**, regenerate all 12 descriptions, update both dashboards. | **1** | October's pitch is a comparison pitch. A comparison made from a listing containing a demonstrably false privacy sentence is the one that gets quoted back at us — and §5's install sentence cannot be published until this is done. **[V]** |
| **3** | **Delivery truth layer** — delivered / failed / never-attempted / total beside "Sent", in the stats response and the panel. | **1** | Owed on its own evidence: the product misreports delivery in three directions (miriam, faisal, and item 1). Ingredients exist — `count_resumable_contacts` is already called by the Stop handler. **[V — §8]** |
| **4** | **Reply detection 4×/day instead of daily** (`celery_app.py:248`), plus a Graph call-volume check across ~64 users. | **0.5** | Narrows the honest gap against "real-time", makes listing sentence #1 nearly true, and closes the 23-hour window in which we can bump someone who already answered — which the code itself calls "the #1 thing users expect follow-ups to never do". **[V]** |
| **5** | **Three lookups.** (a) Mailmeteor's tiers, free tier, pacing and UI languages, tier-by-tier. (b) "mail merge outlook" in Edge Add-ons with store locale zh-CN. (c) 423047 status on the release-communications API. | **0.5** | Everything in §3 ranks 2–3 and the word "only" in §5 hangs on (a). (c) is minutes and already a standing habit — do **not** budget days waiting for Microsoft; as of 2026-08-31 the card was still "In development", untouched since 29 May. **[V]** |
| **6** | **Follow-up condition selector** — not_opened / not_clicked / no-reply — plus an enum on `campaigns.py:95`, 14 locale files, and a server-side gate on Mail.Read consent. | **1** | Mailmeteor's advertised trigger, already implemented in the worker and unreachable from the panel. The Mail.Read gate is not optional: a no-reply condition rests entirely on `replied_at`, which is only stamped for users who granted the scope. **[V]** |
| 7 | Cancel a pending follow-up (wire the existing DELETE) + `repliedAt` in the CSV export | 0.75 | Both are wire-ups over shipped endpoints. Low risk, low reward. **[V]** |
| 8 | **Attach a follow-up to an existing campaign**, reusing `count_due_immediately` + a `confirm_immediate` step | 1.5 | Helene asked for it. The confirm is mandatory: `create_followup` stamps `scheduled_for = now + delay`, so attaching a 3-day follow-up to a month-old campaign would blast everyone at once. The activate endpoint already solved this. **[V]** |
| 9 | **#63 — one-click "spread this campaign over N days"** | 1.5–2 | Ranked here, not higher, deliberately. The machinery ships today and a paying customer is using it right now (Tim, 15/day). It is conversion polish on a wall that already converts in two minutes, not a capability gap. Two real sub-items if it is built: it is unusable without ticking Schedule (`cap_requires_schedule`, `campaigns.py:181-188`), and it is Starter-gated, so the moment it would sell hardest — a Free user uploading 300 rows — is the moment it is invisible. **[V]** |
| 10 | Multi-stage follow-ups (2nd/3rd bump) | 2 | The only advertised-list gap against Mailmeteor left after #6. Per-follow-up machinery already supports it; the UI copy must state that each stage's delay counts from the original send, not from the previous bump. **[V]** |
| 11 | "What stopped you?" email to the ~20 dormant accounts | 1, no code | Demoted, and for a new reason: they left a broken product, so their answers are confounded with defects we have now closed. The unconfounded instrument is free — **does the September cohort come back in October?** Ask only if October's return rate is also near zero, when the answer stops being predictable. **[V/I]** |

Explicitly **not** on this list: per-recipient attachments and inbox
rotation/warmup. Both are category changes, both boundaries are already held
deliberately in the repo. **[V]**

---

## 7. What was refuted here

Three load-bearing claims from the lenses were killed by the skeptic pass. They
are recorded because a plausible-but-wrong claim is the expensive kind.

**Refuted — "Microsoft takes the free tier, not a single paying row."** Three
failures. (a) The commoditised segment is bounded by Exchange's 10,000/24h, not
by our 250/month — the 250 is *our* ceiling, and the repo's own data shows 17
sends of 300+ in 90 days [V]. (b) The one documented Pro purchase with a recorded
motive on that axis — miriam, 417 recipients, paid to sent in two minutes — *was*
a volume basic-merge sale; it only leaves the paying base because the broken
product refunded it, so under this document's own premise it stays [V]. (c) With
8% monthly retention and a 25-day longest relationship, the base *is* its funnel
one cycle later [V]. What survives: the two conversions with documented motives
(Tim → scheduling, bellmed → pacing) bought things 423047 does not ship.

**Refuted — "price and the free tier are anti-differentiators."** "Unavailable
as a differentiator" is true; "loses deals" is not supported by anything in the
repo. Mary Bass chose QuickMail at **$49/mo — 2.6× our Pro** [V]. Both Pro sales
closed at $19 without price friction [V]. Not one upgrade click in the product's
history came from a price surface being too high [V]. And the claim assumed
feature parity with Mailmeteor Premium from two marketing bullets on one page —
their Premium quota, billing period and tier ladder are all unverified [U].

**Refuted — "the data-source question is the single highest-value fact and is
cheap to settle in the first week of September."** The card was still "In
development" on 2026-08-31, untouched since 29 May, with the August preview
window closed [V]. It settles on Microsoft's clock, not Ali's, and whether his
tenant is even on a preview ring is unrecorded. It is cheap to *check* (minutes,
already a habit) and not settleable at any price this month. It is also not a
binary: our free tier carries tracking, reports and reply detection, none of
which 423047 mentions, so a CSV-capable Advanced does not take "the entire free
tier" either way [V].

**Survived, with corrections that change the fix:**

- *"The panel hardcodes the weakest condition"* — survives, but repliers are
  **always** excluded regardless of condition (`followup_worker.py:310`, since
  2026-07-18), so the true gap is only the opened-but-didn't-reply segment, and
  the fix is sidebar-only, not a backend build. **[V]**
- *"The worker already supports no-reply"* — survives, but it rests entirely on
  `contacts.replied_at`, which only exists for users who granted Mail.Read. The
  narrow-consent split is built and waiting (`config.py:106-134`); the day it
  flips, an ungated no-reply condition degrades to "bump everyone, repliers
  included". Gate it server-side. **[V]**
- *"Own-mailbox Graph sending is table stakes"* — survives on the repo's own
  competitor table, **not** on the argument the lens gave ("add-ins send from the
  signed-in mailbox by construction" is architecturally false — an add-in can
  relay). **[V]**

**Two corrections to standing repo facts, found while verifying:**

- Strategy doc §6 item 6 ("correct the Mailmeteor blog claim") is **done** —
  commit `f618697`; the page now says Mailmeteor has an Outlook add-in and names
  two places where OutMass is behind. Remove it from the open list. **[V]**
- `CLAUDE.md` still names the release gate as "üç suite" (three). There are
  **18** test files under `extension/tests/`. The rule is stale relative to the
  tests it governs. **[V]**
