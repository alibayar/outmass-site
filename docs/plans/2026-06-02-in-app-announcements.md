# In-App Announcements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a one-way, owner-controlled in-app announcement channel (sidebar bell + high-priority strip + popup card) so we can reach users when email lands in spam, with server-side read tracking.

**Architecture:** Two new Supabase tables (`announcements`, `announcement_reads`) + a new FastAPI router (`routers/announcements.py`) exposing list/read/dismiss. Visibility + summary are computed **in Python** (the table is tiny) so they're unit-testable with the existing `FakeSupabase`. The badge/banner signal piggybacks the already-polled `GET /settings`. Extension v0.1.12 adds a bell in the sidebar header, a high-priority top strip (reusing the `reauth-banner` style), and a popup card under "Manage Subscription". SQL is the authoring interface (MVP — no admin UI).

**Tech Stack:** Python 3.11 / FastAPI / Supabase (PostgreSQL) backend; vanilla JS Chrome MV3 extension; pytest + FakeSupabase.

**Design doc:** `docs/plans/2026-06-02-in-app-announcements-design.md`

**Conventions:**
- All commits end with: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- Run backend tests from `backend/`: `python -m pytest`
- This is user-visible (new UI) — already designed + approved per CLAUDE.md.
- Work in a dedicated worktree; never touch the main checkout. Merge to master when green.

---

## Task 1: Migration 020 — announcements tables

**Files:**
- Create: `backend/migrations/020_announcements.sql`

**Step 1: Write the migration**

```sql
-- 020: in-app announcements (one-way owner -> user channel).
--
-- announcements      = the messages we author (broadcast or targeted).
-- announcement_reads = per-user read/dismiss state (delivery visibility).
--
-- Additive + reversible (down = DROP both tables). No existing data touched.

BEGIN;

CREATE TABLE IF NOT EXISTS announcements (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audience    TEXT NOT NULL CHECK (audience IN ('broadcast', 'targeted')),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,  -- set iff targeted
    priority    TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal', 'high')),
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    cta_label   TEXT,
    cta_url     TEXT,
    version     TEXT,                       -- release notes: client shows only when running version >= this
    starts_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- targeted rows MUST name a user; broadcast rows MUST NOT
    CONSTRAINT announcements_target_chk CHECK (
        (audience = 'targeted' AND user_id IS NOT NULL)
        OR (audience = 'broadcast' AND user_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_announcements_active ON announcements (active, starts_at);
CREATE INDEX IF NOT EXISTS idx_announcements_user ON announcements (user_id);

CREATE TABLE IF NOT EXISTS announcement_reads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    announcement_id UUID NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    read_at         TIMESTAMPTZ,
    dismissed_at    TIMESTAMPTZ,
    UNIQUE (announcement_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_announcement_reads_user ON announcement_reads (user_id);

COMMIT;

-- Down (manual):
--   DROP TABLE IF EXISTS announcement_reads;
--   DROP TABLE IF EXISTS announcements;

-- Verification:
--   SELECT * FROM announcements ORDER BY created_at DESC LIMIT 5;
```

**Step 2: Apply to prod** — the user runs this in Supabase SQL editor (DB migration → needs user; do NOT auto-apply). Confirm with the user before continuing, per CLAUDE.md.

**Step 3: Commit**

```bash
git add backend/migrations/020_announcements.sql
git commit -m "feat(db): migration 020 — announcements + announcement_reads tables"
```

---

## Task 2: Add `upsert` to the FakeSupabase test harness

The model uses Supabase `.upsert(...)`; `FakeQueryBuilder` doesn't support it yet. Add it so read/dismiss are testable.

**Files:**
- Modify: `backend/tests/conftest.py` (the `FakeQueryBuilder` class, near `insert`)

**Step 1: Write the failing test**

Create `backend/tests/test_announcements.py`:

```python
from tests.conftest import FakeQueryBuilder


def test_fake_upsert_sets_data():
    qb = FakeQueryBuilder()
    qb.upsert({"announcement_id": "a", "user_id": "u", "read_at": "now"})
    assert qb.execute().data == [{"announcement_id": "a", "user_id": "u", "read_at": "now"}]
```

**Step 2: Run — expect FAIL** (`AttributeError: 'FakeQueryBuilder' object has no attribute 'upsert'`)

Run: `python -m pytest tests/test_announcements.py::test_fake_upsert_sets_data -v`

**Step 3: Implement** — add to `FakeQueryBuilder` (mirror `insert`):

```python
    def upsert(self, rows, on_conflict=None, **kw):
        if isinstance(rows, list):
            self._data = rows
        else:
            self._data = [rows]
        return self
```

**Step 4: Run — expect PASS**

**Step 5: Commit**

```bash
git add backend/tests/conftest.py backend/tests/test_announcements.py
git commit -m "test: add upsert to FakeQueryBuilder for announcements"
```

---

## Task 3: `models/announcement.py` — data helpers + visibility logic

All filtering is **pure Python** (table is tiny) so it's unit-testable. The model fetches active rows + the user's reads, then merges.

**Files:**
- Create: `backend/models/announcement.py`
- Test: `backend/tests/test_announcements.py` (append)

**Step 1: Write failing tests** (append to `test_announcements.py`):

```python
from datetime import datetime, timezone, timedelta
from models import announcement as ann


def _row(**kw):
    base = {
        "id": "ann-1", "audience": "broadcast", "user_id": None,
        "priority": "normal", "title": "Hi", "body": "Body",
        "cta_label": None, "cta_url": None, "version": None,
        "starts_at": "2020-01-01T00:00:00Z", "expires_at": None,
        "active": True, "created_at": "2026-06-02T00:00:00Z",
    }
    base.update(kw)
    return base


def test_visible_includes_broadcast(fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([_row()]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    out = ann.get_user_announcements("user-X")
    assert len(out) == 1
    assert out[0]["read"] is False and out[0]["dismissed"] is False


def test_targeted_only_visible_to_owner(fake_db):
    rows = [_row(id="t1", audience="targeted", user_id="owner")]
    fake_db.set_table("announcements", FakeQueryBuilder(rows))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    assert ann.get_user_announcements("owner")  # owner sees it
    assert ann.get_user_announcements("someone-else") == []  # others don't


def test_dismissed_excluded(fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([_row()]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder(
        [{"announcement_id": "ann-1", "user_id": "u", "read_at": None,
          "dismissed_at": "2026-06-02T01:00:00Z"}]))
    assert ann.get_user_announcements("u") == []


def test_inactive_and_expired_excluded(fake_db):
    rows = [
        _row(id="inactive", active=False),
        _row(id="expired", expires_at="2020-02-01T00:00:00Z"),
        _row(id="future", starts_at="2999-01-01T00:00:00Z"),
    ]
    fake_db.set_table("announcements", FakeQueryBuilder(rows))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    assert ann.get_user_announcements("u") == []


def test_summary_counts_unread_and_picks_banner(fake_db):
    rows = [
        _row(id="n", priority="normal"),
        _row(id="h", priority="high", title="Gift"),
    ]
    fake_db.set_table("announcements", FakeQueryBuilder(rows))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    summary = ann.get_summary_for_user("u")
    assert summary["unread"] == 2
    assert summary["banner"]["id"] == "h"  # high priority chosen for the strip
```

**Step 2: Run — expect FAIL** (module/functions don't exist)

Run: `python -m pytest tests/test_announcements.py -v`

**Step 3: Implement `backend/models/announcement.py`:**

```python
"""
OutMass — Announcement model helpers.

In-app one-way announcements. Visibility, read/dismiss merging, and the
settings summary are computed in Python (the table is tiny) so the logic
is unit-testable with the fake Supabase client.
"""

from datetime import datetime, timezone

from database import get_db


def _parse_ts(value):
    """Parse an ISO timestamp (with optional trailing Z) to aware datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _now():
    return datetime.now(timezone.utc)


def _list_active() -> list[dict]:
    """All rows flagged active (date-window filtering happens in Python)."""
    result = (
        get_db()
        .table("announcements")
        .select("*")
        .eq("active", True)
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    return result.data or []


def _reads_for_user(user_id: str) -> dict:
    result = (
        get_db()
        .table("announcement_reads")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    out = {}
    for r in (result.data or []):
        out[r["announcement_id"]] = r
    return out


def _is_within_window(row: dict, now: datetime) -> bool:
    starts = _parse_ts(row.get("starts_at"))
    if starts and starts > now:
        return False
    expires = _parse_ts(row.get("expires_at"))
    if expires and expires <= now:
        return False
    return True


def _is_for_user(row: dict, user_id: str) -> bool:
    if row.get("audience") == "broadcast":
        return True
    return row.get("audience") == "targeted" and row.get("user_id") == user_id


def get_user_announcements(user_id: str) -> list[dict]:
    """Active, in-window, audience-matching, non-dismissed announcements
    with per-user read/dismissed flags. Sorted priority desc, created desc.

    NOTE: the `version` field is intentionally NOT filtered here — the
    client suppresses version-tagged items until its running version
    reaches that version (it has the manifest; the server doesn't)."""
    now = _now()
    reads = _reads_for_user(user_id)
    out = []
    for row in _list_active():
        if not _is_within_window(row, now):
            continue
        if not _is_for_user(row, user_id):
            continue
        rd = reads.get(row["id"], {})
        if rd.get("dismissed_at"):
            continue
        out.append({
            "id": row["id"],
            "audience": row["audience"],
            "priority": row.get("priority", "normal"),
            "title": row["title"],
            "body": row["body"],
            "cta_label": row.get("cta_label"),
            "cta_url": row.get("cta_url"),
            "version": row.get("version"),
            "created_at": row.get("created_at"),
            "read": bool(rd.get("read_at")),
            "dismissed": False,
        })
    out.sort(key=lambda a: (0 if a["priority"] == "high" else 1,
                            a.get("created_at") or ""),
             reverse=False)
    # priority high first, then newest first
    out.sort(key=lambda a: a.get("created_at") or "", reverse=True)
    out.sort(key=lambda a: 0 if a["priority"] == "high" else 1)
    return out


def get_summary_for_user(user_id: str) -> dict:
    """Compact signal for GET /settings: unread count + the single
    highest-priority unread item to render as the top strip."""
    items = get_user_announcements(user_id)
    unread = [a for a in items if not a["read"]]
    banner = None
    high_unread = [a for a in unread if a["priority"] == "high"]
    if high_unread:
        b = high_unread[0]
        banner = {
            "id": b["id"], "priority": b["priority"], "title": b["title"],
            "cta_label": b["cta_label"], "cta_url": b["cta_url"],
            "version": b["version"],
        }
    return {"unread": len(unread), "banner": banner}


def _exists(announcement_id: str, user_id: str) -> bool:
    """Visibility guard for read/dismiss — only rows the user can see."""
    for row in _list_active():
        if row["id"] == announcement_id and _is_for_user(row, user_id):
            return True
    return False


def mark_read(announcement_id: str, user_id: str) -> bool:
    if not _exists(announcement_id, user_id):
        return False
    get_db().table("announcement_reads").upsert(
        {"announcement_id": announcement_id, "user_id": user_id,
         "read_at": _now().isoformat()},
        on_conflict="announcement_id,user_id",
    ).execute()
    return True


def mark_dismissed(announcement_id: str, user_id: str) -> bool:
    if not _exists(announcement_id, user_id):
        return False
    get_db().table("announcement_reads").upsert(
        {"announcement_id": announcement_id, "user_id": user_id,
         "read_at": _now().isoformat(), "dismissed_at": _now().isoformat()},
        on_conflict="announcement_id,user_id",
    ).execute()
    return True
```

> **DRY note:** the double-sort in `get_user_announcements` is redundant — keep only the last two `.sort` calls (stable sort: newest-first, then high-priority-first). Remove the first `.sort`. (Left here so the test author notices; clean it up.)

**Step 4: Run — expect PASS** (all `test_announcements.py` tests)

Run: `python -m pytest tests/test_announcements.py -v`

**Step 5: Commit**

```bash
git add backend/models/announcement.py backend/tests/test_announcements.py
git commit -m "feat(announcements): model with visibility + read/dismiss logic"
```

---

## Task 4: `routers/announcements.py` + register + conftest patches

**Files:**
- Create: `backend/routers/announcements.py`
- Modify: `backend/main.py` (import + include_router)
- Modify: `backend/tests/conftest.py` (add `routers.announcements.get_db` and `models.announcement.get_db` to the `fake_db` patch list)
- Test: `backend/tests/test_announcements.py` (append endpoint tests)

**Step 1: Write failing endpoint tests** (append):

```python
def test_get_announcements_endpoint(client, auth_bypass, fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([_row()]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    resp = client.get("/announcements")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["announcements"][0]["title"] == "Hi"


def test_get_announcements_unauthorized(client):
    assert client.get("/announcements").status_code in (401, 422)


def test_mark_read_endpoint(client, auth_bypass, fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([_row()]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    resp = client.post("/announcements/ann-1/read")
    assert resp.status_code == 200
    assert resp.json()["status"] == "read"


def test_mark_read_unknown_returns_404(client, auth_bypass, fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    resp = client.post("/announcements/nope/read")
    assert resp.status_code == 404


def test_dismiss_endpoint(client, auth_bypass, fake_db):
    fake_db.set_table("announcements", FakeQueryBuilder([_row()]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    resp = client.post("/announcements/ann-1/dismiss")
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"
```

**Step 2: Run — expect FAIL** (404s / endpoint missing)

**Step 3: Implement `backend/routers/announcements.py`:**

```python
"""
OutMass — Announcements Router
GET  /announcements              → list announcements visible to the user
POST /announcements/{id}/read    → mark read
POST /announcements/{id}/dismiss → dismiss (hide permanently for this user)
"""

from fastapi import APIRouter, Depends, HTTPException

from models import announcement as ann
from routers.auth import get_current_user

router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("")
async def list_announcements(user: dict = Depends(get_current_user)):
    items = ann.get_user_announcements(user["id"])
    return {"announcements": items, "count": len(items)}


@router.post("/{announcement_id}/read")
async def mark_read(announcement_id: str, user: dict = Depends(get_current_user)):
    if not ann.mark_read(announcement_id, user["id"]):
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"status": "read"}


@router.post("/{announcement_id}/dismiss")
async def dismiss(announcement_id: str, user: dict = Depends(get_current_user)):
    if not ann.mark_dismissed(announcement_id, user["id"]):
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"status": "dismissed"}
```

**Step 4: Register in `backend/main.py`:**
- Add `announcements` to the routers import (line ~26):
  `from routers import account, ai, announcements, auth, billing, campaigns, launch, onedrive, settings, templates, tracking`
- Add after `app.include_router(onedrive.router)`:
  `app.include_router(announcements.router)`

**Step 5: Add conftest patches** — in `fake_db` fixture patch list (`backend/tests/conftest.py`):
```python
        patch("routers.announcements.get_db", return_value=db, create=True),
        patch("models.announcement.get_db", return_value=db),
```

**Step 6: Run — expect PASS**

Run: `python -m pytest tests/test_announcements.py -v`

**Step 7: Commit**

```bash
git add backend/routers/announcements.py backend/main.py backend/tests/conftest.py backend/tests/test_announcements.py
git commit -m "feat(announcements): list/read/dismiss endpoints"
```

---

## Task 5: Add `announcements_summary` to `GET /settings`

**Files:**
- Modify: `backend/routers/settings.py` (import + add field to `get_settings` return)
- Test: `backend/tests/test_settings.py` (append)

**Step 1: Write failing test** (append to `test_settings.py`):

```python
def test_settings_includes_announcements_summary(client, auth_bypass, fake_db):
    from tests.conftest import FakeQueryBuilder
    fake_db.set_table("announcements", FakeQueryBuilder([{
        "id": "h", "audience": "broadcast", "user_id": None, "priority": "high",
        "title": "Gift", "body": "b", "cta_label": None, "cta_url": None,
        "version": None, "starts_at": "2020-01-01T00:00:00Z", "expires_at": None,
        "active": True, "created_at": "2026-06-02T00:00:00Z",
    }]))
    fake_db.set_table("announcement_reads", FakeQueryBuilder([]))
    data = client.get("/settings").json()
    assert data["announcements_summary"]["unread"] == 1
    assert data["announcements_summary"]["banner"]["id"] == "h"
```

**Step 2: Run — expect FAIL** (`KeyError: 'announcements_summary'`)

**Step 3: Implement** — in `settings.py`:
- Import at top: `from models import announcement as ann`
- In `get_settings`, add to the returned dict:
```python
        "announcements_summary": ann.get_summary_for_user(user["id"]),
```

**Step 4: Run — expect PASS** (and the whole suite: `python -m pytest`)

**Step 5: Commit**

```bash
git add backend/routers/settings.py backend/tests/test_settings.py
git commit -m "feat(settings): expose announcements_summary (badge + banner signal)"
```

---

## Task 6: background.js message handlers

**Files:**
- Modify: `extension/background.js` (add 3 cases near `GET_SETTINGS`, ~line 573)

**Step 1: Add handlers** (mirror the `GET_SETTINGS`/`DELETE_TEMPLATE` pattern):

```javascript
    case "GET_ANNOUNCEMENTS":
      backendFetch("/announcements").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ANNOUNCEMENT_READ":
      backendFetch("/announcements/" + message.id + "/read", {
        method: "POST",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ANNOUNCEMENT_DISMISS":
      backendFetch("/announcements/" + message.id + "/dismiss", {
        method: "POST",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;
```

**Step 2: Verify** — `chrome://extensions` → reload unpacked → no service-worker console errors.

**Step 3: Commit**

```bash
git add extension/background.js
git commit -m "feat(ext): background handlers for announcements"
```

---

## Task 7: i18n keys (10 locales)

**Files:**
- Modify: `extension/_locales/{en,tr,de,fr,es,ru,ar,hi,zh_CN,ja}/messages.json`

**Step 1: Add keys** (English shown; translate per locale, keep ICU-free plain text). Use `$COUNT$` placeholder where noted.

```json
  "announcementsTitle": { "message": "Notifications" },
  "announcementsEmpty": { "message": "No notifications" },
  "announcementsView": { "message": "View" },
  "announcementsDismiss": { "message": "Dismiss" },
  "announcementsMore": {
    "message": "+$COUNT$ more — open panel",
    "placeholders": { "count": { "content": "$1" } }
  }
```

For the `$COUNT$` placeholder key, in JS call: `t("announcementsMore", [String(n)])` (the existing `i18n.js` `t()` passes substitutions through to `chrome.i18n.getMessage`).

> Verify `t()` supports substitutions — check `extension/i18n.js`. If it doesn't, render the count by string-concatenation instead and drop the placeholder.

**Step 2: Verify** — reload extension, switch a locale, confirm no missing-key warnings.

**Step 3: Commit**

```bash
git add extension/_locales
git commit -m "i18n: announcement UI strings (10 locales)"
```

---

## Task 8: Sidebar bell + badge + panel

**Files:**
- Modify: `extension/sidebar.html` (header bell + panel container)
- Modify: `extension/styles/sidebar.css` (bell, badge, panel, announcement-banner)
- Modify: `extension/sidebar.js` (fetch, render, read on open, dismiss; wire summary into existing settings poll)

**Step 1: HTML** — in `.header-left` (sidebar.html ~line 12-15), after `conn-dot`:

```html
      <button class="bell-btn" id="bell-btn" data-i18n-title="announcementsTitle" title="Notifications" style="display:none;">
        🔔<span class="bell-badge" id="bell-badge" style="display:none;">0</span>
      </button>
```

After the `reauth-banner` block (~line 31), add the high-priority strip + dropdown panel:

```html
  <!-- High-priority announcement strip (reuses reauth-banner styling) -->
  <div class="announce-strip" id="announce-strip" style="display:none;">
    <span class="announce-strip-text" id="announce-strip-text"></span>
    <button class="announce-strip-btn" id="announce-strip-btn" data-i18n="announcementsView">View</button>
    <button class="announce-strip-x" id="announce-strip-x" title="Dismiss">&times;</button>
  </div>

  <!-- Bell dropdown panel -->
  <div class="announce-panel" id="announce-panel" style="display:none;">
    <div class="announce-panel-empty" id="announce-panel-empty" data-i18n="announcementsEmpty">No notifications</div>
    <div id="announce-list"></div>
  </div>
```

**Step 2: CSS** — append to `sidebar.css` (reuse the orange `reauth-banner` gradient for the strip):

```css
/* ── Announcements ── */
.bell-btn { background:none; border:none; color:#fff; font-size:15px; cursor:pointer; position:relative; padding:0 2px; line-height:1; }
.bell-badge { position:absolute; top:-6px; right:-8px; background:#f03a17; color:#fff; font-size:10px; font-weight:700; min-width:15px; height:15px; border-radius:8px; padding:0 4px; display:inline-flex; align-items:center; justify-content:center; }
.announce-strip { background:linear-gradient(135deg,#2563eb 0%,#1d4ed8 100%); color:#fff; font-size:13px; padding:10px 14px; display:flex; align-items:center; gap:10px; }
.announce-strip-text { flex:1; line-height:1.35; }
.announce-strip-btn { background:#fff; color:#1d4ed8; border:none; border-radius:6px; padding:5px 12px; font-weight:700; font-size:12px; cursor:pointer; }
.announce-strip-x { background:none; border:none; color:#fff; font-size:18px; cursor:pointer; line-height:1; }
.announce-panel { background:#fff; border-bottom:1px solid #edebe9; max-height:320px; overflow-y:auto; }
.announce-panel-empty { padding:16px; text-align:center; color:#a19f9d; font-size:13px; }
.announce-card { padding:12px 14px; border-bottom:1px solid #f3f2f1; }
.announce-card-title { font-weight:600; font-size:13px; color:#323130; margin-bottom:3px; }
.announce-card-body { font-size:12px; color:#605e5c; line-height:1.4; white-space:pre-wrap; }
.announce-card-actions { margin-top:8px; display:flex; gap:8px; }
.announce-card-cta { color:#0078d4; font-size:12px; text-decoration:none; font-weight:600; }
.announce-card-dismiss { background:none; border:none; color:#a19f9d; font-size:12px; cursor:pointer; padding:0; }
```

**Step 3: JS** — add an announcements module in `sidebar.js`. Key behaviors:
- `loadAnnouncements()` → `GET_ANNOUNCEMENTS`, filter by version (client-side), render bell list + show/hide bell.
- Bell click → toggle panel; on open, mark all visible **unread** items `read` (`ANNOUNCEMENT_READ` each) + clear badge.
- Strip "View" → open panel (+ mark that item read). Strip "×" / card dismiss → `ANNOUNCEMENT_DISMISS` → re-render.
- Wire the **summary** from the existing settings poll: in `pollReauthState` (and wherever `GET_SETTINGS` data is read), pass `data.announcements_summary` to `updateAnnouncementSignal(summary)` which sets the badge count and shows/hides the strip — respecting **precedence: reauth > offline > announcement strip** (only show the strip when the reauth banner is hidden).

```javascript
// ── Announcements ──
function semverGte(a, b) {
  // returns true if version a >= version b ("0.1.12" >= "0.1.12")
  var pa = String(a).split("."), pb = String(b).split(".");
  for (var i = 0; i < Math.max(pa.length, pb.length); i++) {
    var na = parseInt(pa[i] || "0", 10), nb = parseInt(pb[i] || "0", 10);
    if (na > nb) return true;
    if (na < nb) return false;
  }
  return true;
}

function visibleByVersion(item) {
  if (!item.version) return true;
  return semverGte(chrome.runtime.getManifest().version, item.version);
}

var _announcements = [];

function renderAnnouncements() {
  var list = document.getElementById("announce-list");
  var empty = document.getElementById("announce-panel-empty");
  var badge = document.getElementById("bell-badge");
  var bell = document.getElementById("bell-btn");
  if (!list) return;
  var items = _announcements.filter(visibleByVersion);
  list.innerHTML = "";
  bell.style.display = items.length ? "inline-block" : "none";
  empty.style.display = items.length ? "none" : "block";
  var unread = items.filter(function (a) { return !a.read; }).length;
  badge.textContent = unread;
  badge.style.display = unread ? "inline-flex" : "none";
  items.forEach(function (a) {
    var card = document.createElement("div");
    card.className = "announce-card";
    var title = document.createElement("div");
    title.className = "announce-card-title"; title.textContent = a.title;
    var body = document.createElement("div");
    body.className = "announce-card-body"; body.textContent = a.body;
    card.appendChild(title); card.appendChild(body);
    var actions = document.createElement("div");
    actions.className = "announce-card-actions";
    if (a.cta_url && a.cta_label) {
      var link = document.createElement("a");
      link.className = "announce-card-cta"; link.textContent = a.cta_label;
      link.href = a.cta_url; link.target = "_blank"; link.rel = "noopener";
      actions.appendChild(link);
    }
    var dis = document.createElement("button");
    dis.className = "announce-card-dismiss";
    dis.textContent = t("announcementsDismiss");
    dis.addEventListener("click", function () { dismissAnnouncement(a.id); });
    actions.appendChild(dis);
    card.appendChild(actions);
    list.appendChild(card);
  });
}

function loadAnnouncements() {
  chrome.runtime.sendMessage({ type: "GET_ANNOUNCEMENTS" }, function (resp) {
    if (!resp || resp.error) return;
    var data = resp.data || resp;
    _announcements = (data.announcements || []);
    renderAnnouncements();
  });
}

function markReadVisibleUnread() {
  _announcements.filter(visibleByVersion).filter(function (a) { return !a.read; })
    .forEach(function (a) {
      a.read = true;
      chrome.runtime.sendMessage({ type: "ANNOUNCEMENT_READ", id: a.id });
    });
  renderAnnouncements();
}

function dismissAnnouncement(id) {
  chrome.runtime.sendMessage({ type: "ANNOUNCEMENT_DISMISS", id: id });
  _announcements = _announcements.filter(function (a) { return a.id !== id; });
  renderAnnouncements();
  // also hide the strip if it was this one
  var strip = document.getElementById("announce-strip");
  if (strip && strip.getAttribute("data-id") === id) strip.style.display = "none";
}

(function wireBell() {
  var bell = document.getElementById("bell-btn");
  var panel = document.getElementById("announce-panel");
  if (bell && panel) {
    bell.addEventListener("click", function () {
      var open = panel.style.display !== "none";
      panel.style.display = open ? "none" : "block";
      if (!open) markReadVisibleUnread();
    });
  }
  var strip = document.getElementById("announce-strip");
  var stripBtn = document.getElementById("announce-strip-btn");
  var stripX = document.getElementById("announce-strip-x");
  if (stripBtn) stripBtn.addEventListener("click", function () {
    panel.style.display = "block"; markReadVisibleUnread(); strip.style.display = "none";
  });
  if (stripX) stripX.addEventListener("click", function () {
    var id = strip.getAttribute("data-id"); if (id) dismissAnnouncement(id);
  });
})();

// Called from the settings poll with data.announcements_summary.
// Precedence: do not show the strip while the reauth banner is visible.
function updateAnnouncementSignal(summary) {
  if (!summary) return;
  var badge = document.getElementById("bell-badge");
  var bell = document.getElementById("bell-btn");
  if (summary.unread > 0) { bell.style.display = "inline-block"; }
  var reauthVisible = document.getElementById("reauth-banner") &&
    document.getElementById("reauth-banner").style.display !== "none";
  var strip = document.getElementById("announce-strip");
  var b = summary.banner;
  if (b && !visibleByVersionMaybe(b)) b = null;  // see note
  if (b && !reauthVisible) {
    document.getElementById("announce-strip-text").textContent = b.title;
    strip.setAttribute("data-id", b.id);
    strip.style.display = "flex";
  } else if (strip) {
    strip.style.display = "none";
  }
}

// The summary banner may be version-tagged; reuse the same gate.
function visibleByVersionMaybe(b) { return visibleByVersion(b); }
```

- Call `loadAnnouncements()` on sidebar init (near where settings/first load happens) and inside the settings poll callback call `updateAnnouncementSignal(data.announcements_summary)`.

**Step 4: Manual QA** (`chrome://extensions` reload + Outlook):
- Insert a normal broadcast via SQL → bell appears with badge "1"; open panel → reads it (badge clears); dismiss → disappears.
- Insert a high targeted (to your user) → blue strip shows "title — View"; View opens panel; × dismisses.
- Insert a release row with `version='9.9.9'` → must NOT show (running version < 9.9.9). Set `version='0.0.1'` → shows.
- Trigger reauth state (or fake it) → strip hidden while reauth banner visible.

**Step 5: Commit**

```bash
git add extension/sidebar.html extension/styles/sidebar.css extension/sidebar.js
git commit -m "feat(ext): sidebar announcement bell, panel, and high-priority strip"
```

---

## Task 9: Popup card under "Manage Subscription"

**Files:**
- Modify: `extension/popup.html` (container + minimal styles)
- Modify: `extension/popup.js` (fetch + render in `showConnected`)

**Step 1: HTML** — in `#connected-section`, after `#btn-manage-sub` (popup.html ~line 324):

```html
      <div id="popup-announcements" style="display:none; margin-bottom:8px;"></div>
```

Add styles in the popup `<style>`:
```css
    .pa-card { background:#eff6ff; border:1px solid #bfdbfe; border-radius:6px; padding:10px; margin-bottom:6px; text-align:left; }
    .pa-title { font-size:13px; font-weight:600; color:#1e3a8a; }
    .pa-body { font-size:12px; color:#475569; margin-top:3px; line-height:1.4; }
    .pa-actions { margin-top:8px; display:flex; justify-content:space-between; align-items:center; }
    .pa-cta { color:#0078d4; font-size:12px; font-weight:600; text-decoration:none; }
    .pa-dismiss { background:none; border:none; color:#94a3b8; font-size:12px; cursor:pointer; padding:0; }
    .pa-more { font-size:12px; color:#0078d4; cursor:pointer; text-align:center; }
```

**Step 2: JS** — at the end of `showConnected(...)` in popup.js, call `loadPopupAnnouncements()`:

```javascript
  function semverGte(a, b) {
    var pa = String(a).split("."), pb = String(b).split(".");
    for (var i = 0; i < Math.max(pa.length, pb.length); i++) {
      var na = parseInt(pa[i] || "0", 10), nb = parseInt(pb[i] || "0", 10);
      if (na > nb) return true; if (na < nb) return false;
    }
    return true;
  }

  function loadPopupAnnouncements() {
    var box = document.getElementById("popup-announcements");
    if (!box) return;
    chrome.runtime.sendMessage({ type: "GET_ANNOUNCEMENTS" }, function (resp) {
      if (!resp || resp.error) return;
      var data = resp.data || resp;
      var v = chrome.runtime.getManifest().version;
      var items = (data.announcements || []).filter(function (a) {
        return !a.version || semverGte(v, a.version);
      });
      var unread = items.filter(function (a) { return !a.read; });
      if (!unread.length) { box.style.display = "none"; return; }
      box.style.display = "block";
      box.innerHTML = "";
      var a = unread[0];
      var card = document.createElement("div"); card.className = "pa-card";
      var title = document.createElement("div"); title.className = "pa-title"; title.textContent = a.title;
      var body = document.createElement("div"); body.className = "pa-body"; body.textContent = a.body;
      card.appendChild(title); card.appendChild(body);
      var actions = document.createElement("div"); actions.className = "pa-actions";
      if (a.cta_url && a.cta_label) {
        var link = document.createElement("a"); link.className = "pa-cta";
        link.textContent = a.cta_label; link.href = a.cta_url; link.target = "_blank"; link.rel = "noopener";
        actions.appendChild(link);
      } else { actions.appendChild(document.createElement("span")); }
      var dis = document.createElement("button"); dis.className = "pa-dismiss";
      dis.textContent = t("announcementsDismiss");
      dis.addEventListener("click", function () {
        chrome.runtime.sendMessage({ type: "ANNOUNCEMENT_DISMISS", id: a.id });
        box.style.display = "none";
      });
      actions.appendChild(dis); card.appendChild(actions); box.appendChild(card);
      if (unread.length > 1) {
        var more = document.createElement("div"); more.className = "pa-more";
        more.textContent = t("announcementsMore", [String(unread.length - 1)]);
        more.addEventListener("click", openSidebarPanel);
        box.appendChild(more);
      }
      // showing the popup message marks the top item read
      chrome.runtime.sendMessage({ type: "ANNOUNCEMENT_READ", id: a.id });
    });
  }

  function openSidebarPanel() {
    // reuse the existing dashboard button flow to open the sidebar
    document.getElementById("btn-dashboard").click();
  }
```

**Step 3: Manual QA** — open popup with an unread item → card under Manage Subscription; dismiss works; "+N more" opens the sidebar.

**Step 4: Commit**

```bash
git add extension/popup.html extension/popup.js
git commit -m "feat(ext): popup announcement card under Manage Subscription"
```

---

## Task 10: Version bump + full verification

**Files:**
- Modify: `extension/manifest.json` (`"version": "0.1.12"`)
- Modify: `extension/CHANGELOG.md` (add 0.1.12 entry)

**Step 1: Bump version** to `0.1.12`; add CHANGELOG entry ("In-app notifications: sidebar bell, high-priority banner, popup card").

**Step 2: Full backend suite**

Run: `cd backend && python -m pytest`
Expected: all pass (was 299; now ~+12).

**Step 3: Full manual QA matrix** (Outlook Web, reloaded extension):
- normal broadcast → bell+badge, read clears badge, dismiss removes
- high targeted → blue strip + bell; View opens panel; × dismisses
- release `version` future → hidden; past → visible
- reauth precedence → strip hidden under reauth banner
- popup card shows under Manage Subscription; "+N more" → sidebar
- delivery check SQL shows `read_at` after viewing

**Step 4: Commit**

```bash
git add extension/manifest.json extension/CHANGELOG.md
git commit -m "chore(ext): v0.1.12 — in-app announcements"
```

---

## Rollout (after merge to master)

1. **User applies migration 020** in Supabase (confirm done before backend deploy relies on it — but endpoints tolerate missing tables only if migration is applied; apply FIRST).
2. Push backend → Railway auto-deploy.
3. Load v0.1.12 unpacked → full QA matrix.
4. Package + upload to Chrome Web Store (and Edge once approved).
5. **First real announcement** = the v0.1.12 release note (dogfood):
   ```sql
   insert into announcements (audience, priority, title, body, version)
   values ('broadcast','high','OutMass v0.1.12 is live',
           'New: in-app notifications. Plus faster CSV preview and fixes.','0.1.12');
   ```
6. Watch `announcement_reads` to confirm delivery visibility works.

## Notes for the executor
- **DRY:** `semverGte` is duplicated in sidebar.js and popup.js. Acceptable (no shared module between the two contexts today), but if a shared util file exists, prefer it.
- **YAGNI:** no admin UI, no per-locale message content, no two-way reply — all explicitly out of scope.
- **Backward compat:** old extension versions never call `/announcements`; they just ignore the new `settings.announcements_summary` field. No breakage.
- **Security:** `cta_url` should be `https`-only — validate at authoring time (SQL) for MVP; a server-side check can be added later.
