# In-App Announcements — Design

> **Date:** 2026-06-02
> **Status:** Approved (brainstorming)
> **Next:** writing-plans → implementation plan
> **Version:** v0.1.12 (extension UI), backend migration 020 + new router

## Problem

OutMass needs a reliable channel to reach its (small, early) user base:

- Support / outreach **emails land in spam** (e.g. the Abdul gift outreach — we couldn't even confirm it was seen).
- We have **no way to announce beneficial changes** in-product (raised limits, gifts, new features).
- We have **no "what's new" channel** on releases. Note: store extensions **auto-update silently** — users never "install" a new version, so a "please update" prompt is wrong. The post-update *reload* hint already exists (`extUpdatedReload` in `sidebar.js`). What's missing is a **release-notes** message.

So: build a **one-way, in-app announcement channel** the owner controls, visible inside the extension.

## Decision

A server-driven announcement system, reusing the existing "server flag → UI" pattern (`requires_reauth` → sidebar banner is the precedent).

**Scope (locked during brainstorming):**
- **One-way** (owner → users). No reply/inbox. (A "Contact us" mailto link can live in a message CTA if ever needed.)
- **Both broadcast and targeted** audiences.
- **Surfaces:** sidebar bell (primary) + high-priority top strip + popup card (under Manage Subscription — the originally-requested spot).
- **Authoring:** direct **SQL insert** (MVP — like the manual gift grant). No admin UI.
- **Server-side read tracking** — the whole point is delivery visibility ("did the user see it?").

**Key clarification:** an announcement *displays a message*; it does **not** grant anything. "We gave you bonus credits" is informational text only — the actual credit/plan change stays a separate manual `users`-table operation. Announcement = communication; gift = separate.

## Data Model (migration 020 — additive, reversible)

### `announcements` — the messages we author
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | `gen_random_uuid()` |
| `audience` | text | `'broadcast'` (all) \| `'targeted'` (one user) |
| `user_id` | uuid | set when targeted; null when broadcast; FK users on delete cascade |
| `priority` | text | `'normal'` (bell only) \| `'high'` (bell + top strip) |
| `title` | text | |
| `body` | text | |
| `cta_label` | text | optional button label |
| `cta_url` | text | optional button URL (https-validated) |
| `version` | text | optional; release notes. If set, client shows **only when** `manifest.version >= version` |
| `starts_at` | timestamptz | default now() |
| `expires_at` | timestamptz | optional; null = no expiry |
| `active` | boolean | default true |
| `created_at` | timestamptz | default now() |

### `announcement_reads` — per-user delivery state
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `announcement_id` | uuid | FK announcements on delete cascade |
| `user_id` | uuid | FK users on delete cascade |
| `read_at` | timestamptz | set when bell panel / popup message viewed |
| `dismissed_at` | timestamptz | set when × clicked |
| | | `unique(announcement_id, user_id)` |

Answers "did Abdul see it?" via `read_at`.

### "Release / new version" — no separate type
A release note is just **`broadcast` + `priority:'high'` + `version` set**. The optional `version` field makes the client show it only once the running extension actually reaches that version (`semver(manifest.version) >= version`) — so "what's new in 0.1.12" appears exactly when the user is on 0.1.12, not while still auto-updating from 0.1.11. One client-side compare; no server version logic.

## API (new router `routers/announcements.py`)

| Endpoint | Behavior |
|---|---|
| `GET /announcements` | Visible to current user: (`broadcast` OR (`targeted` AND user_id=me)) AND `active` AND within `starts_at..expires_at` AND not dismissed. Each carries `read`/`dismissed`. Sort: priority desc, created_at desc. |
| `POST /announcements/{id}/read` | upsert `announcement_reads`, set `read_at=now()` |
| `POST /announcements/{id}/dismiss` | upsert, set `dismissed_at=now()` (and `read_at` if null) |

Both ack endpoints idempotent (unique constraint → upsert).

### Badge + banner signal piggybacks `GET /settings`
The extension already polls `GET /settings`. Add a compact summary there (no new poll timer):
```json
"announcements_summary": {
  "unread": 2,
  "banner": { "id": "...", "priority": "high", "title": "...",
              "cta_label": "...", "cta_url": "...", "version": null } | null
}
```
- `unread` → bell badge (cheap count).
- `banner` → highest-priority unread `high` message → renders the top strip without a second request.
- Full list fetched **only** when the user opens the bell / popup (`GET /announcements`).

## Extension UI (v0.1.12)

### A) Sidebar bell (primary)
- Add bell + badge to `sidebar-header` (`header-left`, next to `conn-dot`). Badge = unread count; hidden at 0.
- Click → toggle `#announcements-panel` below header: list of non-dismissed messages. Opening marks visible messages `read` → badge clears. Read-but-not-dismissed stay listed (re-readable).
- Each card: title · body · optional CTA button · × (dismiss).

### B) High-priority top strip (gift, release)
- When an unread `priority:'high'` message exists (from settings `banner`), render a strip in the existing `reauth-banner` style: e.g. `🎁 A gift for you — View   ×`.
- "View" opens the bell panel (marks read). × dismisses.
- **Banner precedence (only one at a time):** reauth > offline > announcement. reauth is most critical.

### C) Popup card (originally-requested spot)
- In `connected-section`, after `#btn-manage-sub`, add `#popup-announcements`.
- On open: `GET_ANNOUNCEMENTS`. If unread exists, show the latest message inline (title + short body + CTA + ×). If more, "+N more — open panel" → opens sidebar + bell. Showing marks `read`.

### D) background.js
New message handlers `GET_ANNOUNCEMENTS`, `ANNOUNCEMENT_READ`, `ANNOUNCEMENT_DISMISS` → proxy to backend with JWT (existing `apiFetch` pattern). Popup + content script both route through background.

## Read / Dismiss Semantics
| Action | Trigger | Effect |
|---|---|---|
| **read** | bell panel or popup message viewed | `read_at` set; drops from badge; stays in list/strip |
| **dismiss** | × clicked | `dismissed_at` set; removed entirely for that user |

Badge = unread & not-dismissed count.

## i18n
- **UI chrome** ("Notifications" tooltip, "View", "Dismiss", "N new", "+N more") → new keys across all 10 `_locales`.
- **Message content** (title/body — authored by us via SQL) → **single language, shown verbatim** (no translation). MVP authored in English. Per-locale content is a future enhancement (YAGNI).

## Authoring (SQL templates — MVP)
```sql
-- Broadcast (normal)
insert into announcements (audience, priority, title, body, cta_label, cta_url)
values ('broadcast','normal','New: OneDrive attachments',
        'Attach large files via OneDrive links.','Learn more','https://getoutmass.com/blog/...');

-- Targeted gift (high → strip). Real credits granted separately.
insert into announcements (audience, user_id, priority, title, body)
values ('targeted', (select id from users where email='abdul@example.com'),
        'high','A gift for you 🎁','We added bonus credits to your account. Enjoy!');

-- Release note (high, version-tagged → only users on >= 0.1.12)
insert into announcements (audience, priority, title, body, version)
values ('broadcast','high','OutMass v0.1.12 is live',
        'In-app notifications, faster CSV preview, and bug fixes.','0.1.12');

-- Delivery check
select u.email, r.read_at, r.dismissed_at
from announcement_reads r join users u on u.id=r.user_id
where r.announcement_id = '<id>';
```

## Testing
- **Backend (pytest, FakeSupabase):** visibility rules (broadcast to all; targeted only to owner; inactive/expired excluded; dismissed not counted unread); read/dismiss idempotent upsert; `/settings` summary count + correct `banner`.
- **Frontend (manual):** bell badge, panel open→read, ×→dismiss, popup card, high strip, `version` filter hides on older running version.
- **E2E:** header gains a bell → refresh visual baseline if needed.

## User Impact & Rollout (CLAUDE.md)
- **Migration 020:** additive, reversible (down = drop the two tables). No existing data touched.
- **3 endpoints + settings field:** additive — old clients ignore the new field; no breakage.
- **Extension v0.1.12:** new bell + popup card. New visible UI but non-intrusive → this is exactly why it was designed + approved.
- **Backward compat:** old extension versions never call the new endpoint → simply show nothing, never break.
- **RLS:** `announcement_reads` user-scoped; `announcements` read via backend (service key), same pattern as existing tables.
- **First real announcement:** the v0.1.12 release note itself (dogfood).

## Out of Scope (YAGNI)
Two-way reply/inbox · admin HTML panel · per-locale message content · scheduled/auto-generated release notes · `last_seen_extension_version`-based server targeting (client-side `version` compare is enough).
