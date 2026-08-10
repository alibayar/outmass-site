/**
 * OutMass — Internationalization Helper
 *
 * Translation lookup priority:
 * 1. User's interface language override (chrome.storage.local.uiLanguage)
 * 2. Chrome UI language via chrome.i18n.getMessage
 *
 * The override lets users pick their preferred language regardless of
 * Chrome's UI language, which is also useful for testing AR/ZH/JA/etc.
 */

var _i18nOverride = null;
var _i18nOverrideLocale = null;
var _i18nReady = false;
var _i18nReadyCallbacks = [];

/**
 * Pre-load an override locale's messages.json if the user has picked one.
 * Call this BEFORE applyI18n() and t() to ensure the override is active.
 */
async function initI18n() {
  try {
    var result;
    // sidebar/popup run in extension context, so chrome.storage is available.
    // In Playwright file:// tests, chrome APIs are unavailable — fall through.
    if (typeof chrome === "undefined" || !chrome.storage || !chrome.storage.local) {
      _i18nReady = true;
      _flushReady();
      return;
    }
    result = await new Promise(function (resolve) {
      chrome.storage.local.get("uiLanguage", function (r) { resolve(r || {}); });
    });

    var lang = result.uiLanguage;
    if (lang && lang !== "auto") {
      // Normalize: zh-CN -> zh_CN (Chrome locale dir style)
      var localeDir = lang.replace("-", "_");
      try {
        var url = chrome.runtime.getURL("_locales/" + localeDir + "/messages.json");
        var resp = await fetch(url);
        if (resp.ok) {
          _i18nOverride = await resp.json();
          _i18nOverrideLocale = lang;
        }
      } catch (e) { /* keep null, falls back to chrome.i18n */ }
    }
  } catch (e) { /* ignore */ }

  _i18nReady = true;
  _flushReady();
}

/**
 * Return the active BCP-47 locale tag for `Intl`/`toLocaleString` use.
 *
 * Priority:
 *   1. User's Settings → Interface Language override (e.g. "tr", "zh-CN")
 *   2. Chrome's UI language
 *   3. navigator.language
 *   4. "en"
 *
 * We normalize underscores back to hyphens (Chrome locale dirs use
 * `zh_CN` but `Intl` wants `zh-CN`). Never returns the translations
 * dict by accident — callers used to confuse `_i18nOverride`
 * (the messages object) with the locale tag, which made
 * `toLocaleString` silently fall through to the OS default.
 */
function getActiveLocale() {
  var lang = _i18nOverrideLocale;
  if (!lang && typeof chrome !== "undefined" && chrome.i18n && chrome.i18n.getUILanguage) {
    try { lang = chrome.i18n.getUILanguage(); } catch (e) {}
  }
  if (!lang && typeof navigator !== "undefined" && navigator.language) {
    lang = navigator.language;
  }
  return (lang || "en").replace("_", "-");
}

function _flushReady() {
  var cbs = _i18nReadyCallbacks;
  _i18nReadyCallbacks = [];
  cbs.forEach(function (cb) { try { cb(); } catch (e) {} });
}

function whenI18nReady(cb) {
  if (_i18nReady) cb();
  else _i18nReadyCallbacks.push(cb);
}

/**
 * Substitute placeholders in a message template.
 *
 * Two substitution passes to match Chrome's native behavior:
 *   1. Named placeholders like $EMAIL$, $N$ — resolved via the entry's
 *      `placeholders` map (e.g. { email: { content: "$1" } }). Names are
 *      case-insensitive in the message text but lowercase in the map,
 *      per the Chrome extension i18n spec.
 *   2. Positional placeholders $1, $2, $3 — filled from `subs`.
 */
function _applySubs(message, placeholders, subs) {
  // Pass 1: named placeholders → positional (or literal) content
  if (placeholders) {
    for (var name in placeholders) {
      if (!Object.prototype.hasOwnProperty.call(placeholders, name)) continue;
      var content = placeholders[name] && placeholders[name].content;
      if (typeof content !== "string") continue;
      // Chrome treats $NAME$ case-insensitively. Escape the name for regex.
      var escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      var re = new RegExp("\\$" + escaped + "\\$", "gi");
      message = message.replace(re, content);
    }
  }
  // Pass 2: positional $1..$9
  if (subs && subs.length) {
    for (var i = 0; i < subs.length; i++) {
      message = message.split("$" + (i + 1)).join(subs[i]);
    }
  }
  // Pass 3: collapse Chrome's literal-dollar escape ($$ -> $), so a price
  // written as "$$9/mo" in messages.json renders as "$9/mo" on this override
  // path too (Chrome's native getMessage already collapses $$ -> $).
  message = message.split("$$").join("$");
  return message;
}

/**
 * Look up a translation.
 * Priority: override -> chrome.i18n -> key itself (fallback).
 */
function t(key, subs) {
  // 1. Override (if user picked a specific language)
  if (_i18nOverride && _i18nOverride[key] && _i18nOverride[key].message) {
    var entry = _i18nOverride[key];
    return _applySubs(entry.message, entry.placeholders, subs);
  }
  // 2. Chrome's i18n (auto-detects browser UI language, handles named
  //    placeholders itself via placeholders map in messages.json)
  if (typeof chrome !== "undefined" && chrome.i18n && chrome.i18n.getMessage) {
    var msg = chrome.i18n.getMessage(key, subs);
    if (msg) return msg;
  }
  // 3. Fallback: return the key itself (visible hint that i18n failed)
  return key;
}

/**
 * Microsoft sign-in failure classes, as named by the backend.
 *
 * The auth settle fragment carries two fields: `error` (an English sentence)
 * and `mcode` (this vocabulary). The sentence exists because every client
 * shipped up to 0.2.0 renders the fragment verbatim and cannot be changed;
 * the code exists so a newer client can say the same thing in the user's own
 * panel language, which the server cannot do — it does not know that
 * language, and guessing it from Accept-Language is the mistake the CSV
 * decoder made.
 *
 * Two pairs deliberately share a key: a missing client secret and an
 * unregistered redirect URI are both "we misconfigured this", and the two
 * app-rejection classes are both "our fault, not yours". The user does not
 * need our taxonomy, only the sentence — the distinction survives in
 * telemetry, which is where it is useful.
 *
 * Kept in sync with backend/routers/auth.py's _SETTLE_MESSAGES by
 * extension/tests/ms-auth-codes.test.js, which reads both files. A class
 * added on the server without an entry here would silently show English
 * forever.
 */
var MS_AUTH_MESSAGE_KEYS = {
  user_declined_consent: "authMsUserDeclinedConsent",
  consent_required: "authMsConsentRequired",
  admin_consent_required: "authMsAdminConsentRequired",
  user_not_assigned_to_app: "authMsUserNotAssigned",
  account_from_other_tenant: "authMsOtherTenant",
  blocked_by_conditional_access: "authMsConditionalAccess",
  mfa_required: "authMsMfaRequired",
  app_not_found_in_tenant: "authMsAppNotInTenant",
  client_secret_missing: "authMsMisconfigured",
  redirect_uri_not_registered: "authMsMisconfigured",
  app_registration_rejected: "authMsOurFault",
  app_not_authorized: "authMsOurFault",
  microsoft_server_error: "authMsMicrosoftError",
  microsoft_unavailable: "authMsMicrosoftBusy",
  unclassified_code: "authMsUnknownCode",
  no_code_from_microsoft: "authMsNoReason",
};

/**
 * The localized sentence for a backend failure class, or the server's own
 * English one when we have nothing better.
 *
 * Note t() returns the KEY itself when a lookup misses, not "" — so a
 * locale that has not been updated yet would otherwise put a raw
 * identifier like "authMsOurFault" in front of the user. Falling back to
 * the server sentence keeps them reading English rather than debris.
 */
function msAuthMessage(mcode, fallbackSentence) {
  var key = MS_AUTH_MESSAGE_KEYS[mcode];
  if (!key) return fallbackSentence;
  var msg = t(key);
  return msg && msg !== key ? msg : fallbackSentence;
}

function applyI18n() {
  // Translate textContent
  document.querySelectorAll("[data-i18n]").forEach(function (el) {
    var msg = t(el.getAttribute("data-i18n"));
    if (msg) el.textContent = msg;
  });
  // Translate placeholders
  document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
    var msg = t(el.getAttribute("data-i18n-placeholder"));
    if (msg) el.placeholder = msg;
  });
  // Translate titles
  document.querySelectorAll("[data-i18n-title]").forEach(function (el) {
    var msg = t(el.getAttribute("data-i18n-title"));
    if (msg) el.title = msg;
  });
  // Translate innerHTML (for elements with HTML content like hints)
  document.querySelectorAll("[data-i18n-html]").forEach(function (el) {
    var msg = t(el.getAttribute("data-i18n-html"));
    if (msg) el.innerHTML = msg;
  });

  // Determine effective language for direction
  var effectiveLang = _i18nOverrideLocale;
  if (!effectiveLang && typeof chrome !== "undefined" && chrome.i18n && chrome.i18n.getUILanguage) {
    effectiveLang = chrome.i18n.getUILanguage();
  }
  effectiveLang = (effectiveLang || "en").toLowerCase();

  // RTL support for Arabic (and other RTL scripts)
  if (effectiveLang.startsWith("ar") || effectiveLang.startsWith("he") || effectiveLang.startsWith("fa")) {
    document.documentElement.setAttribute("dir", "rtl");
    document.documentElement.setAttribute("lang", effectiveLang.split("_")[0].split("-")[0]);
  } else {
    document.documentElement.setAttribute("dir", "ltr");
    document.documentElement.setAttribute("lang", effectiveLang.split("_")[0].split("-")[0]);
  }
}
