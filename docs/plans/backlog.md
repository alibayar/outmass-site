# OutMass — Backlog

Identified during the 2026-06-23/24 work but not yet done. Living doc — update
status as items land. (Internal: `docs/plans/` is excluded from the public Jekyll
site, so this never ships to getoutmass.com.)

**Status:** ⬜ todo · 🔧 in progress · ✅ done · ⏸️ deferred

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

### ⬜ Upload extension v0.1.18 to Edge
Chrome is live on 0.1.18. Edge still pending — upload `outmass-0.1.18.zip` at
https://partner.microsoft.com/dashboard/microsoftedge/ (if 0.1.15 is still
"in review", cancel it first, then submit 0.1.18).

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

### ⬜ Support send-as + deliverability
Replies go from `outmassapp@outlook.com`, not the branded `support@getoutmass.com`
(Outlook.com can't send-as an external domain). Set up Gmail "Send mail as
`support@getoutmass.com`" via MailerSend SMTP. Also add **DKIM/DMARC** for
getoutmass.com so support/transactional mail stops landing in recipients' spam.

### ⬜ Re-run the PostHog funnel (verify the fixes)
In 2-3 days, re-run the auth + send funnel: did *"Authorization page could not be
loaded"* drop (healthcheck + retry)? did *"did not approve"* drop after publisher
verification lands? are the new fixes (async send, pacing, the 13 leaks) behaving?
Watch `send_failed` / HTTP 502.

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

### ⬜ Quota follow-ups (deferred from the 2026-07-03 billing-anchored quota review)
Adversarial review of the rolling-quota change surfaced these; all bounded /
rare, deliberately deferred:
1. **Mid-campaign reset/increment race** — send loops increment the counter
   ONCE at the end of a paced (possibly hours-long) run; if the period boundary
   rolls over mid-flight, the whole campaign's count lands in the NEW period.
   Fix: increment in small batches (~25) inside the 5 send loops. Bounded
   (≤1 campaign), self-corrects next period; pre-existed in calendar form.
2. **cancel_at_period_end final-day refill** — date-granularity reset fires at
   00:00 UTC on the final anniversary while the sub dies at its creation TIME
   that day → up to one bonus quota-month for a cancelling user. Fix: persist
   cancel_at_period_end from subscription.updated and defer the rollover.
3. **Month-end anchor drift** — a day-29/30/31 anchor decays to 28 after the
   first short month (stored clamped). User-favorable, ≤3 days; fix = store
   anchor day separately. No current user affected (anchors are the 23rd-25th).
4. **create-checkout StripeError fallthrough** (pre-existing) — a transient
   Stripe error during Subscription.retrieve routes an ACTIVE subscriber to a
   brand-new full-price checkout (dual subscription); later cancelling the
   orphan downgrades a still-paying user. Fix: 502 on retrieve failure when
   stripe_subscription_id exists; match webhooks on subscription id, not
   customer id.

### ⬜ Microsoft-consent funnel leak (promoted from watch, Ali 2026-07-26)
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

### ⬜ Suppressed-skip contacts stay 'pending' forever (found 2026-07-26)
Both send loops (routers/campaigns._run_campaign_send and scheduled_worker)
`continue` past suppressed/unsubscribed contacts WITHOUT marking them, so
they sit in the resumable set indefinitely: inflate pending counts, and an
auto-resumed campaign whose only "pending" are suppressed does one harmless
scheduled→sent churn cycle. Fix: mark them (status or failure_reason
'suppressed') at skip time in both loops + exclude from resumable. Touches
Reports counts → decide display semantics before shipping.

### ✅ Store-listing refresh — DONE 2026-07-29 (content ready; Ali pastes to dashboards)
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

### ✅ 0.1.27 queue — CUT 2026-07-29 (zip built + verified, awaiting Ali's upload)
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
(324 keys) written from English in TAIWAN terminology — 軟體/檔案/資訊/資料/
範本/伺服器/設定/收件者/儲存/登入/排程/主旨/預設/行銷/支援/點選 — deliberately
NOT a character conversion of zh_CN (only 14/324 strings coincide, all of them
short labels that are identical in both scripts anyway).
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

### ⬜ FALSE CLAIM on the live pricing page: "Traditional Chinese" — now fixable (2026-07-29)
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

### ⬜ Claims-audit leftovers (from the 2026-07-15 site audit)
0. **[READY, in master] OneDrive picker consent-loop guard** — one-shot
   `_oneDriveAuthAttempted` guard + `oneDriveAuthStuck` message (11 locales) +
   `onedrive_auth_stuck` telemetry, from the 2026-07-16 lucia incident (paying
   Starter hit an endless consent-window loop). Backend half (persist scoped
   access token without refresh_token; license-403 → no_onedrive) ships with
   the next backend deploy; the sidebar guard rides 0.1.26.
1. ✅ **popupConsentExplainer softened (2026-07-18, in master for 0.1.26)** —
   honest framing in all 11 locales: never reads your other emails; campaigns
   stored securely to power scheduling and follow-ups.
2. ✅ **Reply cancels pending follow-ups (2026-07-18, backend — live on next
   deploy)** — followup_worker excludes contacts with replied_at for every
   condition; tests in test_followup_reply_cancel.py. (Site copy can now
   truthfully claim it again — add to Pro feature bullets AFTER deploy.)
   but followup_worker never reads it. Small real feature: exclude
   contacts with replied_at from follow-up sends. Turns the corrected copy
   back into a truthful selling point.

### ⬜ Move the API to api.getoutmass.com (custom domain — unblocks filtered networks)
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

### ⬜ Fix the e2e CI suite (red on EVERY push since 2026-06-03)
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
PostHog project 152466 also receives a game's events (`match_started`,
`lobby_viewed`, …). Separate into its own project so OutMass analytics stay clean.

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
- **Marketing:** Quora drip answers (drafts ready), alternativeto.net submission
  (reminder set 2026-06-27, after the 7-day account-age gate), SaaSHub.

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
