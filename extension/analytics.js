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
