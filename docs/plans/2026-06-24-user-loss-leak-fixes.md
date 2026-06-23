# User-Loss Leak Fixes — Tracking

**Source:** Multi-agent code audit (workflow `user-loss-leak-audit`, 2026-06-24) over the
auth, send/campaign, and onboarding/quota paths. 13 latent user-loss leaks found, each
verified against source by the audit's completeness critic. Findings here are **leads** —
each is re-verified against the actual source before its fix is applied.

**Branch:** `fix/user-loss-leaks`

**Process (per CLAUDE.md — live production):** verify against source → minimal,
backward-compatible fix → syntax/test → commit on branch → review → merge + deploy with a
plan. No push without explicit approval.

**Status legend:** ⬜ pending · 🔧 in progress · ✅ fixed (branch) · 🚫 dropped (not a real leak)

---

## Scorecard

| # | Severity | Leak | Location | Status |
|---|----------|------|----------|--------|
| 1 | 🔴 high | A/B winner send: failures swallowed, campaign force-marked `sent` (no Resume) | `workers/scheduled_worker.py:360-382` | ✅ |
| 2 | 🔴 high | One bad `created_at` aborts the entire A/B evaluation beat | `workers/scheduled_worker.py:301` | ✅ |
| 3 | 🔴 high | Scheduled campaign permanently `failed` on transient over-quota / user-read | `workers/scheduled_worker.py:50,80` | ✅ |
| 4 | 🔴 high | Quota bar + pre-send gate always read 0 sent → 402 ambush after campaign created | `extension/sidebar.js`, `extension/background.js:437` | ⬜ |
| 5 | 🔴 high | Reconnect banner infinite loop when reconnect returns no refresh_token | `routers/auth.py:303-343` | ✅ |
| 6 | 🔴 high | Send flow never calls `handleSessionExpired` → raw error + orphaned/duplicate campaign | `extension/sidebar.js:1047,1092,1217` | ⬜ |
| 7 | 🟠 med | Mid-batch Graph 401/403 marks recipients permanently `failed` (unresumable) | `routers/campaigns.py:667-693`, `utils/send_classify.py:17-23` | ✅ |
| 8 | 🟠 med | Long immediate sends reuse one ~1h token, dying mid-batch on large campaigns | `routers/campaigns.py:647-698` | ✅ |
| 9 | 🟠 med | Follow-up sends swallow all failures, force-mark follow-up `sent` | `workers/followup_worker.py:90-109` | ✅ |
| 10 | 🟠 med | Logout leaves stale `sessionExpired` flag → wrong "session expired" banner | `extension/background.js:365-374` | ⬜ |
| 11 | 🟠 med | Over-quota 402 shows generic upgrade modal, discards localized "used X of Y" | `extension/sidebar.js:1217-1227` | ⬜ |
| 12 | 🟠 med | No in-Outlook affordance to discover the sidebar; documented shortcut doesn't exist | `extension/content_script.js`, `extension/manifest.json` | ⬜ |
| 13 | 🟡 low | CSV rows with empty email silently dropped; no-email-column error doesn't point at template | `extension/sidebar.js:513-577` | ⬜ |

---

## Details

### 1 ✅ A/B winner send: failures swallowed, campaign force-marked `sent`
**Was:** the A/B remaining-contacts loop had no `else` on send failure and `except Exception: pass`,
then unconditionally set status `sent` → Resume (only on `partial`) never appeared, so most of a
Pro user's list silently never went out.
**Fix:** mirror the immediate-send loop — `mark_failed(_classify_failure(status))` on non-2xx,
`mark_failed('deferred')` on exception, collect `errors`, set final status `partial` if errors.

### 2 ✅ One bad `created_at` aborts the entire A/B evaluation beat
**Was:** `datetime.fromisoformat(created_at.replace('Z','+00:00'))` with no try/except inside the
per-row loop; one null/non-ISO row raised and aborted the whole beat → every awaiting A/B test froze.
**Fix:** defensive parse (try/except → unparseable treated as old-enough), matching `expire_manual_promos`.

### 3 ✅ Scheduled campaign permanently `failed` on transient over-quota / user-read
**Was:** over-quota (resets monthly) and a falsy user read both set status `failed` permanently, with
no retry (beat only picks `scheduled`) and no Resume (only `partial`).
**Fix:** keep the campaign `scheduled` (retries after the monthly reset / next beat) for both cases;
moved the quota check before the token refresh so over-quota campaigns don't burn a refresh each beat.

### 4 ⬜ Quota bar + pre-send gate always read 0 sent
`emailsSentThisMonth` is only ever written to storage as 0; `GET_USER_STATE` returns the real backend
count but never persists it → returning free user sees full quota, hits Send, gets a 402 after the
campaign/contacts were created. **Fix:** persist `emailsSentThisMonth`/`monthly_limit` in
`GET_USER_STATE`, or have `loadQuota` pull live `emails_sent_this_month` on init + after each send.

### 5 ⬜ Reconnect banner infinite loop
`requires_reauth` clear is nested inside `if refresh_token:`, so a silent/repeat consent (no
refresh_token) leaves the flag True → reconnect "succeeds", banner reappears, scheduled sends keep
no-op'ing. **Fix:** clear `requires_reauth`/`reauth_reason`/`reauth_flagged_at` + `touch_login` on any
successful callback; only overwrite the stored token when a refresh_token is present; add
`prompt=consent` on the reconnect path to force a refresh_token.

### 6 ⬜ Send flow never calls `handleSessionExpired`
The three send-flow error branches (CREATE/UPLOAD/SEND) are the only handlers that don't wrap in
`handleSessionExpired`; a 24h JWT expiring overnight → `alert('Send error: session_expired')`, no
reconnect banner, and a 401 on UPLOAD/SEND orphans a persisted campaign row (duplicate risk).
**Fix:** wrap each in `if (!handleSessionExpired(resp)) { showSendError(...) }` + re-enable btnSend.

### 7 ⬜ Mid-batch Graph 401/403 → permanent `failed`
Token pre-checked once but can die mid-batch; `_classify_failure` maps 401/403 to permanent `failed`,
`get_resumable_contacts` returns only pending+deferred → token blip burns the tail to `failed`, no
Resume. **Fix:** on 401/403 stop the batch, mark remaining `deferred`, `_mark_requires_reauth`,
return `requires_reauth`; reconsider 401/403-as-permanent.

### 8 ⬜ Long immediate sends reuse one ~1h token
`send_campaign` fetches one token and reuses it across up to `remaining` recipients with delay; the
~60-75min token can expire mid-batch on large campaigns → remainder 401s + (with #7) lost & unresumable.
**Fix:** refresh token periodically in the loop / move large immediate sends to the Celery queue; at
minimum break on 401 and mark remainder `deferred`.

### 9 ⬜ Follow-up sends swallow failures, force-mark `sent`
`except Exception: pass` then unconditional `update_followup_status('sent')` → a fully-failed follow-up
shows `sent`, recipients never get the bump Pro users pay for. **Fix:** count successes vs failures;
only mark `sent` if threshold met, else leave `scheduled` (re-enters next hour) or add partial/failed.

### 10 ⬜ Logout leaves stale `sessionExpired` flag
`msLogout` clears tokens but not `sessionExpired`; a deliberate sign-out then shows a wrong "session
expired — reconnect" banner. **Fix:** add `sessionExpired:false` (+ requiresReauth/plan/limit resets)
to the `msLogout` storage write.

### 11 ⬜ Over-quota 402 modal discards localized numbers
`proceedToSend` jumps to `showUpgradeModal()` and throws away the backend's structured localized
payload (`message`, `emails_sent`, `limit`) → unexplained paywall pop. **Fix:** read
`sendResp.detail.emails_sent/.limit` and show a quota-specific localized message in/before the modal.

### 12 ⬜ No in-Outlook sidebar affordance
`content_script` does no toolbar injection and `manifest` has no `commands`, so the shortcut its own
comment + CLAUDE.md reference cannot fire; a freshly-signed-in user sees nothing in Outlook.
**Fix:** add a minimal persistent in-page launcher (FAB) posting `SHOW_SIDEBAR`, or a real `commands`
entry, or auto-open the sidebar on OAuth success; at minimum fix the stale comment/CLAUDE.md.

### 13 ⬜ CSV empty-email rows silently dropped
Rows with blank email are dropped via `if (!em) continue;` with no count surfaced (unlike duplicates);
a column-shifted CRM export uploads "500 contacts" and proceeds with fewer. **Fix:** surface a
skipped-for-empty-email count like the duplicate count; point the no-email-column alert at the template.
