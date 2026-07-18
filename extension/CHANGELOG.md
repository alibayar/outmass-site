# OutMass Changelog

All notable user-facing changes to the OutMass Chrome Extension.

## Unreleased (0.1.26)

- **Your CSV columns now appear as clickable tag chips under the editor.** Upload a CSV and every column shows up as a {{tag}} you can click to insert at the cursor — no more typing a tag from memory and finding out at Send time that your file has no such column.
- **Stay signed in while you're active.** Your OutMass session now renews itself in the background as you use it. Previously it quietly expired every 24 hours, and the first Send of the day could fail with a sign-in prompt. (Signing in again after a long break is still required — that part is a security feature.)
- **No more repeated sign-in windows when adding a OneDrive attachment.** If OneDrive access couldn't be enabled, the picker used to open the Microsoft sign-in window again and again. Now it asks at most once per attempt and then explains what's going on (e.g. your Microsoft account may not include OneDrive) and how to proceed. The underlying authorization bug was fixed on our servers, so for most people OneDrive attachments simply work now — no extension update needed.
- Clearer wording on the Microsoft-permissions notice about what OutMass stores: OutMass never reads your other emails, and your campaigns are stored securely to power scheduling and follow-ups.

### Behind the scenes (backend — affects all extension versions)

- **Follow-ups now skip anyone who has replied.** If a recipient answers your campaign, scheduled follow-ups ("didn't open" / "didn't click") will no longer be sent to them. Nobody gets an automated bump mid-conversation.

## v0.1.25 — 2026-07-15

- **NEW: Daily send limit — spread one campaign over multiple days.** In the Schedule section, set an optional "Daily send limit" (e.g. 30): OutMass sends up to that many emails per day, server-side, and automatically continues the next day until your whole list is done. Great for careful cold outreach and gradual warm-up. (Not combinable with A/B testing in this first version. Requires Starter or Pro, like scheduled sending.)
- **The panel now tells you when you haven't signed in yet.** Previously you could build an entire campaign without an account and only hit a cryptic English error at Send. Now a sign-in banner appears at the top of the panel from the start, and Send/Test explain in your own language that sending needs a Microsoft sign-in first (composing still works without one).
- **New-install welcome page.** Right after installing, OutMass opens a short "your first campaign in 3 steps" page — where to find the panel in Outlook, how to sign in, and how to send — instead of leaving you to guess.
- **OutMass now talks to its servers via our own domain (api.getoutmass.com), with the old address kept as an automatic fallback.** Some corporate and national networks block shared hosting domains outright — on those networks OutMass could never connect (or even sign in). Whichever address works on your network is used automatically. Because this adds a new permission, **Chrome/Edge may ask you to re-approve the extension with one click** — that's expected; scheduled sends and follow-ups run on our servers and are never interrupted.

## v0.1.24 — 2026-07-14

- **CSV files from Excel now work in more encodings.** Excel's default "CSV" save on Chinese (and some other) systems isn't UTF-8, which OutMass used to reject outright. OutMass now auto-detects and reads GBK/GB18030 and Big5 files too — and when a file truly can't be read, the error finally tells you the exact fix: save it as "CSV UTF-8 (Comma delimited)" in Excel. (All 11 languages.)
- **Honest message when OutMass can't reach its servers.** If your network, VPN or firewall blocks the connection, sending used to fail with a generic error that looked like an account or plan problem. You now get a clear "this is a connection issue — not your plan" message, and the panel shows a banner as soon as it detects the servers are unreachable (it re-checks and disappears by itself once the connection is back).
- Requests that can't get through now stop after 20 seconds instead of hanging, and failures are reported with their real cause so we can help faster if you contact support.

## v0.1.23 — 2026-07-08

- OutMass now works on Microsoft's **new Outlook web address** (outlook.cloud.microsoft). Microsoft has started moving business accounts there automatically — on moved accounts the OutMass panel and the corner button never appeared, and "Open Campaign Panel" just opened a plain Outlook window. Both now work on the new address.
- Because this update teaches OutMass about the new address, **Chrome/Edge may ask you to re-approve the extension with one click** ("New permissions required"). That's expected — one click and you're back. Scheduled sends and follow-ups run on our servers and are never interrupted.
- "Open Campaign Panel" is now more patient: when it opens a fresh Outlook tab, it keeps trying until the panel is actually ready (slow loads and Outlook's sign-in redirects no longer swallow it).

## v0.1.22 — 2026-07-02

- No more silent partial sends at your quota limit. If your campaign has more recipients than your remaining monthly allowance, OutMass now tells you exactly how many were sent and how many are waiting (e.g. "47 sent, 53 pending") — the rest stay saved, and Resume sends them after an upgrade or your monthly reset. Previously the send quietly stopped at the limit and looked like everything went out.

### Behind the scenes (backend — affects all extension versions)

- The "monthly limit reached" message is now in English (it was accidentally shown in Turkish for everyone).

## v0.1.21 — 2026-06-26

- Smoother first sign-in. The sign-in screen now explains up front why Microsoft asks for mail permissions — OutMass sends from your own Outlook account and never stores your email content — so the Microsoft consent prompt isn't a surprise. (Localized in all 11 languages.)
- Chinese-language users now see the Chinese interface on every variant (Traditional, Hong Kong, Singapore, generic zh), not only Simplified-China — previously those locales fell back to English.
- internal: suppressed a harmless "Could not establish connection. Receiving end does not exist." console error that could appear when opening the campaign panel before an Outlook tab's content script had loaded. No user-visible change. (The v0.1.20 sign-in fixes are unchanged and already live.)

## v0.1.20 — 2026-06-25

- Fixed a sign-in loop that hit Microsoft 365 **work & school accounts**. The "Open Campaign Panel" button now opens *your* Outlook — work accounts land on outlook.office.com, personal accounts on outlook.live.com — instead of always opening the personal host, which bounced work users to a Microsoft sign-in page that looked like an endless login loop.
- Hardened the session: a routine background refresh (when you open the popup) can no longer sign you out on a transient hiccup. Only deliberate sign-out or a real expiry ends your session now.

## v0.1.19 — 2026-06-25

- Smoother sign-in. Clicking "Sign in" (or the reconnect banner) several times in a row no longer opens multiple Microsoft sign-in windows at once — OutMass now reuses the one already in progress. This also clears the stray "didn't approve access" errors that came from closing the extra windows.

## v0.1.18 — 2026-06-25

- Large sends now stay within Outlook's limits automatically. OutMass paces every send (~30 emails/min) so it no longer trips Microsoft's rate limit — and before a big send (500+ recipients) you'll see a heads-up with the estimated time and a reminder that very large cold lists deliver best when spread over several days.
- Clearer feedback confirmation. After you send a message from the Support tab, OutMass now confirms we received it and will reply to your email — instead of a bare "submitted".

### Behind the scenes (backend — affects all extension versions)

- Re-mailing your own list is no longer blocked by a failed send. Cross-campaign de-duplication now only skips recipients who were actually delivered to (or are still queued in a live campaign) — recipients left un-sent by a failed or partial campaign are no longer treated as "already contacted".
- Unsubscribe and open/click links with a truncated or garbled ID (e.g. from some email security scanners) now return a clean page instead of a server error.
- Less noise in our error tracking from harmless browser-internal warnings, so real issues surface faster.

## v0.1.17 — 2026-06-24

- More reliable sign-in. If the Microsoft authorization page occasionally failed to load on the first try (a brief server hiccup), OutMass now wakes the backend and retries once instead of erroring out. (Consent prompts you decline are never retried.)
- Accurate monthly quota. The usage bar and the pre-send check now read your real sent-this-month count from the server, so you're warned about your remaining quota up front instead of only hitting a limit error after building a whole campaign.
- Clearer "limit reached" prompt. The upgrade dialog now shows exactly how much of your plan you've used (e.g. "250 / 250") instead of a numberless wall.
- Smoother recovery if your sign-in expires while composing. Sending now shows the one-click reconnect banner (and keeps your work) instead of a raw error, and won't leave a half-created campaign behind.
- Easier to reopen OutMass. A small floating OutMass button now sits in the corner of Outlook so you can open the sidebar anytime, without going through the menu.
- Clearer CSV import. Rows with no email address are now counted and shown (like duplicates are), and the "missing email column" error points you to the example file.
- Fixed a rare glitch where a stray "session expired" banner could appear right after you deliberately signed out.

### Behind the scenes (backend — affects all extension versions)

- Scheduled and A/B campaigns no longer silently drop recipients on a send hiccup — failures are recorded and the campaign is marked "partial" so **Resume** can finish it. A single malformed record can no longer freeze A/B winner evaluation for everyone.
- Over-quota scheduled campaigns now wait and retry after your monthly reset instead of being marked failed.
- A large send that outruns the ~1-hour Microsoft token now stops cleanly and becomes resumable (Resume refreshes the token and finishes the rest) instead of dropping the remainder.
- Fixed a reconnect-banner loop, and a case where a fully-failed follow-up was reported as sent.

## v0.1.16 — 2026-06-20

- Clearer sign-in errors. If your organization requires an administrator to approve new apps (common on Microsoft 365 work accounts), OutMass now explains what happened and how to proceed — contact support or use a personal Outlook.com account — instead of showing a generic failure.

## v0.1.15 — 2026-06-17

- Fixed the prices shown on the upgrade buttons and upgrade dialog. The "$" before a number was being swallowed by the translation system, so Starter showed no price and Pro showed "9/mo" instead of "$19/mo". Prices now display correctly in all languages.

## v0.1.14 — 2026-06-14

- internal: fixed product analytics region (events were being sent to the US PostHog endpoint while the project is in the EU, so all extension usage telemetry was silently dropped since launch). Now sends to the EU endpoint via CORS; removed the now-unused US host permission. No user-visible change.

## v0.1.13 — 2026-06-02

- Sending account is now shown above the Send button ("Sending as: …"), so you always know which OutMass account a campaign goes out from — with a quick Change link to switch.
- Polish: in-app notifications now refresh instantly when you switch accounts, and the notification panel closes cleanly once everything is read/dismissed.

## v0.1.12 — 2026-06-02

- In-app notifications: a new bell in the sidebar header shows announcements and updates, with a highlighted banner for important news (like a gift or a new release). A matching card appears in the extension popup under Manage Subscription. Read and dismiss right where you work — no need to check email.

## v0.1.11 — 2026-06-01

- Bigger free plan: 250 emails/month (was 50). Starter raised to 2,500/month. Upload limits raised to match. Enjoy the extra room!

## v0.1.10 — 2026-05-30

- Clearer, localized error messages when a merge tag doesn't match your CSV columns (e.g. {{firstName}} casing/spacing). Now tells you exactly which column to add or which tag to fix, in your language.
- More reliable Resume: failed recipients are now distinguished as temporary (retried on Resume) vs permanent (skipped), so a partial campaign finishes correctly.
- internal: auto-expiring manual plan promos.

## v0.1.9 — 2026-05-05

- internal: comprehensive anonymous funnel + engagement telemetry (PostHog) covering install, sign-in, compose, CSV upload (incl. failures), test send, real send, upgrade intent, onboarding, AI writer, templates, scheduling, follow-ups, attachments, exports, and more. Per-user extension version tracking. account_deleted is sent anonymously (identity reset first). No user-visible behavior change. Privacy policy covers this disclosure.

---

## v0.1.8 — 2026-04-29

### OneDrive picker error messages
- When the signed-in Microsoft account has no OneDrive (some old
  Outlook.com accounts and work accounts without an SPO license),
  the picker now shows a clear "this account doesn't have OneDrive"
  message in your interface language, instead of a generic "Could
  not load" error.
- Other failure cases now include the underlying error code in the
  picker status line so it's easier to triage if anything goes wrong.

---

## v0.1.7 — 2026-04-29

### OneDrive picker rebuilt
- The OneDrive file picker has been replaced with a native, in-sidebar
  file browser. Previously it embedded Microsoft's hosted picker via
  iframe — which Microsoft serves with `X-Frame-Options: DENY` for
  personal accounts, producing a blank "onedrive.live.com refused to
  connect" page.
- The new picker shows your OneDrive contents directly: folders first,
  files after, both alphabetical. Click a folder to navigate; breadcrumb
  links jump back. Click a file to attach it. No external iframe, no
  third-party page load — just a clean list inside OutMass.

---

## v0.1.6 — 2026-04-29

### Smarter engagement metrics
- New **Engaged** number on the Reports detail view: distinct
  recipients who opened, clicked, OR replied. More honest than raw
  open rate, especially given how Outlook and Apple Mail Privacy
  Protection distort pixel-based opens.
- New **Replied** number, populated by a daily Inbox scan that
  detects genuine replies to your campaigns. Strongest engagement
  signal we have — counts only real replies from your recipients.
- Inline hint under each metric explains why it exists and why open
  rate alone can mislead.

### Resilience for partially-failed sends
- **Resume sending** button: if a campaign ends in `partial` status
  (some recipients failed to receive due to a transient network or
  rate-limit issue), the Reports detail view now shows a Resume
  button that retries only the still-pending recipients.
- Behind the scenes, every Microsoft Graph send is wrapped in a
  bounded retry (3 attempts, exponential backoff) for HTTP 5xx and
  network errors — so most transient hiccups never reach you.
- Explicit per-phase HTTP timeouts mean a single slow Microsoft
  Graph response can't hang the worker queue indefinitely.
- A daily background sweep detects campaigns stuck in `sending`
  status (worker crashed mid-loop, etc.) and recovers them
  automatically — either to `partial` (if some recipients went out)
  or back to `scheduled` for a clean retry.

---

## v0.1.5 — 2026-04-26

### Attachments via OneDrive sharing links
- New **Attachments** section in the compose area (below the body
  field). Click **+ Add OneDrive link**, choose a file from your own
  OneDrive, and a sharing link is automatically created and added
  to the email.
- Recipients see a clean clickable chip (e.g. "📎 brochure.pdf") that
  opens the file in OneDrive. The file lives in your OneDrive — we
  never download, store, or read it.
- Inbox-friendly by design: links don't trigger spam filters the way
  raw attachments do, and you can update the file later without
  re-sending the email.
- First-time use shows a one-off consent dialog explaining the
  OneDrive permission. The OneDrive permission is optional — if you
  never use this feature, it's never requested.

---

## v0.1.4 — 2026-04-24

### User lifecycle & legal posture
- **Uninstall landing page.** When you remove the extension, Chrome opens
  a friendly page reminding you that any paid subscription is separate
  from the extension and helping you cancel it. Optional feedback form
  tells us why you left.
- **Delete my account** (Account tab → Danger Zone). Self-service
  permanent removal of your OutMass account and all data, with a typed
  DELETE confirmation + irreversibility checkbox. Active subscriptions
  must be cancelled first. A GDPR-compliant anonymised audit record is
  retained for legal and fraud-prevention purposes.

### Behind the scenes (backend, affects every extension version)
- **Immutable audit log.** Every authorization, campaign creation,
  recipient upload, send trigger, and per-email Graph API dispatch is
  recorded with timestamp, IP (anonymised after 12 months), and
  SHA-256 hashes of content. Evidence chain for disputes and chargeback
  defence. Does not store raw recipient addresses.
- **Inactivity follow-up**. Paid users who stop logging in get up to
  three warm, non-threatening reminder emails (30, 60, 90 days) that
  their subscription is still active. Default-off feature flag.
- **Chargeback handling**. A disputed charge automatically cancels the
  subscription and alerts the operator for evidence review.
- **Schema hardening.** FK CASCADE chain across campaigns/contacts/
  tokens/templates/events so a single account-delete transaction
  cleans up every dependent row atomically.

---

## v0.1.3 — 2026-04-21

### Sign-in & authorization
- **Session expired banner** — when your OutMass sign-in times out, a
  one-click reconnect banner appears instead of an opaque "Invalid token"
  modal blocking Settings save / send / AI / templates / exports.
- **Multi-extension OAuth support** — the backend now routes each sign-in
  to the calling extension's chromiumapp.org subdomain via the OAuth
  `state` parameter. Dev builds and the store build can now sign in
  against the same backend without env-var swaps.

### Localization
- **Scheduled-send time, reports dates, and alerts** now use your
  selected interface language. Previously the datetime preview silently
  fell back to your OS locale because the code passed the translations
  dict instead of a BCP-47 tag to `toLocaleString`. Four call sites
  fixed, all routed through a single `getActiveLocale()` helper.
- **Reports tab date column** no longer hardcoded to Turkish.
- **Campaign-name auto-date suffix** (used when you leave the campaign
  name blank) now reflects the selected language.

### Campaigns & email
- **Unsubscribe footer label** in sent emails now respects your
  Settings → Unsubscribe text override. Previously scheduled sends,
  follow-ups, and async-queued emails all hardcoded the Turkish
  default regardless of what you typed.

### UX polish
- **Manage Subscription button** in the sidebar Account tab now shows a
  clear backend error message on failure instead of silently doing
  nothing. Both sidebar and popup now append the backend error detail
  to the "Portal could not open" alert so you can distinguish config
  issues ("Stripe not configured") from account-state issues ("No Stripe
  customer found").

### Backend-only (affects all extension versions deployed against this backend)
- **Token lifecycle hardening.** Scheduled campaigns and follow-ups with
  a dead Microsoft refresh_token now transition to `status='failed_auth'`
  instead of silently looping forever. Users receive a MailerSend
  reconnect email on the first flag transition (not on every retry). A
  daily 03:00 UTC beat task proactively refreshes every connected
  user's token so dead refresh_tokens surface *before* the next
  scheduled send window, not after users miss it.

---

## v0.1.2 — prepared but not shipped

Packaged in the previous session, superseded by v0.1.3.

- **Reconnect-to-Outlook banner** when your Microsoft authorization has
  expired, so scheduled sends no longer fail silently.
- **Test Send** no longer creates placeholder campaigns in Reports.
- **Scheduled sending** shows a proper upgrade prompt when the feature
  is locked to your current plan.
- **i18n named-placeholder substitution** fixed for non-English locales
  (`$EMAIL$`, `$N$`, etc.).
- **Settings placeholder text** cleaned up — removed developer's
  personal data from the Sender Information sample values.
- **Localized datetime** in the scheduled-send success alert.

All of the above are also included in v0.1.3.

---

## v0.1.1 — 2026-04-21 (shipped to Chrome Web Store)

- 10-language store listing descriptions (TR, DE, FR, ES, RU, AR, HI,
  ZH_CN, JA, EN).
- Stateless Test Send (no placeholder campaign row).
- Misc UX polish.

## v0.1.0 — initial public release

First Chrome Web Store publication.
