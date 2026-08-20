# OutMass — Backlog

Identified during the 2026-06-23/24 work but not yet done. Living doc — update
status as items land. (Internal: `docs/plans/` is excluded from the public Jekyll
site, so this never ships to getoutmass.com.)

**Status:** ⬜ todo · 🔧 in progress · ✅ done · ⏸️ deferred

> **Audited 2026-08-08.** Every open entry was re-checked against the code, and
> most of them had drifted: three were done and still marked open, two were
> partly done in ways that read as fully done, and one heading carried a second
> unrelated item that had been invisible for five weeks. One entry ("unit-tests
> green") had gone from true to false without anyone editing it, which is how a
> ten-day CI outage stayed hidden.
>
> Two habits that would have prevented most of it:
> - **A ✅ must not contain an open action.** If the remaining step is Ali's, it
>   is a separate ⬜, not a sentence at the end of a done entry.
> - **Pin claims to evidence, not to memory.** Counts (locale keys, listing
>   languages, send loops) age silently; every number here now carries the date
>   it was measured. Three of them were wrong by the time they were re-read.
>
> Current release state lives in the handoffs, not here — see
> `handoff-2026-08-08.md`. Entries pinned to a version number go stale within
> the week.

---

## 🔴 P0 — blocks users / revenue now

### ✅ Publisher verification → Azure MPN ID — DONE (2026-06-24)

> **Resolved.** The app `3b6a9f9b` was already in the work tenant
> (`outmassappoutlook.onmicrosoft.com`) — no migration / no client-ID change.
> The earlier error was just the wrong signed-in account; redoing it as
> `partner@…onmicrosoft.com` (a CPP admin) got past `MPNAccountNotFoundOrNoAccess`.
> Then `metisbilisim.com` was added as a verified tenant custom domain (DNS TXT)
> to satisfy the publisher-domain match. **M365 work/school consent block lifted.
> Zero code/deploy change, zero service disruption.** _(original notes below.)_
The M365 work/school **consent block** is still live — an unverified multitenant
publisher means end users can't grant consent. Telemetry shows real, motivated
users lost to it (*"The user did not approve access"* — e.g. person `988a5fe3`,
US/Mac, 8 attempts over 4h). Partner Center legal verification is **Authorized**,
but the Azure "Add MPN ID to verify publisher" step failed with
**`MPNAccountNotFoundOrNoAccess`**.

To finish (Azure → App registrations → OutMass `3b6a9f9b-cbb6-4dcb-a3b6-d993de74a1b5`
→ Branding & properties):
1. Partner Center → Account settings → **Identifiers** → use the **`PartnerGlobal`**-type
   ID (NOT a Location/PLA ID). The number we tried (`7128581`) errored — confirm the real one.
2. Sign in to Azure with an account that's **Global / MPN / Accounts Admin** on the
   Partner Center (CPP) account, and confirm the app's tenant is in the CPP
   **associated tenants** list.
3. **Likely next hurdle — `PublisherDomainMismatch`:** the app's Publisher Domain is
   `getoutmass.com`, but the Partner Center vetting domain (primary contact
   `alibayar@metisbilisim.com`) is `metisbilisim.com`. Either add **`metisbilisim.com`**
   as a verified custom domain in the app's Entra tenant (DNS), or set the app's
   publisher domain to it.

*Needs Ali at the Azure / Partner Center portals (share screens).*

---

## 🟠 P1 — bit a paying customer / ship pending

### ✅ Cross-campaign dedup skips never-delivered recipients — DONE (2026-06-24)

> **Resolved.** `_fetch_previous_emails` now dedups `pending` only from campaigns
> still on track to deliver (scheduled/sending/ab_testing); `pending` from a
> failed/partial/cancelled campaign is no longer skipped, so a failed send can't
> lock a user out of re-mailing their own list. `sent` dedup unchanged. Added a
> regression test (`test_pro_user_dedup_keeps_pending_from_failed_campaign`).
`_fetch_previous_emails` (`backend/routers/campaigns.py` ~1204) returns **sent OR
pending** addresses; the upload dedup (~447) then skips them. Recipients left
`pending` by a FAILED/partial send (e.g. the 502 timeout) never received the email
but get skipped → the user is locked out of their own list. **Miriam hit exactly
this.** **Fix:** dedup should skip only actually-`sent` (delivered) contacts, not
`pending` from failed/partial campaigns. (Today's workaround: Settings → "Skip
Repeat Recipients" → off.)

### ✅ Upload extension v0.1.18 to Chrome — DONE (2026-06-25, LIVE)
`outmass-0.1.18.zip` built + verified and **live on the Chrome Web Store** —
confirmed by an organic new user (India, person `2348cf80`) already running
0.1.18 end-to-end. Bundles large-send warning + benign-noise client filter
(P2 #2) + feedback reassurance copy (P2 #3).

### ✅ Upload extension v0.1.18 to Edge — SUPERSEDED (closed 2026-08-08)
Overtaken by events long ago and left open by bookkeeping alone. Edge was
already on 0.1.20 by 2026-07-03 (`handoff-2026-07-03.md:26`), reached 0.1.25 in
July and published 0.1.26 on 07-29 (see the store-listing entry below). The
0.1.18 zip was never the thing to upload.

**Current store state** (self-reported in `handoff-2026-08-08.md:22`, NOT read
from the dashboards — only Ali can confirm those): Chrome 0.1.27 live, Edge
0.1.26 live with 0.1.27 in review, and `outmass-0.2.0.zip` built and verified
but not yet uploaded to either store. Track the live versions in the handoff,
not here — a backlog entry pinned to one version number goes stale the week
after it is written.

---

## 🟡 P2 — flagged bugs / cleanup

### ✅ Truncated unsubscribe IDs — DONE (2026-06-25)

> **Resolved.** `get_contact()` now validates the id is a UUID and returns
> `None` before the query, so the public tracking routes (`/t`, `/c`,
> `/unsubscribe`) fall into their existing "not found" path (clean 200)
> instead of crashing with 22P02 → 500. Test: `test_contact_uuid_guard.py`.
> _(Committed `93815ee`, not yet deployed — batched with the dedup fix.)_
PostHog `$exception` (backend): `/unsubscribe/NjhjYWRjMT…` — 10-char, non-UUID →
`invalid input syntax for type uuid`. Either the unsubscribe links are being
truncated, or email scanners hit partial URLs.

### ✅ Filter benign $exception noise — DONE (2026-06-25)

> **Resolved.** Two layers share one denylist (ResizeObserver loop,
> port-closed/bfcache, extension-context-invalidated): the backend
> `/api/error-report` returns `{"status":"filtered"}` without capturing
> (scrubs noise from already-shipped versions immediately), and
> `reportError()` in `background.js` short-circuits before the fetch.
> Tests in `test_posthog.py`. _(Committed `527941d`; backend deploys in
> the batch, client ships with 0.1.18.)_
363 `ResizeObserver loop completed…` events flooded error tracking
(`extension-client`).

### ✅ Feedback form confirmation — DONE (2026-06-25)

> **Resolved.** The success toast now promises a reply — "Thanks — we got
> your message and will reply to your email soon." across all 10 locales —
> instead of the passive "submitted!". Also fixed the feedback context
> reporting a hardcoded version `"0.1.0"` (now the real manifest version)
> so support tickets carry accurate build info. _(Committed `04e4a6b`;
> ships with 0.1.18.)_
The in-app feedback form gave no clear "we got it — we'll reply to your email"
confirmation, so users felt unheard (Miriam: *"I can't even email support"*, yet
her feedback did arrive).

---

## 🔵 P3 — ops / quality

### ✅ DMARC for getoutmass.com — DONE 2026-08-13

> **Resolved.** The record is live, aggregate reports arrive daily, and
> `scripts/dmarc_report.py` reads them without opening the XML; reports land
> in `dmarc/`. The heading here still said **CONFIRMED MISSING** the day after
> it was fixed — stale by exactly the amount that makes a backlog untrustworthy,
> corrected 2026-08-14.
>
> *(Original entry: `nslookup -type=TXT _dmarc.getoutmass.com 8.8.8.8` →
> NXDOMAIN on 2026-08-08. SPF was already correct
> (`v=spf1 include:_spf.mx.cloudflare.net include:_spf.mailersend.net ~all`), so
> the missing piece was one DNS TXT record. Without DMARC, receivers had no
> policy to apply to mail failing SPF/DKIM, and nothing told us when it
> happened. DKIM was verified in the same sitting.)*

### ⬜ Branded support send-as (`support@getoutmass.com`)
Split out of the entry above on 2026-08-08 because the two are independent and
bundling them hid that one of them is a one-record DNS fix. Replies still come
from `outmassapp@outlook.com` (Outlook.com cannot send-as an external domain).
Note the repo uses MailerSend as an **HTTP API** sender, not SMTP
(`backend/utils/welcome_email.py`, `backend/workers/inactivity_nudge.py`,
`backend/models/ms_token.py`, `backend/routers/account.py`) — so this is a Gmail
"Send mail as" setup against MailerSend SMTP credentials, entirely outside the
codebase. Nothing to implement here; it is an account setting.

### ✅ Re-run the PostHog funnel (verify the fixes) — DONE 2026-08-07

> **Resolved.** Asked on 06-24 for "2-3 days later"; actually done 08-07, and it
> was worth the wait because by then there was enough volume to read. The full
> store→install→sign-in→send funnel is in `handoff-2026-08-07.md:24-54`:
> 430 impressions → 140 views (33%) → 48 installs (34%); post-install
> 63 → 30 opened the panel → 37 tried sign-in → 22 signed in → 16 uploaded →
> 9 sent (14%). Cohort split: of 54 who never opened the panel, **0 sent**;
> of 43 who did, 15 sent (35%).
>
> It answered both original questions with evidence, and both answers were
> different from the guess. *"Authorization page could not be loaded"* was NOT a
> Microsoft-side failure at all — it was our own error page returning HTTP 400,
> which Chromium reports as a page-load failure and the extension auto-retried,
> so a user who had just declined got a fresh consent screen 3 seconds later.
> Fixed and deployed 08-08 (`7233d35`). And *"did not approve"* turned out to be
> partly real: AADSTS65004 events are the first hard proof that users actively
> decline, rather than being blocked.
>
> Two lessons kept: reading the funnel found a bug that no test suite could have
> (the 400 was correct HTTP and wrong behaviour), and store conversion turned out
> to be the healthy part — see `funnel_truth_2026_08`. The lever is impressions
> volume and post-install activation, not the store listing.

**Not a standing cadence.** This was one ad-hoc read. If a weekly rhythm is
wanted, that is a separate commitment nobody has made yet.

### ✅ Debounce the sign-in button (prevent stacked OAuth popups) — DONE (2026-06-25)

> **Resolved (`02f9b62`, ships in 0.1.19).** `startMSLogin` now single-flights:
> while an OAuth flow is in progress, repeated Sign in / reconnect clicks join
> the same in-flight promise instead of launching another `launchWebAuthFlow`.
> Keyed by flow type (signin vs onedrive). `oauth_started` now fires once per
> real flow. Also disabled the sidebar "sending-as change" link mid-flow.
Telemetry from the first 0.1.18 organic user (2026-06-25, person `2348cf80`):
**10 `oauth_started` / 3 `oauth_completed` / 2 `oauth_failed`** in one ~12-min
session, six `oauth_started` within ~10s. The user rapidly re-clicked sign-in,
spawning multiple OAuth popups; the abandoned ones logged
`oauth_failed: "The user did not approve access."` (benign user-cancellation,
**not** the consent block — they completed and ran a successful test send).
**Fix:** disable / debounce the sign-in button while an OAuth flow is in
progress (`background.js` launch path + the sidebar/popup buttons) so a flow
can't be started twice. Also dampens false "did not approve" noise in the
oauth funnel. Low effort, UX-only.

### 🔧 Quota follow-ups (deferred from the 2026-07-03 billing-anchored quota review)
Adversarial review of the rolling-quota change surfaced these; all bounded /
rare, deliberately deferred. **Re-audited 2026-08-15 against the code, every
verdict cross-examined by two skeptics: 1 ✅, 2 ✅ with a narrower accepted
residual, 3 🔧 HALF-done (the skeptic pass caught a missing write path the
first read called done), 4 🔧 half-done.**
1. ✅ **Mid-campaign reset/increment race — DONE 2026-08-11** — send loops incremented the counter
   ONCE at the end of a paced (possibly hours-long) run; if the period boundary
   rolls over mid-flight, the whole campaign's count lands in the NEW period.
   Fix: increment in small batches (~25) inside the send loops. Bounded
   (≤1 campaign), self-corrects next period; pre-existed in calendar form.
   - **Done for ONE loop.** `840ee99` (2026-08-08) added
     `QUOTA_CHARGE_BATCH = 25` (`backend/config.py:264`) and batches inside
     `_run_campaign_send` (`backend/routers/campaigns.py:972-976`, with a
     tail-catch at 995 and handlers for cancellation and generic failure) —
     the **send-now** path only. That commit touched no worker file.
   - ✅ **The three worker loops followed on 2026-08-11** (`ffe9737`): mid-loop
     `QUOTA_CHARGE_BATCH` charging + a guarded remainder flush in the
     scheduled-campaign loop (`scheduled_worker.py:181`), the A/B winner pass
     (`:515`) and follow-ups (`followup_worker.py:109`).
     `test_quota_batching.py` pins the call SHAPE (25+25+10, never one 60)
     and bounds a mid-loop kill to one batch. This bullet claimed "still
     unbatched, all three" for four days after the fix landed — task #26 was
     the correct record and this file was the stale one.
   - **The entry said "5 send loops"; there are 4.** ✅ **Closed 2026-08-14 —
     the fifth was deleted.** `email_worker.send_email_task` had no caller and
     never touched `increment_sent_count`, but the 2026-08-13 send-path
     mapping sharpened what that meant: it POSTed to Graph, marked the contact
     sent and bumped the campaign counter, so it was the one path that could
     put a customer's email on the wire charging no quota and reporting
     nothing — and it stayed **registered** at `celery_app.py`, one
     `celery.send_task()` from a shell away from being live. "Dead code" was
     the wrong frame; dormant and armed was the right one. Ali's call: delete,
     rewrite later if ever needed. A test now asserts the set of files that
     POST to `/me/sendMail` is exactly the three that charge the quota, so a
     fourth cannot reappear quietly.
2. ✅ **cancel_at_period_end final-day refill — DONE 2026-08-14/15**
   (`79398b6` + `28a8c75`). Exactly the fix this line used to propose:
   migration 028 persists cancel_at_period_end from subscription.updated in
   both directions (`billing.py:886-906`) and holds the due-day rollover
   (`user.py:395-401`); a day later the paid_cycle_confirmed hold
   (`user.py:426-436`) covers the same case even if the flag were never set.
   Tests: `test_quota_anchor_and_cancellation.py`,
   `test_billing_cycle_reset.py:109` (the cancel hold wins even over a stray
   paid_cycle_confirmed=True). **Accepted residual, not cancellation-specific:**
   both holds are bounded to today==due, so a Stripe webhook lost past UTC
   midnight lets ONE stale-plan rollover through a day late — the tradeoff
   `user.py:390-394` documents on purpose. Revisit only if the green report's
   "backstop rolled it" flag fires two months running.
3. 🔧 **Month-end anchor drift — READ half shipped, WRITE half missing**
   (re-scoped 2026-08-15; the audit's first pass called this done and two
   skeptics refuted it). Migration 029 added `month_reset_anchor_day` and the
   period math reads it (`user.py:304-324`, `:438-444`) — but **nothing in
   application code ever writes the column**; the only writer is the
   migration's one-time backfill. So (a) every user created after the
   migration has NULL forever → falls back to the clamped day → the original
   29/30/31→28 decay reproduces for all new users; and (b) NEW and sharper:
   the checkout re-anchor (`billing.py:576-580`) sets month_reset_date=today
   without touching the anchor day, so a subscriber who pays on a different
   day than they signed up keeps the STALE signup anchor and the next quota
   "month" can be days long (signup day 5, pay Aug 31 → due Sep 5). Fix =
   write the anchor at user creation and at every month_reset_date re-anchor,
   plus a source-scan test that every writer of one writes the other
   (`test_send_telemetry.py` has the pattern). → task #57.
4. ✅ **create-checkout StripeError fallthrough — DONE 2026-08-15** (second
   half closed same day it was re-scoped). The 502 half had shipped earlier
   (`billing.py:236-255`). The identity half now exists as
   `_event_subscription_is_current`: subscription.deleted / subscription
   .updated / the renewal invoice only act when the event describes the
   subscription the account RUNS on; stored-NULL and no-id cases fail open
   to the old behaviour, a mismatch skips loudly (log + Telegram). Covers
   the orphan-cancel scenario AND the ordinary cancel-then-resubscribe flow,
   where the old subscription's period-end death used to downgrade the
   freshly re-paying customer. The invoice id is read in both the pre-basil
   and basil payload shapes. Tests:
   `test_webhook_subscription_identity.py`. The same review added three
   checkout hardenings: a >14-day-old session event is refused (dashboard
   "Resend" resurrection), an anomalous no-subscription session no longer
   NULLs a stored id, and the quota anchor now comes from the
   subscription's own `current_period_start`, not our webhook-processing
   clock. **Endpoint API version confirmed by Ali 2026-08-15:
   `2026-03-25.dahlia`** — post-basil, so the `parent.subscription_details`
   path is the one live payloads actually use; without the two-shape read
   the renewal guard would have shipped permanently inert. Every other
   field the webhooks read has months of production behaviour proving it
   arrives — `invoice.subscription` was the one field never read before,
   which is exactly why its absence would have been silent.

### ✅ Microsoft-consent funnel leak — ALL THREE SHIPPED, measure it now (2026-08-15)

> **Re-audited 2026-08-15. All three ideas are in the code; the 08-08 audit
> below is what was true a week ago and is kept because its warning still
> applies — adjacent work lands near this and it is easy to miscount.**
>
> - **Idea 1, pre-OAuth trust panel: SHIPPED in 0.2.1**, published to Chrome
>   on 08-15. `extension/sidebar.html:43` carries `popupConsentExplainer`,
>   which the 08-08 audit correctly reported as living only in popup.html.
> - **Idea 2, consent-decline follow-up: SHIPPED.** `i18n.js:197`
>   `msAuthMessage(mcode, fallback)` maps 14 classifications to sentences, and
>   it takes PRECEDENCE at all three places a user sees the failure —
>   `sidebar.js:186`, `sidebar.js:249`, `popup.js:258`. The static
>   `authErrorConsent` the audit flagged is now only the fallback for when the
>   backend sent no code. (Read one line further than the `consent_declined`
>   branch before concluding otherwise; that mistake was made twice.)
> - **Idea 3, per-step measurement: SHIPPED, cadence still unmade.** Nothing
>   reads the funnel on a schedule. `workers/green_report.py` is the obvious
>   home; Gate 2 in it still says "PostHog, by hand".
>
> **The baseline to beat, measured 2026-08-15** — `oauth_started` and
> `oauth_completed` are both client-side and lossy, so this counts
> `ms_auth_window_opened` against the SERVER-side `login`:
>
> | week | reached Microsoft | signed in | rate |
> |---|---|---|---|
> | 08-09 | 28 | 13 | 46% |
> | 08-02 | 17 | 7 | 41% |
>
> More than half of everyone who reaches Microsoft's screen never comes back.
>
> **And the shape of the loss, last 30 days by AADSTS:** user_declined_consent
> (65004) 8 people — the largest classified group by far; no_code_from_
> microsoft 3; account_from_other_tenant (50020) 1; unclassified 3.
>
> **AADSTS65001, the M365 admin-consent block this entry warned about, does
> not appear at all.** The loss is people choosing "no", not a tenant policy
> refusing them — which is the one kind a plain-language explanation before
> the screen can actually move. That is the bet 0.2.1 places.
>
> **Nothing left to build. Two things left to do:** put 0.2.1 on Edge (Edge
> received 0.2.0 on 08-15, and 0.2.0 does NOT contain the explainer), and
> re-measure the table above in a week.

> **Audited 2026-08-08 — one of the three ideas shipped. Read this before
> assuming the other two did, because adjacent work landed near both.**
>
> - **Idea 3, per-step funnel measurement: SHIPPED and used.** `abfae48`
>   (07-31) added `ms_auth_failed` with AADSTS classification;
>   `0f0636c` (08-03) added `ms_auth_window_opened` as the midpoint between
>   `oauth_started` (client) and completion. Real numbers came out of it on
>   08-07 (37 tried sign-in → 22 signed in). No weekly cadence exists though —
>   that was part of the idea and remains unmade.
> - **Idea 1, pre-OAuth trust panel: NOT shipped.** `popupConsentExplainer`
>   still lives only in `popup.html` and the locale files — grep finds it
>   nowhere in `sidebar.html`/`sidebar.js`. The panel, which is where users
>   actually are when they hit sign-in, still says nothing about what Microsoft
>   is about to ask for.
> - **Idea 2, consent-decline follow-up UX: NOT shipped — and this is the one
>   most likely to be miscounted as done.** The 08-08 auth work (error page
>   400→200, `_SETTLE_MESSAGES`, dwell 9s→5s) fixed the *repeat-prompt bug* and
>   improved the *server-side* settle text. But the client still collapses every
>   consent failure to one `consent_declined` code (`background.js:553-557`) and
>   renders one static alert (`authErrorConsent`) for all of them. Stopping a
>   loop is not the same as replacing a dead end with an explanation.
>
> So: 1 of 3. Do not close this entry.

~5 anonymous users lost AT the Microsoft consent screen in 10 days (AU 07-17,
BR 07-21, TR ×3 07-23, PH 07-25 — the PH one had a NEAR-PERFECT activation:
29-recipient CSV + 6 chip insertions in 5 minutes, then bailed at consent).
The 0.1.25 sign-in gate works — users now FIND and attempt OAuth (pre-gate
they never did) — the drop is now at Microsoft's permissions screen itself.
Ideas to explore: pre-OAuth trust panel (plain-language per-permission
explainer with the honest popupConsentExplainer framing + "we can never read
your inbox" + refund/privacy links), consent-decline follow-up UX (after
oauth_failed=declined, show "what Microsoft asked and why" instead of a dead
end), measure per-step funnel (oauth_started → completed rate) weekly.

### ✅ Scheduled-send early-close strand — FIXED 2026-07-29 (0.1.27 cut)
The twin of the router-path strand bug (c1705f2). `scheduled_worker` sliced the
list to the remaining quota (`pending[:remaining]`) but still closed the
campaign `"sent" if not errors` — so a scheduled campaign longer than the
remaining quota reported COMPLETE with contacts still 'pending', unreachable by
the Resume endpoint (409s on non-partial) and by the auto-resume beat (queries
`status='partial'`). Worse than the router case: the truncation is server-side,
so the user never even saw the quota alert. Now tracks `quota_capped` and lands
'partial'. Tests: `test_scheduled_quota_cap.py`.

### ✅ Auto-resume window vs rolling quota cycle — FIXED 2026-07-29 (0.1.27 cut)
`AUTO_RESUME_MAX_AGE_DAYS = 14` was compared against `created_at`, but the quota
period is a rolling month on the user's own `month_reset_date`, so the gap
between hitting the cap and the next reset is 0-31 days. Anyone who burned their
quota early in their cycle was ALREADY outside the 14-day window on reset day
and stayed outside it forever — while the in-app text promised an automatic
send. (Faisal's cap landed 5 days before his reset, which is why it worked.)
Now: query bound widened to 70 days, real rule is per-user
`_capped_in_last_quota_cycle()` = created within the current or previous cycle.
Tests: 4 new cases in `test_auto_resume.py`.
**Remaining limitation (accepted):** a campaign so large it needs 3+ cycles to
drain falls out after two. Reports still offers Resume. Proper fix needs a
`campaigns.updated_at`/last-activity column (migration) — revisit if a real
user hits it.

### ✅ Suppressed-skip contacts stay 'pending' forever — FIXED 2026-08-04
`contact_model.mark_suppressed()` records the skip in all three send loops
(router send-now, scheduled worker, A/B winner pass); `get_resumable_contacts`
already filters on `status IN (pending, deferred)` so they drop out with no
query change. 5 tests.

Two things the original diagnosis had wrong, worth keeping:
- **unsubscribed needed no fix.** `get_resumable_contacts` already carries
  `.eq("unsubscribed", False)`, so those were never the problem — only the
  suppression-list path was. Marking them too would touch rows for no gain.
- **"Decide Reports display semantics" was a non-issue.** The stats endpoint
  returns sent/opened/clicked/engaged/reply rates plus pending_followups; it
  never counts contact status. The only consumer is the resumable set, so
  nothing user-visible moved.

Scope note: suppressed addresses are filtered at UPLOAD time, so the rows
reaching these loops are only those added to the list AFTER the CSV went in
(including anyone who unsubscribed from an earlier campaign). Deliberately
NOT reversible — if the user later un-suppresses an address, the contact
stays skipped. Re-emailing someone who was on a do-not-email list should be
a deliberate act, not a side effect.

### ✅ Store-listing refresh — VERIFIED LIVE on the public listings (2026-08-15)

> Ali said the paste "should have happened"; instead of trusting memory or
> the dashboards, the PUBLIC store pages were scraped — they are what users
> actually see, which makes them the evidence rather than a proxy for it.
> **All 12 Chrome locales** (en, tr, de, fr, es, ru, ar, hi, zh-CN, zh-TW,
> ja, pt-BR) **and 2 sampled Edge locales** (tr, de) carry the new copy:
> 250/2,500 quotas, the 🚦 daily-limit and ♻️ auto-resume bullets, and no
> timezone claim anywhere. Chrome shows 0.2.1 live. Edge takes its listing
> as one submission, so two clean samples speak for the set.
>
> One false alarm during verification worth keeping: a grep for the OLD
> "50 emails/mo" marker matched — inside "2**50** emails/month". Read the
> context before believing a marker, even one you wrote yourself.
>
> The pt_PT question that used to live at the bottom of this entry moved to
> its own item below — a ✅ must not contain an open question.

> **Re-marked 2026-08-08.** This was ✅ while its last line said "Remaining: Ali
> pastes all 11 languages into BOTH dashboards" — so the repo-side prep was
> done and the only part users can actually see was not, tracked nowhere. A ✅
> with an open action inside it is how work disappears.
>
> **And the number moved: it is 12 now, not 11.** `listings.json` currently
> holds en, tr, de, fr, es, ru, ar, hi, zh_CN, **zh_TW**, ja, pt_BR — zh_TW was
> added the day after this entry was written, when Traditional Chinese became a
> real translation. `docs/store-listing/README.md` still says 11 and still
> describes pt_BR as "listing-only until the pt locales ship in 0.1.27"; 0.1.27
> shipped on 08-05.
>
> *(the pt_PT question moved to its own ⬜ item below on 2026-08-15)*

Trigger fired: Edge published 0.1.26 on 07-29. All 9 points applied to
`docs/store-listing/listings.json` (10 languages edited + NEW pt_BR entry) via
a 15-agent translate+verify workflow; `check-limits.js` guards limits + banned
claims (timezone phrases, "Claude"). Outcomes vs the audit:
- Point 1-2 (250/2500): repo copy was already correct — the DASHBOARDS are
  staler than the repo; every language must be re-pasted, not just TR.
- Point 3 (language count): stays **10** — the 11th `_locales` folder is `zh`,
  a zh-TW/HK fallback with the same Simplified content, not a new language.
  Becomes 11 at 0.1.27 (Portuguese counted once). Policy note in README.
- Point 4 (timezone claim): removed in all languages; check-limits.js has
  per-language tripwire regexes so it can never return.
- Point 5: follow-ups marked (Pro) + "stops when someone replies" added.
- Point 6-7: 🚦 daily-limit and ♻️ auto-resume bullets added ×11.
- Point 8: AI quota 50/mo verified in config.py; "Claude-powered" genericized
  (model-name maintenance liability) — one-word revert if Ali disagrees.
- Point 9: 30-day guarantee kept.
- **BONUS fix found during the code claims-check: the old Pro pricing line
  claimed templates — templates are Starter+ in code (templates.py). Starter
  line now lists scheduled sending + templates + CSV export; Pro line lists
  AI + A/B + follow-ups. Plan labels added to feature bullets to match gates.**
- Verify pass caught an **ar bidi bug**: "(Starter+)" renders "(+Starter)" in
  RTL — replaced with "(Starter فأعلى)". (zh-lesson class of defect.)
Remaining: Ali pastes all 11 languages into BOTH dashboards (Edge listing edit
= new metadata-only submission; batch it, don't trickle).

Original audit (for history):
1. "Free — 50 emails/mo" → **250/mo** (ancient pre-launch number; underselling).
2. "Starter — 2,000/mo" → **2,500/mo** (underselling).
3. "10 interface languages" → 11 today, **13 once 0.1.27 ships** — sync the
   number with whatever is LIVE at edit time (claims discipline).
4. "send across timezones" → REMOVE — this exact claim was killed in the
   2026-07-15 site audit but survives in listing translations.
5. Follow-ups bullet: mark **Pro-only** (align with site decision b) and may
   now truthfully add "stops automatically when someone replies".
6. ADD: **Daily send limit** (live since 0.1.25 — the bellmed feature).
7. ADD (optional): quota-capped recipients auto-resume after reset (live
   2026-07-20).
8. Verify the AI-writer "(Pro, 50/mo)" quota against config before keeping the
   number; reconsider naming the model ("Claude destekli") in store copy.
9. "30-day money-back guarantee" ✓ verified real (refund.html + pricing FAQ) —
   keep.

### ⬜ pt_PT store-listing entry — decide, don't drift

Split from the store-listing entry above (a ✅ must not carry an open
question). The extension ships pt_PT but `listings.json` has no pt_PT
entry. Next time Ali is inside either dashboard: do the stores offer pt-PT
as a separate listing locale? If yes, decide add-or-skip deliberately; if
no, close this entry with that fact written down.

### ✅ 0.1.27 queue — CUT 2026-07-29, PUBLISHED on Chrome 2026-08-05
*(Heading corrected 08-08: it still said "awaiting Ali's upload" nine days after
the upload happened — the same ✅-with-an-open-action-inside pattern flagged at
the top of this file. Edge 0.1.27 was still in review at the time of writing.)*
Both queue items shipped, plus what the mandated adversarial review turned up.
**Shipped:** pt_BR + pt_PT locales (323 keys each, translated separately — not
one file copied; verified BR/PT vocabulary split) · reworded `alertQuotaCapped`
AND `resumeHint` ×13 · `aiLangPt` + AI-writer `pt` option + `pt_BR`/`pt_PT` in
Settings → Interface Language · backend `_LANG_NAMES["pt"]` · Portuguese
unsubscribe page · the two backend strand/window fixes above · new suites
`locale-variants` (script + regional purity) and `test_ai_language_contract`.
Package: `outmass-0.1.27.zip`, 29 entries, 13 locales, no leakage.

**Findings raised by the review that are NOT fixed (deliberate, documented):**
- **AI writer has one generic "pt" option** — a pt_PT user asking for a
  Portuguese draft may get Brazilian-leaning text. Accepted for now: Pro-only
  feature, output lands in the editor for review before sending, and both
  variants are mutually intelligible. Proper fix = send `pt_BR`/`pt_PT` from
  `getActiveLocale()` and add both to `_LANG_NAMES` (keep bare `pt` for
  already-shipped clients). Do it when a Portuguese Pro user actually appears.
- **AI-language preselect reads the browser language, never the Settings
  override** (`sidebar.js` ~1739 `chrome.i18n.getUILanguage()`): someone whose
  browser is English but who set the panel to Turkish gets English preselected.
  Pre-existing for all 13 languages, cosmetic (dropdown is one click). Fix =
  read `uiLanguage` from storage / expose the resolved locale, and normalise
  `pt_BR`/`zh_CN` → base code before the `supported` lookup.

**DEPLOY ORDER MATTERS:** backend first (`_LANG_NAMES` + unsubscribe strings +
the two worker fixes), extension after. New extension against an un-updated
backend = Portuguese requested, English email delivered, no error anywhere.

1. ✅ **Partial-send quota message text update ×13** — the in-app alert said
   "Resume sends them after an upgrade or your monthly reset"; since 2026-07-20
   the backend auto-resumes capped recipients (auto_resume_partial_campaigns
   beat + quota-cap email). Update wording to "they'll be sent automatically
   after your reset — or upgrade to send them now". Harmless meanwhile (user
   goes to click Resume, finds the campaign already completed).
2. ✅ **New locales: pt_BR + pt_PT (11 → 13 folders, 11 languages)** — approved by Ali 2026-07-21,
   data-driven: 2 observed pt-BR users in 90 days (the only uncovered locale in
   telemetry); pt_PT rides along nearly free. No generic "pt" code in Chrome —
   both folders required (pt-PT does NOT fall back to pt_BR). At cut: translate
   full messages.json ×2 in the correct variants, locale-consistency suite
   enforces parity automatically. Mind script/variant consistency (zh lesson,
   see memory release_adversarial_review). ALSO update item 1's new strings in
   13 files, not 11.
   - **Parallel, no release needed:** ✅ pt-BR store-listing translation is
     READY in listings.json (2026-07-29, verified pt-BR-not-pt-PT); Ali pastes
     it into Chrome/Edge dashboards with the listing refresh. Conscious call:
     it markets to users who get an English UI until 0.1.27 ships pt locales.
   - **NL: deliberately NOT added** — both observed NL users run en-US browser
     UIs (self-selected English; NL = top English-proficiency market). Policy
     stays demand-triggered: first real request/nl-locale telemetry → add same
     week.

### ✅ Traditional Chinese is now REAL — shipped in 0.1.27 (2026-07-30)
Ali's call after the count discussion: rather than keep explaining that `zh` was
a Simplified fallback, make Traditional genuine. `extension/_locales/zh_TW/`
(324 keys at the time) written from English in TAIWAN terminology — 軟體/檔案/
資訊/資料/範本/伺服器/設定/收件者/儲存/登入/排程/主旨/預設/行銷/支援/點選 —
deliberately NOT a character conversion of zh_CN (only 14/324 strings coincide,
all of them short labels that are identical in both scripts anyway).
*(Re-measured 2026-08-08: both files are now 340 keys with 15 coinciding —
later releases added strings. The claim holds; only the numbers aged.)*
Also: AI writer gained a Traditional option (and the Simplified one is now
labelled explicitly); `_LANG_NAMES["zh_TW"]`; recipient-facing unsubscribe page
in Traditional with `_detect_lang` preserving the region FOR CHINESE ONLY;
`zh` stays Simplified as the fallback for bare `zh`/zh-SG.
The `locale-variants` suite gained the sharper half of the check: correct
characters are the easy part (any converter does that), so it also greps for
**mainland vocabulary in Traditional dress** (軟件/信息/數據/模板/服務器/網絡/
設置/視頻/收件人/登錄/註銷/郵箱/回复/技術支持/應用程序…). Character lists were
vetted against the real file — 回/系/准/台/里/西 are standard Traditional and
were excluded after producing only false alarms.
NOTE: the pt/zh_TW work was done by hand — the subagent API returned 529 twice
with zero output, so the usual multi-lens review could not run on this half.
Verification was: 4 extension suites + a wide one-off character/vocabulary
audit + structural parity check against en.

### ✅ FALSE CLAIM on the live pricing page: "Traditional Chinese" — DONE 2026-08-05
**Closed the day Chrome published 0.1.27**, per claims-follow-product. Ali
approved; `docs/pricing.html` now says 13 in all four places and the
"joined at a user's request" anecdote is gone (it was never true).

Three counts turned out to be different, and the old copy claimed one number
for all three — each verified against the code, not assumed:
- **interface: 13** — options in `sidebar.html`'s language `<select>`, minus Auto
- **AI Writer: 12** — options built in `sidebar.js` (`aiLang*`)
- **unsubscribe pages: 12** — keys in `_UNSUB_STRINGS`, `backend/routers/tracking.py`

Both 12s differ from 13 for the same reason (Portuguese is offered once, not
twice), so the FAQ explains it in one clause instead of three numbers.

Found while doing it: **`docs/store-listing/edge-description-en.txt`** had sat
unvalidated since June and still advertised "10 UI languages", "across time
zones" AND "Claude-powered" — every claim the 07-15 audit removed elsewhere —
in the one directory whose purpose is paste sources. Deleted (superseded by
`descriptions/en.txt`); `check-limits.js` now fails on ANY loose `.txt` there.
`docs/launch/producthunt.md` carried the same three plus "Free forever at
50/month" (real free tier is **250**) and "Starter 2k" (real: **2,500**) —
all corrected.

Original plan (for history):
**Update 2026-07-30: the claim is about to become TRUE** — 0.1.27 ships a real
Traditional translation. So the page no longer needs the claim removed, only
corrected: the count and the list. Honest post-publish wording: **13 interface
languages** (see `docs/store-listing/README.md` for why 13 and not 11/14), list
"…Simplified Chinese, Traditional Chinese, Japanese, and Portuguese (Brazil &
Portugal)", drop the "joined at a user's request" anecdote (it was never true
of the old `zh` fallback), and fix line 129's AI-writer count to match.
Still needs Ali's OK (live pricing copy) and must wait for the store to show
0.1.27.

Original finding (for history):
`docs/pricing.html:230` tells visitors the UI supports **11 languages** and lists
"Simplified Chinese, **Traditional Chinese**", with a story attached: "Traditional
Chinese joined exactly that way, at a user's request." **It did not.** The `zh`
folder was created as a GENERIC Chinese fallback (`bf58ab7` — "generic zh locale
so all Chinese variants get Chinese, not English") and its content is
**321/323 keys byte-identical to `zh_CN`**, i.e. Simplified. A zh-TW/HK visitor
gets Simplified text, not Traditional. Same page also says "11 languages" at
line 77 while line 129 says the AI Writer has "10 languages" — internally
inconsistent too.
**Needs Ali's OK (live pricing copy).** Proposed wording once 0.1.27 is
published (claims-follow-product: only after the store shows it):
- honest count = **11 languages** (en, tr, de, fr, es, ru, ar, hi, zh-Hans, ja,
  pt) — Portuguese counted once, `zh` is a fallback not a language
- list: "…Simplified Chinese, Japanese, and Portuguese (Brazil & Portugal)"
- drop the Traditional-Chinese anecdote; if worth keeping, say the true thing:
  "browsers set to Traditional Chinese get the Simplified translation rather
  than English"
- line 129 AI-writer count → 11
- also `docs/store-listing/descriptions/*.txt` + `edge-description-en.txt` still
  say "10 UI languages" (they feed the same dashboards as listings.json).

### ✅ Claims-audit leftovers (from the 2026-07-15 site audit) — ALL THREE DONE

> **Closed 2026-08-08 after verifying each sub-item against the code.** The
> header had been left ⬜ while every item under it shipped — a section marker
> that outlived its contents.

0. ✅ **OneDrive picker consent-loop guard** — deployed, not just "in master".
   `_oneDriveAuthAttempted` one-shot guard (`sidebar.js:3465,3573-3578,3736`),
   `onedrive_auth_stuck` telemetry, `oneDriveAuthStuck` present in all 14 locale
   files. Backend half is live too: `_persist_ms_tokens` keeps the access token
   when Microsoft omits a refresh token (`auth.py:363-433`) and the license-403
   marker maps to `no_onedrive` (`onedrive.py:65`, 5 tests). Shipped in
   `060a6d0`, deployed per `handoff-2026-07-26.md:9-13` — with field proof in
   the same handoff (a user self-recovered and used OneDrive cleanly).
1. ✅ **popupConsentExplainer softened (2026-07-18, in master for 0.1.26)** —
   honest framing in all 11 locales: never reads your other emails; campaigns
   stored securely to power scheduling and follow-ups.
2. ✅ **Reply cancels pending follow-ups (2026-07-18, backend — DEPLOYED)** —
   `_get_filtered_contacts` applies `.is_("replied_at", "null")` before the
   per-condition filters (`followup_worker.py:124-148`), so replied contacts
   drop out for every condition, not just the not-opened one; three tests in
   `test_followup_reply_cancel.py`. Shipped in `4460729`, deployed per
   `handoff-2026-07-26.md`. **The follow-on action is done too:** the claim is
   back on the site — `docs/pricing.html:126` "stops automatically when someone
   replies", added in `bd606fd` only after it went live.

   *(A dangling sentence fragment from an earlier draft of this item lived here
   until 2026-08-08 and was deleted; it described the pre-fix state.)*

### ✅ Move the API to api.getoutmass.com — DONE 2026-08-12 (closed with #27)

> **Resolved.** The one remaining item — Railway's `BACKEND_URL` still pointing
> at the railway host — was confirmed changed on 2026-08-12. Every part of this
> entry has shipped; it stayed marked 🔧 for two more days, which is the same
> staleness the DMARC entry above had. The audit below is kept because it
> records how the halves came to ship six weeks apart.

### 🔧 Original entry (audited 2026-08-08)

> **Step 1 and the extension half of step 2 both shipped on 2026-07-14**
> (`eb5e81b`, folded into 0.1.25), and the entry was simply never updated:
> `extension/config.js:13-14` makes `api.getoutmass.com` the primary base with
> the railway host as fallback, and `manifest.json:15-16` carries both. Probed
> live 08-08: both return `{"status":"ok"}` — api.getoutmass.com through
> Cloudflare, the fallback through Railway direct.
>
> **What is NOT confirmed: the backend's own `BACKEND_URL` env var on Railway.**
> It is not in the repo, and no public probe distinguishes it — `AZURE_REDIRECT_URI`
> can be set independently (so the OAuth redirect proves nothing), CORS allow-lists
> several origins explicitly (so origin reflection proves nothing), and the
> unsubscribe page uses a relative form action. This variable stamps **tracking
> pixels, click-tracking links, unsubscribe links and Stripe redirect URLs** into
> outgoing mail — i.e. it carries the entire reason this item exists, since a
> recipient behind the GFW or a corporate filter is exactly who gets a broken
> tracking pixel and a dead unsubscribe link. If it still reads
> `outmass-production.up.railway.app`, the user-facing half of this fix has not
> landed at all.
>
> **Ali: Railway → web service → Variables → `BACKEND_URL`.** Or open any recent
> sent email and look at where the unsubscribe link points.

Original entry (for history):
The 2026-07-14 zh-CN churn exposed a structural reach problem: our API lives on
`outmass-production.up.railway.app`, and shared-platform domains like
railway.app are blocked wholesale by some corporate filters and national
firewalls (GFW) — users on those networks can NEVER sign in, and we only see
it as silence. 0.1.24 makes the failure honest (connectivity banner); this fix
removes the failure class. Steps:
1. **Ali:** Railway → web service → Settings → Networking → Custom Domain →
   `api.getoutmass.com` (Railway shows a CNAME target) → add that CNAME at the
   DNS provider → wait for the auto-provisioned cert → verify
   `https://api.getoutmass.com/` returns `{"status":"ok"}`.
2. **Code (next meaty extension release, to amortize the host-permission
   re-approval prompt):** extension `OUTMASS_BACKEND_URL` + manifest
   `host_permissions` → api.getoutmass.com (optionally keep the railway URL as
   a runtime fallback for resilience); backend `BACKEND_URL` env → new domain
   (Stripe redirect URLs + future tracking/unsubscribe links; old railway
   links keep working as long as both domains stay attached).
Bonus: branded tracking/unsub links also help deliverability.

### ✅ Fix the e2e CI suite — DONE 2026-08-04 (`25389b7`)

> **Resolved** with option (a), exactly as proposed: `e2e/chrome-stub.ts`
> supplies a `window.chrome` stub (runtime, storage, i18n, identity, alarms)
> installed via `page.addInitScript` in the `beforeEach` of both
> `extension.spec.ts` and `i18n-visual.spec.ts`. Verified three ways: 51/51 pass
> locally, the `e2e-tests` job has been green on every CI run since, and the
> red→green boundary lines up with that commit (run 30852879659 red at the
> parent, 30937885670 green at the first push after).

### ✅ Backend unit tests were dark in CI for 10 days — FOUND AND FIXED 2026-08-08

> Found while auditing the entry above, which opens with the words "unit-tests
> green". That was true when it was written and false by the time anyone read
> it again — the entry described a red CI and named the wrong job.
>
> `backend/tests/test_ai_language_contract.py` (added `bb2ea71`, 2026-07-29)
> built an assertion message as
> `f"{src.count('t(\"aiLang')} aiLang labels"`. A backslash inside an f-string
> **expression** is legal from Python 3.12 (PEP 701) and a `SyntaxError` before
> it. Local dev runs 3.14 and never blinked; CI pins **3.11**
> (`.github/workflows/ci.yml:30`), where pytest raised at COLLECTION time:
>
> ```
> collected 555 items / 1 error
> E   SyntaxError: f-string expression part cannot include a backslash
> !!!! Interrupted: 1 error during collection !!!!
> ```
>
> So **zero** backend tests ran in CI from 07-29 to 08-08 — including through
> the 0.1.27, 0.1.28 and 0.2.0 cuts. Nothing shipped broken (the suites were run
> locally every time, where they pass), but the CI safety net was not there.
>
> Fixed by hoisting the count into a local. Two things worth keeping:
> - **A syntax error in one test file silently disables every other one.** Not
>   "that file fails" — collection aborts and the whole job dies.
> - **A local/CI interpreter gap makes a whole class of error invisible.** A
>   sweep of all 106 backend files found no other instance. `ast.parse(...,
>   feature_version=(3,11))` does NOT detect this — it accepts the known-bad
>   snippet on 3.14, so any checker built on it must self-test first or it will
>   report a clean sweep it cannot actually see. A token-stream scan does work.
>
> Now that the job runs again, CI itself is the guard for the next one.

### ⬜ Separate the polluting game events from PostHog project 152466
Split back out on 2026-08-08 into the heading it originally had — it was
swallowed into the e2e-CI entry by `8d38b1a` and spent five weeks as an
orphaned paragraph under an unrelated title, which is a good way for an item to
never be done. PostHog project 152466 receives a game's events
(`match_started`, `lobby_viewed`); the org still has exactly one project, so no
separation has happened. Mitigating: the pollution was a single burst on
2026-06-19 (15 events in about an hour) and has not recurred in the seven weeks
since, so this is low priority — but the shared key is still in place, so it
can recur without warning.

**2026-08-15 — measured, not assumed:** `match_started` / `lobby_viewed` no
longer appear in the PostHog project's event schema at all; zero recurrence
since the single 2026-06-19 burst. The shared key remains the only residue,
so the item stays open at the lowest priority in this file.

Original entry (for history):
GitHub Actions CI: unit-tests green, **e2e-tests failing ~24/48 on every push
for a month** (Ali only noticed via the 07-03 email). Last green run =
06-03 21:35; first red = 06-03 21:49 → commit `76b6317` ("refresh announcements
on account switch"). Mechanism: `e2e/extension.spec.ts` loads `sidebar.html`
via **file:// with NO chrome stub** (`chrome` is undefined); 76b6317 added an
init-time `if (chrome.storage && chrome.storage.onChanged)` block — that guard
survives a chrome WITHOUT storage but **throws ReferenceError when `chrome`
itself is undefined**, killing the IIFE before the tab/JS handlers bind →
every interaction test fails (static CSS-visibility tests still pass).
**Fix options:** (a) cleanest — add a minimal `window.chrome` stub via
`page.addInitScript` in the spec's beforeEach (test-only, no production risk,
lets all 48 exercise real logic); (b) also audit init-path `chrome.*` refs
added since June (quota loadQuota etc.) if any still throw. Verify locally
with `npx playwright test` before pushing. Not urgent (product unaffected —
unit tests + manual verification carried the last month) but a red CI on every
push trains us to ignore CI, which is dangerous.

---

## 🧭 Exit-readiness — TRIGGER: $2k MRR + 3 consecutive months of growth (Ali, 2026-08-04)

Not a goal, an option to keep alive. Decision from the 2026-08-04 discussion:
exits in this market price on **MRR and its trend, never on user count** (free
users are a cost, not an asset). Realistic ladder: ~100 paying (~$1-1.5k MRR)
→ ~$35-60k marketplace sale (Acquire.com/Flippa) and TinySeed application
territory; ~1000 paying (~$10-15k MRR) → $350-600k+ at 2.5-4x ARR. Strategic
buyers (GMass, Mailmeteor, cold-outreach suites missing an Outlook leg) pay
for the Graph sending infra + store history + SEO assets, not the P&L. VC
path: not applicable (feature-market, capped TAM) — don't spend time on it.
Biggest multiple discount we cannot fix: platform risk (Chrome/Edge stores +
Graph API dependency).

**Standing rules until the trigger (all cheap, mostly already true):**
- Books stay clean: Stripe is the ledger; assets (domain, Azure app, store
  accounts, PostHog) stay owned by Metis Ltd and transferable.
- Keep the diligence trail buyers pay a premium for: tests, runbooks,
  handoffs, telemetry, `emails_sent_total` lifetime metrics.
- Store ratings/reviews are an ACQUISITION asset too (featuring playbook).
- **Never sign exclusivity** in partnerships (HeyReach-class outreach) — it
  handcuffs a sale.

**At the trigger:** revisit deliberately — Acquire.com listing and a TinySeed
application are each ~two weeks of prep from our books. Until then the best
exit strategy is growing MRR.

---

## ⏸️ Deferred (deliberately)

- **Send pacing Phase 2/3:** account-type awareness (personal ~300/day vs business
  ~10k/day) + auto-spread a very large list over several days (GMass-style "N/day").
  Phase 1 (30/min pacing + warning) already protects business accounts; Phase 2
  matters most for personal accounts.
  - **#63 — promoted out of deferral (approved 2026-08-18): one-click
    "spread this campaign over N days".** Headline of 0.2.3; trigger = Edge
    publishes 0.2.2 (don't reset their review queue). Bundle with #59 and
    #56 — one locale pass ×14 files, one review, one zip. Scope: UI control
    computing the existing daily cap + worker honoring a per-campaign day
    budget; NOT rotation, NOT warmup (that boundary stays). The data
    (90d): median send is 4 recipients, but 5 users fired 17 sends of
    300+ (max 1,876 in one sitting) and nobody heeds the large-send
    warning — the feature protects our heaviest users from themselves,
    earns the GMass "N/day" parity claim, and surfaces Starter's value at
    the exact moment someone uploads a big list. Design note + Ali onay
    before build (user-affecting).
    - **0.2.3 release ritual addition — store-listing review pass (both
      stores, all 13 languages), caught 2026-08-18:** (1) the live
      listing claims "our servers never store email content" — false as
      written: scheduled sends and follow-ups keep subject+body server-side
      and campaigns persist for reports; soften to "sent from your own
      Microsoft account; we never read your inbox; campaign content is
      stored only to run scheduled sends and reports." (2) "30-day
      money-back guarantee, no questions asked" appears in the listing —
      either mirror it on the pricing page and EN listing (a promise in one
      language is still a promise) or remove it; Ali decides. (3) zh (and
      possibly other) listings have no screenshots/promo tiles — add the EN
      set now, retake with zh UI later. Also fold in #63's new copy and any
      claim the release makes true.
  - Market datapoint #2 (2026-08-18): Mary Bass (Business Solutions Weekly,
    #31 prospect) chose QuickMail ($49/mo, 5k emails) over us for 6k contacts
    at a-few-per-day over weeks — "better able to handle that volume." The
    honest read: that job needs inbox rotation + warmup, not just auto-spread;
    entering it is a category change, not a feature. (Datapoint #1 was Alan /
    per-recipient attachments → SecureMailMerge, 2026-07-06.)
- **Marketing:** Quora drip answers (drafts ready). Directory submissions went
  out 2026-08-16; follow-through (#60) now has measured dates, not guesses:
  - **SaaSHub:** listing live + ownership VERIFIED same day — but "verified"
    and "approved" are two separate flags. The public page still says
    "Pending approval..." and carries `noindex`; site search, the
    *-alternatives lists and compare pages all wait on the second flag.
    ✅ APPROVED 2026-08-19 — the free queue took 3 days (their own UI
    threatened "up to 32"; the $75 Priority+ declined on 08-17 stayed in
    the pocket). Verified from outside: "Pending approval" gone from the
    public page, site search returns OutMass. Remaining: the
    *-alternatives cross-lists (gmass/mailmeteor/yamm) don't surface us
    yet — they rank by votes; check weekly, don't force.
  - **alternativeto.net:** ✅ APPROVED 2026-08-17 after Ali paid the $5
    priority review (worked as advertised: same-day-to-24h). Listing live
    with screenshots, UK origin, Chrome+Edge platforms. GMass and
    Mailmeteor alternative-pairings already linked from the original
    submission (they rode along with the paid review). YAMM pairing
    suggested 08-17 → sits in the separate suggestion-moderation queue
    ("can take a while", no paid fast-track, nothing is lost). Remaining:
    Ali ♥s the live GMass/Mailmeteor pairings (each at 0 likes; one like
    lifts them above the zero-like rows). Re-scrape gmass/mailmeteor/yamm pages in a few days to confirm
    cross-listing renders (note: their alternatives lists lazy-load —
    a markdown scrape can miss entries that ARE there; 08-17 false alarm).
  - Search engines: getoutmass.com is #1 for "outmass" on Google and Bing;
    the directory pages are noindex-while-pending, so `site:` checks before
    ~08-24 measure nothing.
  - **SoftwareSuggest (India):** ✅ LIVE 2026-08-20 at
    softwaresuggest.com/outmass — approved in under 24h (they said up to
    3 business days). Verified from the public page: our short/long
    descriptions, three plans and FAQs published verbatim, no mutations.
    Original submission notes (2026-08-19): Free tier; vendor profile HQ set
    to United Kingdom (signup widget locks HQ to phone country — the
    portal's Company Profile does not). Full listing: 12 features, 11
    languages, 3 plans, 5 screenshots (compressed under their 150 KB cap),
    6 FAQs (no URLs allowed in answers), original-content descriptions
    (they run plagiarism checks — G2/site copy was rewritten). Expect the
    sales call pitching paid packages: decline, free listing is the plan.
    Competitors linked: GMass, Mailmeteor, QuickMail (YAMM and
    SecureMailMerge are not in their catalog).
  - **TrustRadius:** closed to us — vendor access requires a LinkedIn
    company page with 10+ employees (verified on the form 2026-08-19).
  - **Softonic:** ✅ claim APPROVED same day (2026-08-19, Certificate of
    Incorporation did the job). Remaining 5-minute move: in the Publishing
    Center, replace their auto-generated OutMass copy with the audited
    G2 short+long text and check the screenshots. Bonus unlocked: reply
    access to user reviews + visits/downloads metrics.
  - **G2 Digital Markets:** submitted 2026-08-17 via
    app.g2digitalmarkets.com (account: support@getoutmass.com, company
    Metis Information Technologies Ltd, UK). Their own confirmation screen
    says review within 1-2 business days → publishes on Capterra; add
    GetApp + Software Advice from the panel after approval. Every section
    was audited against the live product; the AI draft's two real errors
    were caught before submit (calendar-month quota reset claim — ours is
    anchor-day; English-only language list — we ship 12+). Still to do:
    the separate G2.com profile via sell.g2.com/create-a-profile.

---

## ✅ Done in this stretch (for context)
Telemetry EU fix · Railway healthcheck (zero-downtime deploys) · sign-in auto-retry
· M365 FAQ + Fix A error message · Stripe verified end-to-end · 13 user-loss leak
fixes (`docs/plans/2026-06-24-user-loss-leak-fixes.md`) · async immediate send (no
more 502) · rate-limit pacing (30/min) + large-send warning.

**Deployed 2026-06-25** (`449be63`, verified live on prod): cross-campaign dedup
fix · P2 #1 non-UUID tracking ids → clean 200 (no 500) · P2 #2 benign-noise filter
(server `{"status":"filtered"}` + client) · P2 #3 feedback reassurance · FAQ
reframed (M365 work/school now supported by default after publisher verification).
