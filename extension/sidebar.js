/**
 * OutMass — Sidebar
 * Campaign creation UI inside iframe
 */

(function () {
  "use strict";

  var LOG_PREFIX = "[OutMass-Sidebar]";
  var csvRawText = null; // Raw CSV string for backend upload
  var _debugEnabled = false;

  try {
    chrome.storage.local.get("debug", function (r) { _debugEnabled = !!r.debug; });
  } catch (e) { /* chrome API unavailable in test environment */ }

  function log() {
    if (!_debugEnabled) return;
    var args = [LOG_PREFIX];
    for (var i = 0; i < arguments.length; i++) args.push(arguments[i]);
    console.log.apply(console, args);
  }

  var OUTLOOK_ORIGINS = [
    "https://outlook.live.com",
    "https://outlook.office.com",
    "https://outlook.office365.com"
  ];

  // ── Error Reporting ──
  window.addEventListener("error", function (event) {
    chrome.runtime.sendMessage({
      type: "REPORT_ERROR",
      payload: { message: event.message, stack: event.filename + ":" + event.lineno, source: "sidebar" },
    });
  });

  window.addEventListener("unhandledrejection", function (event) {
    var msg = event.reason ? event.reason.message || String(event.reason) : "Unhandled rejection";
    chrome.runtime.sendMessage({
      type: "REPORT_ERROR",
      payload: { message: msg, stack: "", source: "sidebar" },
    });
  });

  // ── Elements ──
  var tabs = document.querySelectorAll(".tab");
  var tabContents = document.querySelectorAll(".tab-content");
  var btnClose = document.getElementById("btn-close");
  var csvDropzone = document.getElementById("csv-dropzone");
  var csvInput = document.getElementById("csv-input");
  var csvInfo = document.getElementById("csv-info");
  var csvFilename = document.getElementById("csv-filename");
  var csvCount = document.getElementById("csv-count");
  var btnClearCsv = document.getElementById("btn-clear-csv");
  var subjectInput = document.getElementById("subject");
  var bodyInput = document.getElementById("body");
  var btnPreview = document.getElementById("btn-preview");
  var btnSend = document.getElementById("btn-send");
  var quotaText = document.getElementById("quota-text");
  var quotaFill = document.getElementById("quota-fill");

  var csvData = null;

  // ── Re-auth banner ──
  // Backend flags users whose Microsoft refresh_token stopped working.
  // We call GET_SETTINGS periodically anyway; pipe the requires_reauth
  // field into a banner + sign-in button so scheduled sends don't die
  // silently.
  // Banner shows for two distinct situations, both fixed by signing in:
  //  - requires_reauth: MS refresh_token died (backend flag)
  //  - sessionExpired: our own JWT expired (backendFetch 401)
  // The CTA is identical (MS_LOGIN) but the explanatory text differs so
  // the user isn't confused about what broke.
  function updateReauthBanner(requiresMsReauth, sessionExpired) {
    var banner = document.getElementById("reauth-banner");
    if (!banner) return;
    var show = !!(requiresMsReauth || sessionExpired);
    banner.style.display = show ? "flex" : "none";
    if (!show) return;
    var textEl = banner.querySelector(".reauth-banner-text");
    if (textEl) {
      // Session-expired takes precedence if both true — it's the more
      // immediate, always-recoverable case.
      textEl.textContent = sessionExpired
        ? t("sessionExpiredBannerText")
        : t("reauthBannerText");
    }
  }

  var reauthBtn = document.getElementById("reauth-banner-btn");
  if (reauthBtn) {
    reauthBtn.addEventListener("click", function () {
      reauthBtn.disabled = true;
      reauthBtn.textContent = "…";
      // Fresh OAuth flow. On success, backend clears the flag; on next
      // GET_SETTINGS, banner hides.
      chrome.runtime.sendMessage({ type: "MS_LOGIN" }, function (resp) {
        reauthBtn.disabled = false;
        reauthBtn.textContent = t("reauthBannerCta");
        if (resp && resp.error) {
          alert(t("reauthFailed", [resp.error]));
          return;
        }
        // Refresh settings so banner hides (backend cleared the flag,
        // and MS_LOGIN success cleared our local sessionExpired flag).
        chrome.runtime.sendMessage({ type: "GET_SETTINGS" }, function (r) {
          var data = r && (r.data || r);
          chrome.storage.local.get(["sessionExpired"], function (s) {
            updateReauthBanner(
              !!(data && data.requires_reauth),
              !!(s && s.sessionExpired)
            );
          });
        });
      });
    });
  }

  // Short-circuit backend error handlers when the JWT has expired.
  // If `resp.error === "session_expired"`, the reconnect banner is the
  // user's signal to act — we don't want to also pop a modal with the
  // raw error string. Callers wrap: `if (!handleSessionExpired(resp)) alert(...)`.
  function handleSessionExpired(resp) {
    if (resp && resp.error === "session_expired") {
      pollReauthState();
      return true;
    }
    return false;
  }

  function pollReauthState() {
    chrome.runtime.sendMessage({ type: "GET_SETTINGS" }, function (resp) {
      // Always read the session-expired flag — even a failed /settings
      // call (e.g. when JWT has just expired) should surface the banner.
      chrome.storage.local.get(["sessionExpired"], function (s) {
        var sessionExpired = !!(s && s.sessionExpired);
        var requiresReauth = false;
        if (resp && !resp.error) {
          var data = resp.data || resp;
          requiresReauth = !!(data && data.requires_reauth);
        }
        updateReauthBanner(requiresReauth, sessionExpired);
      });
    });
  }

  // ── Tabs ──
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      var target = tab.getAttribute("data-tab");

      tabs.forEach(function (t) { t.classList.remove("active"); });
      tabContents.forEach(function (tc) { tc.classList.remove("active"); });

      tab.classList.add("active");
      document.getElementById("tab-" + target).classList.add("active");

      if (target === "reports") {
        loadReports();
      }
      if (target === "settings") {
        loadSettings();
      }
      if (target === "account") {
        loadAccount();
      }

      log("Tab switched to:", target);
    });
  });

  // ── Close ──
  btnClose.addEventListener("click", function () {
    try {
      OUTLOOK_ORIGINS.forEach(function (origin) {
        window.parent.postMessage({ source: "outmass-sidebar", type: "CLOSE_SIDEBAR" }, origin);
      });
    } catch (e) { /* postMessage may fail in test/non-iframe context */ }
  });

  // ── CSV Upload ──
  csvDropzone.addEventListener("click", function () {
    csvInput.click();
  });

  csvDropzone.addEventListener("dragover", function (e) {
    e.preventDefault();
    csvDropzone.classList.add("dragover");
  });

  csvDropzone.addEventListener("dragleave", function () {
    csvDropzone.classList.remove("dragover");
  });

  csvDropzone.addEventListener("drop", function (e) {
    e.preventDefault();
    csvDropzone.classList.remove("dragover");
    var files = e.dataTransfer.files;
    if (files.length > 0 && files[0].name.endsWith(".csv")) {
      handleCSV(files[0]);
    }
  });

  csvInput.addEventListener("change", function () {
    if (csvInput.files.length > 0) {
      handleCSV(csvInput.files[0]);
    }
  });

  // RFC 4180 compliant CSV line parser — handles quoted fields, escaped quotes
  function parseCSVLine(line) {
    var result = [];
    var current = "";
    var inQuotes = false;
    for (var i = 0; i < line.length; i++) {
      var ch = line[i];
      if (inQuotes) {
        if (ch === '"' && i + 1 < line.length && line[i + 1] === '"') {
          current += '"';
          i++;
        } else if (ch === '"') {
          inQuotes = false;
        } else {
          current += ch;
        }
      } else {
        if (ch === '"') {
          inQuotes = true;
        } else if (ch === ',') {
          result.push(current.trim());
          current = "";
        } else {
          current += ch;
        }
      }
    }
    result.push(current.trim());
    return result;
  }

  var CSV_MAX_BYTES = 5 * 1024 * 1024; // 5 MB (backend enforces same limit)

  function handleCSV(file) {
    // A.3: size limit check before reading
    if (file.size > CSV_MAX_BYTES) {
      alert(t("csvErrTooLarge"));
      return;
    }
    var reader = new FileReader();
    reader.onload = function (e) {
      var text = e.target.result;
      // A.3: strip UTF-8 BOM
      if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);
      // A.3: reject botched encoding (replacement chars)
      if (text.indexOf("\uFFFD") >= 0) {
        alert(t("csvErrEncoding"));
        return;
      }
      csvRawText = text; // keep (normalized) raw CSV for backend upload
      var lines = text.trim().split(/\r?\n/);
      var headers = parseCSVLine(lines[0]).map(function (h) { return h.trim(); });
      var lowerHeaders = headers.map(function (h) { return h.toLowerCase(); });
      // A.3: mandatory email column
      if (lowerHeaders.indexOf("email") < 0) {
        alert(t("csvErrNoEmailColumn"));
        return;
      }
      var rows = [];
      var seen = {};
      var dupCount = 0;
      for (var i = 1; i < lines.length; i++) {
        if (!lines[i].trim()) continue; // skip empty lines
        var values = parseCSVLine(lines[i]);
        var row = {};
        headers.forEach(function (h, idx) {
          row[h] = values[idx] !== undefined ? values[idx] : "";
        });
        // A.1 mirror: lowercase + dedupe on email
        var em = (row.email || row.Email || row.EMAIL || "").trim().toLowerCase();
        if (!em) continue;
        row.email = em;
        if (seen[em]) { dupCount++; continue; }
        seen[em] = true;
        rows.push(row);
      }

      csvData = { headers: headers, rows: rows };

      csvDropzone.style.display = "none";
      csvInfo.style.display = "flex";
      csvFilename.textContent = file.name;
      var msg = rows.length + " " + t("csvCountSuffix");
      if (dupCount > 0) msg += " (" + dupCount + " " + t("csvDupRemoved") + ")";
      csvCount.textContent = msg;

      updateSendButton();
      log("CSV loaded:", file.name, rows.length, "rows,", dupCount, "duplicates removed");
    };
    reader.readAsText(file, "UTF-8");
  }

  btnClearCsv.addEventListener("click", function () {
    csvData = null;
    csvRawText = null;
    csvDropzone.style.display = "block";
    csvInfo.style.display = "none";
    csvInput.value = "";
    updateSendButton();
    log("CSV cleared");
  });

  // ── CSV template download (example file with 3 locale-specific sample rows) ──
  var csvTemplateLink = document.getElementById("csv-template-link");
  if (csvTemplateLink) {
    csvTemplateLink.addEventListener("click", function (e) {
      e.preventDefault();
      // Headers stay English — they map to merge tags ({{firstName}} etc.)
      // Sample rows are localized via i18n keys (names/companies in user's language)
      var rows = [
        t("csvTemplateRow1"),
        t("csvTemplateRow2"),
        t("csvTemplateRow3"),
      ].filter(function (r) { return r && r !== "csvTemplateRow1" && r !== "csvTemplateRow2" && r !== "csvTemplateRow3"; });
      // Fallback in case i18n lookup fails
      if (rows.length === 0) {
        rows = [
          "john@example.com,John,Smith,Acme Corp,CEO",
          "jane@example.com,Jane,Doe,TechFlow Inc,Marketing Director",
          "mike@example.com,Michael,Johnson,Pioneer Labs,VP of Sales",
        ];
      }
      var template = "email,firstName,lastName,company,position\n" + rows.join("\n") + "\n";
      // UTF-8 BOM helps Excel display non-Latin chars correctly
      var blob = new Blob(["\uFEFF" + template], { type: "text/csv;charset=utf-8" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = "outmass_recipients_template.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  }

  // ── Form validation → enable/disable Send button ──
  function updateSendButton() {
    var hasCSV = csvData && csvData.rows.length > 0;
    var hasSubject = subjectInput.value.trim().length > 0;
    var hasBody = bodyInput.value.trim().length > 0;
    btnSend.disabled = !(hasCSV && hasSubject && hasBody);
  }

  subjectInput.addEventListener("input", updateSendButton);
  bodyInput.addEventListener("input", updateSendButton);

  // ── Preview (D.1: HTML modal, was plain-text alert) ──
  btnPreview.addEventListener("click", function () {
    if (!csvData || csvData.rows.length === 0) {
      alert(t("alertUploadCsvFirst"));
      return;
    }
    var subject = subjectInput.value;
    var body = bodyInput.value;
    var firstRow = csvData.rows[0];

    getSenderDefaults(function (sender) {
      // Merge CSV row first, then sender defaults for unresolved placeholders
      var mergeCtx = Object.assign({}, sender, firstRow);
      var previewSubject = mergePlaceholders(subject, mergeCtx);
      var previewBody = mergePlaceholders(body, mergeCtx);
      showPreviewModal(previewSubject, textToHtml(previewBody));
      log("Preview shown for first row");
    });
  });

  function mergePlaceholders(template, row) {
    return template.replace(/\{\{(\w+)\}\}/g, function (match, key) {
      return row[key] !== undefined ? row[key] : match;
    });
  }

  // ── C.4: Test Send button ──
  var btnTestSend = document.getElementById("btn-test-send");
  if (btnTestSend) {
    btnTestSend.addEventListener("click", function () {
      var subject = subjectInput.value.trim();
      var body = bodyInput.value.trim();
      if (!subject || !body) { alert(t("testSendNeedsContent")); return; }
      if (!confirm(t("testSendPrompt"))) return;

      btnTestSend.disabled = true;
      var original = btnTestSend.textContent;
      btnTestSend.textContent = "…";

      var sample = (csvData && csvData.rows && csvData.rows[0]) || {};
      // Stateless test-send — no campaign row is created on the backend.
      chrome.runtime.sendMessage(
        {
          type: "TEST_SEND_STATELESS",
          payload: { subject: subject, body: body, sample: sample },
        },
        function (resp) {
          btnTestSend.disabled = false;
          btnTestSend.textContent = original;
          if (!resp || resp.error) {
            if (!handleSessionExpired(resp)) {
              alert(t("testSendFailed", [resp ? resp.error : "send failed"]));
            }
            return;
          }
          var data = resp.data || resp;
          alert(t("testSendSuccess", [data.sent_to || ""]));
        }
      );
    });
  }

  // ── C.5 / C-future: Content warnings ──
  var SPAM_WORDS = [
    "free!!!", "act now", "100% guaranteed", "click here", "buy now",
    "limited time", "urgent", "winner", "congratulations", "$$$", "cash bonus"
  ];

  // Known URL shorteners — hurt deliverability because receivers can't
  // inspect the destination and spam filters treat them as suspicious.
  var LINK_SHORTENERS = [
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "buff.ly",
    "is.gd", "cutt.ly", "rebrand.ly", "t.ly", "shorturl.at", "rb.gy",
    "bl.ink", "tiny.cc", "lnkd.in"
  ];

  // Block-level HTML tags we expect to be balanced. Void elements (img, br, hr)
  // excluded. Self-closing forms like <br/> handled by the regex.
  var BALANCED_TAGS = [
    "div", "p", "span", "a", "table", "tr", "td", "th", "tbody", "thead",
    "ul", "ol", "li", "strong", "em", "b", "i", "u", "h1", "h2", "h3",
    "h4", "h5", "h6", "blockquote"
  ];

  function findUnbalancedTags(html) {
    var offenders = [];
    for (var i = 0; i < BALANCED_TAGS.length; i++) {
      var tag = BALANCED_TAGS[i];
      // Count <tag ...> but skip <tag /> (self-closing)
      var openRe = new RegExp("<" + tag + "(?:\\s[^>]*)?(?<!/)>", "gi");
      var closeRe = new RegExp("</" + tag + "\\s*>", "gi");
      var opens = (html.match(openRe) || []).length;
      var closes = (html.match(closeRe) || []).length;
      if (opens !== closes) offenders.push(tag);
    }
    return offenders;
  }

  function getContentWarnings(subject, body) {
    var warnings = [];
    if (subject.length > 78) warnings.push(t("warnSubjectLong"));
    var letters = subject.replace(/[^A-Za-z]/g, "");
    if (letters.length >= 8) {
      var upper = subject.replace(/[^A-Z]/g, "").length;
      if (upper / letters.length > 0.5) warnings.push(t("warnAllCaps"));
    }
    var combined = (subject + " " + body).toLowerCase();
    var hits = SPAM_WORDS.filter(function (w) { return combined.indexOf(w) >= 0; });
    if (hits.length > 0) warnings.push(t("warnSpamWords", [hits.slice(0, 3).join(", ")]));

    var linkCount = (body.match(/https?:\/\//gi) || []).length;
    if (linkCount >= 5) warnings.push(t("warnTooManyLinks", [String(linkCount)]));

    // C-future: HTML validation — unbalanced block tags
    if (/<[a-z][^>]*>/i.test(body)) {
      var unbalanced = findUnbalancedTags(body);
      if (unbalanced.length > 0) {
        warnings.push(t("warnHtmlInvalid", [unbalanced.slice(0, 3).join(", ")]));
      }
    }

    // C-future: Image count limit (5+ → spam signal)
    var imgCount = (body.match(/<img\b/gi) || []).length;
    if (imgCount >= 5) warnings.push(t("warnTooManyImages", [String(imgCount)]));

    // C-future: Link-shortener detection
    var combinedBodyLower = body.toLowerCase();
    var shortenerHits = LINK_SHORTENERS.filter(function (d) {
      // Match the domain as part of a URL, not arbitrary text
      return new RegExp("https?://(?:www\\.)?" + d.replace(/\./g, "\\.") + "\\b").test(combinedBodyLower);
    });
    if (shortenerHits.length > 0) {
      warnings.push(t("warnShortenedLinks", [shortenerHits.slice(0, 3).join(", ")]));
    }

    return warnings;
  }

  // Mirror of backend _text_to_html — pass-through if HTML, else escape
  // special chars + paragraphs on blank lines + <br> on single newlines.
  function textToHtml(body) {
    if (!body) return "";
    if (/<[a-z!/][^>]*>/i.test(body)) return body;
    var esc = body.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    esc = esc.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    var parts = esc.split(/\n\n+/).map(function (p) { return p.replace(/\n/g, "<br>"); });
    return "<p>" + parts.join("</p><p>") + "</p>";
  }

  // Fetch sender profile from backend; cached after first call.
  var _senderCache = null;
  function getSenderDefaults(cb) {
    if (_senderCache) { cb(_senderCache); return; }
    chrome.runtime.sendMessage({ type: "GET_SETTINGS" }, function (resp) {
      var d = (resp && resp.data) || resp || {};
      _senderCache = {
        senderName: d.sender_name || "",
        senderPosition: d.sender_position || "",
        senderCompany: d.sender_company || "",
        senderPhone: d.sender_phone || "",
      };
      cb(_senderCache);
    });
  }

  function showPreviewModal(subject, bodyHtml) {
    var existing = document.getElementById("preview-modal");
    if (existing) existing.remove();
    var wrap = document.createElement("div");
    wrap.id = "preview-modal";
    wrap.className = "om-modal-overlay";
    wrap.innerHTML =
      '<div class="om-modal">' +
        '<div class="om-modal-header">' +
          '<span>' + t("previewSubjectLabel") + '</span>' +
          '<button type="button" class="om-modal-close" aria-label="Close">&times;</button>' +
        '</div>' +
        '<div class="om-modal-subject"></div>' +
        '<iframe class="om-modal-iframe" sandbox=""></iframe>' +
      '</div>';
    document.body.appendChild(wrap);
    wrap.querySelector(".om-modal-subject").textContent = subject;
    var iframe = wrap.querySelector(".om-modal-iframe");
    // sandbox="" fully isolates the iframe: no JS, no same-origin privileges.
    iframe.srcdoc =
      '<!doctype html><meta charset="utf-8">' +
      '<body style="font:14px system-ui,-apple-system,Segoe UI,Arial;margin:16px;color:#323130;line-height:1.5">' +
      bodyHtml + '</body>';
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap || e.target.classList.contains("om-modal-close")) {
        wrap.remove();
      }
    });
  }

  // ── Quota ──
  function loadQuota() {
    chrome.storage.local.get(["emailsSentThisMonth", "plan"], function (result) {
      var sent = result.emailsSentThisMonth || 0;
      var plan = result.plan || "free";
      var limit = plan === "pro" ? 10000 : plan === "starter" ? 2000 : 50;
      var remaining = Math.max(0, limit - sent);
      // quotaDefault template already has "Plan" suffix, so pass just the tier name
      var planLabel = plan === "pro" ? "Pro" : plan === "starter" ? "Starter" : "Free";

      quotaText.textContent = t("quotaDefault", [String(remaining), String(limit), planLabel]);
      quotaFill.style.width = (remaining / limit * 100) + "%";
    });
  }

  // Quota info modal (platform limit disclaimer)
  var quotaInfoBtn = document.getElementById("quota-info-btn");
  if (quotaInfoBtn) {
    quotaInfoBtn.addEventListener("click", function () {
      var overlay = document.createElement("div");
      overlay.style.cssText = "position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:10000;display:flex;align-items:center;justify-content:center;padding:20px;";
      var modal = document.createElement("div");
      modal.style.cssText = "background:#fff;border-radius:12px;padding:24px;max-width:340px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.2);font-size:13px;line-height:1.5;";
      modal.innerHTML =
        '<h3 style="margin:0 0 12px;font-size:15px;color:#323130;">' + t("quotaInfoTitle") + '</h3>' +
        '<p style="margin:0 0 10px;color:#605e5c;">' + t("quotaInfoBody1") + '</p>' +
        '<ul style="margin:8px 0 10px 18px;color:#605e5c;padding:0;">' +
          '<li>' + t("quotaInfoOutlookCom") + '</li>' +
          '<li>' + t("quotaInfoMs365") + '</li>' +
          '<li>' + t("quotaInfoExchange") + '</li>' +
        '</ul>' +
        '<p style="margin:0 0 14px;color:#605e5c;font-size:12px;">' + t("quotaInfoBody2") + '</p>' +
        '<button id="quota-info-close" style="width:100%;padding:8px;background:#0078d4;color:#fff;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-family:inherit;">' + t("btnClose") + '</button>';
      overlay.appendChild(modal);
      document.body.appendChild(overlay);
      document.getElementById("quota-info-close").addEventListener("click", function () { overlay.remove(); });
      overlay.addEventListener("click", function (e) { if (e.target === overlay) overlay.remove(); });
    });
  }

  // ── Send Campaign ──
  btnSend.addEventListener("click", function () {
    if (!csvData || !csvRawText) {
      alert(t("alertUploadCsvFirst"));
      return;
    }

    var subject = subjectInput.value.trim();
    var body = bodyInput.value.trim();

    if (!subject || !body) {
      alert(t("alertFillSubjectBody"));
      return;
    }

    // C.5: soft content warnings — allow user to override
    var warnings = getContentWarnings(subject, body);
    if (warnings.length > 0) {
      var bullets = "• " + warnings.join("\n• ");
      if (!confirm(bullets + "\n\n" + t("warnContinueAnyway"))) return;
    }

    // Check quota first
    chrome.storage.local.get(["emailsSentThisMonth", "plan"], function (storage) {
      var sent = storage.emailsSentThisMonth || 0;
      var plan = storage.plan || "free";
      var limit = plan === "pro" ? 10000 : plan === "starter" ? 2000 : 50;
      var remaining = limit - sent;

      if (remaining <= 0) {
        alert(t("alertLimitReached", [String(limit)]));
        return;
      }

      if (csvData.rows.length > remaining) {
        alert(t("alertPartialCsvQuota", [String(remaining), String(csvData.rows.length)]));
      }

      startSendFlow(subject, body);
    });
  });

  // B.2: cache of existing campaign names (lowercase) for duplicate warning
  var _cachedCampaignNames = null;

  function fetchCampaignNames(cb) {
    chrome.runtime.sendMessage({ type: "GET_CAMPAIGNS" }, function (resp) {
      var list = (resp && resp.data && resp.data.campaigns) || [];
      _cachedCampaignNames = list.map(function (c) { return (c.name || "").toLowerCase(); });
      cb();
    });
  }

  function startSendFlow(subject, body) {
    // Use explicit campaign name if user provided one,
    // otherwise fall back to subject + date suffix for uniqueness
    var nameInput = document.getElementById("campaign-name");
    var campaignName = nameInput && nameInput.value.trim();
    if (!campaignName) {
      var d = new Date();
      var dateSuffix = d.toLocaleDateString(getActiveLocale(), {
        month: "short", day: "numeric", year: "numeric"
      });
      var subj = subject.substring(0, 50) || t("tabCampaign");
      campaignName = subj + " — " + dateSuffix;
    }

    // B.2: warn if a campaign with this name already exists
    fetchCampaignNames(function () {
      if (_cachedCampaignNames.indexOf(campaignName.toLowerCase()) >= 0) {
        if (!confirm(t("campaignNameDuplicate", [campaignName]))) return;
      }
      _startSendFlowInner(campaignName, subject, body);
    });
  }

  function _startSendFlowInner(campaignName, subject, body) {
    // Check schedule
    var scheduledFor = null;
    if (scheduleCheckbox && scheduleCheckbox.checked) {
      var dtInput = document.getElementById("schedule-datetime");
      if (dtInput && dtInput.value) {
        scheduledFor = new Date(dtInput.value).toISOString();
      }
    }

    // Disable button, show progress
    btnSend.disabled = true;
    btnSend.textContent = scheduledFor ? t("alertScheduling") : t("alertPreparing");
    log("Send flow started", scheduledFor ? "scheduled:" + scheduledFor : "immediate");

    // Step 1: Create campaign
    var createPayload = { name: campaignName, subject: subject, body: body };
    if (scheduledFor) {
      createPayload.scheduled_for = scheduledFor;
    }

    chrome.runtime.sendMessage(
      {
        type: "CREATE_CAMPAIGN",
        payload: createPayload,
      },
      function (createResp) {
        if (!createResp || createResp.error) {
          // Detect Pro-gated feature (e.g. scheduled sending on Free plan)
          // and show a friendlier upgrade prompt instead of raw error code.
          var detail = createResp && createResp.detail;
          var err = detail && typeof detail === "object"
            ? detail.error
            : (createResp && createResp.error);
          if (err === "feature_locked") {
            btnSend.textContent = t("btnSend");
            btnSend.disabled = false;
            var feature = detail && detail.feature;
            var msgKey = feature === "scheduled_sending"
              ? "errScheduledFeatureLocked"
              : "errFeatureLocked";
            if (confirm(t(msgKey))) {
              showUpgradeModal();
            }
            return;
          }
          showSendError(createResp ? createResp.error : t("alertCampaignCreateFailed"));
          return;
        }

        var campaignId = createResp.data
          ? createResp.data.campaign_id
          : createResp.campaign_id;
        log("Campaign created:", campaignId);
        btnSend.textContent = t("alertContactsUploading");

        // Step 2: Upload contacts
        chrome.runtime.sendMessage(
          {
            type: "UPLOAD_CONTACTS",
            campaignId: campaignId,
            payload: { csv_string: csvRawText },
          },
          function (uploadResp) {
            if (!uploadResp || uploadResp.error) {
              showSendError(uploadResp ? uploadResp.error : t("alertContactsUploadFailed"));
              return;
            }

            var uploadData = uploadResp.data || uploadResp;
            var count = uploadData.count;
            log("Contacts uploaded:", count, "skipped_previous:",
                uploadData.skipped_previous || 0);

            // Show a one-time info alert if cross-campaign dedup removed anything.
            var skippedPrev = uploadData.skipped_previous || 0;
            if (skippedPrev > 0) {
              alert(t("uploadSkippedPrevious", [String(skippedPrev)]));
            }

            // Guard: if every row was filtered (dedup, invalid, suppressed),
            // don't proceed to a 0-recipient scheduled/immediate send.
            if (count === 0) {
              showSendError(t("alertNoContactsAfterUpload"));
              return;
            }

            // If A/B test enabled, create it before sending
            var abEnabled = abTestCheckbox && abTestCheckbox.checked;
            var abSubjectB = document.getElementById("ab-subject-b");
            var abTestPct = document.getElementById("ab-test-pct");

            if (abEnabled && abSubjectB && abSubjectB.value.trim()) {
              chrome.runtime.sendMessage(
                {
                  type: "CREATE_AB_TEST",
                  campaignId: campaignId,
                  payload: {
                    subject_a: subject,
                    subject_b: abSubjectB.value.trim(),
                    test_percentage: parseInt(abTestPct ? abTestPct.value : "20", 10) || 20,
                  },
                },
                function (abResp) {
                  if (abResp && abResp.error) {
                    if (abResp.status === 402) {
                      alert(t("alertAbTestProOnly"));
                    } else {
                      log("A/B test creation failed:", abResp.error);
                    }
                    // Continue with normal send anyway
                  } else {
                    log("A/B test created:", abResp);
                  }
                  // Proceed to send step
                  proceedToSend(campaignId, count, scheduledFor);
                }
              );
              return;
            }

            proceedToSend(campaignId, count, scheduledFor);
          }
        );
      }
    );
  }

  function proceedToSend(campaignId, count, scheduledFor) {
    // If scheduled, don't send now
    if (scheduledFor) {
      btnSend.textContent = t("btnSend");
      btnSend.disabled = false;
      var schedDate = new Date(scheduledFor);
      // Format using extension's active UI locale so Turkish users don't
      // see "4/19/2026, 11:35 PM" in an otherwise-Turkish alert.
      var localeTag = getActiveLocale();
      var formatted;
      try {
        formatted = schedDate.toLocaleString(localeTag, {
          weekday: "short",
          year: "numeric",
          month: "long",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        });
      } catch (e) {
        formatted = schedDate.toLocaleString();
      }
      alert(t("alertScheduledSuccess", [String(count), formatted]));
      log("Campaign scheduled:", campaignId, "for", scheduledFor);
      maybeCreateFollowup(campaignId);
      return;
    }

    btnSend.textContent = t("alertSending") + count;

    // Step 3: Send
    chrome.runtime.sendMessage(
      {
        type: "SEND_CAMPAIGN",
        campaignId: campaignId,
      },
      function (sendResp) {
        if (!sendResp) {
          showSendError(t("alertSendFailed"));
          return;
        }
        if (sendResp.error) {
          if (sendResp.status === 402 || sendResp.error === "limit_exceeded") {
            btnSend.textContent = t("btnSend");
            btnSend.disabled = false;
            showUpgradeModal();
            return;
          }
          showSendError(sendResp.error);
          return;
        }

        var data = sendResp.data || sendResp;
        var queued = data.queued || 0;
        var sendErrors = data.errors || [];
        var hasAbTest = data.ab_test;
        btnSend.textContent = t("btnSend");
        btnSend.disabled = false;

        if (queued === 0 && sendErrors.length > 0) {
          alert(t("alertSendError") + sendErrors[0].error);
          log("Campaign send errors:", sendErrors);
        } else if (hasAbTest) {
          alert(t("alertAbSendSuccess", [String(queued)]));
        } else if (sendErrors.length > 0) {
          alert(t("alertPartialSend", [String(queued), String(sendErrors.length)]) + sendErrors[0].error);
        } else {
          alert(t("alertSendSuccess", [String(queued)]));
        }
        log("Campaign sent:", queued, "emails, errors:", sendErrors.length);

        // Create follow-up if enabled
        maybeCreateFollowup(campaignId);

        // Refresh quota
        loadQuota();
      }
    );
  }

  function showSendError(message) {
    btnSend.textContent = t("btnSend");
    btnSend.disabled = false;
    alert(t("alertSendError") + message);
    log("Send error:", message);
  }

  // ── AI Writer ──
  var btnAiWriter = document.getElementById("btn-ai-writer");

  if (btnAiWriter) {
    btnAiWriter.addEventListener("click", function () {
      showAiWriterModal();
    });
  }

  function showAiWriterModal() {
    var existing = document.getElementById("ai-modal");
    if (existing) existing.remove();

    var overlay = document.createElement("div");
    overlay.id = "ai-modal";
    overlay.style.cssText = "position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;";

    var modal = document.createElement("div");
    modal.style.cssText = "background:#fff;border-radius:12px;padding:24px;max-width:320px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.2);";
    modal.innerHTML =
      '<h3 style="margin:0 0 12px;font-size:16px;color:#323130;">' + t("aiModalTitle") + '</h3>' +
      '<textarea id="ai-prompt" rows="3" placeholder="' + t("aiPromptPlaceholder") + '" style="width:100%;padding:8px;border:1px solid #c8c6c4;border-radius:4px;font-size:13px;font-family:inherit;resize:vertical;box-sizing:border-box;"></textarea>' +
      '<div style="display:flex;gap:8px;margin-top:8px;">' +
        '<select id="ai-tone" style="flex:1;padding:6px;border:1px solid #c8c6c4;border-radius:4px;font-size:12px;">' +
          '<option value="professional">' + t("aiToneProfessional") + '</option>' +
          '<option value="friendly">' + t("aiToneFriendly") + '</option>' +
          '<option value="formal">' + t("aiToneFormal") + '</option>' +
          '<option value="casual">' + t("aiToneCasual") + '</option>' +
        '</select>' +
        '<select id="ai-lang" style="flex:1;padding:6px;border:1px solid #c8c6c4;border-radius:4px;font-size:12px;">' +
          '<option value="en">' + t("aiLangEn") + '</option>' +
          '<option value="tr">' + t("aiLangTr") + '</option>' +
          '<option value="de">' + t("aiLangDe") + '</option>' +
          '<option value="fr">' + t("aiLangFr") + '</option>' +
          '<option value="es">' + t("aiLangEs") + '</option>' +
          '<option value="ru">' + t("aiLangRu") + '</option>' +
          '<option value="ar">' + t("aiLangAr") + '</option>' +
          '<option value="hi">' + t("aiLangHi") + '</option>' +
          '<option value="zh">' + t("aiLangZh") + '</option>' +
          '<option value="ja">' + t("aiLangJa") + '</option>' +
        '</select>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:12px;">' +
        '<button id="ai-generate-btn" style="flex:1;padding:10px;background:#0078d4;color:#fff;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-family:inherit;">' + t("btnAiGenerate") + '</button>' +
        '<button id="ai-cancel-btn" style="padding:10px 16px;background:none;border:1px solid #c8c6c4;border-radius:6px;color:#605e5c;font-size:13px;cursor:pointer;font-family:inherit;">' + t("btnCancel") + '</button>' +
      '</div>';

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Pre-select language matching the user's browser UI language
    try {
      var uiLang = (chrome.i18n.getUILanguage() || "en").split("-")[0].toLowerCase();
      if (uiLang === "zh_cn" || uiLang === "zh_tw") uiLang = "zh";
      var langSelectEl = document.getElementById("ai-lang");
      if (langSelectEl) {
        var supported = ["en", "tr", "de", "fr", "es", "ru", "ar", "hi", "zh", "ja"];
        if (supported.indexOf(uiLang) !== -1) {
          langSelectEl.value = uiLang;
        }
      }
    } catch (e) { /* fallback to English */ }

    document.getElementById("ai-generate-btn").addEventListener("click", function () {
      var promptInput = document.getElementById("ai-prompt");
      var toneSelect = document.getElementById("ai-tone");
      var langSelect = document.getElementById("ai-lang");
      var generateBtn = document.getElementById("ai-generate-btn");

      var promptText = promptInput.value.trim();
      if (!promptText) {
        alert(t("alertAiPromptEmpty"));
        return;
      }

      generateBtn.textContent = t("aiGenerating");
      generateBtn.disabled = true;

      // Include sender info from settings for AI context
      var senderNameEl = document.getElementById("settings-sender-name");
      var senderPosEl = document.getElementById("settings-sender-position");
      var senderCompEl = document.getElementById("settings-sender-company");

      chrome.runtime.sendMessage(
        {
          type: "AI_GENERATE_EMAIL",
          payload: {
            prompt: promptText,
            tone: toneSelect.value,
            language: langSelect.value,
            sender_name: senderNameEl ? senderNameEl.value.trim() : "",
            sender_position: senderPosEl ? senderPosEl.value.trim() : "",
            sender_company: senderCompEl ? senderCompEl.value.trim() : "",
          },
        },
        function (resp) {
          generateBtn.textContent = t("btnAiGenerate");
          generateBtn.disabled = false;

          if (!resp || resp.error) {
            if (resp && resp.status === 402) {
              alert(t("alertAiProOnly"));
            } else {
              if (!handleSessionExpired(resp)) {
                alert(t("alertAiFailed") + (resp ? resp.error : t("popupUnknownError")));
              }
            }
            return;
          }

          var data = resp.data || resp;
          if (data.subject) subjectInput.value = data.subject;
          if (data.body) bodyInput.value = data.body;
          updateSendButton();
          overlay.remove();
          log("AI email generated");
        }
      );
    });

    document.getElementById("ai-cancel-btn").addEventListener("click", function () {
      overlay.remove();
    });

    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) overlay.remove();
    });
  }

  // ── Templates ──
  var templateSelect = document.getElementById("template-select");
  var btnSaveTemplate = document.getElementById("btn-save-template");
  var btnDeleteTemplate = document.getElementById("btn-delete-template");

  function loadTemplates() {
    try {
      chrome.runtime.sendMessage({ type: "GET_TEMPLATES" }, function (resp) {
        if (chrome.runtime.lastError) {
          log("Templates load error:", chrome.runtime.lastError.message);
          return;
        }

        // Clear existing options except first
        while (templateSelect && templateSelect.options.length > 1) {
          templateSelect.remove(1);
        }
        if (btnDeleteTemplate) btnDeleteTemplate.disabled = true;

        if (!resp || resp.error || !resp.data) {
          log("Templates: no data or error", resp && resp.error);
          return;
        }

        var templates = resp.data.templates || [];
        templates.forEach(function (t) {
          var opt = document.createElement("option");
          opt.value = JSON.stringify({ subject: t.subject, body: t.body });
          opt.textContent = t.name;
          opt.dataset.templateId = t.id;
          templateSelect.appendChild(opt);
        });
        log("Templates loaded:", templates.length);
      });
    } catch (e) {
      log("Templates load exception:", e);
    }
  }

  function updateDeleteTemplateButton() {
    if (!btnDeleteTemplate || !templateSelect) return;
    var selected = templateSelect.options[templateSelect.selectedIndex];
    btnDeleteTemplate.disabled = !selected || !selected.dataset.templateId;
  }

  if (templateSelect) {
    templateSelect.addEventListener("change", function () {
      updateDeleteTemplateButton();
      if (!templateSelect.value) return;
      try {
        var tmpl = JSON.parse(templateSelect.value);
        subjectInput.value = tmpl.subject || "";
        bodyInput.value = tmpl.body || "";

        // Auto-fill campaign name with template name if input is empty
        var selected = templateSelect.options[templateSelect.selectedIndex];
        var templateName = selected ? selected.textContent : "";
        var nameInput = document.getElementById("campaign-name");
        if (nameInput && !nameInput.value.trim() && templateName) {
          nameInput.value = templateName;
        }

        updateSendButton();
        log("Template loaded");
      } catch (e) {
        log("Template parse error:", e);
      }
    });
  }

  // Delete template
  if (btnDeleteTemplate) {
    btnDeleteTemplate.addEventListener("click", function () {
      var selected = templateSelect.options[templateSelect.selectedIndex];
      if (!selected || !selected.dataset.templateId) return;

      var templateName = selected.textContent;
      if (!confirm(t("templateConfirmDelete", [templateName]))) return;

      btnDeleteTemplate.disabled = true;
      btnDeleteTemplate.textContent = "...";

      chrome.runtime.sendMessage(
        { type: "DELETE_TEMPLATE", templateId: selected.dataset.templateId },
        function (resp) {
          btnDeleteTemplate.textContent = t("btnDeleteTemplate");
          if (resp && !resp.error) {
            log("Template deleted:", templateName);
            loadTemplates();
          } else {
            btnDeleteTemplate.disabled = false;
            if (!handleSessionExpired(resp)) {
              alert(t("alertTemplateDeleteFailed") + ((resp && resp.error) || t("popupUnknownError")));
            }
          }
        }
      );
    });
  }

  // Save template
  if (btnSaveTemplate) {
    btnSaveTemplate.addEventListener("click", function () {
      var subject = subjectInput.value.trim();
      var body = bodyInput.value.trim();
      if (!subject && !body) {
        alert(t("alertTemplateFillFirst"));
        return;
      }
      // Suggest the campaign name first (if user filled it),
      // then fall back to subject prefix, then a default placeholder.
      var nameInput = document.getElementById("campaign-name");
      var suggested = (nameInput && nameInput.value.trim())
        || subject.substring(0, 40)
        || t("templateDefaultName");
      var name = prompt(t("templatePromptName"), suggested);
      if (!name) return;

      btnSaveTemplate.disabled = true;
      btnSaveTemplate.textContent = "...";

      chrome.runtime.sendMessage(
        {
          type: "SAVE_TEMPLATE",
          payload: { name: name, subject: subject, body: body },
        },
        function (resp) {
          btnSaveTemplate.disabled = false;
          btnSaveTemplate.textContent = t("btnSaveTemplate");

          if (resp && !resp.error) {
            log("Template saved");
            loadTemplates();
          } else {
            var errMsg = resp && resp.error;
            if (resp && resp.status === 402) {
              alert(t("alertTemplateStandardOnly"));
            } else {
              alert(t("alertTemplateSaveFailed") + (errMsg || t("popupUnknownError")));
            }
          }
        }
      );
    });
  }

  // ── A/B Test ──
  var abTestCheckbox = document.getElementById("ab-test-enabled");
  var abTestFields = document.getElementById("ab-test-fields");

  if (abTestCheckbox) {
    abTestCheckbox.addEventListener("change", function () {
      if (abTestCheckbox.checked) {
        abTestFields.classList.add("visible");
      } else {
        abTestFields.classList.remove("visible");
      }
    });
  }

  // ── Schedule ──
  var scheduleCheckbox = document.getElementById("schedule-enabled");
  var scheduleFields = document.getElementById("schedule-fields");

  if (scheduleCheckbox) {
    scheduleCheckbox.addEventListener("change", function () {
      if (scheduleCheckbox.checked) {
        scheduleFields.classList.add("visible");
        // Set default to tomorrow 9:00
        var tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        tomorrow.setHours(9, 0, 0, 0);
        var dtInput = document.getElementById("schedule-datetime");
        dtInput.value = tomorrow.toISOString().slice(0, 16);
        updateScheduleParsed();
      } else {
        scheduleFields.classList.remove("visible");
      }
    });
  }

  // Show the selected datetime in the user's locale format so the
  // browser's native MM/DD vs DD/MM picker ambiguity is resolved.
  function updateScheduleParsed() {
    var dtInput = document.getElementById("schedule-datetime");
    var hint = document.getElementById("schedule-parsed");
    if (!dtInput || !hint) return;
    if (!dtInput.value) {
      hint.textContent = t("scheduleParsedEmpty");
      return;
    }
    try {
      var d = new Date(dtInput.value);
      if (isNaN(d.getTime())) {
        hint.textContent = t("scheduleParsedEmpty");
        return;
      }
      // Use the extension's active UI locale for formatting, not the
      // browser's (so Turkish users with an English OS still see Turkish).
      // NOTE: previous code passed `_i18nOverride` (the translations
      // dict, not a locale string) which made toLocaleString silently
      // fall back to the OS locale. Use getActiveLocale() instead.
      var localeOverride = getActiveLocale();
      var formatted = d.toLocaleString(localeOverride, {
        weekday: "short",
        year: "numeric",
        month: "long",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
      hint.textContent = t("scheduleParsedPrefix") + formatted;
    } catch (e) {
      hint.textContent = t("scheduleParsedEmpty");
    }
  }

  var _dtInputForHint = document.getElementById("schedule-datetime");
  if (_dtInputForHint) {
    _dtInputForHint.addEventListener("input", updateScheduleParsed);
    _dtInputForHint.addEventListener("change", updateScheduleParsed);
  }

  // ── Follow-up ──
  var followupCheckbox = document.getElementById("followup-enabled");
  var followupFields = document.getElementById("followup-fields");

  if (followupCheckbox) {
    followupCheckbox.addEventListener("change", function () {
      if (followupCheckbox.checked) {
        followupFields.classList.add("visible");
      } else {
        followupFields.classList.remove("visible");
      }
    });
  }

  function maybeCreateFollowup(campaignId) {
    if (!followupCheckbox || !followupCheckbox.checked) return;

    var delayInput = document.getElementById("followup-delay");
    var subjectInput2 = document.getElementById("followup-subject");
    var bodyInput2 = document.getElementById("followup-body");

    var delay = parseInt(delayInput.value, 10) || 3;
    var fSubject = subjectInput2.value.trim();
    var fBody = bodyInput2.value.trim();

    if (!fSubject || !fBody) return;

    chrome.runtime.sendMessage(
      {
        type: "CREATE_FOLLOWUP",
        campaignId: campaignId,
        payload: {
          delay_days: delay,
          subject: fSubject,
          body: fBody,
          condition: "not_opened",
        },
      },
      function (resp) {
        if (resp && !resp.error) {
          log("Follow-up created for campaign:", campaignId);
        } else {
          log("Follow-up creation failed:", resp ? resp.error : "unknown");
        }
      }
    );
  }

  // ── Reports ──
  var reportsList = document.getElementById("reports-list");
  var reportsDetail = document.getElementById("reports-detail");
  var campaignListEl = document.getElementById("campaign-list");
  var reportsLoading = document.getElementById("reports-loading");
  var btnReportsBack = document.getElementById("btn-reports-back");

  // D.2: track which sub-tab (Active / Archived) is selected
  var _reportsArchived = false;

  function loadReports() {
    reportsList.style.display = "block";
    reportsDetail.style.display = "none";
    reportsLoading.style.display = "block";
    campaignListEl.innerHTML = "";

    chrome.runtime.sendMessage(
      { type: "GET_CAMPAIGNS", archived: _reportsArchived },
      function (resp) {
        reportsLoading.style.display = "none";

        if (!resp || resp.error) {
          campaignListEl.innerHTML = '<div class="no-campaigns">' + t("noCampaignsFound") + '</div>';
          return;
        }

        var campaigns = resp.data ? resp.data.campaigns : resp.campaigns;
        if (!campaigns || campaigns.length === 0) {
          campaignListEl.innerHTML = '<div class="no-campaigns">' + t("noCampaignsYet") + '</div>';
          return;
        }

        campaigns.forEach(function (c) {
          var sent = c.sent_count || 0;
          var openRate = sent > 0 ? Math.round((c.open_count / sent) * 100) : 0;
          var clickRate = sent > 0 ? Math.round((c.click_count / sent) * 100) : 0;
          var date = c.created_at ? new Date(c.created_at).toLocaleDateString(getActiveLocale()) : "";

          var row = document.createElement("div");
          row.className = "campaign-row";
          var archiveLabel = _reportsArchived ? t("btnUnarchive") : t("btnArchive");
          row.innerHTML =
            '<div class="campaign-row-name">' + escapeHtml(c.name) + '</div>' +
            '<div class="campaign-row-meta">' +
              '<span>' + date + '</span>' +
              '<span>' + sent + t("reportsSentSuffix") + '</span>' +
              '<span class="rate">' + t("reportsOpenRate") + openRate + '%</span>' +
              '<span class="rate">' + t("reportsClickRate") + clickRate + '%</span>' +
              '<button class="campaign-archive-btn" data-id="' + c.id + '">' + archiveLabel + '</button>' +
            '</div>';
          row.addEventListener("click", function (e) {
            if (e.target && e.target.classList.contains("campaign-archive-btn")) return;
            showCampaignDetail(c.id);
          });
          var archBtn = row.querySelector(".campaign-archive-btn");
          if (archBtn) {
            archBtn.addEventListener("click", function (e) {
              e.stopPropagation();
              if (!_reportsArchived && !confirm(t("archiveConfirm"))) return;
              var msgType = _reportsArchived ? "UNARCHIVE_CAMPAIGN" : "ARCHIVE_CAMPAIGN";
              chrome.runtime.sendMessage({ type: msgType, campaignId: c.id }, function () {
                loadReports();
              });
            });
          }
          campaignListEl.appendChild(row);
        });

        log("Reports loaded:", campaigns.length, "campaigns (archived=" + _reportsArchived + ")");
      }
    );
  }

  // D.2: wire sub-tab switching (Active / Archived)
  document.querySelectorAll(".reports-subtabs .sub-tab").forEach(function (el) {
    el.addEventListener("click", function () {
      document.querySelectorAll(".reports-subtabs .sub-tab").forEach(function (s) {
        s.classList.remove("active");
      });
      el.classList.add("active");
      _reportsArchived = el.getAttribute("data-archived") === "true";
      loadReports();
    });
  });

  // D.4: Export all campaigns as CSV
  var btnExportList = document.getElementById("btn-export-list");
  if (btnExportList) {
    btnExportList.addEventListener("click", function () {
      chrome.runtime.sendMessage({ type: "EXPORT_CAMPAIGN_LIST" }, function (resp) {
        if (!resp || resp.error) {
          if (!handleSessionExpired(resp)) {
            alert(resp && resp.error ? resp.error : t("popupUnknownError"));
          }
          return;
        }
        var data = resp.data || resp;
        if (!data.csv_data) { alert(t("alertCsvExportEmpty")); return; }
        var blob = new Blob(["\uFEFF" + data.csv_data], { type: "text/csv;charset=utf-8" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = data.filename || "outmass_campaigns.csv";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      });
    });
  }

  function showCampaignDetail(campaignId) {
    reportsList.style.display = "none";
    reportsDetail.style.display = "block";
    currentDetailCampaignId = campaignId;

    chrome.runtime.sendMessage(
      { type: "GET_CAMPAIGN_STATS", campaignId: campaignId },
      function (resp) {
        if (!resp || resp.error) {
          document.getElementById("detail-name").textContent = t("reportsError");
          return;
        }

        var stats = resp.data || resp;
        document.getElementById("detail-name").textContent = stats.name || t("tabCampaign");
        document.getElementById("stat-sent").textContent = stats.sent_count || 0;
        document.getElementById("stat-opened").textContent = stats.open_count || 0;
        document.getElementById("stat-clicked").textContent = stats.click_count || 0;
        document.getElementById("stat-open-rate").textContent = (stats.open_rate || 0) + "%";
        document.getElementById("stat-click-rate").textContent = (stats.click_rate || 0) + "%";

        // Follow-up status
        var followupEl = document.getElementById("followup-status");
        if (stats.pending_followups > 0) {
          followupEl.textContent = stats.pending_followups + t("reportsFollowupPending");
        } else {
          followupEl.textContent = "";
        }

        // Draw bar chart
        drawBarChart(stats.sent_count || 0, stats.open_count || 0, stats.click_count || 0);
      }
    );
  }

  // ── CSV Export ──
  var currentDetailCampaignId = null;

  var btnExportCsv = document.getElementById("btn-export-csv");
  if (btnExportCsv) {
    btnExportCsv.addEventListener("click", function () {
      if (!currentDetailCampaignId) return;
      btnExportCsv.textContent = t("csvExportDownloading");
      btnExportCsv.disabled = true;

      chrome.runtime.sendMessage(
        { type: "EXPORT_CAMPAIGN_CSV", campaignId: currentDetailCampaignId },
        function (resp) {
          btnExportCsv.textContent = t("btnExportCsv");
          btnExportCsv.disabled = false;

          if (!resp || resp.error) {
            if (resp && resp.status === 402) {
              alert(t("alertCsvExportStandardOnly"));
            } else {
              if (!handleSessionExpired(resp)) {
                alert(t("alertCsvExportFailed") + (resp ? resp.error : t("popupUnknownError")));
              }
            }
            return;
          }

          // resp.data contains { csv_data, filename }
          var data = resp.data || {};
          var csvContent = data.csv_data;
          var filename = data.filename || "outmass_export.csv";
          if (csvContent) {
            var blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
            var url = URL.createObjectURL(blob);
            var a = document.createElement("a");
            a.href = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);
          } else {
            alert(t("alertCsvExportEmpty"));
          }
        }
      );
    });
  }

  function drawBarChart(sent, opened, clicked) {
    var canvas = document.getElementById("stats-chart");
    if (!canvas) return;
    var ctx = canvas.getContext("2d");
    var w = canvas.width;
    var h = canvas.height;

    ctx.clearRect(0, 0, w, h);

    var maxVal = Math.max(sent, 1);
    var barWidth = 60;
    var gap = 30;
    var startX = (w - (barWidth * 3 + gap * 2)) / 2;
    var chartH = h - 30;

    var bars = [
      { label: t("chartSent"), value: sent, color: "#0078d4" },
      { label: t("chartOpened"), value: opened, color: "#107c10" },
      { label: t("chartClicked"), value: clicked, color: "#ff8c00" },
    ];

    bars.forEach(function (bar, i) {
      var x = startX + i * (barWidth + gap);
      var barH = (bar.value / maxVal) * chartH;
      var y = chartH - barH;

      ctx.fillStyle = bar.color;
      ctx.fillRect(x, y, barWidth, barH);

      // Value on top
      ctx.fillStyle = "#323130";
      ctx.font = "bold 12px Segoe UI";
      ctx.textAlign = "center";
      ctx.fillText(bar.value, x + barWidth / 2, y - 4);

      // Label below
      ctx.fillStyle = "#605e5c";
      ctx.font = "11px Segoe UI";
      ctx.fillText(bar.label, x + barWidth / 2, h - 4);
    });
  }

  if (btnReportsBack) {
    btnReportsBack.addEventListener("click", function () {
      reportsDetail.style.display = "none";
      reportsList.style.display = "block";
    });
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Upgrade Modal ──
  function showUpgradeModal() {
    // Remove existing modal if any
    var existing = document.getElementById("upgrade-modal");
    if (existing) existing.remove();

    var overlay = document.createElement("div");
    overlay.id = "upgrade-modal";
    overlay.style.cssText = "position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;";

    var modal = document.createElement("div");
    modal.style.cssText = "background:#fff;border-radius:12px;padding:32px 24px;max-width:300px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.2);";
    modal.innerHTML =
      '<div style="font-size:32px;margin-bottom:12px;">🚀</div>' +
      '<h3 style="margin:0 0 8px;color:#323130;font-size:18px;">' + t("upgradeModalTitle") + '</h3>' +
      '<p style="color:#605e5c;font-size:13px;margin-bottom:16px;">' + t("upgradeModalText") + '</p>' +
      '<ul style="text-align:left;font-size:12px;color:#605e5c;margin:0 0 20px 16px;padding:0;">' +
        '<li>' + t("upgradeModalStandard") + '</li>' +
        '<li>' + t("upgradeModalPro") + '</li>' +
        '<li>' + t("upgradeModalFeatures") + '</li>' +
      '</ul>' +
      '<button id="btn-upgrade" style="width:100%;padding:10px;background:#0078d4;color:#fff;border:none;border-radius:6px;font-size:14px;cursor:pointer;font-family:inherit;margin-bottom:8px;">' + t("upgradeModalBtn") + '</button>' +
      '<button id="btn-upgrade-cancel" style="width:100%;padding:8px;background:none;border:1px solid #c8c6c4;border-radius:6px;color:#605e5c;font-size:13px;cursor:pointer;font-family:inherit;">' + t("upgradeModalLater") + '</button>';

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    document.getElementById("btn-upgrade").addEventListener("click", function () {
      chrome.runtime.sendMessage({ type: "CREATE_CHECKOUT", plan: "starter" }, function (resp) {
        if (resp && resp.data && resp.data.checkout_url) {
          window.open(resp.data.checkout_url, "_blank");
        } else {
          alert(t("alertUpgradeCheckoutFailed"));
        }
        overlay.remove();
      });
    });

    document.getElementById("btn-upgrade-cancel").addEventListener("click", function () {
      overlay.remove();
    });

    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) overlay.remove();
    });
  }

  // ── Settings ──
  function loadSettings() {
    var settingsLoading = document.getElementById("settings-loading");
    var settingsContent = document.getElementById("settings-content");

    if (settingsLoading) settingsLoading.style.display = "block";
    if (settingsContent) settingsContent.style.display = "none";

    chrome.runtime.sendMessage({ type: "GET_SETTINGS" }, function (resp) {
      if (settingsLoading) settingsLoading.style.display = "none";
      if (settingsContent) settingsContent.style.display = "block";

      if (!resp || resp.error) {
        log("Settings load failed:", resp ? resp.error : "unknown");
        return;
      }

      var data = resp.data || resp;

      // Tracking
      var trackOpens = document.getElementById("settings-track-opens");
      var trackClicks = document.getElementById("settings-track-clicks");
      if (trackOpens) trackOpens.checked = data.track_opens !== false;
      if (trackClicks) trackClicks.checked = data.track_clicks !== false;

      // Unsub text
      var unsubText = document.getElementById("settings-unsub-text");
      if (unsubText && data.unsubscribe_text) unsubText.value = data.unsubscribe_text;

      // Timezone — auto-detect browser timezone if user has default UTC
      var tzSelect = document.getElementById("settings-timezone");
      if (tzSelect) {
        var tz = data.timezone || "UTC";
        // If user is still on default UTC, try auto-detecting their browser timezone
        if (tz === "UTC") {
          try {
            var browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
            // Only use if it's in our supported list
            var supported = Array.from(tzSelect.options).map(function (o) { return o.value; });
            if (browserTz && supported.indexOf(browserTz) !== -1) {
              tz = browserTz;
            }
          } catch (e) { /* ignore, keep UTC */ }
        }
        tzSelect.value = tz;
      }

      // Sender profile
      var senderName = document.getElementById("settings-sender-name");
      var senderPosition = document.getElementById("settings-sender-position");
      var senderCompany = document.getElementById("settings-sender-company");
      var senderPhone = document.getElementById("settings-sender-phone");
      if (senderName) senderName.value = data.sender_name || "";
      if (senderPosition) senderPosition.value = data.sender_position || "";
      if (senderCompany) senderCompany.value = data.sender_company || "";
      if (senderPhone) senderPhone.value = data.sender_phone || "";

      // Cross-campaign dedup — Pro-only section
      var dedupSection = document.getElementById("settings-dedup-section");
      var dedupEnabled = document.getElementById("settings-dedup-enabled");
      var dedupDays = document.getElementById("settings-dedup-days");
      if (dedupSection) {
        if ((data.plan || "free") === "pro") {
          dedupSection.style.display = "block";
          if (dedupEnabled) dedupEnabled.checked = data.cross_campaign_dedup_enabled !== false;
          if (dedupDays) dedupDays.value = data.cross_campaign_dedup_days || 60;
        } else {
          dedupSection.style.display = "none";
        }
      }

      log("Settings loaded");
    });

    // Load suppression list
    loadSuppressionList();
  }

  // ── Account (plan, usage, support) ──
  function loadAccount() {
    var accountLoading = document.getElementById("account-loading");
    var accountContent = document.getElementById("account-content");

    if (accountLoading) accountLoading.style.display = "block";
    if (accountContent) accountContent.style.display = "none";

    chrome.runtime.sendMessage({ type: "GET_SETTINGS" }, function (resp) {
      if (accountLoading) accountLoading.style.display = "none";
      if (accountContent) accountContent.style.display = "block";

      if (!resp || resp.error) {
        log("Account load failed:", resp ? resp.error : "unknown");
        return;
      }

      var data = resp.data || resp;

      var emailEl = document.getElementById("account-email");
      var planEl = document.getElementById("account-plan");
      var sentEl = document.getElementById("account-sent-count");
      if (emailEl) emailEl.textContent = data.email || "-";
      if (planEl) {
        var plan = data.plan || "free";
        planEl.textContent = plan.charAt(0).toUpperCase() + plan.slice(1);
        planEl.className = "plan-badge " + plan;
      }
      if (sentEl) sentEl.textContent = data.emails_sent_this_month || 0;

      var btnUpgrade = document.getElementById("account-btn-upgrade");
      var btnPortal = document.getElementById("account-btn-portal");
      if (data.plan === "free") {
        if (btnUpgrade) btnUpgrade.style.display = "block";
        if (btnPortal) btnPortal.style.display = "none";
      } else {
        if (btnUpgrade) btnUpgrade.style.display = "none";
        if (btnPortal) btnPortal.style.display = "block";
      }

      log("Account loaded");
    });
  }

  var _suppressionData = []; // cached for client-side filtering

  function loadSuppressionList() {
    chrome.runtime.sendMessage({ type: "GET_SUPPRESSION_LIST" }, function (resp) {
      if (!resp || resp.error || !resp.data) {
        _suppressionData = [];
        renderSuppressionList("");
        return;
      }
      _suppressionData = resp.data.emails || [];
      var searchEl = document.getElementById("suppression-search");
      renderSuppressionList(searchEl ? searchEl.value.trim().toLowerCase() : "");
    });
  }

  function renderSuppressionList(filter) {
    var listEl = document.getElementById("suppression-list");
    var emptyEl = document.getElementById("suppression-empty");
    var countEl = document.getElementById("suppression-count");
    if (!listEl) return;

    var filtered = filter
      ? _suppressionData.filter(function (item) { return item.email.toLowerCase().indexOf(filter) !== -1; })
      : _suppressionData;

    // Update count
    if (countEl) {
      countEl.textContent = _suppressionData.length > 0
        ? (filter ? filtered.length + "/" + _suppressionData.length : _suppressionData.length + " " + t("suppressionEmailSuffix"))
        : "";
    }

    listEl.innerHTML = "";

    if (_suppressionData.length === 0) {
      if (emptyEl) emptyEl.style.display = "block";
      return;
    }

    if (emptyEl) emptyEl.style.display = "none";

    filtered.forEach(function (item) {
      var row = document.createElement("div");
      row.className = "suppression-row";
      row.innerHTML =
        '<span class="suppression-email">' + escapeHtml(item.email) + '</span>' +
        '<span class="suppression-reason">' + (item.reason === "user_unsubscribed" ? t("suppressionReasonUnsub") : t("suppressionReasonManual")) + '</span>' +
        '<button class="btn-remove-suppression" data-email="' + escapeHtml(item.email) + '">&times;</button>';
      listEl.appendChild(row);
    });

    // Attach remove handlers
    listEl.querySelectorAll(".btn-remove-suppression").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var email = btn.getAttribute("data-email");
        chrome.runtime.sendMessage(
          { type: "REMOVE_SUPPRESSION", payload: { email: email } },
          function () {
            loadSuppressionList();
          }
        );
      });
    });
  }

  // Suppression search — filter as you type
  var suppressionSearchEl = document.getElementById("suppression-search");
  if (suppressionSearchEl) {
    suppressionSearchEl.addEventListener("input", function () {
      renderSuppressionList(suppressionSearchEl.value.trim().toLowerCase());
    });
  }

  // Settings save button
  var btnSaveSettings = document.getElementById("settings-btn-save");
  if (btnSaveSettings) {
    btnSaveSettings.addEventListener("click", function () {
      btnSaveSettings.textContent = t("settingsSaving");
      btnSaveSettings.disabled = true;

      var payload = {
        track_opens: document.getElementById("settings-track-opens").checked,
        track_clicks: document.getElementById("settings-track-clicks").checked,
        unsubscribe_text: document.getElementById("settings-unsub-text").value.trim(),
        timezone: document.getElementById("settings-timezone").value,
        sender_name: (document.getElementById("settings-sender-name").value || "").trim(),
        sender_position: (document.getElementById("settings-sender-position").value || "").trim(),
        sender_company: (document.getElementById("settings-sender-company").value || "").trim(),
        sender_phone: (document.getElementById("settings-sender-phone").value || "").trim(),
      };

      // Only send dedup fields if the section is visible (Pro users).
      var dedupSectionVis = document.getElementById("settings-dedup-section");
      if (dedupSectionVis && dedupSectionVis.style.display !== "none") {
        var dedupEnabledEl = document.getElementById("settings-dedup-enabled");
        var dedupDaysEl = document.getElementById("settings-dedup-days");
        if (dedupEnabledEl) payload.cross_campaign_dedup_enabled = !!dedupEnabledEl.checked;
        if (dedupDaysEl) payload.cross_campaign_dedup_days = parseInt(dedupDaysEl.value, 10) || 60;
      }

      chrome.runtime.sendMessage(
        { type: "UPDATE_SETTINGS", payload: payload },
        function (resp) {
          btnSaveSettings.textContent = t("btnSaveSettings");
          btnSaveSettings.disabled = false;

          if (resp && !resp.error) {
            btnSaveSettings.textContent = t("settingsSaved");
            setTimeout(function () {
              btnSaveSettings.textContent = t("btnSaveSettings");
            }, 2000);
          } else {
            if (!handleSessionExpired(resp)) {
              alert(t("settingsSaveFailed") + (resp ? resp.error : t("popupUnknownError")));
            }
          }
        }
      );
    });
  }

  // Upgrade button (in Account tab)
  var accountBtnUpgrade = document.getElementById("account-btn-upgrade");
  if (accountBtnUpgrade) {
    accountBtnUpgrade.addEventListener("click", function () {
      chrome.runtime.sendMessage({ type: "CREATE_CHECKOUT", plan: "starter" }, function (resp) {
        if (resp && resp.data && resp.data.checkout_url) {
          window.open(resp.data.checkout_url, "_blank");
        } else {
          alert(t("settingsCheckoutFailed"));
        }
      });
    });
  }

  // Manage subscription button (in Account tab)
  var accountBtnPortal = document.getElementById("account-btn-portal");
  if (accountBtnPortal) {
    accountBtnPortal.addEventListener("click", function () {
      chrome.runtime.sendMessage({ type: "OPEN_PORTAL" }, function (resp) {
        if (resp && resp.data && resp.data.portal_url) {
          window.open(resp.data.portal_url, "_blank");
        }
      });
    });
  }

  // Add suppression
  var btnAddSuppression = document.getElementById("btn-add-suppression");
  if (btnAddSuppression) {
    btnAddSuppression.addEventListener("click", function () {
      var input = document.getElementById("suppression-email-input");
      var email = input.value.trim();
      if (!email) return;

      chrome.runtime.sendMessage(
        { type: "ADD_SUPPRESSION", payload: { email: email } },
        function (resp) {
          if (resp && !resp.error) {
            input.value = "";
            loadSuppressionList();
          } else {
            if (!handleSessionExpired(resp)) {
              alert(t("alertSendFailed") + ": " + (resp ? resp.error : t("popupUnknownError")));
            }
          }
        }
      );
    });
  }

  // ── Connection Status ──
  var connDot = document.getElementById("conn-dot");
  var offlineBanner = document.getElementById("offline-banner");
  var _lastConnState = null;

  function setConnectionState(online) {
    if (online === _lastConnState) return;
    _lastConnState = online;

    if (connDot) {
      connDot.className = "conn-dot " + (online ? "online" : "offline");
      connDot.title = online ? t("connOnline") : t("connOffline");
    }
    if (offlineBanner) {
      offlineBanner.style.display = online ? "none" : "block";
    }
  }

  function checkConnection() {
    try {
      if (!chrome.runtime?.id) {
        // Extension was reloaded/updated — stop polling, show reload hint
        if (_healthInterval) clearInterval(_healthInterval);
        setConnectionState(false);
        if (offlineBanner) offlineBanner.textContent = t("extUpdatedReload");
        return;
      }
      chrome.runtime.sendMessage({ type: "HEALTH_CHECK" }, function (resp) {
        if (chrome.runtime.lastError) {
          setConnectionState(false);
          return;
        }
        setConnectionState(!!(resp && resp.ok));
      });
    } catch (e) {
      // Extension context invalidated — stop polling
      if (_healthInterval) clearInterval(_healthInterval);
      setConnectionState(false);
      if (offlineBanner) {
        offlineBanner.textContent = t("extUpdatedReload");
        offlineBanner.style.display = "block";
      }
    }
  }

  // Check immediately, then every 30 seconds
  var _healthInterval = null;
  function startHealthCheck() {
    checkConnection();
    _healthInterval = setInterval(checkConnection, 30000);
  }

  // Also react to browser online/offline events
  window.addEventListener("online", checkConnection);
  window.addEventListener("offline", function () { setConnectionState(false); });

  // ── Feedback ──
  var btnSendFeedback = document.getElementById("btn-send-feedback");
  var feedbackMessage = document.getElementById("feedback-message");
  var feedbackStatus = document.getElementById("feedback-status");

  if (btnSendFeedback) {
    btnSendFeedback.addEventListener("click", function () {
      var msg = feedbackMessage ? feedbackMessage.value.trim() : "";
      if (!msg) {
        if (feedbackStatus) {
          feedbackStatus.textContent = t("feedbackEmpty");
          feedbackStatus.className = "feedback-status error";
        }
        return;
      }

      btnSendFeedback.disabled = true;
      btnSendFeedback.textContent = t("reportsLoading");

      // Get user email from account tab if loaded
      var emailEl = document.getElementById("account-email");
      var userEmail = emailEl && emailEl.textContent !== "-" ? emailEl.textContent : "";

      chrome.runtime.sendMessage(
        {
          type: "SEND_FEEDBACK",
          payload: {
            message: msg,
            email: userEmail,
            context: {
              url: window.location.href,
              userAgent: navigator.userAgent,
              version: "0.1.0",
            },
          },
        },
        function (resp) {
          btnSendFeedback.disabled = false;
          btnSendFeedback.textContent = t("btnSendFeedback");

          if (resp && !resp.error) {
            feedbackMessage.value = "";
            if (feedbackStatus) {
              feedbackStatus.textContent = t("feedbackSent");
              feedbackStatus.className = "feedback-status success";
            }
          } else {
            if (feedbackStatus) {
              feedbackStatus.textContent = t("feedbackFailed");
              feedbackStatus.className = "feedback-status error";
            }
          }
        }
      );
    });
  }

  // ── Language selector ──
  var langSelect = document.getElementById("settings-language");
  if (langSelect) {
    // Load current preference
    try {
      chrome.storage.local.get("uiLanguage", function (r) {
        if (r && r.uiLanguage) langSelect.value = r.uiLanguage;
      });
    } catch (e) { /* ignore */ }

    langSelect.addEventListener("change", function () {
      var newLang = langSelect.value;
      chrome.storage.local.set({ uiLanguage: newLang }, function () {
        // Reload sidebar to apply new language
        window.location.reload();
      });
    });
  }

  // ── D.3: Onboarding wizard (first-run only) ──
  var ONB_STEPS = ["onbStep1", "onbStep2", "onbStep3"];
  var _onbStep = 0;

  function showOnboardingIfFirstRun() {
    var overlay = document.getElementById("onboarding-overlay");
    if (!overlay) return;
    chrome.storage.local.get("onboardingDone", function (r) {
      if (r.onboardingDone) return;
      _onbStep = 0;
      renderOnbStep();
      overlay.style.display = "flex";
    });
  }

  function renderOnbStep() {
    var body = document.getElementById("onb-step-body");
    if (!body) return;
    body.textContent = t(ONB_STEPS[_onbStep]);
    document.getElementById("onb-progress").textContent = (_onbStep + 1) + " / " + ONB_STEPS.length;
    document.getElementById("onb-prev").disabled = _onbStep === 0;
    document.getElementById("onb-next").textContent =
      _onbStep === ONB_STEPS.length - 1 ? t("onbFinish") : t("onbNext");
  }

  function finishOnboarding() {
    chrome.storage.local.set({ onboardingDone: true });
    var overlay = document.getElementById("onboarding-overlay");
    if (overlay) overlay.style.display = "none";
  }

  var _onbNextBtn = document.getElementById("onb-next");
  if (_onbNextBtn) {
    _onbNextBtn.addEventListener("click", function () {
      if (_onbStep < ONB_STEPS.length - 1) { _onbStep++; renderOnbStep(); return; }
      finishOnboarding();
    });
  }
  var _onbPrevBtn = document.getElementById("onb-prev");
  if (_onbPrevBtn) {
    _onbPrevBtn.addEventListener("click", function () {
      if (_onbStep > 0) { _onbStep--; renderOnbStep(); }
    });
  }
  var _onbSkipBtn = document.getElementById("onb-skip");
  if (_onbSkipBtn) {
    _onbSkipBtn.addEventListener("click", finishOnboarding);
  }

  // ── Init ──
  function init() {
    log("Sidebar loaded");
    startHealthCheck();
    loadQuota();
    updateSendButton();
    loadTemplates();
    showOnboardingIfFirstRun();
    pollReauthState();
    // Re-check reauth state every 5 minutes — catches the case where a
    // background scheduled send flagged the user but the sidebar stayed open.
    setInterval(pollReauthState, 5 * 60 * 1000);
  }

  // Load i18n override first (if user picked a specific language), then apply
  if (typeof initI18n === "function") {
    initI18n().then(function () {
      applyI18n();
      init();
    });
  } else {
    applyI18n();
    init();
  }
})();
