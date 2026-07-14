/**
 * OutMass — Background Service Worker
 * Microsoft OAuth 2.0 flow, token management, Graph API, alarms
 */

// ── Azure Config (user must fill in Client ID) ──
const AZURE_CLIENT_ID = "3b6a9f9b-cbb6-4dcb-a3b6-d993de74a1b5";
const AZURE_REDIRECT_URI = chrome.identity.getRedirectURL("auth");
const MS_AUTH_ENDPOINT =
  "https://login.microsoftonline.com/common/oauth2/v2.0/authorize";
const MS_TOKEN_ENDPOINT =
  "https://login.microsoftonline.com/common/oauth2/v2.0/token";
const MS_SCOPES = [
  "https://graph.microsoft.com/Mail.Send",
  "https://graph.microsoft.com/Mail.Read",
  "https://graph.microsoft.com/User.Read",
  "offline_access",
].join(" ");

// ── Import modules ──
importScripts("config.js");
importScripts("analytics.js");
importScripts("graph_api.js");

// Override backend URL from storage (set during install or via settings)
chrome.storage.local.get(["backendUrl", "debug"], function (result) {
  if (result.backendUrl) {
    OUTMASS_BACKEND_URL = result.backendUrl;
  }
  if (result.debug) {
    _debugEnabled = true;
  }
});

const LOG_PREFIX = "[OutMass-BG]";
var _debugEnabled = false;

function log(...args) {
  if (!_debugEnabled) return;
  console.log(LOG_PREFIX, ...args);
}

// ── Error Reporting ──
// Browser-internal warnings that are harmless but noisy (a ResizeObserver
// reflow loop, message-port/bfcache teardown, extension-context-invalidated
// after a reload). They flooded error tracking and drowned the real signal,
// so we drop them before the network round-trip. The backend filters the
// same list as a backstop for older clients.
var BENIGN_ERROR_PATTERNS = [
  "resizeobserver loop",
  "could not establish connection. receiving end does not exist",
  "the message channel closed before a response was received",
  "extension context invalidated",
];

function isBenignError(message) {
  var msg = String(message || "").toLowerCase();
  for (var i = 0; i < BENIGN_ERROR_PATTERNS.length; i++) {
    if (msg.indexOf(BENIGN_ERROR_PATTERNS[i]) !== -1) return true;
  }
  return false;
}

function reportError(message, stack, context) {
  if (isBenignError(message)) return; // harmless browser-internal noise
  try {
    fetch(_backendBases()[0] + "/api/error-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: message,
        source: "extension-bg",
        stack: stack || "",
        context: context || {},
      }),
    }).catch(function () {}); // Fire and forget
  } catch (e) {
    // Silent
  }
}

// Global error handler
self.addEventListener("error", function (event) {
  reportError(event.message, event.filename + ":" + event.lineno, {});
});

self.addEventListener("unhandledrejection", function (event) {
  var msg = event.reason ? event.reason.message || String(event.reason) : "Unhandled rejection";
  var stack = event.reason ? event.reason.stack || "" : "";
  reportError(msg, stack, {});
});

// ── Installation ──
chrome.runtime.onInstalled.addListener(function (details) {
  if (details.reason === "install") {
    log("First install — initializing storage");
    chrome.storage.local.set({
      user: null,
      plan: "free",
      emailsSentThisMonth: 0,
      accessToken: null,
      refreshToken: null,
      expiresAt: null,
    });
    // First-run welcome tab: without it a fresh install is pure silence —
    // the user must guess to open Outlook Web and find the round button.
    // One prospect reinstalled 9 times without ever finding sign-in
    // (2026-07-08), and a paying customer emailed support to ask where
    // the panel was. The page walks the 3 steps to a first campaign.
    try {
      chrome.tabs.create({ url: "https://getoutmass.com/welcome.html" });
    } catch (e) {
      log("Welcome tab failed:", e);
    }
  }
  log("Extension installed/updated:", details.reason);
  log("Redirect URI:", AZURE_REDIRECT_URI);

  // Set the URL Chrome opens when the user uninstalls the extension.
  // Best-effort: it requires a network connection and an open browser,
  // so it isn't guaranteed. We use it to (a) surface a reminder that
  // paid subscriptions are separate from the extension, and (b) collect
  // feedback on why the user left.
  //
  // Must run inside onInstalled because manifest.json doesn't support
  // a declarative uninstall URL in MV3. Re-setting on updates is cheap
  // and keeps us covered if the URL ever changes.
  try {
    chrome.runtime.setUninstallURL(
      "https://getoutmass.com/uninstall.html",
      function () {
        if (chrome.runtime.lastError) {
          log("setUninstallURL failed:", chrome.runtime.lastError.message);
        }
      }
    );
  } catch (e) {
    log("setUninstallURL threw:", e);
  }

  // Telemetry: install vs update
  if (details.reason === "install") {
    track("ext_installed", { version: chrome.runtime.getManifest().version });
  } else if (details.reason === "update") {
    track("ext_updated", {
      from_version: details.previousVersion || "unknown",
      to_version: chrome.runtime.getManifest().version,
    });
  }
});

// ── Microsoft OAuth 2.0 Flow (Web Auth — backend does code exchange) ──

/**
 * Start the Microsoft OAuth login flow (Web Auth Flow).
 * Opens MS auth page with backend callback URL. Backend does the code
 * exchange with client_secret, then redirects back to extension with
 * OutMass JWT in the URL fragment.
 */
// Single-flight guard for the OAuth flow. Rapid re-clicks on "Sign in" or a
// reconnect banner must NOT spawn multiple launchWebAuthFlow popups — we saw
// real users fire 6+ oauth_started in ~10s, stacking auth windows and logging
// spurious "did not approve" failures from the ones they closed. While a flow
// is in progress, every new request joins the SAME in-flight promise instead
// of launching another window. Keyed by flow type so a OneDrive incremental-
// consent flow and a plain sign-in don't return each other's result. The key
// is cleared when the flow settles (success OR cancel/error), so the next
// deliberate sign-in always starts fresh.
var _authFlightByKey = {};

function startMSLogin(includeOneDrive) {
  var key = includeOneDrive ? "onedrive" : "signin";
  if (_authFlightByKey[key]) {
    log("MS OAuth already in progress (" + key + ") — joining existing flow");
    return _authFlightByKey[key];
  }
  var flight = _startMSLoginInner(includeOneDrive);
  _authFlightByKey[key] = flight;
  var clear = function () { delete _authFlightByKey[key]; };
  flight.then(clear, clear);
  return flight;
}

async function _startMSLoginInner(includeOneDrive) {
  log("Starting MS OAuth flow (Web)...", includeOneDrive ? "with OneDrive scope" : "");
  track("oauth_started", { with_onedrive: !!includeOneDrive });

  // Extension tells backend where to redirect at the end (passed via state)
  const extRedirectUri = chrome.identity.getRedirectURL("auth");

  // Pass our own extension ID so the backend routes the final
  // chromiumapp.org redirect back to us (not to whatever AZURE_EXTENSION_ID
  // happens to be set to on Railway). The backend allowlists accepted
  // IDs — unknown IDs fall back to the env default.
  // `include_onedrive=true` triggers incremental consent: Microsoft
  // shows the consent screen only for the OneDrive scopes (the Mail
  // scopes are already approved from the original sign-in), and the
  // resulting token covers everything.
  const extId = chrome.runtime.id;
  // Sticky base: if the primary host is blocked on this network, the OAuth
  // flow must start from the base that actually answers.
  let authUrl =
    _backendBases()[0] + "/auth/login?ext=" + encodeURIComponent(extId);
  if (includeOneDrive) {
    authUrl += "&include_onedrive=true";
  }

  return new Promise((resolve) => {
    // One-shot auto-retry guard. The auth window's first navigation is our own
    // backend (/auth/login on Railway), so a cold / restarting / just-deployed
    // backend can make Chrome report "Authorization page could not be loaded."
    // We warm the backend and relaunch ONCE before giving up.
    let retried = false;

    function launch() {
      chrome.identity.launchWebAuthFlow(
        { url: authUrl, interactive: true },
        handleResult
      );
    }

    function handleResult(redirectUrl) {
      if (chrome.runtime.lastError) {
        const m = String(chrome.runtime.lastError.message || "");
        log("Auth flow error:", m);
        // Classify the Chrome WebAuthFlow error so the UI can show a helpful,
        // localized message instead of a raw string. The big one is
        // consent-declined: work/school (M365) tenants block end-user consent
        // for unverified multitenant apps, so the flow returns "did not
        // approve" — users need to know their org may require admin approval.
        let errorCode = "auth_failed";
        if (/did not approve|access was denied|consent_required/i.test(m)) {
          errorCode = "consent_declined";
        } else if (/could not be loaded|failed to load|page could not/i.test(m)) {
          errorCode = "auth_page_failed";
        }

        // Auto-retry ONCE when the authorization PAGE failed to load — almost
        // always a transient backend blip (cold start / restart / fresh deploy).
        // Wake the backend, then relaunch. Never retry consent declines: that's
        // a user/tenant decision, and reopening the window would only annoy.
        if (errorCode === "auth_page_failed" && !retried) {
          retried = true;
          log("Auth page failed to load — warming backend, retrying once");
          track("oauth_retry", { after: "auth_page_failed" });
          warmBackend(20000).then(launch);
          return;
        }

        resolve({ error: m, errorCode: errorCode });
        track("oauth_failed", { reason: "chrome_error", message: m.slice(0, 256), code: errorCode });
        return;
      }

      if (!redirectUrl) {
        resolve({ error: "No redirect URL received" });
        track("oauth_failed", { reason: "no_redirect" });
        return;
      }

      log("Auth redirect received");

      // Parse URL fragment (#jwt=...&email=...&name=...&plan=...)
      let fragment = "";
      try {
        const u = new URL(redirectUrl);
        fragment = u.hash.startsWith("#") ? u.hash.substring(1) : u.hash;
      } catch (e) {
        resolve({ error: "Invalid redirect URL" });
        track("oauth_failed", { reason: "invalid_redirect" });
        return;
      }

      const params = new URLSearchParams(fragment);
      const jwtToken = params.get("jwt");
      const email = params.get("email");
      const name = params.get("name");
      const plan = params.get("plan") || "free";
      const errorMsg = params.get("error");

      if (errorMsg) {
        resolve({ error: errorMsg });
        track("oauth_failed", { reason: "backend_error", code: String(errorMsg).slice(0, 64) });
        return;
      }

      if (!jwtToken || !email) {
        resolve({ error: "Incomplete auth response from backend" });
        track("oauth_failed", { reason: "incomplete_response" });
        return;
      }

      const user = { email: email, name: name || email };

      // Save auth state
      chrome.storage.local.set(
        {
          backendJwt: jwtToken,
          user: user,
          plan: plan,
          // Fresh JWT → clear any pending session-expired flag so the
          // sidebar banner hides on next poll.
          sessionExpired: false,
          // accessToken is managed server-side now; extension no longer needs it
          accessToken: null,
          refreshToken: null,
          expiresAt: null,
        },
        function () {
          log("LOGIN_SUCCESS:", email);
          // Backend doesn't return user_id in the redirect fragment today, so
          // we identify by email — PostHog accepts any string as distinct_id.
          identify(email);
          track("oauth_completed", { plan: plan });
          resolve({ error: null, user: user });
        }
      );
    }

    launch();
  });
}

/**
 * Best-effort warm-up of the OutMass backend before retrying the OAuth flow.
 *
 * The Railway web service can be momentarily unavailable — a cold start, a
 * crash-restart, or a fresh deploy with no readiness gate — during which the
 * auth window's first navigation (/auth/login) fails with "Authorization page
 * could not be loaded." Hitting the lightweight "/" health route wakes the
 * instance and blocks until it answers (or we time out), so the retried
 * launchWebAuthFlow lands on a backend that's actually ready. Never throws.
 */
async function warmBackend(timeoutMs) {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(function () { ctrl.abort(); }, timeoutMs || 15000);
    await fetch(_backendBases()[0] + "/", { method: "GET", cache: "no-store", signal: ctrl.signal });
    clearTimeout(timer);
    log("warmBackend: backend responded, retrying auth");
  } catch (e) {
    // Network error or timeout — relaunch anyway; the retry is still worthwhile.
    log("warmBackend: warm-up failed, retrying anyway:", e && e.message);
  }
}

/**
 * Make an authenticated request to the OutMass backend.
 */
// Track last successful backend contact for health check optimization
var _lastBackendOk = 0;
var HEALTH_CHECK_FRESHNESS_MS = 30000; // 30 seconds

// Which backend base answered last. Primary is api.getoutmass.com; some
// networks block one host or the other (railway.app is filtered outright in
// places), so whichever base works becomes sticky for this service-worker
// lifetime — users behind a blocked host pay the 20s timeout once, not on
// every request. MV3 restarts the worker often, so stickiness self-heals.
var _activeBackendBase = null;

function _backendBases() {
  var all = [OUTMASS_BACKEND_URL, OUTMASS_BACKEND_FALLBACK_URL].filter(
    function (b, i, arr) { return b && arr.indexOf(b) === i; }
  );
  if (_activeBackendBase && all.indexOf(_activeBackendBase) > -1) {
    return [_activeBackendBase].concat(all.filter(function (b) {
      return b !== _activeBackendBase;
    }));
  }
  return all;
}

async function backendFetch(endpoint, options) {
  let storage = await chrome.storage.local.get(["backendJwt"]);

  if (!storage.backendJwt) {
    // auth_required routes this to the sidebar's sign-in banner + a
    // localized "sign in first" alert. The raw English fallback string
    // cost us a zh-CN user who couldn't read it for two days (2026-07-14).
    return { error: "Not authenticated. Please login.", auth_required: true };
  }

  const headers = {
    "Content-Type": "application/json",
    Authorization: "Bearer " + storage.backendJwt,
    "X-Extension-Version": chrome.runtime.getManifest().version,
    ...(options?.headers || {}),
  };

  // Try each base in order; fall through to the next ONLY on fetch-level
  // (network:true) failures — an HTTP error is a real server answer and
  // must be surfaced, not retried against the other host.
  const bases = _backendBases();
  let result;
  for (const base of bases) {
    result = await _backendFetchOnce(base, endpoint, headers, options);
    if (!result.network) {
      _activeBackendBase = base;
      return result;
    }
  }
  return result; // every base unreachable → last network-failure shape
}

async function _backendFetchOnce(base, endpoint, headers, options) {
  // A request that can't reach the server otherwise hangs at the browser's
  // mercy (a zh-CN user watched Send spin ~8s per click against a network
  // that blocked our host, 2026-07-14). Cap it so callers fail fast and can
  // tell the user it's a CONNECTION problem.
  const controller = new AbortController();
  const timeoutTimer = setTimeout(() => controller.abort(), 20000);

  try {
    const resp = await fetch(base + endpoint, {
      method: options?.method || "GET",
      headers: headers,
      // Never serve authenticated API responses from the HTTP cache: the URL
      // is identical across users and Authorization isn't a cache key, so a
      // cached GET (e.g. /announcements, /settings) could leak the previous
      // account's data after switching accounts in the same browser.
      cache: "no-store",
      body: options?.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      // FastAPI puts our structured errors under errData.detail. For 402 we
      // want to preserve the actual `error` code (e.g. "feature_locked" vs
      // "limit_exceeded") so the frontend can show the right upgrade prompt
      // — not hardcode to "limit_exceeded".
      const detail = errData && errData.detail ? errData.detail : errData;
      if (resp.status === 402) {
        const code = (detail && typeof detail === "object" && detail.error) || "limit_exceeded";
        return { error: code, status: 402, detail: detail };
      }
      // Any endpoint can return {detail: {error: "<code>", message: "..."}}
      // and we'll surface the code to callers so they can show a
      // localized message. This replaces the old 402-only and 409-only
      // special cases with a general pattern.
      if (detail && typeof detail === "object" && detail.error) {
        return { error: detail.error, status: resp.status, detail: detail };
      }
      // 401 means our JWT is expired or invalid. Clear it and raise the
      // session-expired flag so the sidebar can show its reconnect banner
      // instead of a raw "Invalid or expired token" alert. The flag is
      // cleared by msLogin() on a successful re-auth.
      //
      // EXCEPT for `silent` (background/refresh) calls: a routine plan-refresh
      // on popup-open must never wipe auth on a single transient/edge 401 —
      // that dropped the popup to a hard login screen and re-prompted sign-in
      // in a loop. Silent callers just get the error; genuine expiry is still
      // caught by user-initiated calls and the sidebar's reconnect poll.
      if (resp.status === 401) {
        if (!options || !options.silent) {
          await chrome.storage.local.set({
            backendJwt: null,
            sessionExpired: true,
          });
        }
        return { error: "session_expired", status: 401 };
      }
      return { error: (detail && typeof detail === "string" ? detail : null) || `HTTP ${resp.status}` };
    }

    _lastBackendOk = Date.now();
    return { data: await resp.json(), error: null };
  } catch (err) {
    // fetch() rejecting means NO HTTP response ever arrived — offline, DNS
    // failure, a firewall/VPN/national filter blocking our host, or the 20s
    // timeout above. Flag it so the UI can say "connection problem, not your
    // account/plan" — a real user misread this exact failure as a paywall,
    // clicked Upgrade, then deleted their account.
    const timedOut = err && err.name === "AbortError";
    return {
      error: timedOut ? "network_timeout" : "network_unreachable",
      network: true,
      detail: String((err && err.message) || err),
    };
  } finally {
    clearTimeout(timeoutTimer);
  }
}

/**
 * Logout: clear all auth state.
 */
async function msLogout() {
  await chrome.storage.local.set({
    accessToken: null,
    refreshToken: null,
    expiresAt: null,
    user: null,
    backendJwt: null,
    // A deliberate sign-out must not leave the prior 401's session-expired
    // flag set, otherwise the reauth poll shows a wrong "session expired —
    // reconnect" banner. Clear it plus cached plan state so the next account
    // starts clean.
    sessionExpired: false,
    plan: "free",
    monthlyLimit: null,
    emailsSentThisMonth: 0,
  });
  log("User logged out, storage cleared");
}

// ── Outlook host resolution ──
// Which Outlook Web host to open for "Open Campaign Panel" when the user has no
// Outlook tab open. Hardcoding outlook.live.com (the PERSONAL host) bounced
// work/school (M365) accounts — whose mailbox lives on outlook.office.com — to
// a Microsoft sign-in page that they read as an endless OutMass login loop.
var VALID_OUTLOOK_ORIGINS = [
  "https://outlook.live.com",
  "https://outlook.office.com",
  "https://outlook.office365.com",
  // Microsoft is migrating work/school Outlook Web here tenant-by-tenant
  // (rollout started Nov 2025); office.com redirects to it for moved tenants.
  "https://outlook.cloud.microsoft",
];

var PERSONAL_OUTLOOK_DOMAINS = [
  "outlook.com", "hotmail.com", "live.com", "msn.com", "passport.com",
  "hotmail.co.uk", "live.co.uk", "outlook.co.uk",
];

function isPersonalOutlookEmail(email) {
  var domain = String(email || "").toLowerCase().split("@")[1] || "";
  return PERSONAL_OUTLOOK_DOMAINS.indexOf(domain) !== -1;
}

async function resolveOutlookMailUrl() {
  var s = await chrome.storage.local.get(["lastOutlookOrigin", "user"]);
  // 1) Reopen the exact host the user actually uses (content_script records it
  //    on every Outlook page load) — the most reliable signal.
  if (s.lastOutlookOrigin && VALID_OUTLOOK_ORIGINS.indexOf(s.lastOutlookOrigin) !== -1) {
    return s.lastOutlookOrigin + "/mail/";
  }
  // 2) No prior host yet: infer from the signed-in account. Personal Microsoft
  //    accounts use outlook.live.com; work/school (custom domain) use
  //    outlook.office.com. Default to office.com when unknown — work accounts
  //    are exactly the ones the old hardcode broke.
  var email = s.user && s.user.email;
  return isPersonalOutlookEmail(email)
    ? "https://outlook.live.com/mail/"
    : "https://outlook.office.com/mail/";
}

// ── Message Handler ──
chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  log("Message received:", message.type);

  switch (message.type) {
    case "MS_LOGIN":
      startMSLogin().then(function (result) {
        sendResponse(result);
      });
      return true; // async

    case "MS_LOGOUT":
      msLogout().then(function () {
        sendResponse({ success: true });
      });
      return true;

    case "GET_AUTH_TOKEN":
      getValidToken().then(function (result) {
        sendResponse({ token: result.token, error: result.error });
      });
      return true;

    case "GET_USER_STATE":
      chrome.storage.local.get(
        ["user", "plan", "emailsSentThisMonth", "backendJwt"],
        function (result) {
          var hasValidAuth = !!(result.user && result.backendJwt);

          if (!hasValidAuth) {
            sendResponse({
              user: null,
              plan: "free",
              emailsSentThisMonth: 0,
            });
            if (result.user && !result.backendJwt) {
              log("Stale user data found without JWT, clearing...");
              chrome.storage.local.remove(["user"]);
            }
            return;
          }

          // Refresh plan from backend (catches Stripe upgrades).
          // `silent`: a 401 on this background refresh must NOT clear the JWT
          // or it would log the user out on a mere popup-open (see backendFetch).
          if (result.backendJwt) {
            backendFetch("/settings", { silent: true }).then(function (resp) {
              if (resp && resp.data && resp.data.plan) {
                var freshPlan = resp.data.plan;
                // Cache the backend-derived monthly limit so the sidebar reads
                // it instead of hardcoding — raising a limit needs no extension
                // update. Stored alongside plan.
                var freshLimit = resp.data.monthly_limit;
                // Persist the real monthly count from the backend so the sidebar
                // quota bar + pre-send guard (which read storage) see the true
                // value instead of a stale 0 — a returning user was otherwise
                // ambushed by a 402 after creating a campaign.
                var freshSent = resp.data.emails_sent_this_month || 0;
                var _set = { emailsSentThisMonth: freshSent };
                if (freshPlan !== result.plan) _set.plan = freshPlan;
                if (freshLimit) _set.monthlyLimit = freshLimit;
                chrome.storage.local.set(_set);
                log("Plan/limit/count refreshed from backend:", freshPlan, freshLimit, freshSent);
                sendResponse({
                  user: result.user,
                  plan: freshPlan,
                  emailsSentThisMonth: freshSent,
                  monthlyLimit: freshLimit,
                });
              } else {
                sendResponse({
                  user: result.user,
                  plan: result.plan || "free",
                  emailsSentThisMonth: result.emailsSentThisMonth || 0,
                });
              }
            }).catch(function () {
              sendResponse({
                user: result.user,
                plan: result.plan || "free",
                emailsSentThisMonth: result.emailsSentThisMonth || 0,
              });
            });
          } else {
            sendResponse({
              user: result.user,
              plan: result.plan || "free",
              emailsSentThisMonth: result.emailsSentThisMonth || 0,
            });
          }
        }
      );
      return true;

    case "GET_USER_INFO":
      fetchUserProfile().then(function (profile) {
        sendResponse(profile);
      });
      return true;

    case "SEND_EMAIL":
      sendEmail(
        message.to,
        message.subject,
        message.body,
        message.trackingPixelUrl || null
      ).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "SYNC_AUTH":
      chrome.storage.local.get(["accessToken", "user"], function (storage) {
        if (!storage.accessToken || !storage.user) {
          sendResponse({ error: "Not logged in" });
          return;
        }
        syncAuthWithBackend(storage.accessToken, storage.user).then(function () {
          sendResponse({ success: true });
        });
      });
      return true;

    case "CREATE_CAMPAIGN":
      backendFetch("/campaigns", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "UPLOAD_CONTACTS":
      backendFetch("/campaigns/" + message.campaignId + "/contacts", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "SEND_CAMPAIGN":
      backendFetch("/campaigns/" + message.campaignId + "/send", {
        method: "POST",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_CAMPAIGNS":
      backendFetch("/campaigns" + (message.archived ? "?archived=true" : "")).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "TEST_SEND":
      // Legacy path (kept for older sidebar builds that still pre-create a campaign).
      backendFetch("/campaigns/" + message.campaignId + "/test-send", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "TEST_SEND_STATELESS":
      // Preferred: backend validates subject+body directly, no DB write.
      backendFetch("/campaigns/test-send", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "VALIDATE_TAGS":
      // Validate-only (no send) — used by Preview so it shows the same
      // merge-tag errors as Send/Test Send before opening the modal.
      backendFetch("/campaigns/validate-tags", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ARCHIVE_CAMPAIGN":
      backendFetch("/campaigns/" + message.campaignId + "/archive", {
        method: "POST",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "UNARCHIVE_CAMPAIGN":
      backendFetch("/campaigns/" + message.campaignId + "/unarchive", {
        method: "POST",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "EXPORT_CAMPAIGN_LIST":
      backendFetch("/campaigns/export-list").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_CAMPAIGN_STATS":
      backendFetch("/campaigns/" + message.campaignId + "/stats").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "EXPORT_CAMPAIGN_CSV":
      backendFetch("/campaigns/" + message.campaignId + "/export").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "CREATE_FOLLOWUP":
      backendFetch("/campaigns/" + message.campaignId + "/followups", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "CREATE_AB_TEST":
      backendFetch("/campaigns/" + message.campaignId + "/ab-test", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_AB_TEST":
      backendFetch("/campaigns/" + message.campaignId + "/ab-test").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "SAVE_TEMPLATE":
      backendFetch("/templates", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_TEMPLATES":
      backendFetch("/templates").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "DELETE_TEMPLATE":
      backendFetch("/templates/" + message.templateId, {
        method: "DELETE",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_SETTINGS":
      backendFetch("/settings").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "UPDATE_SETTINGS":
      backendFetch("/settings", {
        method: "PUT",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

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

    case "GET_SUPPRESSION_LIST":
      backendFetch("/settings/suppression").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ADD_SUPPRESSION":
      backendFetch("/settings/suppression", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "REMOVE_SUPPRESSION":
      backendFetch("/settings/suppression", {
        method: "DELETE",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "REPORT_ERROR":
      reportError(
        message.payload ? message.payload.message : "Unknown",
        message.payload ? message.payload.stack : "",
        { source: message.payload ? message.payload.source : "unknown" }
      );
      sendResponse({ status: "reported" });
      return false;

    case "AI_GENERATE_EMAIL":
      backendFetch("/ai/generate-email", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "SEND_FEEDBACK":
      backendFetch("/api/feedback", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      }).catch(function () {
        // Fallback: try without auth (feedback should work even if not logged in)
        fetch(_backendBases()[0] + "/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(message.payload),
        }).then(function () {
          sendResponse({ data: { status: "received" } });
        }).catch(function () {
          sendResponse({ error: "Failed to send feedback" });
        });
      });
      return true;

    case "CREATE_CHECKOUT":
      backendFetch("/billing/create-checkout", {
        method: "POST",
        body: { plan: message.plan || "pro" },
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "OPEN_PORTAL":
      backendFetch("/billing/portal").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "RESUME_CAMPAIGN":
      backendFetch("/campaigns/" + encodeURIComponent(message.campaignId) + "/resume", {
        method: "POST",
        body: {},
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ONEDRIVE_SHARE_LINK":
      backendFetch("/api/onedrive/share-link", {
        method: "POST",
        body: message.payload || {},
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ONEDRIVE_BROWSE":
      // Custom file picker fetches the user's OneDrive folder contents
      // through our backend (we hold the MS token server-side).
      var folderId =
        (message.payload && message.payload.folder_id) || "root";
      backendFetch(
        "/api/onedrive/browse?folder_id=" + encodeURIComponent(folderId)
      ).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "MS_LOGIN_ONEDRIVE":
      // Incremental consent flow: launches OAuth with the OneDrive
      // scopes added on top of the existing Mail grant. Microsoft
      // shows the consent screen for ONLY the new scopes (scopes
      // the user already approved are skipped automatically).
      startMSLogin(true).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "TRACK":
      track(message.event, message.properties || {});
      sendResponse({ ok: true });
      return false; // sync, no async response

    case "TRACK_ANONYMOUS":
      // Clear the user_id alias FIRST, then track — so the event attaches
      // to the anonymous distinct_id, not the signed-in email. Used for
      // account_deleted: we keep the churn signal (count) without tying it
      // to the identity the user just asked us to erase (GDPR-cleaner).
      resetIdentity().then(function () {
        track(message.event, message.properties || {});
      });
      sendResponse({ ok: true });
      return false; // sync ack; track runs async after reset

    case "DELETE_ACCOUNT":
      // backendFetch extracts the structured 409 code (e.g.
      // "active_subscription") into result.error, so the sidebar can
      // branch on it for a localized message.
      backendFetch("/account/delete", {
        method: "POST",
        body: message.payload || {},
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_BILLING_STATUS":
      backendFetch("/billing/status").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "OPEN_POPUP":
      chrome.action.openPopup();
      sendResponse({ success: true });
      break;

    case "COMPOSE_OPENED":
      log("Compose window opened in tab:", sender.tab?.id);
      sendResponse({ ack: true });
      break;

    case "SIDEBAR_TOGGLE":
      log("Sidebar toggled:", message.visible ? "open" : "closed");
      sendResponse({ ack: true });
      break;

    case "HEALTH_CHECK":
      // Skip ping if a backend call succeeded recently
      if (Date.now() - _lastBackendOk < HEALTH_CHECK_FRESHNESS_MS) {
        sendResponse({ ok: true });
        break;
      }
      // "Reachable" means ANY base answers — the fallback host counts, and
      // whichever responds becomes the sticky base for real API calls too.
      (async function () {
        var bases = _backendBases();
        for (var i = 0; i < bases.length; i++) {
          try {
            var resp = await fetch(bases[i] + "/", { method: "GET" });
            if (resp.ok) {
              _lastBackendOk = Date.now();
              _activeBackendBase = bases[i];
              sendResponse({ ok: true });
              return;
            }
          } catch (e) { /* try the next base */ }
        }
        sendResponse({ ok: false });
      })();
      return true; // async sendResponse

    case "OPEN_OUTLOOK_WITH_SIDEBAR":
      // Open the user's REAL Outlook host (work=office.com, personal=live.com),
      // not a hardcoded guess — see resolveOutlookMailUrl.
      resolveOutlookMailUrl().then(function (mailUrl) {
        chrome.tabs.create({ url: mailUrl }, function (newTab) {
          // Outlook boots slowly and may redirect across hosts mid-load
          // (office.com → cloud.microsoft for migrated tenants), so a single
          // post-"complete" message can fire while no content script exists
          // and the sidebar never opens. Retry until the content script acks.
          var attempts = 0;
          var timer = setInterval(function () {
            attempts++;
            if (attempts > 16) {
              clearInterval(timer);
              return;
            }
            chrome.tabs.sendMessage(newTab.id, { type: "SHOW_SIDEBAR" })
              .then(function (resp) {
                if (resp && resp.ack) clearInterval(timer);
              })
              .catch(function () {
                /* content script not ready yet (or tab closed) — keep trying */
              });
          }, 1500);
        });
      });
      sendResponse({ ack: true });
      break;

    default:
      log("Unknown message type:", message.type);
      sendResponse({ error: "Unknown message type" });
  }
});

// ── Alarms ──
// Follow-up email sending is handled server-side by Celery beat (hourly).
// This alarm refreshes campaign stats so the UI reflects follow-up results.
chrome.alarms.onAlarm.addListener(function (alarm) {
  log("Alarm fired:", alarm.name);

  if (alarm.name.startsWith("followup_")) {
    var campaignId = alarm.name.replace("followup_", "");
    log("Follow-up stats refresh for campaign:", campaignId);
    backendFetch("/campaigns/" + campaignId + "/stats").then(function (result) {
      if (result && result.data) {
        log("Campaign stats refreshed:", result.data);
      }
    }).catch(function (err) {
      log("Failed to refresh follow-up stats:", err);
    });
  }
});

log("Service worker started");
log("Redirect URI for Azure registration:", AZURE_REDIRECT_URI);
