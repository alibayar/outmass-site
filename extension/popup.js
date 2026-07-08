/**
 * OutMass — Popup
 * Real Microsoft OAuth 2.0 login flow with loading/error states
 */

(function () {
  "use strict";

  function track(eventName, properties) {
    try {
      chrome.runtime.sendMessage({
        type: "TRACK",
        event: eventName,
        properties: properties || {},
      });
    } catch (e) {
      /* never break popup code path */
    }
  }

  // ── Elements ──
  var loginSection = document.getElementById("login-section");
  var loadingSection = document.getElementById("loading-section");
  var errorSection = document.getElementById("error-section");
  var connectedSection = document.getElementById("connected-section");
  var btnLogin = document.getElementById("btn-login");
  var btnRetry = document.getElementById("btn-retry");
  var btnDashboard = document.getElementById("btn-dashboard");
  var btnLogout = document.getElementById("btn-logout");
  var userName = document.getElementById("user-name");
  var userEmail = document.getElementById("user-email");
  var userPlan = document.getElementById("user-plan");
  var errorText = document.getElementById("error-text");

  // Current plan, set in showConnected — lets the Manage Subscription
  // handler distinguish a real free user (needs to upgrade) from a
  // manually-granted paid plan (no Stripe customer to manage).
  var _currentPlan = "free";

  // ── State Management ──
  function showSection(name) {
    loginSection.style.display = "none";
    loadingSection.style.display = "none";
    errorSection.style.display = "none";
    connectedSection.style.display = "none";

    switch (name) {
      case "login":
        loginSection.style.display = "block";
        break;
      case "loading":
        loadingSection.style.display = "block";
        break;
      case "error":
        errorSection.style.display = "block";
        break;
      case "connected":
        connectedSection.style.display = "block";
        break;
    }
  }

  // ── Load State ──
  function loadState() {
    chrome.runtime.sendMessage({ type: "GET_USER_STATE" }, function (response) {
      if (chrome.runtime.lastError) {
        showSection("login");
        return;
      }

      if (response && response.user && response.user.email) {
        showConnected(response.user, response.plan);
      } else {
        showSection("login");
      }
    });
  }

  function showConnected(user, plan) {
    userName.textContent = user.name || user.email || t("popupConnected");
    userEmail.textContent = user.email || "";

    var planKey = plan || "free";
    _currentPlan = planKey;
    var planLabel = planKey.charAt(0).toUpperCase() + planKey.slice(1);
    userPlan.textContent = planLabel;
    userPlan.className = "plan-badge " + planKey;

    // Show/hide upgrade and manage buttons
    var btnUpgradeStarter = document.getElementById("btn-upgrade-starter");
    var btnUpgradePro = document.getElementById("btn-upgrade-pro");
    var btnManage = document.getElementById("btn-manage-sub");
    if (planKey === "free") {
      // Free user can pick either Starter or Pro directly
      btnUpgradeStarter.style.display = "block";
      btnUpgradePro.style.display = "block";
      btnManage.style.display = "none";
    } else if (planKey === "starter") {
      // Starter user can upgrade to Pro
      btnUpgradeStarter.style.display = "none";
      btnUpgradePro.style.display = "block";
      btnManage.style.display = "block";
    } else {
      // Pro user — only manage subscription
      btnUpgradeStarter.style.display = "none";
      btnUpgradePro.style.display = "none";
      btnManage.style.display = "block";
    }

    showSection("connected");
    loadPopupAnnouncements();
  }

  // ── Announcements ──
  // Only treat http(s) CTA URLs as links (defense-in-depth: never let a
  // javascript:/data: URL become a clickable link in the popup DOM).
  function safeCtaUrl(u) {
    return (typeof u === "string" && /^https?:\/\//i.test(u)) ? u : null;
  }

  function semverGte(a, b) {
    var pa = String(a).split("."), pb = String(b).split(".");
    for (var i = 0; i < Math.max(pa.length, pb.length); i++) {
      var na = parseInt(pa[i] || "0", 10), nb = parseInt(pb[i] || "0", 10);
      if (na > nb) return true;
      if (na < nb) return false;
    }
    return true;
  }

  function openSidebarPanel() {
    // reuse the existing dashboard button flow to open the sidebar
    document.getElementById("btn-dashboard").click();
  }

  function loadPopupAnnouncements() {
    var box = document.getElementById("popup-announcements");
    if (!box) return;
    chrome.runtime.sendMessage({ type: "GET_ANNOUNCEMENTS" }, function (resp) {
      if (!resp || resp.error) return;
      var data = resp.data || resp;
      var v = chrome.runtime.getManifest().version;
      var items = (data.announcements || []).filter(function (a) {
        return !a.version || semverGte(v, a.version);
      });
      var unread = items.filter(function (a) { return !a.read; });
      if (!unread.length) { box.style.display = "none"; return; }
      box.style.display = "block";
      box.innerHTML = "";
      var a = unread[0];
      var card = document.createElement("div"); card.className = "pa-card";
      var title = document.createElement("div"); title.className = "pa-title"; title.textContent = a.title;
      var body = document.createElement("div"); body.className = "pa-body"; body.textContent = a.body;
      card.appendChild(title); card.appendChild(body);
      var actions = document.createElement("div"); actions.className = "pa-actions";
      var url = safeCtaUrl(a.cta_url);
      if (url && a.cta_label) {
        var link = document.createElement("a"); link.className = "pa-cta";
        link.textContent = a.cta_label; link.href = url; link.target = "_blank"; link.rel = "noopener";
        actions.appendChild(link);
      } else { actions.appendChild(document.createElement("span")); }
      var dis = document.createElement("button"); dis.className = "pa-dismiss";
      dis.textContent = t("announcementsDismiss");
      dis.addEventListener("click", function () {
        chrome.runtime.sendMessage({ type: "ANNOUNCEMENT_DISMISS", id: a.id });
        box.style.display = "none";
      });
      actions.appendChild(dis); card.appendChild(actions); box.appendChild(card);
      if (unread.length > 1) {
        var more = document.createElement("div"); more.className = "pa-more";
        more.textContent = t("announcementsMore", [String(unread.length - 1)]);
        more.addEventListener("click", openSidebarPanel);
        box.appendChild(more);
      }
      // showing the popup message marks the top item read
      chrome.runtime.sendMessage({ type: "ANNOUNCEMENT_READ", id: a.id });
    });
  }

  function showError(message) {
    errorText.textContent = message || t("popupUnknownError");
    showSection("error");
  }

  // Map a classified OAuth failure to a helpful, localized message. The key
  // case is consent_declined: M365 work/school tenants block end-user consent
  // for unverified multitenant apps, so point the user at admin approval /
  // support / a personal account instead of showing a raw error string.
  function friendlyAuthError(resp) {
    var code = resp && resp.errorCode;
    if (code === "consent_declined") return t("authErrorConsent");
    if (code === "auth_page_failed") return t("authErrorPageLoad");
    return (resp && resp.error) || t("popupUnknownError");
  }

  // ── Login ──
  function doLogin() {
    showSection("loading");

    track("signin_clicked", { context: "popup" });
    chrome.runtime.sendMessage({ type: "MS_LOGIN" }, function (response) {
      if (chrome.runtime.lastError) {
        showError(chrome.runtime.lastError.message);
        return;
      }

      if (!response) {
        showError(t("popupNoResponse"));
        return;
      }

      if (response.error) {
        showError(friendlyAuthError(response));
        return;
      }

      if (response.user) {
        // Reload full state to get plan info too
        loadState();
      } else {
        showError(t("popupUserInfoFailed"));
      }
    });
  }

  btnLogin.addEventListener("click", doLogin);
  btnRetry.addEventListener("click", doLogin);

  // ── Logout ──
  btnLogout.addEventListener("click", function () {
    chrome.runtime.sendMessage({ type: "MS_LOGOUT" }, function () {
      showSection("login");
    });
  });

  // ── Dashboard ──
  var outlookPatterns = [
    "https://outlook.live.com/*",
    "https://outlook.office.com/*",
    "https://outlook.office365.com/*",
    "https://outlook.cloud.microsoft/*"
  ];

  function isOutlookUrl(url) {
    if (!url) return false;
    return (
      url.startsWith("https://outlook.live.com") ||
      url.startsWith("https://outlook.office.com") ||
      url.startsWith("https://outlook.office365.com") ||
      url.startsWith("https://outlook.cloud.microsoft")
    );
  }

  btnDashboard.addEventListener("click", function (e) {
    e.preventDefault();

    chrome.tabs.query(
      { active: true, currentWindow: true },
      function (tabs) {
        var activeTab = tabs[0];

        if (activeTab && isOutlookUrl(activeTab.url)) {
          // Active tab is Outlook — ensure sidebar is open. The .catch swallows
          // the benign "Could not establish connection. Receiving end does not
          // exist." that fires when the content script isn't in this tab yet
          // (e.g. an Outlook tab opened before the extension loaded/updated).
          chrome.tabs.sendMessage(activeTab.id, { type: "SHOW_SIDEBAR" }).catch(function () {});
          window.close();
        } else {
          // Not on Outlook — find an existing Outlook tab or open one
          chrome.tabs.query({}, function (allTabs) {
            var outlookTab = allTabs.find(function (t) {
              return isOutlookUrl(t.url);
            });

            if (outlookTab) {
              // Focus existing Outlook tab and ensure sidebar is open
              chrome.tabs.update(outlookTab.id, { active: true }, function () {
                chrome.windows.update(outlookTab.windowId, { focused: true }, function () {
                  chrome.tabs.sendMessage(outlookTab.id, { type: "SHOW_SIDEBAR" }).catch(function () {});
                  window.close();
                });
              });
            } else {
              // No Outlook tab open — ask background to open Outlook and toggle sidebar
              chrome.runtime.sendMessage({ type: "OPEN_OUTLOOK_WITH_SIDEBAR" }).catch(function () {});
              window.close();
            }
          });
        }
      }
    );
  });

  // ── Billing ──
  var btnUpgradeStarterEl = document.getElementById("btn-upgrade-starter");
  var btnUpgradeProEl = document.getElementById("btn-upgrade-pro");
  var btnManageSub = document.getElementById("btn-manage-sub");

  function startCheckout(plan) {
    track("upgrade_button_clicked", { context: "popup" });
    chrome.runtime.sendMessage({ type: "CREATE_CHECKOUT", plan: plan }, function (resp) {
      if (resp && resp.data && resp.data.checkout_url) {
        // New subscription — open Stripe Checkout
        chrome.tabs.create({ url: resp.data.checkout_url });
        window.close();
      } else if (resp && resp.data && resp.data.modified) {
        // Existing subscription — modified in place with proration
        alert(t("upgradeSuccessProrated"));
        loadState(); // refresh plan badge
      } else {
        var errMsg = (resp && resp.error) || t("popupUnknownError");
        alert(t("popupCheckoutFailed") + errMsg);
      }
    });
  }

  if (btnUpgradeStarterEl) {
    btnUpgradeStarterEl.addEventListener("click", function () { startCheckout("starter"); });
  }
  if (btnUpgradeProEl) {
    btnUpgradeProEl.addEventListener("click", function () { startCheckout("pro"); });
  }

  if (btnManageSub) {
    btnManageSub.addEventListener("click", function () {
      chrome.runtime.sendMessage({ type: "OPEN_PORTAL" }, function (resp) {
        if (resp && resp.data && resp.data.portal_url) {
          chrome.tabs.create({ url: resp.data.portal_url });
          window.close();
          return;
        }
        // Branch on structured error codes (see billing.py /portal)
        // so the message is localized, not raw English from the server.
        var code = resp && resp.error;
        if (code === "no_stripe_customer") {
          // A paid plan with no Stripe customer was granted manually (e.g. a
          // promo) and can't be managed via the billing portal. A genuine
          // free user, on the other hand, just needs to upgrade first.
          if (_currentPlan && _currentPlan !== "free") {
            alert(t("portalErrorManualPlan"));
          } else {
            alert(t("portalErrorNoSubscription"));
          }
          return;
        }
        if (code === "stripe_not_configured") {
          alert(t("portalErrorNotConfigured"));
          return;
        }
        var detail = code ? "\n\n" + code : "";
        alert(t("popupPortalFailed") + detail);
      });
    });
  }

  // ── Init ──
  // Footer version: always read from the manifest so it can never drift
  // out of sync with the actual published version.
  var _versionEl = document.getElementById("popup-version");
  if (_versionEl) {
    _versionEl.textContent = "OutMass v" + chrome.runtime.getManifest().version;
  }

  if (typeof initI18n === "function") {
    initI18n().then(function () {
      applyI18n();
      loadState();
    });
  } else {
    applyI18n();
    loadState();
  }
})();
