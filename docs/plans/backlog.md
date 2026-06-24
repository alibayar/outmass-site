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

### ⬜ Cross-campaign dedup skips never-delivered recipients
`_fetch_previous_emails` (`backend/routers/campaigns.py` ~1204) returns **sent OR
pending** addresses; the upload dedup (~447) then skips them. Recipients left
`pending` by a FAILED/partial send (e.g. the 502 timeout) never received the email
but get skipped → the user is locked out of their own list. **Miriam hit exactly
this.** **Fix:** dedup should skip only actually-`sent` (delivered) contacts, not
`pending` from failed/partial campaigns. (Today's workaround: Settings → "Skip
Repeat Recipients" → off.)

### ⬜ Package + upload extension v0.1.18
The large-send warning is committed (manifest `0.1.18`). Backend pacing is already
live; the warning ships with the store upload. Build `outmass-0.1.18.zip` → upload
to Chrome (over 0.1.17) + Edge.

### ⬜ Confirm 0.1.17 on Edge
Chrome has 0.1.17. Edge: was it uploaded (cancel 0.1.15 → 0.1.17)? If not, 0.1.18
supersedes it.

---

## 🟡 P2 — flagged bugs / cleanup

### ⬜ Truncated unsubscribe IDs
PostHog `$exception` (backend): `/unsubscribe/NjhjYWRjMT…` — 10-char, non-UUID →
`invalid input syntax for type uuid`. Either the unsubscribe links are being
truncated, or email scanners hit partial URLs. Investigate URL generation vs.
harmless bot traffic; if bot traffic, return a clean 400 instead of throwing.

### ⬜ Filter benign $exception noise
363 `ResizeObserver loop completed…` events flooded error tracking
(`extension-client`). Filter ResizeObserver + known-benign messages in the
extension before POSTing to `/api/error-report` — protects the signal + PostHog
quota.

### ⬜ Feedback form confirmation
The in-app feedback form gives no clear "we got it — we'll reply to your email"
confirmation, so users feel unheard (Miriam: *"I can't even email support"*, yet
her feedback did arrive). Add a clear success state.

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

### ⬜ Separate the polluting game events
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
