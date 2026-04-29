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
function reportError(message, stack, context) {
  try {
    fetch(OUTMASS_BACKEND_URL + "/api/error-report", {
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
});

// ── Microsoft OAuth 2.0 Flow (Web Auth — backend does code exchange) ──

/**
 * Start the Microsoft OAuth login flow (Web Auth Flow).
 * Opens MS auth page with backend callback URL. Backend does the code
 * exchange with client_secret, then redirects back to extension with
 * OutMass JWT in the URL fragment.
 */
async function startMSLogin(includeOneDrive) {
  log("Starting MS OAuth flow (Web)...", includeOneDrive ? "with OneDrive scope" : "");

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
  let authUrl =
    OUTMASS_BACKEND_URL + "/auth/login?ext=" + encodeURIComponent(extId);
  if (includeOneDrive) {
    authUrl += "&include_onedrive=true";
  }

  return new Promise((resolve) => {
    chrome.identity.launchWebAuthFlow(
      { url: authUrl, interactive: true },
      function (redirectUrl) {
        if (chrome.runtime.lastError) {
          log("Auth flow error:", chrome.runtime.lastError.message);
          resolve({ error: chrome.runtime.lastError.message });
          return;
        }

        if (!redirectUrl) {
          resolve({ error: "No redirect URL received" });
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
          return;
        }

        if (!jwtToken || !email) {
          resolve({ error: "Incomplete auth response from backend" });
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
            resolve({ error: null, user: user });
          }
        );
      }
    );
  });
}

/**
 * Make an authenticated request to the OutMass backend.
 */
// Track last successful backend contact for health check optimization
var _lastBackendOk = 0;
var HEALTH_CHECK_FRESHNESS_MS = 30000; // 30 seconds

async function backendFetch(endpoint, options) {
  let storage = await chrome.storage.local.get(["backendJwt"]);

  if (!storage.backendJwt) {
    return { error: "Not authenticated. Please login." };
  }

  const headers = {
    "Content-Type": "application/json",
    Authorization: "Bearer " + storage.backendJwt,
    ...(options?.headers || {}),
  };

  try {
    const resp = await fetch(OUTMASS_BACKEND_URL + endpoint, {
      method: options?.method || "GET",
      headers: headers,
      body: options?.body ? JSON.stringify(options.body) : undefined,
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
      if (resp.status === 401) {
        await chrome.storage.local.set({
          backendJwt: null,
          sessionExpired: true,
        });
        return { error: "session_expired", status: 401 };
      }
      return { error: (detail && typeof detail === "string" ? detail : null) || `HTTP ${resp.status}` };
    }

    _lastBackendOk = Date.now();
    return { data: await resp.json(), error: null };
  } catch (err) {
    return { error: err.message };
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
  });
  log("User logged out, storage cleared");
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

          // Refresh plan from backend (catches Stripe upgrades)
          if (result.backendJwt) {
            backendFetch("/settings").then(function (resp) {
              if (resp && resp.data && resp.data.plan) {
                var freshPlan = resp.data.plan;
                if (freshPlan !== result.plan) {
                  chrome.storage.local.set({ plan: freshPlan });
                  log("Plan refreshed from backend:", freshPlan);
                }
                sendResponse({
                  user: result.user,
                  plan: freshPlan,
                  emailsSentThisMonth: resp.data.emails_sent_this_month || 0,
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
        fetch(OUTMASS_BACKEND_URL + "/api/feedback", {
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
      fetch(OUTMASS_BACKEND_URL + "/", { method: "GET" })
        .then(function (resp) {
          if (resp.ok) _lastBackendOk = Date.now();
          sendResponse({ ok: resp.ok });
        })
        .catch(function () {
          sendResponse({ ok: false });
        });
      return true; // async sendResponse

    case "OPEN_OUTLOOK_WITH_SIDEBAR":
      chrome.tabs.create({ url: "https://outlook.live.com/mail/" }, function (newTab) {
        function onUpdated(tabId, changeInfo) {
          if (tabId === newTab.id && changeInfo.status === "complete") {
            chrome.tabs.onUpdated.removeListener(onUpdated);
            // Wait for content script to initialize after page load
            setTimeout(function () {
              chrome.tabs.sendMessage(newTab.id, { type: "SHOW_SIDEBAR" });
            }, 1500);
          }
        }
        chrome.tabs.onUpdated.addListener(onUpdated);
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
