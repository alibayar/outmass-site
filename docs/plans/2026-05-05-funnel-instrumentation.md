# Funnel Instrumentation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add anonymous behavioral telemetry (12 PostHog events from the extension) and a `users.last_seen_extension_version` column so we can identify install→signup→first-mail funnel dropoffs and track per-user extension version.

**Architecture:** Extension fires events via direct REST `POST` to `https://us.i.posthog.com/capture/` from the background service worker. Distinct IDs are random UUIDs in `chrome.storage.local`, aliased to backend `user_id` after signin. Every event auto-attaches `extension_version` / `browser` / `os` / `locale`. Backend gets one new nullable column updated through a header on each authenticated request, gated by the existing 15-minute `last_activity_at` rate-limiter.

**Tech Stack:** Vanilla JS (MV3), `fetch()` to PostHog REST, Python 3.11+ FastAPI, Supabase Postgres, pytest + FakeSupabase.

**Order:** Phase 0 (baseline) → Phase 1 (backend column + header) → Phase 2 (extension `analytics.js`) → Phase 3 (background.js wiring) → Phase 4 (sidebar.js wiring) → Phase 5 (manifest + version bump) → Phase 6 (privacy policy) → Phase 7 (self-test + ZIP).

**Testing philosophy:**
- **TDD** for backend changes (FakeSupabase fixture, ~3s suite).
- **Test-after** for extension wiring (manual self-test via Chrome DevTools + PostHog Live view; existing pattern in this codebase).
- One unit test for the `analytics.js` queue/dedup logic in isolation if it's worth the JS test infra; otherwise rely on PostHog Live view confirmation.
- E2E (Playwright) untouched — no UI change.

**i18n rule:** No new user-facing strings in this plan, so no `messages.json` updates. Privacy policy update is `docs/privacy.html` only (English; existing localized privacy pages are out of scope per project pattern).

**User-impact policy (CLAUDE.md):**
- Migration 018 = additive nullable column = **reversible**, **no behavior change**. Approved during brainstorming.
- Telemetry = anonymous, non-PII. Privacy policy gets a one-line update. Approved during brainstorming.
- No release notes / banner needed (invisible to user). Will note in CHANGELOG.md.

---

## PHASE 0 — Baseline

### Task 0.1: Confirm test suite green before changes

**Step 1:** Run full unit suite

```bash
cd D:/dev/git/outmass && npm run test:unit
```
Expected: ~261 tests pass, no failures.

**Step 2:** If any failure, STOP and surface to user before proceeding. The plan assumes a clean baseline.

---

## PHASE 1 — Backend: `last_seen_extension_version`

### Task 1.1: Write migration 018

**Files:**
- Create: `backend/migrations/018_last_seen_extension_version.sql`

**Step 1:** Create the migration file with this content:

```sql
-- 018: track last extension version each user signed in / made an authenticated request from.
--
-- Purpose: feed analytics queries like "what % of paid users are still
-- on v0.1.5?" and enable future stale-version nudge emails. Updated on
-- every authenticated request, gated by the same 15-minute rate-limiter
-- that protects last_activity_at, so this is essentially free.
--
-- Safety: nullable, additive. Reversible with `ALTER TABLE users DROP COLUMN`.
-- Existing rows treated as "unknown" (NULL) until their next signed-in request.

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_seen_extension_version TEXT;

COMMIT;

-- Verification:
--   SELECT column_name FROM information_schema.columns
--   WHERE table_name='users' AND column_name='last_seen_extension_version';
```

**Step 2:** Commit (no apply yet — applied manually by user via Supabase SQL editor at end of Phase 1).

```bash
git add backend/migrations/018_last_seen_extension_version.sql
git commit -m "migrations(018): add users.last_seen_extension_version (nullable text)"
```

---

### Task 1.2: TDD — extend `maybe_touch_activity` to accept and persist version

**Files:**
- Test: `backend/tests/test_activity_tracking.py` (extend existing file)
- Modify: `backend/models/user.py:108-124` (the `maybe_touch_activity` function)

**Step 1:** Write the failing test. Append to the bottom of `test_activity_tracking.py`:

```python
# ── extension version tracking ──


def test_maybe_touch_activity_writes_version_when_provided(fake_db):
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    user = {**FAKE_USER, "last_activity_at": None,
            "last_seen_extension_version": None}
    user_model.maybe_touch_activity(user, extension_version="0.1.9")

    assert len(users.update_calls) == 1
    assert users.update_calls[0].get("last_seen_extension_version") == "0.1.9"
    assert user["last_seen_extension_version"] == "0.1.9"


def test_maybe_touch_activity_skips_version_when_unchanged(fake_db):
    """If version matches what's already on the row, no need to write it
    (saves a roundtrip when the rate-limiter would otherwise have skipped)."""
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    fresh = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    user = {**FAKE_USER,
            "last_activity_at": fresh,
            "last_seen_extension_version": "0.1.9"}
    user_model.maybe_touch_activity(user, extension_version="0.1.9")

    # Activity is fresh AND version matches → no write
    assert users.update_calls == []


def test_maybe_touch_activity_writes_version_change_even_when_activity_fresh(fake_db):
    """Version change is rare but always interesting — bypass the
    activity-freshness rate limiter when the version differs."""
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    fresh = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    user = {**FAKE_USER,
            "last_activity_at": fresh,
            "last_seen_extension_version": "0.1.8"}
    user_model.maybe_touch_activity(user, extension_version="0.1.9")

    assert len(users.update_calls) == 1
    assert users.update_calls[0].get("last_seen_extension_version") == "0.1.9"


def test_maybe_touch_activity_no_version_param_keeps_existing(fake_db):
    """Backward compat — callers that don't pass extension_version still work."""
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    user = {**FAKE_USER,
            "last_activity_at": None,
            "last_seen_extension_version": "0.1.5"}
    user_model.maybe_touch_activity(user)  # no version arg

    # Activity is stale → writes activity, but does NOT touch version
    assert len(users.update_calls) == 1
    assert "last_seen_extension_version" not in users.update_calls[0]


def test_maybe_touch_activity_ignores_too_long_version(fake_db):
    """Defensive: a malicious or accidental huge header value must not
    bloat the DB. Cap at a reasonable length (e.g. 32 chars)."""
    users = _RecordingUsersTable(rows=[FAKE_USER])
    fake_db.set_table("users", users)

    user = {**FAKE_USER, "last_activity_at": None,
            "last_seen_extension_version": None}
    huge = "X" * 5000
    user_model.maybe_touch_activity(user, extension_version=huge)

    # Either rejected entirely OR truncated — but never written full-length
    written = users.update_calls[0].get("last_seen_extension_version", "")
    assert len(written) <= 32
```

**Step 2:** Run the new tests — expect failures.

```bash
cd D:/dev/git/outmass/backend && python -m pytest tests/test_activity_tracking.py -v -k "version"
```
Expected: 5 FAILs (function signature doesn't accept the new arg).

**Step 3:** Modify `models/user.py:108-124`. Replace the existing `maybe_touch_activity` with:

```python
_MAX_VERSION_LEN = 32  # semver + suffix is well under this; defensive cap


def _is_valid_version(v: str | None) -> str | None:
    """Sanitize a version string: must be non-empty, ASCII-printable,
    capped at 32 chars. Returns the cleaned value or None."""
    if not v or not isinstance(v, str):
        return None
    cleaned = v.strip()[:_MAX_VERSION_LEN]
    if not cleaned:
        return None
    # Drop anything weird; allow common semver chars only
    if not all(c.isalnum() or c in ".-+_" for c in cleaned):
        return None
    return cleaned


def maybe_touch_activity(user: dict, extension_version: str | None = None) -> None:
    """Bump last_activity_at if stale, and/or update last_seen_extension_version
    if it changed.

    Called from the auth dependency on every authenticated request. Mutates
    the passed-in dict so downstream handlers see the fresh values without
    a re-fetch.
    """
    activity_fresh = _is_activity_fresh(user.get("last_activity_at"))
    cleaned_version = _is_valid_version(extension_version)
    version_changed = (
        cleaned_version is not None
        and cleaned_version != user.get("last_seen_extension_version")
    )

    if activity_fresh and not version_changed:
        return

    updates: dict = {}
    if not activity_fresh:
        now = datetime.now(timezone.utc).isoformat()
        updates["last_activity_at"] = now
        user["last_activity_at"] = now  # mutate so downstream sees fresh
    if version_changed:
        updates["last_seen_extension_version"] = cleaned_version
        user["last_seen_extension_version"] = cleaned_version

    if not updates:
        return
    try:
        get_db().table("users").update(updates).eq("id", user["id"]).execute()
    except Exception:  # noqa: BLE001
        logger.exception("maybe_touch_activity failed for user %s", user.get("id"))
```

**Step 4:** Re-run tests — expect ALL pass (including the 4 pre-existing ones).

```bash
cd D:/dev/git/outmass/backend && python -m pytest tests/test_activity_tracking.py -v
```
Expected: All `test_maybe_touch_activity_*` and `test_touch_login_*` PASS.

**Step 5:** Run the full backend suite to catch any regression.

```bash
cd D:/dev/git/outmass && npm run test:unit
```
Expected: ~265 tests pass (4 new ones added).

**Step 6:** Commit.

```bash
git add backend/models/user.py backend/tests/test_activity_tracking.py
git commit -m "feat(user): track last_seen_extension_version in maybe_touch_activity"
```

---

### Task 1.3: Wire `X-Extension-Version` header into `get_current_user`

**Files:**
- Modify: `backend/routers/auth.py:79-93` (the `get_current_user` dependency)
- Test: `backend/tests/test_activity_tracking.py` (extend existing integration test)

**Step 1:** Write the failing integration test. Append to `test_activity_tracking.py`:

```python
def test_get_current_user_passes_extension_version_header(fake_db):
    """The X-Extension-Version header should reach maybe_touch_activity
    so the user's last_seen_extension_version stays current."""
    from routers.auth import get_current_user

    with patch("models.user.get_by_id",
               return_value={**FAKE_USER,
                             "last_activity_at": None,
                             "last_seen_extension_version": None}), \
         patch("models.user.maybe_touch_activity") as mock_touch, \
         patch("routers.auth.decode_jwt", return_value={"sub": FAKE_USER["id"]}):
        import asyncio
        asyncio.run(get_current_user(
            authorization="Bearer faketoken",
            x_extension_version="0.1.9",
        ))

    mock_touch.assert_called_once()
    call_kwargs = mock_touch.call_args
    assert call_kwargs.kwargs.get("extension_version") == "0.1.9"


def test_get_current_user_no_header_passes_none(fake_db):
    """Backward compat: requests without the header (legacy clients,
    direct API calls) should still succeed."""
    from routers.auth import get_current_user

    with patch("models.user.get_by_id",
               return_value={**FAKE_USER, "last_activity_at": None}), \
         patch("models.user.maybe_touch_activity") as mock_touch, \
         patch("routers.auth.decode_jwt", return_value={"sub": FAKE_USER["id"]}):
        import asyncio
        asyncio.run(get_current_user(authorization="Bearer faketoken"))

    mock_touch.assert_called_once()
    call_kwargs = mock_touch.call_args
    assert call_kwargs.kwargs.get("extension_version") is None
```

**Step 2:** Run the test — expect failures.

```bash
cd D:/dev/git/outmass/backend && python -m pytest tests/test_activity_tracking.py -v -k "extension_version"
```
Expected: 2 FAILs (`get_current_user` doesn't accept `x_extension_version`).

**Step 3:** Modify `routers/auth.py:79`. Replace the `get_current_user` signature and body:

```python
async def get_current_user(
    authorization: str = Header(...),
    x_extension_version: str | None = Header(default=None),
) -> dict:
    """Dependency: extract and verify JWT from Authorization header.

    Also records the calling extension's version (sent via X-Extension-Version
    header). Both the activity timestamp and the version write are gated by
    a 15-minute rate-limiter inside maybe_touch_activity, so this is cheap.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")
    token = authorization[7:]
    payload = decode_jwt(token)
    user_id = payload.get("sub")
    user = user_model.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    user_model.maybe_touch_activity(user, extension_version=x_extension_version)
    return user
```

**Step 4:** Re-run tests — expect PASS.

```bash
cd D:/dev/git/outmass/backend && python -m pytest tests/test_activity_tracking.py -v
```

**Step 5:** Run the full backend suite.

```bash
cd D:/dev/git/outmass && npm run test:unit
```
Expected: All ~267 tests pass.

**Step 6:** Commit.

```bash
git add backend/routers/auth.py backend/tests/test_activity_tracking.py
git commit -m "feat(auth): read X-Extension-Version header, propagate to user touch"
```

---

### Task 1.4: Apply migration 018 to production

> **STOP — user action required.**

This is the only DB-touching step. The user must manually:

1. Open Supabase SQL editor: `https://qhfefazyfhyqnjcmfmdd.supabase.co/project/_/sql`
2. Paste the contents of `backend/migrations/018_last_seen_extension_version.sql`
3. Run it
4. Confirm with the verification query at the bottom of the migration file

After confirmation, proceed to Phase 2.

---

## PHASE 2 — Extension: `analytics.js` (PostHog client)

### Task 2.1: Add PostHog public key to `extension/config.js`

**Files:**
- Modify: `extension/config.js`

**Step 1:** Append to `extension/config.js`:

```js
// PostHog project public key (safe to ship in extension — public by design)
// EU host because backend uses EU per .env (POSTHOG_HOST). Keep in sync.
var OUTMASS_POSTHOG_KEY = "phc_REPLACE_WITH_PROJECT_PUBLIC_KEY";
var OUTMASS_POSTHOG_HOST = "https://us.i.posthog.com";
```

> **STOP — user action required.** Reach out for the actual `phc_*` key (same value as backend's `POSTHOG_API_KEY` env var on Railway) and replace the placeholder. Do not commit until the real key is in place.

**Step 2:** Commit (with real key) once user provides it.

```bash
git add extension/config.js
git commit -m "config(ext): add PostHog project key + host"
```

---

### Task 2.2: Create `extension/analytics.js` — track helper + queue

**Files:**
- Create: `extension/analytics.js`

**Step 1:** Create the file with this content:

```js
/**
 * OutMass — Extension Analytics
 *
 * Direct PostHog REST client for MV3. Buffers events in memory + chrome.storage
 * so service worker restarts don't lose them. Flushes on a short timer or when
 * the queue grows past a threshold.
 *
 * Distinct ID is a random UUID in chrome.storage.local; once the user signs
 * in, identify() aliases it to the backend user_id so pre-signin events
 * attach to the same person in PostHog.
 */

const _PH_QUEUE_KEY = "outmass_analytics_queue";
const _PH_DISTINCT_ID_KEY = "outmass_analytics_distinct_id";
const _PH_USER_ID_KEY = "outmass_analytics_user_id";
const _PH_FLUSH_INTERVAL_MS = 10 * 1000; // 10s
const _PH_QUEUE_CAP = 100; // hard cap; drop oldest if exceeded
let _phFlushTimer = null;

function _phUuid() {
  // RFC4122 v4 — good enough for analytics distinct_id
  if (self.crypto && self.crypto.randomUUID) return self.crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

async function _phGetDistinctId() {
  const stored = await chrome.storage.local.get([_PH_DISTINCT_ID_KEY]);
  if (stored[_PH_DISTINCT_ID_KEY]) return stored[_PH_DISTINCT_ID_KEY];
  const fresh = _phUuid();
  await chrome.storage.local.set({ [_PH_DISTINCT_ID_KEY]: fresh });
  return fresh;
}

async function _phDefaultProps() {
  const manifest = chrome.runtime.getManifest();
  let os = "unknown";
  try {
    const info = await chrome.runtime.getPlatformInfo();
    os = info.os;
  } catch (e) {
    /* ignore */
  }
  let browser = "Chrome";
  try {
    const ua = (self.navigator && self.navigator.userAgent) || "";
    if (/Edg\//.test(ua)) browser = "Edge";
    else if (/OPR\//.test(ua)) browser = "Opera";
    else if (/Brave/.test(ua)) browser = "Brave";
  } catch (e) {
    /* ignore */
  }
  let locale = "en";
  try {
    locale = chrome.i18n.getUILanguage() || "en";
  } catch (e) {
    /* ignore */
  }
  return {
    extension_version: manifest.version,
    browser: browser,
    os: os,
    locale: locale,
  };
}

async function _phEnqueue(event) {
  const cur = (await chrome.storage.local.get([_PH_QUEUE_KEY]))[_PH_QUEUE_KEY] || [];
  cur.push(event);
  // Hard cap — drop oldest events if we ever back up
  while (cur.length > _PH_QUEUE_CAP) cur.shift();
  await chrome.storage.local.set({ [_PH_QUEUE_KEY]: cur });
}

async function _phFlush() {
  if (!OUTMASS_POSTHOG_KEY || OUTMASS_POSTHOG_KEY.indexOf("REPLACE") === 0) return;
  const stored = await chrome.storage.local.get([_PH_QUEUE_KEY]);
  const queue = stored[_PH_QUEUE_KEY] || [];
  if (queue.length === 0) return;
  // Optimistically clear the queue. On failure, re-enqueue.
  await chrome.storage.local.set({ [_PH_QUEUE_KEY]: [] });
  try {
    const resp = await fetch(OUTMASS_POSTHOG_HOST + "/batch/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: OUTMASS_POSTHOG_KEY,
        batch: queue,
      }),
    });
    if (!resp.ok) {
      // Re-enqueue (front, preserve order) — caller's loop will retry
      const cur = (await chrome.storage.local.get([_PH_QUEUE_KEY]))[_PH_QUEUE_KEY] || [];
      await chrome.storage.local.set({ [_PH_QUEUE_KEY]: queue.concat(cur).slice(-_PH_QUEUE_CAP) });
    }
  } catch (e) {
    // Network down — re-enqueue
    const cur = (await chrome.storage.local.get([_PH_QUEUE_KEY]))[_PH_QUEUE_KEY] || [];
    await chrome.storage.local.set({ [_PH_QUEUE_KEY]: queue.concat(cur).slice(-_PH_QUEUE_CAP) });
  }
}

function _phStartFlushTimer() {
  if (_phFlushTimer) return;
  _phFlushTimer = setInterval(_phFlush, _PH_FLUSH_INTERVAL_MS);
}

/**
 * Public: track an event with optional properties.
 * Safe to call from any extension context that has imported analytics.js.
 */
async function track(eventName, properties) {
  try {
    const distinctId = await _phGetDistinctId();
    const stored = await chrome.storage.local.get([_PH_USER_ID_KEY]);
    const userId = stored[_PH_USER_ID_KEY] || null;
    const defaults = await _phDefaultProps();
    const props = Object.assign({}, defaults, properties || {});
    const event = {
      event: eventName,
      distinct_id: userId || distinctId,
      properties: Object.assign({}, props, {
        $anon_distinct_id: distinctId,
      }),
      timestamp: new Date().toISOString(),
    };
    await _phEnqueue(event);
    _phStartFlushTimer();
  } catch (e) {
    // Telemetry must NEVER break the calling code path
    console.warn("[OutMass-PH] track failed:", e);
  }
}

/**
 * Public: associate the anonymous distinct_id with a backend user_id.
 * Sends an explicit $identify event so PostHog joins past + future events.
 * Idempotent — calling it again with the same userId is a no-op.
 */
async function identify(userId) {
  try {
    if (!userId) return;
    const stored = await chrome.storage.local.get([_PH_USER_ID_KEY]);
    if (stored[_PH_USER_ID_KEY] === userId) return; // already aliased
    const distinctId = await _phGetDistinctId();
    await chrome.storage.local.set({ [_PH_USER_ID_KEY]: userId });

    // PostHog $identify event — server-side joining of anon + signed-in.
    const defaults = await _phDefaultProps();
    await _phEnqueue({
      event: "$identify",
      distinct_id: userId,
      properties: Object.assign({}, defaults, {
        $anon_distinct_id: distinctId,
      }),
      timestamp: new Date().toISOString(),
    });
    _phStartFlushTimer();
  } catch (e) {
    console.warn("[OutMass-PH] identify failed:", e);
  }
}

/**
 * Public: clear user_id alias on logout. Future events go back to anon
 * distinct_id. Does NOT clear the distinct_id itself — same install,
 * same anon identity.
 */
async function resetIdentity() {
  try {
    await chrome.storage.local.remove([_PH_USER_ID_KEY]);
  } catch (e) {
    /* ignore */
  }
}
```

**Step 2:** Commit.

```bash
git add extension/analytics.js
git commit -m "feat(ext): add analytics.js — PostHog REST client + queue"
```

---

## PHASE 3 — Wire events into `background.js`

### Task 3.1: Import `analytics.js` and emit install/update events

**Files:**
- Modify: `extension/background.js:21-22` (importScripts block)
- Modify: `extension/background.js:72-108` (`chrome.runtime.onInstalled` handler)

**Step 1:** Update the importScripts block at line 21:

```js
importScripts("config.js");
importScripts("analytics.js");
importScripts("graph_api.js");
```

**Step 2:** Inside the existing `chrome.runtime.onInstalled.addListener(...)` (line 72), add at the end of the function (before the closing `}`):

```js
  // Telemetry: install vs update
  if (details.reason === "install") {
    track("ext_installed", { version: chrome.runtime.getManifest().version });
  } else if (details.reason === "update") {
    track("ext_updated", {
      from_version: details.previousVersion || "unknown",
      to_version: chrome.runtime.getManifest().version,
    });
  }
```

**Step 3:** Manual test — reload extension in `chrome://extensions`, open Service Worker DevTools, run:

```js
chrome.storage.local.get(["outmass_analytics_queue"], console.log);
```

Expected: queue contains an `ext_updated` event with version props.

**Step 4:** Commit.

```bash
git add extension/background.js
git commit -m "feat(ext): track ext_installed / ext_updated"
```

---

### Task 3.2: Emit `oauth_started` / `oauth_completed` / `oauth_failed`

**Files:**
- Modify: `extension/background.js:118-280` (`startMSLogin` function)

**Step 1:** Inside `startMSLogin(includeOneDrive)` (line 118), at the very top of the function body (after `log("Starting...")`):

```js
  track("oauth_started", { with_onedrive: !!includeOneDrive });
```

**Step 2:** In the `chrome.identity.launchWebAuthFlow` callback, at each terminal `resolve(...)` branch, add the matching event:

- After `resolve({ error: chrome.runtime.lastError.message })`:
  ```js
  track("oauth_failed", { reason: "chrome_error", message: String(chrome.runtime.lastError.message || "") });
  ```
- After `resolve({ error: "No redirect URL received" })`:
  ```js
  track("oauth_failed", { reason: "no_redirect" });
  ```
- After `resolve({ error: "Invalid redirect URL" })`:
  ```js
  track("oauth_failed", { reason: "invalid_redirect" });
  ```
- After `resolve({ error: errorMsg })`:
  ```js
  track("oauth_failed", { reason: "backend_error", code: String(errorMsg).slice(0, 64) });
  ```
- After `resolve({ error: "Incomplete auth response from backend" })`:
  ```js
  track("oauth_failed", { reason: "incomplete_response" });
  ```
- After the success path (after `chrome.storage.local.set({ ... }, function () { ... })`), inside the success callback:
  ```js
  // Backend doesn't return user_id in the redirect fragment today, so
  // we identify by email — PostHog accepts any string as distinct_id.
  // (If/when backend adds user_id to the fragment, swap to that.)
  identify(email);
  track("oauth_completed", { plan: plan });
  ```

**Step 3:** Manual test — fresh install, sign in. Inspect queue:

```js
chrome.storage.local.get(["outmass_analytics_queue"], console.log);
```

Expected: `oauth_started` then `oauth_completed` (with plan) OR `oauth_failed` (with reason). Within ~10s the queue empties (flushed to PostHog).

**Step 4:** Commit.

```bash
git add extension/background.js
git commit -m "feat(ext): track oauth_started / completed / failed"
```

---

## PHASE 4 — Wire events into `sidebar.js`

### Task 4.1: Make `track()` callable from sidebar via background relay

> Sidebar runs in an iframe and cannot import `analytics.js` directly (different context). We add a TRACK message handler in background.js, and a tiny helper in sidebar.js.

**Files:**
- Modify: `extension/background.js:290+` (the `chrome.runtime.onMessage.addListener` switch)
- Modify: `extension/sidebar.js` (add helper near the top, before any uses)

**Step 1:** Add a new case to the message switch in `background.js`:

```js
    case "TRACK":
      track(message.event, message.properties || {});
      sendResponse({ ok: true });
      return false; // sync
```

**Step 2:** Add a helper near the top of `sidebar.js` (after the existing `chrome.runtime.sendMessage(...)` usage, around line 32):

```js
function track(eventName, properties) {
  try {
    chrome.runtime.sendMessage({
      type: "TRACK",
      event: eventName,
      properties: properties || {},
    });
  } catch (e) {
    /* never break sidebar code path */
  }
}
```

**Step 3:** Manual test — open sidebar, in sidebar iframe DevTools console:

```js
track("debug_test", { foo: "bar" });
```

Expected: `outmass_analytics_queue` in background storage gets a `debug_test` event.

**Step 4:** Commit.

```bash
git add extension/background.js extension/sidebar.js
git commit -m "feat(ext): TRACK message relay so sidebar can emit events"
```

---

### Task 4.2: Emit `sidebar_opened`, `signin_clicked`, `compose_view_seen`

**Files:**
- Modify: `extension/sidebar.js`

**Step 1:** Find the sidebar init / DOMContentLoaded handler (search for `DOMContentLoaded` or top-level init code). Add at the end of init:

```js
track("sidebar_opened");
```

**Step 2:** Find the sign-in button handler. Search for `MS_LOGIN`:

```bash
grep -n "MS_LOGIN" extension/sidebar.js
```

Located around line 98. **Before** the existing `chrome.runtime.sendMessage({ type: "MS_LOGIN" }, ...)`:

```js
track("signin_clicked");
```

**Step 3:** Find where the compose / campaign view is shown. Look for the function that switches the visible tab/view to "compose" or "new campaign" — typically a function name like `showComposeView` or a tab change handler. Add at the start of that function (only fire once per session — use a module-level flag):

```js
// Top of file, near other module-level state:
var _composeViewSeenThisSession = false;

// Inside the show-compose function:
if (!_composeViewSeenThisSession) {
  _composeViewSeenThisSession = true;
  track("compose_view_seen");
}
```

**Step 4:** Reload sidebar, walk through: sidebar load → click sign-in → switch to compose. Inspect the queue:

```js
chrome.storage.local.get(["outmass_analytics_queue"], console.log);
```

Expected: 3 events in order.

**Step 5:** Commit.

```bash
git add extension/sidebar.js
git commit -m "feat(ext): track sidebar_opened, signin_clicked, compose_view_seen"
```

---

### Task 4.3: Emit `recipients_uploaded`, `send_clicked`, `send_completed`, `send_failed`

**Files:**
- Modify: `extension/sidebar.js`

**Step 1:** Find the CSV upload handler. Search:

```bash
grep -n "csv\|recipient\|upload" extension/sidebar.js | head -20
```

In the success path (after recipients parsed and the count is known), add:

```js
track("recipients_uploaded", { recipient_count: recipients.length });
```

**Step 2:** Find the "Send All" button handler. Search:

```bash
grep -n "SEND_CAMPAIGN\|sendCampaign\|send.*all\|Send All" extension/sidebar.js | head -20
```

At the start of the click handler (before validation, before sending the message to background):

```js
track("send_clicked", { recipient_count: (recipients && recipients.length) || 0 });
```

In the success callback (`resp.ok === true` or `resp.success`):

```js
track("send_completed", {
  recipient_count: (recipients && recipients.length) || 0,
  campaign_id: resp.campaign_id || null,
});
```

In the failure callback:

```js
track("send_failed", {
  recipient_count: (recipients && recipients.length) || 0,
  error_code: (resp && resp.error) ? String(resp.error).slice(0, 64) : "unknown",
});
```

**Step 3:** Manual test — upload a 2-row test CSV, click Send All to a test recipient (your own email). Inspect queue.

Expected: `recipients_uploaded` (count=2), `send_clicked` (count=2), then `send_completed` OR `send_failed`.

**Step 4:** Commit.

```bash
git add extension/sidebar.js
git commit -m "feat(ext): track recipients_uploaded / send_clicked / send_completed / send_failed"
```

---

## PHASE 5 — Manifest, version bump, X-Extension-Version header

### Task 5.1: Update `manifest.json` — host permission + version

**Files:**
- Modify: `extension/manifest.json`

**Step 1:** Add to `host_permissions` array (after the existing entries):

```json
    "https://us.i.posthog.com/*"
```

**Step 2:** Bump `"version"`:

```json
"version": "0.1.9"
```

**Step 3:** Verify the file parses:

```bash
node -e "JSON.parse(require('fs').readFileSync('extension/manifest.json','utf8')); console.log('ok')"
```

Expected: `ok`.

**Step 4:** Commit.

```bash
git add extension/manifest.json
git commit -m "chore(ext): manifest v0.1.9 + posthog host_permission"
```

---

### Task 5.2: Send `X-Extension-Version` header on every backend API call

**Files:**
- Modify: `extension/background.js` — find the `backendFetch` helper (the place where all `outmass-production.up.railway.app` calls share auth header logic)

**Step 1:** Find the helper:

```bash
grep -n "backendFetch\|Authorization.*Bearer\|backendJwt" extension/background.js | head -20
```

**Step 2:** In the `headers` object construction, add:

```js
"X-Extension-Version": chrome.runtime.getManifest().version,
```

next to the existing `Authorization` and `Content-Type` headers.

**Step 3:** Manual test — load the extension, sign in, then in Service Worker DevTools Network tab make any authenticated call (open sidebar). Verify the request headers include `X-Extension-Version: 0.1.9`.

**Step 4:** Commit.

```bash
git add extension/background.js
git commit -m "feat(ext): send X-Extension-Version header on backend calls"
```

---

## PHASE 6 — Privacy policy update

### Task 6.1: Add anonymous telemetry disclosure to `docs/privacy.html`

**Files:**
- Modify: `docs/privacy.html`

**Step 1:** Find the section that currently mentions PostHog (the existing error-tracking disclosure). Add one paragraph immediately after it:

```html
<p>
  We collect anonymous usage telemetry through our extension to understand
  how features are used and where users encounter friction. These events
  contain no personal information — only event names (e.g.
  <em>sidebar_opened</em>, <em>send_completed</em>) and technical metadata
  (extension version, browser, operating system, language). The anonymous
  ID linking these events is generated locally by your browser and is not
  shared with third parties beyond our analytics provider (PostHog). Once
  you sign in, the anonymous ID is associated with your account so we can
  measure end-to-end product usage.
</p>
```

**Step 2:** Locate `docs/CHANGELOG.md` (extension-side has its own). Add to extension `CHANGELOG.md`:

```markdown
## v0.1.9 — 2026-05-05

- internal: anonymous funnel telemetry (PostHog) + per-user extension version tracking. No user-visible behavior change. Privacy policy updated to reflect this.
```

**Step 3:** Commit.

```bash
git add docs/privacy.html extension/CHANGELOG.md
git commit -m "docs(privacy): disclose anonymous funnel telemetry (v0.1.9)"
```

---

## PHASE 7 — Self-test, ZIP, deploy gate

### Task 7.1: Full local self-test walkthrough

**Step 1:** Reload extension fully in `chrome://extensions` (Remove → Load unpacked, to simulate fresh install).

**Step 2:** Walk through and confirm in PostHog Live view (https://us.posthog.com → Activity → Live events) each event appears within ~15 seconds:

| Action | Expected event |
|---|---|
| Just reloaded the unpacked ext | `ext_installed` (from a fresh storage; or `ext_updated` from prior load) |
| Open Outlook Web tab | `sidebar_opened` |
| Click "Sign in with Microsoft" | `signin_clicked`, `oauth_started` |
| Complete OAuth | `oauth_completed` (with plan), `$identify` |
| Switch to compose tab | `compose_view_seen` (first time only) |
| Upload 2-row CSV | `recipients_uploaded` (count=2) |
| Click Send All | `send_clicked`, then `send_completed` OR `send_failed` |

**Step 3:** Verify default props on each event in PostHog: `extension_version=0.1.9`, `browser=Chrome` (or Edge), `os` matches your OS, `locale` matches.

**Step 4:** In Supabase SQL editor:

```sql
SELECT email, last_seen_extension_version, last_activity_at
FROM users
WHERE email = '<your test email>';
```

Expected: `last_seen_extension_version = "0.1.9"`, `last_activity_at` recent.

**Step 5:** If any event missing → debug. If all pass → proceed to ZIP.

---

### Task 7.2: Run all tests, ZIP, push, deploy backend

**Step 1:** Full test suite green:

```bash
cd D:/dev/git/outmass && npm run test:all
```
Expected: 261+ unit + 48 E2E pass.

**Step 2:** Build the ZIP for Chrome Web Store upload:

```powershell
cd D:/dev/git/outmass/extension
Compress-Archive -Path * -DestinationPath ../outmass-v0.1.9.zip -Force
cd ..
```

**Step 3:** Push to remote.

```bash
git push origin master
```

Expected: Railway auto-deploys backend (web + worker + beat). Migration 018 should already be applied (Task 1.4).

**Step 4:** Sanity check Railway deploy:

```bash
curl -s https://outmass-production.up.railway.app/health | jq
```

Expected: `{"status": "ok"}`.

**Step 5:** Manually upload `outmass-v0.1.9.zip` to Chrome Web Store dashboard. Submit for review (typically 1–3 days).

---

### Task 7.3: Post-deploy verification (24h after Web Store approval)

**Step 1:** PostHog → Insights → create a funnel:
- Step 1: `ext_installed`
- Step 2: `sidebar_opened`
- Step 3: `signin_clicked`
- Step 4: `oauth_started`
- Step 5: `oauth_completed`
- Step 6: `compose_view_seen`
- Step 7: `send_clicked`
- Step 8: `send_completed`

**Step 2:** Wait 7 days for organic traffic. Identify the largest dropoff step. Bring findings back to a new session for the next iteration.

---

## Done

Final deliverable: v0.1.9 in the Chrome Web Store with full funnel telemetry plus per-user version tracking. After 7 days of data, we'll know exactly where the install→signup→first-mail funnel is leaking and can prioritize Rota 2 fixes (free tier 100/mo, viral footer, Edge listing) against the actual blocker.
