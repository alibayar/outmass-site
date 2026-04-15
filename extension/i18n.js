/**
 * OutMass — Internationalization Helper
 * Applies translations from chrome.i18n to DOM elements
 */

function applyI18n() {
  // Translate textContent
  document.querySelectorAll("[data-i18n]").forEach(function(el) {
    var key = el.getAttribute("data-i18n");
    var msg = chrome.i18n.getMessage(key);
    if (msg) el.textContent = msg;
  });
  // Translate placeholders
  document.querySelectorAll("[data-i18n-placeholder]").forEach(function(el) {
    var key = el.getAttribute("data-i18n-placeholder");
    var msg = chrome.i18n.getMessage(key);
    if (msg) el.placeholder = msg;
  });
  // Translate titles
  document.querySelectorAll("[data-i18n-title]").forEach(function(el) {
    var key = el.getAttribute("data-i18n-title");
    var msg = chrome.i18n.getMessage(key);
    if (msg) el.title = msg;
  });
  // Translate innerHTML (for elements with HTML content like hints)
  document.querySelectorAll("[data-i18n-html]").forEach(function(el) {
    var key = el.getAttribute("data-i18n-html");
    var msg = chrome.i18n.getMessage(key);
    if (msg) el.innerHTML = msg;
  });
  // RTL support for Arabic
  if (chrome.i18n.getUILanguage().startsWith("ar")) {
    document.documentElement.setAttribute("dir", "rtl");
  }
}

// Shortcut function for JS strings
function t(key, subs) {
  return chrome.i18n.getMessage(key, subs) || key;
}
