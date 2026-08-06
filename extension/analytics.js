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

// ── Uninstall funnel stage ──
//
// Chrome hands the uninstall page a URL we must register in ADVANCE — there is
// no callback at uninstall time to compute one. So we keep it current: every
// time the user reaches a further stage of the funnel we re-point the uninstall
// URL at that stage. Whoever eventually uninstalls tells us where they gave up.
//
// Why this is worth the plumbing: on 2026-08-03 a user uninstalled after six
// dead "Sign in" clicks and wrote "GARBAGE. DOES NOT WORK". Explaining that
// took Railway log forensics plus PostHog archaeology. `?stage=signin_clicked`
// would have said it at a glance — and says it for every future uninstall,
// including the silent majority who never write anything.
//
// Only two values ride along, both already covered by our privacy policy's
// "anonymous usage telemetry (event names, extension version)" disclosure:
// the stage name and the extension version. No id, no email, no counters.
const _PH_STAGE_KEY = "outmass_funnel_stage";
const _UNINSTALL_URL = "https://getoutmass.com/uninstall.html";

// Ordered — index IS the rank. The stage only ever moves forward, so a user
// who signs in and later signs out is still recorded at their high-water mark
// rather than looking like a fresh install.
const _PH_STAGE_LADDER = [
  "installed",
  // Reaching Outlook at all. Between "installed" and everything below sat the
  // largest hole in the funnel — 32 of 97 installs over 60 days (2026-08-06)
  // never opened the panel and never tried to sign in, and we could not tell
  // whether they never got to Outlook or got there and missed the launcher.
  "outlook_reached",
  "onboarded",
  "panel_opened",
  "signin_clicked",
  "auth_started",
  "signed_in",
  "recipients_uploaded",
  "test_sent",
  "sent",
];

// Which existing events advance the ladder. Deliberately a subset: these are
// the transitions that mean "the user got materially further", not every event
// we emit. Both onboarding outcomes count — skipping onboarding is still
// leaving it behind.
const _PH_STAGE_EVENTS = {
  outlook_reached: "outlook_reached",
  onboarding_completed: "onboarded",
  onboarding_skipped: "onboarded",
  sidebar_opened: "panel_opened",
  signin_clicked: "signin_clicked",
  oauth_started: "auth_started",
  oauth_completed: "signed_in",
  recipients_uploaded: "recipients_uploaded",
  test_send_completed: "test_sent",
  send_completed: "sent",
};

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

// Writes to the queue are SERIALIZED through this promise chain. The
// read-modify-write below is not atomic, and the one moment two writers
// reliably overlap is sign-in completion: identify() enqueues $identify while
// track() enqueues oauth_completed, both awaited nowhere, and whichever set()
// lands second erases the other's event. That lost update ate oauth_completed
// for a real Edge user on 2026-07-30 — who had actually signed in and sent a
// campaign — and made "zero Edge completions" look like a browser-breaking
// bug for a whole investigation. Only ever possible for FIRST sign-ins (the
// only time identify() has work to do), i.e. it corrupted the funnel at
// exactly the new-user conversion step.
let _phEnqueueChain = Promise.resolve();

function _phEnqueue(event) {
  const link = _phEnqueueChain.then(async function () {
    const cur = (await chrome.storage.local.get([_PH_QUEUE_KEY]))[_PH_QUEUE_KEY] || [];
    cur.push(event);
    // Hard cap — drop oldest events if we ever back up
    while (cur.length > _PH_QUEUE_CAP) cur.shift();
    await chrome.storage.local.set({ [_PH_QUEUE_KEY]: cur });
  });
  // The chain must survive a failed write, or one storage error would make
  // every later enqueue reject too.
  _phEnqueueChain = link.catch(function () {});
  return link;
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
 * Re-register the uninstall URL carrying the stage the user has reached.
 *
 * Best-effort in every direction: setUninstallURL is only meaningful in the
 * service worker, the call can fail, and none of that should ever be visible
 * to the user or interrupt telemetry.
 */
function _phSetUninstallUrl(stage) {
  try {
    if (!chrome.runtime || typeof chrome.runtime.setUninstallURL !== "function") return;
    const version = chrome.runtime.getManifest().version;
    const url =
      _UNINSTALL_URL +
      "?stage=" + encodeURIComponent(stage) +
      "&v=" + encodeURIComponent(version);
    chrome.runtime.setUninstallURL(url, function () {
      // Reading lastError is what SUPPRESSES the unchecked-error warning;
      // there is nothing useful to do about a failure here.
      if (chrome.runtime.lastError) {
        console.warn("[OutMass-PH] setUninstallURL:", chrome.runtime.lastError.message);
      }
    });
  } catch (e) {
    console.warn("[OutMass-PH] setUninstallURL threw:", e);
  }
}

/**
 * Advance the funnel high-water mark if this event represents progress.
 * Monotonic: never moves backwards, so signing out or reinstalling the panel
 * cannot erase the fact that the user once reached a later stage.
 */
async function _phNoteStage(eventName) {
  try {
    const stage = _PH_STAGE_EVENTS[eventName];
    if (!stage) return;
    const rank = _PH_STAGE_LADDER.indexOf(stage);
    if (rank < 0) return;
    const stored = await chrome.storage.local.get([_PH_STAGE_KEY]);
    const current = stored[_PH_STAGE_KEY];
    if (current && _PH_STAGE_LADDER.indexOf(current) >= rank) return;
    await chrome.storage.local.set({ [_PH_STAGE_KEY]: stage });
    _phSetUninstallUrl(stage);
  } catch (e) {
    // Bookkeeping only — must never break the calling code path.
    console.warn("[OutMass-PH] stage note failed:", e);
  }
}

/**
 * Public: register the uninstall URL from whatever stage we already know.
 *
 * Called from onInstalled for BOTH install and update. Reading the stored
 * stage rather than hardcoding "installed" is the point: an update must not
 * demote a user who has been sending campaigns for months back to a fresh
 * install.
 */
async function refreshUninstallUrl() {
  let stage = "installed";
  try {
    const stored = await chrome.storage.local.get([_PH_STAGE_KEY]);
    if (stored[_PH_STAGE_KEY]) stage = stored[_PH_STAGE_KEY];
  } catch (e) {
    /* fall through with "installed" — a wrong stage beats no URL at all */
  }
  _phSetUninstallUrl(stage);
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
    // Every client event funnels through here (sidebar and popup both forward
    // via the TRACK message), so this is the one place that sees the whole
    // journey — and therefore the only place the stage ladder belongs.
    await _phNoteStage(eventName);
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
