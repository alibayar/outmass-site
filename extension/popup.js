/**
 * OutMass — Popup
 * Real Microsoft OAuth 2.0 login flow with loading/error states
 */

(function () {
  "use strict";

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
  }

  function showError(message) {
    errorText.textContent = message || t("popupUnknownError");
    showSection("error");
  }

  // ── Login ──
  function doLogin() {
    showSection("loading");

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
        showError(response.error);
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
    "https://outlook.office365.com/*"
  ];

  function isOutlookUrl(url) {
    if (!url) return false;
    return (
      url.startsWith("https://outlook.live.com") ||
      url.startsWith("https://outlook.office.com") ||
      url.startsWith("https://outlook.office365.com")
    );
  }

  btnDashboard.addEventListener("click", function (e) {
    e.preventDefault();

    chrome.tabs.query(
      { active: true, currentWindow: true },
      function (tabs) {
        var activeTab = tabs[0];

        if (activeTab && isOutlookUrl(activeTab.url)) {
          // Active tab is Outlook — ensure sidebar is open
          chrome.tabs.sendMessage(activeTab.id, { type: "SHOW_SIDEBAR" });
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
                  chrome.tabs.sendMessage(outlookTab.id, { type: "SHOW_SIDEBAR" });
                  window.close();
                });
              });
            } else {
              // No Outlook tab open — ask background to open Outlook and toggle sidebar
              chrome.runtime.sendMessage({ type: "OPEN_OUTLOOK_WITH_SIDEBAR" });
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
          alert(t("portalErrorNoSubscription"));
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
