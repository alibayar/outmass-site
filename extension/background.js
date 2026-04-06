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

const LOG_PREFIX = "[OutMass-BG]";

function log(...args) {
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
});

// ── Microsoft OAuth 2.0 Flow ──

/**
 * Generate a random string for PKCE code verifier.
 */
function generateCodeVerifier() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return base64UrlEncode(array);
}

/**
 * Create SHA-256 code challenge from verifier (PKCE).
 */
async function generateCodeChallenge(verifier) {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return base64UrlEncode(new Uint8Array(digest));
}

/**
 * Base64-URL encode a Uint8Array.
 */
function base64UrlEncode(buffer) {
  let str = "";
  for (let i = 0; i < buffer.length; i++) {
    str += String.fromCharCode(buffer[i]);
  }
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * Start the Microsoft OAuth login flow.
 * Uses PKCE (no client secret needed for public clients).
 */
async function startMSLogin() {
  log("Starting MS OAuth flow...");

  const codeVerifier = generateCodeVerifier();
  const codeChallenge = await generateCodeChallenge(codeVerifier);

  const authUrl =
    MS_AUTH_ENDPOINT +
    "?client_id=" + encodeURIComponent(AZURE_CLIENT_ID) +
    "&response_type=code" +
    "&redirect_uri=" + encodeURIComponent(AZURE_REDIRECT_URI) +
    "&scope=" + encodeURIComponent(MS_SCOPES) +
    "&response_mode=query" +
    "&code_challenge=" + encodeURIComponent(codeChallenge) +
    "&code_challenge_method=S256" +
    "&prompt=select_account";

  return new Promise((resolve) => {
    chrome.identity.launchWebAuthFlow(
      { url: authUrl, interactive: true },
      async function (redirectUrl) {
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

        // Extract authorization code from redirect URL
        const url = new URL(redirectUrl);
        const code = url.searchParams.get("code");
        const error = url.searchParams.get("error");

        if (error) {
          const errorDesc = url.searchParams.get("error_description") || error;
          log("Auth error:", errorDesc);
          resolve({ error: errorDesc });
          return;
        }

        if (!code) {
          resolve({ error: "No authorization code received" });
          return;
        }

        // Exchange code for tokens
        const tokenResult = await exchangeCodeForTokens(code, codeVerifier);
        resolve(tokenResult);
      }
    );
  });
}

/**
 * Exchange authorization code for access + refresh tokens.
 */
async function exchangeCodeForTokens(code, codeVerifier) {
  try {
    const body = new URLSearchParams({
      client_id: AZURE_CLIENT_ID,
      grant_type: "authorization_code",
      code: code,
      redirect_uri: AZURE_REDIRECT_URI,
      code_verifier: codeVerifier,
      scope: MS_SCOPES,
    });

    const resp = await fetch(MS_TOKEN_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      log("Token exchange failed:", resp.status, errData);
      return {
        error: errData.error_description || `Token exchange failed (${resp.status})`,
      };
    }

    const tokens = await resp.json();
    const expiresAt = Date.now() + tokens.expires_in * 1000;

    // Save tokens to storage
    await chrome.storage.local.set({
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token || null,
      expiresAt: expiresAt,
    });

    log("Tokens saved, fetching user profile...");

    // Fetch user profile
    const profile = await fetchUserProfile();

    if (profile.error) {
      log("Profile fetch failed:", profile.error);
      // Tokens are saved, but we couldn't get profile
      return {
        error: null,
        user: { email: "Unknown", name: "Unknown" },
      };
    }

    const user = {
      email: profile.mail || "Unknown",
      name: profile.displayName || "Unknown",
    };

    // Save user info
    await chrome.storage.local.set({ user: user });

    log("LOGIN_SUCCESS:", user.email);

    // Sync with backend (wait for it so plan info is ready)
    await syncAuthWithBackend(tokens.access_token, user).catch(function (e) {
      log("Backend sync failed (non-blocking):", e.message);
    });

    return { error: null, user: user };
  } catch (err) {
    log("Token exchange error:", err.message);
    return { error: err.message };
  }
}

/**
 * Sync authentication with OutMass backend.
 * Sends MS access token → backend verifies → returns JWT.
 */
async function syncAuthWithBackend(msAccessToken, user) {
  try {
    // Get refresh token to store server-side for follow-up emails
    const storage = await chrome.storage.local.get(["refreshToken"]);

    const resp = await fetch(OUTMASS_BACKEND_URL + "/auth/microsoft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        access_token: msAccessToken,
        microsoft_id: user.microsoftId || "",
        email: user.email,
        name: user.name,
        refresh_token: storage.refreshToken || null,
      }),
    });

    if (!resp.ok) {
      log("Backend auth failed:", resp.status);
      return;
    }

    const data = await resp.json();
    await chrome.storage.local.set({
      backendJwt: data.jwt,
      plan: data.user.plan || "free",
      emailsSentThisMonth: data.user.emailsSentThisMonth || 0,
    });

    log("Backend sync OK, JWT saved, plan:", data.user.plan);
  } catch (err) {
    log("Backend sync error:", err.message);
  }
}

/**
 * Make an authenticated request to the OutMass backend.
 */
async function backendFetch(endpoint, options) {
  let storage = await chrome.storage.local.get(["backendJwt", "accessToken", "user"]);

  // Auto-sync if we have MS token but no backend JWT yet
  if (!storage.backendJwt && storage.accessToken && storage.user) {
    log("No backendJwt found, auto-syncing with backend...");
    await syncAuthWithBackend(storage.accessToken, storage.user);
    storage = await chrome.storage.local.get(["backendJwt", "accessToken"]);
  }

  if (!storage.backendJwt) {
    return { error: "Not synced with backend. Please re-login." };
  }

  const headers = {
    "Content-Type": "application/json",
    Authorization: "Bearer " + storage.backendJwt,
    ...(options?.headers || {}),
  };

  // Get a fresh MS token (refresh if expired)
  const tokenResult = await getValidToken();
  if (tokenResult.token) {
    headers["X-MS-Token"] = tokenResult.token;
  } else if (storage.accessToken) {
    headers["X-MS-Token"] = storage.accessToken;
  }

  try {
    const resp = await fetch(OUTMASS_BACKEND_URL + endpoint, {
      method: options?.method || "GET",
      headers: headers,
      body: options?.body ? JSON.stringify(options.body) : undefined,
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      if (resp.status === 402) {
        return { error: "limit_exceeded", status: 402, detail: errData.detail || errData };
      }
      return { error: errData.detail || `HTTP ${resp.status}` };
    }

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
        ["user", "plan", "emailsSentThisMonth", "accessToken"],
        function (result) {
          // Only return user if there is a real access token
          var hasValidAuth = !!(result.user && result.accessToken);
          sendResponse({
            user: hasValidAuth ? result.user : null,
            plan: result.plan || "free",
            emailsSentThisMonth: result.emailsSentThisMonth || 0,
          });

          // Clean up stale user data if token is missing
          if (result.user && !result.accessToken) {
            log("Stale user data found without token, clearing...");
            chrome.storage.local.remove(["user"]);
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
      backendFetch("/campaigns").then(function (result) {
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

    default:
      log("Unknown message type:", message.type);
      sendResponse({ error: "Unknown message type" });
  }
});

// ── Alarms (follow-up scheduler placeholder) ──
chrome.alarms.onAlarm.addListener(function (alarm) {
  log("Alarm fired:", alarm.name);

  if (alarm.name.startsWith("followup_")) {
    const campaignId = alarm.name.replace("followup_", "");
    log("Follow-up triggered for campaign:", campaignId);
    // TODO: Implement follow-up email sending via Graph API
  }
});

log("Service worker started");
log("Redirect URI for Azure registration:", AZURE_REDIRECT_URI);
