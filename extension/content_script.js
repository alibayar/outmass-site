/**
 * OutMass — Content Script
 * Outlook Web compose window detection + toolbar injection + sidebar management
 */

(function () {
  "use strict";

  function t(key, subs) { return chrome.i18n.getMessage(key, subs) || key; }

  const LOG_PREFIX = "[OutMass-CS]";
  const SIDEBAR_WIDTH = 380;
  const COMPOSE_SELECTORS = [
    '[aria-label="Message body"]',
    ".dFCbN",
    '[role="textbox"][aria-multiline="true"]',
  ];
  const TOOLBAR_SELECTORS = [
    '[role="toolbar"]',
    ".ms-CommandBar",
    ".dFCbN",
  ];

  let sidebarIframe = null;
  let sidebarVisible = false;
  let injectedComposeWindows = new WeakSet();

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

  // ── Toolbar Button ──
  function createOutMassButton() {
    const btn = document.createElement("button");
    btn.className = "outmass-toolbar-btn";
    btn.textContent = "\uD83D\uDCE7 " + t("toolbarButton");
    btn.title = t("toolbarButtonTitle");
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggleSidebar();
    });
    return btn;
  }

  function injectToolbarButton(composeElement) {
    if (injectedComposeWindows.has(composeElement)) return;

    // Walk up from compose body to find the toolbar
    let container = composeElement.closest('[role="dialog"]')
      || composeElement.closest('[role="main"]')
      || composeElement.parentElement;

    let toolbar = null;
    for (const sel of TOOLBAR_SELECTORS) {
      toolbar = container ? container.querySelector(sel) : document.querySelector(sel);
      if (toolbar) break;
    }

    if (!toolbar) {
      // Fallback: insert next to compose element's parent
      toolbar = composeElement.parentElement;
    }

    if (toolbar && !toolbar.querySelector(".outmass-toolbar-btn")) {
      const btn = createOutMassButton();
      toolbar.appendChild(btn);
      injectedComposeWindows.add(composeElement);
      log("Toolbar button injected");
    }
  }

  // ── Compose Detection ──
  function detectComposeWindows() {
    for (const selector of COMPOSE_SELECTORS) {
      const elements = document.querySelectorAll(selector);
      elements.forEach(function (el) {
        if (!injectedComposeWindows.has(el)) {
          log("Compose window detected");
          injectToolbarButton(el);

          chrome.runtime.sendMessage({ type: "COMPOSE_OPENED" }, function() {
            if (chrome.runtime.lastError) { /* ignore */ }
          });
        }
      });
    }
  }

  // ── MutationObserver ──
  function startObserver() {
    const observer = new MutationObserver(function (mutations) {
      let shouldCheck = false;
      for (const mutation of mutations) {
        if (mutation.addedNodes.length > 0) {
          shouldCheck = true;
          break;
        }
      }
      if (shouldCheck) {
        detectComposeWindows();
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });

    log("MutationObserver started");
    return observer;
  }

  // ── SPA Navigation Handler ──
  function handleSPANavigation() {
    let lastUrl = location.href;

    // Observe URL changes via popstate and pushState/replaceState
    const originalPushState = history.pushState;
    const originalReplaceState = history.replaceState;

    history.pushState = function () {
      originalPushState.apply(this, arguments);
      onUrlChange();
    };

    history.replaceState = function () {
      originalReplaceState.apply(this, arguments);
      onUrlChange();
    };

    window.addEventListener("popstate", onUrlChange);

    function onUrlChange() {
      const newUrl = location.href;
      if (newUrl !== lastUrl) {
        lastUrl = newUrl;
        log("SPA navigation detected:", newUrl);
        // Re-scan for compose windows after navigation
        setTimeout(detectComposeWindows, 500);
      }
    }
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

  // ── Init ──
  function init() {
    log("Content script loaded on", location.hostname);
    startObserver();
    handleSPANavigation();
    // Initial scan
    detectComposeWindows();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
