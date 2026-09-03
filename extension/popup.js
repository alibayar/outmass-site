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
    renderPopupPrices();
  }

  // ── The price the popup used to keep for itself ──
  //
  // popupUpgradeStarter and popupUpgradePro read "Upgrade → Starter ($9/mo)"
  // until 2026-08-13, which put the price into the product a second time, in
  // fourteen message files. That is the shape that had docs/terms.html
  // promising a 50-email free tier for months after config.py said 250: a
  // number nobody remembers to change goes quietly wrong.
  //
  // The labels now name the plan only. The amount comes from Stripe via
  // /billing/status and is formatted in the reader's own locale — and when
  // the catalogue cannot be read the button carries no price at all, rather
  // than a stale one.
  function renderPopupPrices() {
    // Literal keys, not built from p.key: the i18n-usage suite can only check
    // what it can read, and a computed key is invisible to it.
    var labels = {
      starter: { id: "btn-upgrade-starter", text: t("popupUpgradeStarter") },
      pro: { id: "btn-upgrade-pro", text: t("popupUpgradePro") },
    };

    chrome.runtime.sendMessage({ type: "GET_BILLING_STATUS" }, function (resp) {
      var data = resp && (resp.data || resp);
      var plans = (data && data.plans) || [];
      if (!plans.length) return;

      var locale = getActiveLocale();

      plans.forEach(function (p) {
        var label = labels[p.key];
        if (!label) return;
        var el = document.getElementById(label.id);
        if (!el) return;

        var money;
        try {
          money = new Intl.NumberFormat(locale, {
            style: "currency",
            currency: (p.currency || "usd").toUpperCase(),
          }).format((p.amount || 0) / 100);
        } catch (e) {
          // A currency Intl cannot render must not blank the button.
          return;
        }

        // Rebuilt from the base label, never appended to whatever is already
        // there: loadState() runs again after a proration, and appending
        // would print the price twice.
        el.textContent = label.text + " · " + t("planPriceInterval", [money]);
      });
    });
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

  // `retry` decides whether the error section's only button is shown, and it
  // is not cosmetic: that button is wired to doLogin, so it means "start a
  // Microsoft sign-in" and nothing else. Every caller until 0.1.28 was an
  // auth failure, where that is exactly right. The deaf-tab message added in
  // 0.1.28 ("Extension updated. Please reload the page.") is not — it would
  // have put a Try Again button under a reload instruction and opened an
  // OAuth window for an already-signed-in user who pressed it.
  function showError(message, retry) {
    errorText.textContent = message || t("popupUnknownError");
    btnRetry.style.display = retry === false ? "none" : "";
    showSection("error");
  }

  // Map a classified OAuth failure to a helpful, localized message. The key
  // case is consent_declined: M365 work/school tenants block end-user consent
  // for unverified multitenant apps, so point the user at admin approval /
  // support / a personal account instead of showing a raw error string.
  function friendlyAuthError(resp) {
    var code = resp && resp.errorCode;
    // The backend's classification outranks everything below it: it read
    // Microsoft's actual response, while the codes underneath are inferred
    // from Chrome's wrapper or from the sentence itself. It also covers
    // classes we never had names for — a tenant block and a user's own
    // refusal both used to arrive here as consent_declined.
    if (resp && resp.msCode) {
      return msAuthMessage(resp.msCode, resp.error || t("popupUnknownError"));
    }
    if (code === "consent_declined") return t("authErrorConsent");
    if (code === "auth_page_failed") return t("authErrorPageLoad");
    if (code === "auth_window_already_open") return t("authWindowAlreadyOpen");
    // Not a failure: the 5-minute ceiling released the UI while the Microsoft
    // window is still open and still usable. Shipped 0.1.27 with a hardcoded
    // English string and no mapping here, so a non-English user got an
    // untranslated sentence that also told them the wrong thing.
    if (code === "auth_timeout") return t("authTimeout");
    return (resp && resp.error) || t("popupUnknownError");
  }

  // ── Login ──
  var _loginInFlight = false;

  function doLogin() {
    // One flight per click, and a held Enter key is not seven clicks.
    //
    // ravi@quick-hire.com fired seven complete signin_clicked → oauth_started
    // → oauth_failed triples inside 947 milliseconds on 2026-09-03, at a very
    // even 140ms apart — the signature of a key repeating on a focused
    // button, not of fingers. Every one of them landed on a Chrome auth
    // window that was already open and came back "Only one web auth flow is
    // allowed at a time".
    //
    // The sidebar's own sign-in button has disabled itself during the flow
    // since it was written; this one never did. The background single-flights
    // too, but that is a second line of defence, and it did not hold here.
    if (_loginInFlight) return;
    _loginInFlight = true;

    showSection("loading");

    track("signin_clicked", { context: "popup" });
    chrome.runtime.sendMessage({ type: "MS_LOGIN", context: "popup" }, function (response) {
      // Released on EVERY path out of this callback, before any branch can
      // return. A guard that leaks on one error path is worse than none: the
      // button would be dead until the popup is reopened, and the person it
      // fails on is the one already having trouble signing in.
      _loginInFlight = false;

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
          // Active tab is Outlook — ensure sidebar is open.
          //
          // The rejection here is "Could not establish connection. Receiving
          // end does not exist.", which we used to swallow as benign. It is
          // benign for the CODE and total failure for the USER: Chrome kills
          // the content script in every already-open tab when the extension
          // updates and never re-injects one (no "scripting" permission), so
          // that tab is deaf until it is reloaded. Ten versions shipped
          // 0.1.18 → 0.1.27, each minting this state in every long-lived
          // Outlook tab — the normal state for a mail tool. The old empty
          // catch plus window.close() on the next line meant the panel never
          // opened, nothing was said, and nothing was recorded: in PostHog a
          // user who tried five times looked identical to one who never came
          // back. window.close() now only runs on success.
          chrome.tabs.sendMessage(activeTab.id, { type: "SHOW_SIDEBAR" })
            .then(function () {
              window.close();
            })
            .catch(function () {
              track("panel_open_failed", { reason: "no_content_script" });
              showError(t("extUpdatedReload"), false);
            });
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
                  // Same deaf-tab case as above, and MORE likely here: this
                  // branch finds an Outlook tab the user left open in another
                  // window, which is exactly the tab most likely to predate
                  // the current build.
                  chrome.tabs.sendMessage(outlookTab.id, { type: "SHOW_SIDEBAR" })
                    .then(function () {
                      window.close();
                    })
                    .catch(function () {
                      track("panel_open_failed", { reason: "no_content_script_other_window" });
                      showError(t("extUpdatedReload"), false);
                    });
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
