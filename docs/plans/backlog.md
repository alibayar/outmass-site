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

### ⬜ Claims-audit leftovers (from the 2026-07-15 site audit)
1. **popupConsentExplainer says "We never store your email content"** — the same
   overstatement the audit killed on the site lives in the EXTENSION consent
   explainer (11 locales). Soften in 0.1.26 to the honest framing (sends via
   your own account, never reads your inbox, campaign drafts stored to power
   scheduling — mirroring the corrected pricing FAQ).
2. **Reply should cancel pending follow-ups** — the site used to CLAIM it,
   users expect it, and the data exists (reply_detector stamps replied_at)
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
