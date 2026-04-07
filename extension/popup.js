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
    userName.textContent = user.name || user.email || "Bagli";
    userEmail.textContent = user.email || "";

    var planKey = plan || "free";
    var planLabel = planKey.charAt(0).toUpperCase() + planKey.slice(1);
    userPlan.textContent = planLabel;
    userPlan.className = "plan-badge " + planKey;

    // Show/hide upgrade and manage buttons
    var btnUpgrade = document.getElementById("btn-upgrade-popup");
    var btnManage = document.getElementById("btn-manage-sub");
    if (planKey === "free") {
      btnUpgrade.style.display = "block";
      btnUpgrade.textContent = "Yukselt \u2192 Standard ($15/ay)";
      btnManage.style.display = "none";
    } else if (planKey === "standard") {
      btnUpgrade.style.display = "block";
      btnUpgrade.textContent = "Yukselt \u2192 Pro ($25/ay)";
      btnManage.style.display = "block";
    } else {
      btnUpgrade.style.display = "none";
      btnManage.style.display = "block";
    }

    showSection("connected");
  }

  function showError(message) {
    errorText.textContent = message || "Bilinmeyen bir hata olustu.";
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
        showError("Yanit alinamadi.");
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
        showError("Kullanici bilgisi alinamadi.");
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
  var btnUpgradePopup = document.getElementById("btn-upgrade-popup");
  var btnManageSub = document.getElementById("btn-manage-sub");

  if (btnUpgradePopup) {
    btnUpgradePopup.addEventListener("click", function () {
      var currentPlan = userPlan.textContent.toLowerCase();
      var targetPlan = currentPlan === "standard" ? "pro" : "standard";
      chrome.runtime.sendMessage({ type: "CREATE_CHECKOUT", plan: targetPlan }, function (resp) {
        if (resp && resp.data && resp.data.checkout_url) {
          chrome.tabs.create({ url: resp.data.checkout_url });
          window.close();
        } else {
          alert("Odeme sayfasi olusturulamadi.");
        }
      });
    });
  }

  if (btnManageSub) {
    btnManageSub.addEventListener("click", function () {
      chrome.runtime.sendMessage({ type: "OPEN_PORTAL" }, function (resp) {
        if (resp && resp.data && resp.data.portal_url) {
          chrome.tabs.create({ url: resp.data.portal_url });
          window.close();
        } else {
          alert("Portal acilamadi.");
        }
      });
    });
  }

  // ── Init ──
  loadState();
})();
