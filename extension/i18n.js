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
