/**
 * OutMass — Graph API Wrapper
 * All Microsoft Graph API calls go through here.
 * Imported by background.js via importScripts (MV3 service worker).
 */

const GRAPH_BASE = "https://graph.microsoft.com/v1.0";

/**
 * Get a valid access token, refreshing if expired.
 * Returns { token, error }
 */
async function getValidToken() {
  const data = await chrome.storage.local.get([
    "accessToken",
    "refreshToken",
    "expiresAt",
  ]);

  if (!data.accessToken) {
    return { token: null, error: "Not authenticated" };
  }

  // Token still valid (with 5-min buffer)
  if (data.expiresAt && Date.now() < data.expiresAt - 5 * 60 * 1000) {
    return { token: data.accessToken, error: null };
  }

  // Token expired — refresh it
  if (data.refreshToken) {
    log("[OutMass-BG] Token expired, refreshing...");
    const refreshResult = await refreshAccessToken(data.refreshToken);
    if (refreshResult.error) {
      return { token: null, error: refreshResult.error };
    }
    return { token: refreshResult.accessToken, error: null };
  }

  return { token: null, error: "Token expired and no refresh token" };
}

/**
 * Refresh the access token using the refresh token.
 */
async function refreshAccessToken(refreshToken) {
  try {
    const body = new URLSearchParams({
      client_id: AZURE_CLIENT_ID,
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      scope: MS_SCOPES,
    });

    const resp = await fetch(MS_TOKEN_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      log("[OutMass-BG] Token refresh failed:", resp.status, errData);
      // Clear auth state on refresh failure
      await chrome.storage.local.remove([
        "accessToken",
        "refreshToken",
        "expiresAt",
        "user",
      ]);
      return { error: errData.error_description || "Token refresh failed" };
    }

    const tokens = await resp.json();
    const expiresAt = Date.now() + tokens.expires_in * 1000;

    await chrome.storage.local.set({
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token || refreshToken,
      expiresAt: expiresAt,
    });

    log("[OutMass-BG] Token refreshed successfully");
    return { accessToken: tokens.access_token, error: null };
  } catch (err) {
    log("[OutMass-BG] Token refresh error:", err.message);
    return { error: err.message };
  }
}

/**
 * GET request to Graph API.
 */
async function graphGet(endpoint) {
  const { token, error } = await getValidToken();
  if (error) return { error };

  try {
    const resp = await fetch(`${GRAPH_BASE}${endpoint}`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (resp.status === 401) {
      // Token might have been revoked — clear auth
      await chrome.storage.local.remove([
        "accessToken",
        "refreshToken",
        "expiresAt",
        "user",
      ]);
      return { error: "Unauthorized — please login again" };
    }

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      return { error: errData.error?.message || `HTTP ${resp.status}` };
    }

    return { data: await resp.json(), error: null };
  } catch (err) {
    return { error: err.message };
  }
}

/**
 * POST request to Graph API.
 */
async function graphPost(endpoint, body) {
  const { token, error } = await getValidToken();
  if (error) return { error };

  try {
    const resp = await fetch(`${GRAPH_BASE}${endpoint}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    // Rate limited — wait and retry once
    if (resp.status === 429) {
      const retryAfter =
        parseInt(resp.headers.get("Retry-After"), 10) || 60;
      log("[OutMass-BG] Rate limited, retrying after", retryAfter, "seconds");
      await new Promise((resolve) => setTimeout(resolve, retryAfter * 1000));

      const retryResp = await fetch(`${GRAPH_BASE}${endpoint}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });

      if (!retryResp.ok) {
        const errData = await retryResp.json().catch(() => ({}));
        return { error: errData.error?.message || `HTTP ${retryResp.status}` };
      }

      // 202 = accepted (sendMail returns 202 with no body)
      if (retryResp.status === 202) return { data: null, error: null };
      return { data: await retryResp.json(), error: null };
    }

    if (resp.status === 401) {
      await chrome.storage.local.remove([
        "accessToken",
        "refreshToken",
        "expiresAt",
        "user",
      ]);
      return { error: "Unauthorized — please login again" };
    }

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      return { error: errData.error?.message || `HTTP ${resp.status}` };
    }

    // sendMail returns 202 with no body
    if (resp.status === 202) return { data: null, error: null };
    return { data: await resp.json(), error: null };
  } catch (err) {
    return { error: err.message };
  }
}

/**
 * Send an email via Microsoft Graph.
 * @param {string} to          — Recipient email address
 * @param {string} subject     — Email subject
 * @param {string} htmlBody    — HTML body content
 * @param {string|null} trackingPixelUrl — Optional tracking pixel URL
 * @returns {{ success: boolean, error?: string }}
 */
async function sendEmail(to, subject, htmlBody, trackingPixelUrl) {
  let finalBody = htmlBody;

  // Inject tracking pixel at end of body if provided
  if (trackingPixelUrl) {
    finalBody += `<img src="${trackingPixelUrl}" width="1" height="1" style="display:none" alt="" />`;
  }

  const payload = {
    message: {
      subject: subject,
      body: {
        contentType: "HTML",
        content: finalBody,
      },
      toRecipients: [
        {
          emailAddress: { address: to },
        },
      ],
    },
    saveToSentItems: true,
  };

  const result = await graphPost("/me/sendMail", payload);

  if (result.error) {
    return { success: false, error: result.error };
  }

  return { success: true };
}

/**
 * Fetch current user profile from Graph API.
 * @returns {{ displayName, mail, error? }}
 */
async function fetchUserProfile() {
  const result = await graphGet("/me");

  if (result.error) {
    return { error: result.error };
  }

  return {
    displayName: result.data.displayName,
    mail:
      result.data.mail ||
      result.data.userPrincipalName ||
      null,
    error: null,
  };
}
