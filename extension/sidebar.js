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

  function handleCSV(file) {
    var reader = new FileReader();
    reader.onload = function (e) {
      var text = e.target.result;
      csvRawText = text; // Keep raw CSV for backend
      var lines = text.trim().split("\n");
      var headers = parseCSVLine(lines[0]);
      var rows = [];

      for (var i = 1; i < lines.length; i++) {
        if (!lines[i].trim()) continue; // skip empty lines
        var values = parseCSVLine(lines[i]);
        var row = {};
        headers.forEach(function (h, idx) {
          row[h] = values[idx] !== undefined ? values[idx] : "";
        });
        rows.push(row);
      }

      csvData = { headers: headers, rows: rows };

      csvDropzone.style.display = "none";
      csvInfo.style.display = "flex";
      csvFilename.textContent = file.name;
      csvCount.textContent = rows.length + " " + t("csvCountSuffix");

      updateSendButton();
      log("CSV loaded:", file.name, rows.length, "rows");
    };
    reader.readAsText(file);
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

  // ── Form validation → enable/disable Send button ──
  function updateSendButton() {
    var hasCSV = csvData && csvData.rows.length > 0;
    var hasSubject = subjectInput.value.trim().length > 0;
    var hasBody = bodyInput.value.trim().length > 0;
    btnSend.disabled = !(hasCSV && hasSubject && hasBody);
  }

  subjectInput.addEventListener("input", updateSendButton);
  bodyInput.addEventListener("input", updateSendButton);

  // ── Preview ──
  btnPreview.addEventListener("click", function () {
    if (!csvData || csvData.rows.length === 0) {
      alert(t("alertUploadCsvFirst"));
      return;
    }

    var subject = subjectInput.value;
    var body = bodyInput.value;
    var firstRow = csvData.rows[0];

    var previewSubject = mergePlaceholders(subject, firstRow);
    var previewBody = mergePlaceholders(body, firstRow);

    alert(t("alertPreviewTitle") + previewSubject + "\n\n" + previewBody);
    log("Preview shown for first row");
  });

  function mergePlaceholders(template, row) {
    return template.replace(/\{\{(\w+)\}\}/g, function (match, key) {
      return row[key] !== undefined ? row[key] : match;
    });
  }

  // ── Quota ──
  function loadQuota() {
    chrome.storage.local.get(["emailsSentThisMonth", "plan"], function (result) {
      var sent = result.emailsSentThisMonth || 0;
      var plan = result.plan || "free";
      var limit = plan === "pro" ? 10000 : plan === "starter" ? 2000 : 50;
      var remaining = Math.max(0, limit - sent);
      var planLabel = plan === "pro" ? "Pro Plan" : plan === "starter" ? "Starter Plan" : "Free Plan";

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

  function startSendFlow(subject, body) {
    var campaignName = subject.substring(0, 50) || t("tabCampaign");

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

            var count = uploadResp.data ? uploadResp.data.count : uploadResp.count;
            log("Contacts uploaded:", count);

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
      alert(t("alertScheduledSuccess", [String(count), schedDate.toLocaleString()]));
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
              alert(t("alertAiFailed") + (resp ? resp.error : t("popupUnknownError")));
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
            alert(t("alertTemplateDeleteFailed") + ((resp && resp.error) || t("popupUnknownError")));
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
      var name = prompt(t("templatePromptName"), subject.substring(0, 40) || t("templateDefaultName"));
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
      } else {
        scheduleFields.classList.remove("visible");
      }
    });
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

  function loadReports() {
    reportsList.style.display = "block";
    reportsDetail.style.display = "none";
    reportsLoading.style.display = "block";
    campaignListEl.innerHTML = "";

    chrome.runtime.sendMessage({ type: "GET_CAMPAIGNS" }, function (resp) {
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
        var date = c.created_at ? new Date(c.created_at).toLocaleDateString("tr-TR") : "";

        var row = document.createElement("div");
        row.className = "campaign-row";
        row.innerHTML =
          '<div class="campaign-row-name">' + escapeHtml(c.name) + '</div>' +
          '<div class="campaign-row-meta">' +
            '<span>' + date + '</span>' +
            '<span>' + sent + t("reportsSentSuffix") + '</span>' +
            '<span class="rate">' + t("reportsOpenRate") + openRate + '%</span>' +
            '<span class="rate">' + t("reportsClickRate") + clickRate + '%</span>' +
          '</div>';
        row.addEventListener("click", function () {
          showCampaignDetail(c.id);
        });
        campaignListEl.appendChild(row);
      });

      log("Reports loaded:", campaigns.length, "campaigns");
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
              alert(t("alertCsvExportFailed") + (resp ? resp.error : t("popupUnknownError")));
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
            alert(t("settingsSaveFailed") + (resp ? resp.error : t("popupUnknownError")));
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
            alert(t("alertSendFailed") + ": " + (resp ? resp.error : t("popupUnknownError")));
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

  // ── Init ──
  function init() {
    log("Sidebar loaded");
    startHealthCheck();
    loadQuota();
    updateSendButton();
    loadTemplates();
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
