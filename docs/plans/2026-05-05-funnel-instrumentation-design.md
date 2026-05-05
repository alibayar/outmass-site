# Funnel Instrumentation — Design

> **Date:** 2026-05-05
> **Status:** Approved (brainstorming session)
> **Next:** writing-plans skill → implementation plan

## Problem

Chrome Web Store dashboard shows ~31 installs in the first month, but only **2 backend users** (the developer + 1 unknown) and **0 emails sent by anyone except the developer**. The install→signup ratio is ~3% and the signup→activation ratio is ~0%.

Current PostHog usage is **error-only** — no funnel events exist anywhere in the extension or backend. We cannot tell where users drop off:

```
Install → ??? → ??? → ??? → Backend user (1)
                                    ↓
                                 First mail (0)
```

Adding new install channels (Edge store, viral footer, free tier 50→100) is **wasteful before we understand the leak**. Any traffic we drive will hit the same broken funnel.

## Goal

Instrument the install→signup→first-mail funnel with anonymous behavioral telemetry so we can:
1. Identify the dropoff step (install→sidebar, sidebar→signin click, signin→OAuth complete, OAuth→first mail)
2. Measure the impact of upcoming UX fixes
3. Track which extension version each user is on (for staleness emails, paid-user version distribution)

## Non-Goals

- Backend funnel events (audit_log already covers this; querying SQL is fine)
- A/B testing framework
- Performance / load timing telemetry
- Telemetry opt-out toggle (YAGNI for MVP — privacy policy already covers anonymous PostHog use)
- Replacing the existing `audit_log` system

## Approach

### 1. Identity model

| State | Distinct ID |
|---|---|
| Signed-out (just installed) | Random UUID stored in `chrome.storage.local` |
| Signed-in | Backend `user_id` — aliased on signin via `posthog.alias` so pre-signin events attach to the same person |

This way an install at T+0 and a signin at T+3 days are joined in PostHog as one user journey.

### 2. Transport (MV3-compatible)

- **No `posthog-js` package** — bundling adds friction in MV3 and the JS lib is overkill for ~12 events.
- **Direct REST**: `POST https://us.i.posthog.com/capture/` from the background service worker.
- **One file**: `extension/analytics.js` exporting `track(event, properties)`.
- **Background queue**: events are buffered in-memory; flushed every N seconds or on `chrome.runtime.onSuspend`. Survives service worker restart via `chrome.storage.local`.
- **Manifest**: add `https://us.i.posthog.com/*` to `host_permissions`.

### 3. Default properties (auto-attached to every event)

- `extension_version` — `chrome.runtime.getManifest().version`
- `browser` — `Chrome` / `Edge` / `Brave` (UA detect)
- `os` — `chrome.runtime.getPlatformInfo().os` (`win` / `mac` / `linux` / `cros` / `android`)
- `locale` — `chrome.i18n.getUILanguage()`

### 4. Event list (MVP)

| # | Event | Trigger | Key properties |
|---|---|---|---|
| 1 | `ext_installed` | `chrome.runtime.onInstalled`, reason=install | `version` |
| 2 | `ext_updated` | `chrome.runtime.onInstalled`, reason=update | `from_version`, `to_version` |
| 3 | `sidebar_opened` | Sidebar becomes visible in Outlook Web | — |
| 4 | `signin_clicked` | "Sign in with Microsoft" button | — |
| 5 | `oauth_started` | `chrome.identity.launchWebAuthFlow` invoked | — |
| 6 | `oauth_completed` | Token returned successfully | — |
| 7 | `oauth_failed` | OAuth flow failed | `reason` (cancelled/network/error) |
| 8 | `compose_view_seen` | Campaign compose UI first rendered | — |
| 9 | `recipients_uploaded` | CSV uploaded | `recipient_count` |
| 10 | `send_clicked` | "Send All" button clicked | `recipient_count` |
| 11 | `send_completed` | Backend returned success | `recipient_count` |
| 12 | `send_failed` | Backend returned error | `error_code` |

### 5. Backend version tracking

Migration **018** adds:

```sql
ALTER TABLE users ADD COLUMN last_seen_extension_version TEXT;
```

- Nullable, reversible (`DROP COLUMN` rollback)
- Extension sends `X-Extension-Version` header on every authenticated API call
- Backend `get_current_user` updates this column when version differs (rate-limited along with existing `last_activity_at` 15-min throttle)
- Bonus future use: stale-version nudge emails to paid users

### 6. Privacy

- No PII in event properties
- Privacy policy gets one-line update: explicit mention of "anonymous usage telemetry (events: install, signin, send, etc.)" alongside the existing PostHog error-tracking disclosure
- 10-locale i18n update for privacy.html localized versions if applicable (check existing structure)

### 7. Out of scope (deferred)

- Backend-emitted PostHog events (we have `audit_log`)
- Event opt-out toggle in Settings
- Page-load / render-time perf metrics
- A/B test event framework

## Validation Plan

After deploy:

1. **Day 0 (deploy day)**: Self-test — install fresh, walk through signin + send. Verify all 12 events show in PostHog Live view with correct distinct_id, version, browser, locale.
2. **Day 1**: Confirm at least 1 organic event arrives.
3. **Day 7**: Pull funnel report. Identify largest dropoff step.
4. **Day 7+**: Fix top dropoff. Re-measure after a week.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| PostHog free-tier event quota | 12 events × ~30 installs/mo + retries = ~500 events/mo, well under 1M free quota |
| Background SW killed mid-flush, events lost | `chrome.storage.local` persistent queue, flush on next wake |
| User in airplane mode | Queue retains until network restored; capped at 100 events to avoid runaway growth |
| Distinct ID collision | UUID v4 — collision probability negligible at our scale |
| Extension version inflation if we deploy often | `last_seen_extension_version` is plain text; no constraint, easy to query for distribution |

## Versioning

This ships as **v0.1.9** — minor bump.

- No user-visible behavior change (telemetry is invisible to user)
- Privacy policy link in extension footer remains; user can read updated policy if curious
- No store-listing notes update needed (no new feature for end-user)

## Effort

- Code: ~2–3 hours
- Manual self-test: ~30 min
- Privacy policy update + commit: ~15 min
- **Total: half a day**
