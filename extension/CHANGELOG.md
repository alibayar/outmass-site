# OutMass Changelog

All notable user-facing changes to the OutMass Chrome Extension.

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
