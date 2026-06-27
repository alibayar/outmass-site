# OutMass — Experience & Know-How Transfer

> **Nasıl kullanılır (TR):** Bu dosyayı yeni bir Claude oturumuna ver, sonra sor:
> *"Bu deneyim ve know-how'ı utilize edebileceğimiz başka ne tür uygulamalar yapabiliriz?"*
> Dosya, bağlamı sıfır olan bir oturumun bizim 1+ ayda öğrendiklerimizi anlaması için yazıldı: ne yaptık, hangi kalıplar işe yaradı, **nerede yandık**, hangi önlemleri aldık.

> **For a fresh session (EN):** This is an experience-transfer doc, not a spec. The point is to make the *reusable know-how* legible so you can reason about adjacent products. Don't just summarize OutMass — extract the transferable assets in §2 and the scar-tissue in §5/§6.

---

## 1. What OutMass is (in 3 sentences)
A Chrome/Edge MV3 extension that turns **Outlook on the web** into a GMass-style mass-email / mail-merge tool: CSV personalization, open/click tracking, reply detection, scheduled sends, automated follow-ups. It sends through the **user's own Microsoft 365 / Outlook.com account via Microsoft Graph** (delegated OAuth) — not a relay — so deliverability and trust ride on the user's real mailbox. Backed by a FastAPI + Supabase + Celery backend on Railway, freemium with Stripe (Free 250/mo, Starter $9/2.5k, Pro $19/10k). Live with real paying customers.

---

## 2. Transferable assets (THE reusable know-how — start ideation here)

These are the capabilities we now know how to build well. Any new product that needs ≥2 of these is a strong fit.

1. **Browser-extension-that-augments-someone-else's-web-app.** MV3: a content script injects a sidebar/toolbar into a host web app (Outlook), a service worker handles auth/API/jobs, a popup handles account/billing. We know the injection, message-passing, storage, i18n, and packaging mechanics cold. → *Any "power-tool layered on top of an existing SaaS the user already lives in" (Gmail, Outlook, LinkedIn, Salesforce, Notion, Jira, Shopify admin, WhatsApp Web, etc.).*
2. **Act on the user's behalf through a provider's API via delegated OAuth.** Microsoft Graph here (Mail.Send, Mail.Read). We know the OAuth 2.0 multitenant dance, **publisher verification** to unblock work/school orgs, the chromiumapp.org redirect, the `state`/CSRF/ext-routing, server-side refresh-token storage, work-vs-personal account differences. → *Anything that reads/writes a user's data in Google/Microsoft/Slack/Zoom/HubSpot on their behalf.*
3. **High-deliverability, rate-limit-aware sending.** Send from the user's own mailbox; pace under the provider's throttle (M365 ≈ 30 msg/min, 10k recipients/day; Outlook.com ≈ 300/day, 100/msg); individual sends not BCC; unsubscribe + suppression list; reply detection via inbox metadata scan; warm-up & list-hygiene awareness; SPF/DKIM/DMARC literacy. → *Cold outreach, CRM sequencing, transactional/notification senders, anything where "don't get the user's account flagged" is the core hard part.*
4. **Freemium SaaS plumbing.** Stripe Checkout + webhooks + customer portal; usage metering & monthly quota reset; plan gates; manual/promo plan grants; the billing edge-cases (no-stripe-customer, proration). → *Any metered SaaS.*
5. **Background automation: scheduled, recurring, and conditional jobs.** Celery worker + beat: scheduled sends, follow-ups conditioned on "not opened / no reply," daily reply-detection sweep, stuck-job recovery sweep, idempotent + `acks_late`. → *Drip campaigns, reminders, monitors, "do X when Y happens to my data" automations.*
6. **Telemetry-driven product + debugging.** PostHog (events, funnels, `$exception`, person properties) on both client and backend; we diagnose prod incidents by **cross-referencing app-server request logs with product telemetry**. → *Any product where you want to see and fix the real funnel.*
7. **Operational discipline for live users** (see §5). The muscle of shipping to people who are mid-task without breaking them.

---

## 3. Tech stack (what we'd reuse close to verbatim)
- **Extension:** Vanilla JS, Chrome MV3 — `background.js` (service worker: OAuth, message router, server-side token mgmt), `content_script.js` (injects sidebar iframe), `sidebar.js` (the app UI, ~120KB), `popup.js` (account + billing), `config.js`, `i18n.js` (11 locales via `_locales` + `default_locale` fallback).
- **Backend:** Python 3.11+, FastAPI on **Railway** as 3 services sharing one codebase — `web` (has a healthcheck → **zero-downtime deploys**), `worker` (Celery), `beat` (Celery scheduler). One `git push` redeploys all three.
- **Data:** Supabase (Postgres + RLS), Upstash Redis (Celery broker).
- **Auth:** Microsoft Graph OAuth 2.0 delegated (multitenant `/common/`) + our own JWT (server-side token management).
- **Billing:** Stripe (Checkout, webhooks, portal).
- **Email infra:** send via Graph; receive support via Cloudflare Email Routing; transactional via MailerSend; DKIM/DMARC.
- **Analytics:** PostHog (EU region — region matters, see §6).
- **Packaging:** Windows .NET `ZipArchive` (NOT `Compress-Archive` — see §6).

---

## 4. Architecture patterns that worked
- **Server-side token management.** The extension never holds the Microsoft refresh token; the backend stores it and refreshes. Workers can send on the user's behalf even when the browser is closed (scheduled/follow-up sends). Cleaner security boundary; client ID/secret are backend-only env.
- **Validate sync, do the work async.** `/send` validates the payload synchronously, returns immediately, and hands the recipient loop to a FastAPI BackgroundTask. (We learned this the hard way — a synchronous large send → 502 gateway timeout. See §5.)
- **Idempotent, recoverable jobs.** `acks_late=True`, mark-failed + partial-status so a hiccup mid-batch is resumable, plus an hourly "reset stuck sending campaigns" sweep. Never silently drop a user's recipients.
- **Parametric limits via env + exposed through `/settings`.** Raising a plan quota needs no extension update.
- **i18n with graceful fallback.** `default_locale="en"`; a generic `zh` folder catches all Chinese variants; always keep a JS fallback string.
- **Capture telemetry without forcing an extension update.** When we needed Chrome-vs-Edge install source, we read the `?ext=<id>` the OAuth flow already sends and tagged it **server-side** — no new extension version. Prefer server-side capture of data that already flows through the backend.

---

## 5. Hard-won lessons & precautions (where we got burned — read this twice)

Each is: *the symptom → the real cause → the fix → the rule we adopted.*

- **Live-users rule #1 (our north star).** We added a hard rule to CLAUDE.md: **get approval before any user-affecting change** (API/schema/extension behavior/auth/pricing/rate), keep changes minimal + backward-compatible, make migrations reversible, notify affected users, and run a deploy sanity-check (what changes for the user? reversible? mid-session race? rollback plan?). This single discipline prevented most self-inflicted wounds. *Rule: ship to live users as if they'll never notice the change happened.*
- **"All 200s in the app log" ≠ "no bug."** A paying customer hit an endless sign-in loop; Railway showed her requests all returning 200, her DB row was healthy. We almost shipped a JWT-TTL "workaround." The real cause was 100% client-side: (a) the "Open Campaign" button **hardcoded `outlook.live.com`** (the *personal* host), which bounced **work/school** accounts to Microsoft's own sign-in page — read as our login loop; (b) a background `/settings` refresh that **cleared auth on any 401**. *Rule: app-server logs only prove what the app router returned; the bug can live in the client or an edge layer. Find the root cause; don't ship a workaround the founder rightly smelled as a band-aid.*
- **Latent bugs surface when you remove a gate.** Those two bugs were ~2 months old but **invisible until publisher verification let work accounts in for the first time.** *Rule: when you unblock a new cohort, expect to discover bugs that were dormant because no one in that cohort could reach the code path.*
- **Sync send → 502.** A large "Send now" ran synchronously and tripped the gateway timeout. *Rule: anything that loops over N network calls must be async/queued; validate sync, work async.*
- **Cross-campaign dedup locked users out of their own list.** A failed send left recipients `pending`; dedup treated `pending` as "already contacted," so the user couldn't re-mail their own list. *Rule: only dedup against actually-delivered state; a failure must never poison future attempts.*
- **Rate-limit / spam is OUR problem, not the user's.** A Pro customer's big send got throttled/flagged by Microsoft. We added pacing (≈30/min) + a large-send warning, instead of telling the user "spread it out." *Rule: own the provider's limits in the product; don't push provider rules onto the user.*
- **Consent-screen drop-off.** Telemetry showed new users **declining Microsoft's permission prompt seconds after install** (Mail.Send/Mail.Read sounds scary with no context). We added a one-line pre-consent explainer on our own screen ("we send from your own account, never store your email") — framing the scary screen before they hit it. *Rule: pre-frame every third-party permission/consent screen; unexplained scopes kill activation.*
- **Publisher verification is a slog but unblocks all work accounts.** Unverified multitenant publisher = M365 orgs can't grant consent. Fixing it meant the Azure MPN dance + matching the app's publisher domain to the Partner Center vetting domain via DNS. *Rule: if you target business Microsoft/Google users, do publisher/brand verification early — it gates your entire B2B funnel.*
- **Financial actions are the founder's, not the AI's.** Refunds, subscription cancels, moving money — the assistant must NOT execute these; it prepares everything and the human clicks. *Rule: hard line around money + credentials.*
- **Support with honesty + goodwill.** When we couldn't immediately fix a paying customer, we refunded + offered a free month + told her the truth ("it's on our side") and promised to notify when fixed — instead of over-promising. BCC a support archive on every reply. *Rule: candor + a goodwill gesture beats a defensive non-answer.*

---

## 6. Gotchas that cost us real time
- **Windows `Compress-Archive` produces backslash-path zips that Chrome rejects** ("0 locales"). Use .NET `ZipArchive` with forward-slash entry names.
- **PostHog region mismatch silently drops all events.** We were sending EU-project events to the US endpoint → months of telemetry lost. Pin the region.
- **JWT TTL is a UX/security trade-off.** 24h TTL means a daily re-login; a too-aggressive 401→logout path turns that into a loop. Consider longer TTL + silent refresh, and never let a *background* call hard-logout the user.
- **A background refresh that clears auth is a footgun.** Only user-initiated actions should be able to end a session.
- **Multi-tab + a single service worker + shared `chrome.storage`** create subtle races (one tab's stale flag flips state for all). Single-flight auth flows; broadcast auth-success across tabs.
- **Quora/SEO content:** links are `nofollow` (no SEO value); promo links on a new account get collapsed; **read every existing answer before writing** (we nearly posted rehashes of better answers). Put the link in the profile, not the answer body, until the account has authority.

---

## 7. Growth / distribution know-how
- **GEO / AI-search optimization:** comparison pages ("X alternative for Outlook"), cited stats, Bing Webmaster — getting cited by AI answers, not just ranked.
- **Quora drip:** 1/day at a ~2:1 value-to-product ratio on a new account; warm up with pure-value answers in your niche; target **thin-competition** questions where you can genuinely be the best answer; disclose affiliation.
- **Store listings:** Chrome + Edge; Edge approval is slower; the same code ships to both with different extension IDs.
- **alternativeto.net / SaaSHub / Product Hunt** as discovery channels.

---

## 8. What I'd watch / do differently next time
- Build **install-source + funnel telemetry on day one** (we retrofitted it).
- Do **publisher/brand verification before** chasing B2B users.
- Treat the **consent screen as part of the funnel** from the start (pre-frame it).
- Account-type-aware behavior (personal vs business limits/hosts) from the start, not as a bug fix.
- A staging environment + a smoke test that exercises the real OAuth + send path, since the worst bugs were only visible in the live client.

---

## 9. Seeds for ideation (categories, not answers — for the new session to expand)
The strongest reuse is when a new idea needs the **extension-augments-a-SaaS** pattern **+** **act-on-the-user's-behalf via OAuth** **+** **deliverability/automation** **+** **freemium metering**. Think along axes:
- **Same surface, different job:** other power-tools inside Outlook/M365 the same users would pay for (CRM-lite, meeting scheduling, inbox automation, email analytics, signature/branding management, shared-inbox/helpdesk).
- **Same job, different surface:** the GMass-for-Outlook playbook ported to another host app the user already lives in.
- **Same plumbing, different provider:** swap Microsoft Graph for Google/Slack/Zoom/HubSpot and reuse the OAuth + automation + billing spine.
- **Same pain, deeper:** deliverability/warm-up/reputation tooling, where "don't get flagged" is itself the product.
- **B2B-Microsoft moat:** anything that benefits from us already knowing publisher verification + M365 org realities (a real barrier most indie builders never clear).

*When you brainstorm: for each idea, name which §2 assets it reuses and which §5 scars it sidesteps. Favor ideas that reuse the most know-how and inherit the fewest new unknowns.*
