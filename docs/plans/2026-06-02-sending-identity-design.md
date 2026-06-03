# Sending Identity Indicator — Design

> **Date:** 2026-06-02
> **Status:** Approved (brainstorming)
> **Next:** implement directly (small, extension-only) — folded into v0.1.12 (not yet published)

## Problem

OutMass authenticates with its **own** Microsoft OAuth session (e.g. `outmassapp@outlook.com`). That identity is **independent of the Outlook account currently displayed in the browser** (e.g. `bayar_ali@hotmail.com`). A user can therefore:

- Send a campaign from a different account than the one they think they're using.
- Be confused about whose quota / announcements they see.

This surfaced in QA: OutMass was signed in as `outmassapp@outlook.com` while the browser showed `bayar_ali@hotmail.com`, and the bell "didn't appear" simply because OutMass was operating as a different (already-dismissed) user.

We do **not** promise that OutMass tracks the displayed Outlook account — the separate sign-in is intentional. So the fix is not to synchronize them, but to make the **sending identity obvious at the moment it matters: sending.**

## Decision

Show a small, always-visible **"Sending as: \<email\>"** line directly above the Send button, with a quick **"Change"** link to re-authenticate. No detection of the displayed Outlook account (that would require fragile DOM scraping and was explicitly dropped as out of scope).

### Why this approach
- **Robust & exact:** the OutMass account is known with 100% certainty (`chrome.storage.local.user.email`, set at login). No fragile DOM reading, no false positives.
- **Right moment:** appears in the campaign/send area, seen every time before clicking Send — zero extra clicks, no nagging dialog.
- **Recoverable:** "Change" lets the user switch the sending account on the spot.

### Rejected alternatives
- **Mismatch detection + warning** (read the displayed Outlook account from the DOM, compare, warn): fragile (Outlook UI changes break it), false-positive/negative risk. Out of scope — we don't promise sync.
- **Send-time confirmation dialog:** stronger but adds friction on every send; there are already conditional confirms. The persistent line is enough.

## UI

A muted line inserted just above `.form-actions` (which holds Preview / Test Send / Send) in the Campaign tab of `sidebar.html`:

```
✉️ Sending as: outmassapp@outlook.com · Change
```

- Muted styling (`#605e5c`, ~12px), non-intrusive.
- `Change` is a link/button that triggers re-auth.

## Data Flow

- **Source:** `chrome.storage.local.get("user")` → `user.email`. The background already stores `user` on login (used by the popup's `GET_USER_STATE`) and clears it on logout. Instantly available — no `/settings` round-trip.
- **Render on init:** read `user` and populate the line.
- **Refresh on change:** a `chrome.storage.onChanged` listener on `user` (local) re-renders the line, so an account switch / re-auth reflects immediately. (A `backendJwt` watcher already exists for announcements; add `user` handling alongside or a small dedicated one.)
- **Change link:** `chrome.runtime.sendMessage({ type: "MS_LOGIN" })`. On success the background stores the new `user` → the onChanged listener re-renders the line; also refresh quota/settings/announcements so the whole sidebar reflects the new account.

## Edge Cases

- **Not signed in / no email:** hide the line entirely (the Send button is disabled until ready anyway).
- **Re-auth cancelled/failed:** leave the existing line unchanged.

## i18n

Two new keys across all 10 `_locales`:
- `sendingAsLabel` → "Sending as:"
- `sendingAsChange` → "Change"

The email is dynamic and not translated.

## Scope / Impact (CLAUDE.md)

- **Extension-only, additive UI.** No backend, no API contract change, no migration, no tests to add (manual QA + `node --check`).
- **Folded into v0.1.12** (not yet published to the Web Store) — no separate version bump; add one CHANGELOG bullet to the existing 0.1.12 entry.
- **Backward compatible:** purely additive display; nothing removed or changed in the send flow itself.

## Testing

- Manual QA: line shows the correct OutMass email above Send; "Change" triggers re-auth and the line updates to the new account; signing out hides the line.
- `node --check extension/sidebar.js`.

## Out of Scope (YAGNI)

Displayed-Outlook-account detection, mismatch warnings, send-time confirmation dialog, any backend change.
