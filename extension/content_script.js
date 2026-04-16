/**
 * OutMass — Content Script
 * Injects sidebar iframe into Outlook Web. Responds to toggle/show messages
 * from popup and background. No compose window injection (sidebar is opened
 * via extension popup or keyboard shortcut).
 */

(function () {
  "use strict";

  const LOG_PREFIX = "[OutMass-CS]";

  let sidebarIframe = null;
  let sidebarVisible = false;

  // ── Logging ──
  let _debugEnabled = false;
  chrome.storage.local.get("debug", function (r) { _debugEnabled = !!r.debug; });

  function log(...args) {
    if (!_debugEnabled) return;
    console.log(LOG_PREFIX, ...args);
  }

  // ── Error Reporting ──
  window.addEventListener("error", function (event) {
    try {
      chrome.runtime.sendMessage({
        type: "REPORT_ERROR",
        payload: { message: event.message, stack: event.filename + ":" + event.lineno, source: "content_script" },
      });
    } catch (e) { /* extension context may be invalid */ }
  });

  window.addEventListener("unhandledrejection", function (event) {
    try {
      var msg = event.reason ? event.reason.message || String(event.reason) : "Unhandled rejection";
      chrome.runtime.sendMessage({
        type: "REPORT_ERROR",
        payload: { message: msg, stack: "", source: "content_script" },
      });
    } catch (e) { /* extension context may be invalid */ }
  });

  // ── Sidebar ──
  function createSidebar() {
    if (sidebarIframe) return;

    const wrapper = document.createElement("div");
    wrapper.id = "outmass-sidebar-wrapper";

    const iframe = document.createElement("iframe");
    iframe.id = "outmass-sidebar-iframe";
    iframe.src = chrome.runtime.getURL("sidebar.html");

    wrapper.appendChild(iframe);
    document.body.appendChild(wrapper);
    sidebarIframe = wrapper;

    log("Sidebar iframe created");
  }

  function toggleSidebar() {
    if (!sidebarIframe) {
      createSidebar();
    }

    sidebarVisible = !sidebarVisible;
    sidebarIframe.style.display = sidebarVisible ? "block" : "none";

    log("Sidebar toggled:", sidebarVisible ? "open" : "closed");

    chrome.runtime.sendMessage({
      type: "SIDEBAR_TOGGLE",
      visible: sidebarVisible,
    });
  }

  // ── Message listener from sidebar (postMessage) ──
  window.addEventListener("message", function (event) {
    // Only accept messages from our extension's chrome-extension:// origin
    if (event.origin && !event.origin.startsWith("chrome-extension://")) return;

    if (event.data && event.data.source === "outmass-sidebar") {
      log("Message from sidebar:", event.data.type);

      if (event.data.type === "CLOSE_SIDEBAR") {
        if (sidebarVisible) {
          toggleSidebar();
        }
      }
    }
  });

  // ── Message listener from popup/background (chrome.runtime) ──
  chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
    if (message.type === "TOGGLE_SIDEBAR") {
      toggleSidebar();
      sendResponse({ ack: true });
    } else if (message.type === "SHOW_SIDEBAR") {
      // Only open, never close
      if (!sidebarVisible) {
        toggleSidebar();
      }
      sendResponse({ ack: true });
    }
  });

  log("Content script loaded on", location.hostname);
})();
