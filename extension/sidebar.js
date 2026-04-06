/**
 * OutMass — Sidebar
 * Campaign creation UI inside iframe
 */

(function () {
  "use strict";

  var LOG_PREFIX = "[OutMass-Sidebar]";
  var csvRawText = null; // Raw CSV string for backend upload

  function log() {
    var args = [LOG_PREFIX];
    for (var i = 0; i < arguments.length; i++) args.push(arguments[i]);
    console.log.apply(console, args);
  }

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

      log("Tab switched to:", target);
    });
  });

  // ── Close ──
  btnClose.addEventListener("click", function () {
    window.parent.postMessage({ source: "outmass-sidebar", type: "CLOSE_SIDEBAR" }, "*");
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

  function handleCSV(file) {
    var reader = new FileReader();
    reader.onload = function (e) {
      var text = e.target.result;
      csvRawText = text; // Keep raw CSV for backend
      var lines = text.trim().split("\n");
      var headers = lines[0].split(",").map(function (h) { return h.trim(); });
      var rows = [];

      for (var i = 1; i < lines.length; i++) {
        var values = lines[i].split(",");
        var row = {};
        headers.forEach(function (h, idx) {
          row[h] = values[idx] ? values[idx].trim() : "";
        });
        rows.push(row);
      }

      csvData = { headers: headers, rows: rows };

      csvDropzone.style.display = "none";
      csvInfo.style.display = "flex";
      csvFilename.textContent = file.name;
      csvCount.textContent = rows.length + " alici";

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
      alert("Once bir CSV dosyasi yukleyin.");
      return;
    }

    var subject = subjectInput.value;
    var body = bodyInput.value;
    var firstRow = csvData.rows[0];

    var previewSubject = mergePlaceholders(subject, firstRow);
    var previewBody = mergePlaceholders(body, firstRow);

    alert("--- ONIZLEME ---\nKonu: " + previewSubject + "\n\n" + previewBody);
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
      var limit = plan === "pro" ? 10000 : plan === "standard" ? 5000 : 50;
      var remaining = Math.max(0, limit - sent);
      var planLabel = plan === "pro" ? "Pro Plan" : plan === "standard" ? "Standard Plan" : "Free Plan";

      quotaText.textContent = remaining + "/" + limit + " email kaldi (" + planLabel + ")";
      quotaFill.style.width = (remaining / limit * 100) + "%";
    });
  }

  // ── Send Campaign ──
  btnSend.addEventListener("click", function () {
    if (!csvData || !csvRawText) {
      alert("Once bir CSV dosyasi yukleyin.");
      return;
    }

    var subject = subjectInput.value.trim();
    var body = bodyInput.value.trim();

    if (!subject || !body) {
      alert("Konu ve email icerigi doldurun.");
      return;
    }

    // Check quota first
    chrome.storage.local.get(["emailsSentThisMonth", "plan"], function (storage) {
      var sent = storage.emailsSentThisMonth || 0;
      var plan = storage.plan || "free";
      var limit = plan === "pro" ? 10000 : plan === "standard" ? 5000 : 50;
      var remaining = limit - sent;

      if (remaining <= 0) {
        alert("Plan limitinize ulastiniz (" + limit + " email/ay).\nPlaninizi yukseltin.");
        return;
      }

      if (csvData.rows.length > remaining) {
        alert(
          remaining + " email hakkiniz kaldi.\n" +
          "CSV'de " + csvData.rows.length + " alici var.\n" +
          "Ilk " + remaining + " aliciya gonderilecek."
        );
      }

      startSendFlow(subject, body);
    });
  });

  function startSendFlow(subject, body) {
    var campaignName = subject.substring(0, 50) || "Kampanya";

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
    btnSend.textContent = scheduledFor ? "Zamanlaniyor..." : "Hazirlaniyor...";
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
          showSendError(createResp ? createResp.error : "Kampanya olusturulamadi");
          return;
        }

        var campaignId = createResp.data
          ? createResp.data.campaign_id
          : createResp.campaign_id;
        log("Campaign created:", campaignId);
        btnSend.textContent = "Alicilar yukleniyor...";

        // Step 2: Upload contacts
        chrome.runtime.sendMessage(
          {
            type: "UPLOAD_CONTACTS",
            campaignId: campaignId,
            payload: { csv_string: csvRawText },
          },
          function (uploadResp) {
            if (!uploadResp || uploadResp.error) {
              showSendError(uploadResp ? uploadResp.error : "Alicilar yuklenemedi");
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
                      alert("A/B testing sadece Pro planda kullanilabilir.");
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
      btnSend.textContent = "Gonder";
      btnSend.disabled = false;
      var schedDate = new Date(scheduledFor);
      alert("Basarili! " + count + " aliciya " + schedDate.toLocaleString("tr-TR") + " tarihinde gonderilecek.");
      log("Campaign scheduled:", campaignId, "for", scheduledFor);
      maybeCreateFollowup(campaignId);
      return;
    }

    btnSend.textContent = "Gonderiliyor... 0/" + count;

    // Step 3: Send
    chrome.runtime.sendMessage(
      {
        type: "SEND_CAMPAIGN",
        campaignId: campaignId,
      },
      function (sendResp) {
        if (!sendResp) {
          showSendError("Gonderim basarisiz");
          return;
        }
        if (sendResp.error) {
          if (sendResp.status === 402 || sendResp.error === "limit_exceeded") {
            btnSend.textContent = "Gonder";
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
        btnSend.textContent = "Gonder";
        btnSend.disabled = false;

        if (queued === 0 && sendErrors.length > 0) {
          alert("Gonderim basarisiz!\n\nHata: " + sendErrors[0].error);
          log("Campaign send errors:", sendErrors);
        } else if (hasAbTest) {
          alert("Basarili! " + queued + " email gonderildi (A/B test).\nKazanan konu satiri otomatik gonderilecek.");
        } else if (sendErrors.length > 0) {
          alert(queued + " email gonderildi, " + sendErrors.length + " hata olustu.\n\nIlk hata: " + sendErrors[0].error);
        } else {
          alert("Basarili! " + queued + " email gonderildi.");
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
    btnSend.textContent = "Gonder";
    btnSend.disabled = false;
    alert("Hata: " + message);
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
      '<h3 style="margin:0 0 12px;font-size:16px;color:#323130;">AI Email Yazici</h3>' +
      '<textarea id="ai-prompt" rows="3" placeholder="Ne hakkinda email yazilsin?&#10;Ornek: SaaS urunumuz icin soguk satis emaili" style="width:100%;padding:8px;border:1px solid #c8c6c4;border-radius:4px;font-size:13px;font-family:inherit;resize:vertical;box-sizing:border-box;"></textarea>' +
      '<div style="display:flex;gap:8px;margin-top:8px;">' +
        '<select id="ai-tone" style="flex:1;padding:6px;border:1px solid #c8c6c4;border-radius:4px;font-size:12px;">' +
          '<option value="professional">Profesyonel</option>' +
          '<option value="friendly">Samimi</option>' +
          '<option value="formal">Resmi</option>' +
          '<option value="casual">Rahat</option>' +
        '</select>' +
        '<select id="ai-lang" style="flex:1;padding:6px;border:1px solid #c8c6c4;border-radius:4px;font-size:12px;">' +
          '<option value="tr">Turkce</option>' +
          '<option value="en">English</option>' +
        '</select>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:12px;">' +
        '<button id="ai-generate-btn" style="flex:1;padding:10px;background:#0078d4;color:#fff;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-family:inherit;">Olustur</button>' +
        '<button id="ai-cancel-btn" style="padding:10px 16px;background:none;border:1px solid #c8c6c4;border-radius:6px;color:#605e5c;font-size:13px;cursor:pointer;font-family:inherit;">Iptal</button>' +
      '</div>';

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    document.getElementById("ai-generate-btn").addEventListener("click", function () {
      var promptInput = document.getElementById("ai-prompt");
      var toneSelect = document.getElementById("ai-tone");
      var langSelect = document.getElementById("ai-lang");
      var generateBtn = document.getElementById("ai-generate-btn");

      var promptText = promptInput.value.trim();
      if (!promptText) {
        alert("Lutfen ne hakkinda email istediginizi yazin.");
        return;
      }

      generateBtn.textContent = "Olusturuluyor...";
      generateBtn.disabled = true;

      chrome.runtime.sendMessage(
        {
          type: "AI_GENERATE_EMAIL",
          payload: {
            prompt: promptText,
            tone: toneSelect.value,
            language: langSelect.value,
          },
        },
        function (resp) {
          generateBtn.textContent = "Olustur";
          generateBtn.disabled = false;

          if (!resp || resp.error) {
            if (resp && resp.status === 402) {
              alert("AI email yazici sadece Pro planda kullanilabilir.");
            } else {
              alert("AI olusturma basarisiz: " + (resp ? resp.error : "Bilinmeyen hata"));
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

  function loadTemplates() {
    chrome.runtime.sendMessage({ type: "GET_TEMPLATES" }, function (resp) {
      if (!resp || resp.error || !resp.data) return;
      var templates = resp.data.templates || [];

      // Clear existing options except first
      while (templateSelect.options.length > 1) {
        templateSelect.remove(1);
      }

      templates.forEach(function (t) {
        var opt = document.createElement("option");
        opt.value = JSON.stringify({ subject: t.subject, body: t.body });
        opt.textContent = t.name;
        opt.dataset.templateId = t.id;
        templateSelect.appendChild(opt);
      });
    });
  }

  if (templateSelect) {
    templateSelect.addEventListener("change", function () {
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

  if (btnSaveTemplate) {
    btnSaveTemplate.addEventListener("click", function () {
      var subject = subjectInput.value.trim();
      var body = bodyInput.value.trim();
      if (!subject && !body) {
        alert("Once konu ve icerik doldurun.");
        return;
      }
      var name = prompt("Sablon adi:", subject.substring(0, 40) || "Sablonum");
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
          btnSaveTemplate.textContent = "Kaydet";

          if (resp && !resp.error) {
            log("Template saved");
            loadTemplates(); // Refresh list
          } else {
            var errMsg = resp && resp.error;
            if (resp && resp.status === 402) {
              alert("Email sablonlari Standard ve Pro planlarda kullanilabilir.");
            } else {
              alert("Sablon kaydedilemedi: " + (errMsg || "Bilinmeyen hata"));
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
        campaignListEl.innerHTML = '<div class="no-campaigns">Kampanya bulunamadi.</div>';
        return;
      }

      var campaigns = resp.data ? resp.data.campaigns : resp.campaigns;
      if (!campaigns || campaigns.length === 0) {
        campaignListEl.innerHTML = '<div class="no-campaigns">Henuz kampanya yok.</div>';
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
            '<span>' + sent + ' gonderildi</span>' +
            '<span class="rate">Acilma: ' + openRate + '%</span>' +
            '<span class="rate">Tiklama: ' + clickRate + '%</span>' +
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
          document.getElementById("detail-name").textContent = "Hata";
          return;
        }

        var stats = resp.data || resp;
        document.getElementById("detail-name").textContent = stats.name || "Kampanya";
        document.getElementById("stat-sent").textContent = stats.sent_count || 0;
        document.getElementById("stat-opened").textContent = stats.open_count || 0;
        document.getElementById("stat-clicked").textContent = stats.click_count || 0;
        document.getElementById("stat-open-rate").textContent = (stats.open_rate || 0) + "%";
        document.getElementById("stat-click-rate").textContent = (stats.click_rate || 0) + "%";

        // Follow-up status
        var followupEl = document.getElementById("followup-status");
        if (stats.pending_followups > 0) {
          followupEl.textContent = stats.pending_followups + " follow-up bekliyor";
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
      btnExportCsv.textContent = "Indiriliyor...";
      btnExportCsv.disabled = true;

      chrome.runtime.sendMessage(
        { type: "EXPORT_CAMPAIGN_CSV", campaignId: currentDetailCampaignId },
        function (resp) {
          btnExportCsv.textContent = "CSV Indir";
          btnExportCsv.disabled = false;

          if (!resp || resp.error) {
            if (resp && resp.status === 402) {
              alert("CSV export Standard ve Pro planlarda kullanilabilir.");
            } else {
              alert("Export basarisiz: " + (resp ? resp.error : "Bilinmeyen hata"));
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
            alert("CSV export basarili ancak veri bos.");
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
      { label: "Gonderildi", value: sent, color: "#0078d4" },
      { label: "Acildi", value: opened, color: "#107c10" },
      { label: "Tiklandi", value: clicked, color: "#ff8c00" },
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
      '<h3 style="margin:0 0 8px;color:#323130;font-size:18px;">Planinizi Yukseltin</h3>' +
      '<p style="color:#605e5c;font-size:13px;margin-bottom:16px;">Email limitinize ulastiniz.<br/>Daha fazla email gondermek icin yukseltin.</p>' +
      '<ul style="text-align:left;font-size:12px;color:#605e5c;margin:0 0 20px 16px;padding:0;">' +
        '<li>Standard: 5,000 email/ay — $15/ay</li>' +
        '<li>Pro: 10,000 email/ay — $25/ay</li>' +
        '<li>Detayli raporlama + oncelikli destek</li>' +
      '</ul>' +
      '<button id="btn-upgrade" style="width:100%;padding:10px;background:#0078d4;color:#fff;border:none;border-radius:6px;font-size:14px;cursor:pointer;font-family:inherit;margin-bottom:8px;">Simdi Yukselt — Standard $15/ay</button>' +
      '<button id="btn-upgrade-cancel" style="width:100%;padding:8px;background:none;border:1px solid #c8c6c4;border-radius:6px;color:#605e5c;font-size:13px;cursor:pointer;font-family:inherit;">Belki sonra</button>';

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    document.getElementById("btn-upgrade").addEventListener("click", function () {
      chrome.runtime.sendMessage({ type: "CREATE_CHECKOUT", plan: "standard" }, function (resp) {
        if (resp && resp.data && resp.data.checkout_url) {
          window.open(resp.data.checkout_url, "_blank");
        } else {
          alert("Odeme sayfasi olusturulamadi. Lutfen tekrar deneyin.");
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

      // Account info
      var emailEl = document.getElementById("settings-email");
      var planEl = document.getElementById("settings-plan");
      var sentEl = document.getElementById("settings-sent-count");
      if (emailEl) emailEl.textContent = data.email || "-";
      if (planEl) {
        var plan = data.plan || "free";
        planEl.textContent = plan.charAt(0).toUpperCase() + plan.slice(1);
        planEl.className = "plan-badge " + plan;
      }
      if (sentEl) sentEl.textContent = data.emails_sent_this_month || 0;

      // Plan buttons
      var btnUpgrade = document.getElementById("settings-btn-upgrade");
      var btnPortal = document.getElementById("settings-btn-portal");
      if (data.plan === "free") {
        if (btnUpgrade) btnUpgrade.style.display = "block";
        if (btnPortal) btnPortal.style.display = "none";
      } else {
        if (btnUpgrade) btnUpgrade.style.display = "none";
        if (btnPortal) btnPortal.style.display = "block";
      }

      // Tracking
      var trackOpens = document.getElementById("settings-track-opens");
      var trackClicks = document.getElementById("settings-track-clicks");
      if (trackOpens) trackOpens.checked = data.track_opens !== false;
      if (trackClicks) trackClicks.checked = data.track_clicks !== false;

      // Unsub text
      var unsubText = document.getElementById("settings-unsub-text");
      if (unsubText && data.unsubscribe_text) unsubText.value = data.unsubscribe_text;

      // Timezone
      var tzSelect = document.getElementById("settings-timezone");
      if (tzSelect && data.timezone) tzSelect.value = data.timezone;

      log("Settings loaded");
    });

    // Load suppression list
    loadSuppressionList();
  }

  function loadSuppressionList() {
    chrome.runtime.sendMessage({ type: "GET_SUPPRESSION_LIST" }, function (resp) {
      var listEl = document.getElementById("suppression-list");
      var emptyEl = document.getElementById("suppression-empty");
      if (!listEl) return;

      if (!resp || resp.error || !resp.data) {
        if (emptyEl) emptyEl.style.display = "block";
        return;
      }

      var emails = resp.data.emails || [];
      listEl.innerHTML = "";

      if (emails.length === 0) {
        if (emptyEl) emptyEl.style.display = "block";
        return;
      }

      if (emptyEl) emptyEl.style.display = "none";

      emails.forEach(function (item) {
        var row = document.createElement("div");
        row.className = "suppression-row";
        row.innerHTML =
          '<span class="suppression-email">' + escapeHtml(item.email) + '</span>' +
          '<span class="suppression-reason">' + (item.reason === "user_unsubscribed" ? "Abone cikildi" : "Manuel") + '</span>' +
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
    });
  }

  // Settings save button
  var btnSaveSettings = document.getElementById("settings-btn-save");
  if (btnSaveSettings) {
    btnSaveSettings.addEventListener("click", function () {
      btnSaveSettings.textContent = "Kaydediliyor...";
      btnSaveSettings.disabled = true;

      var payload = {
        track_opens: document.getElementById("settings-track-opens").checked,
        track_clicks: document.getElementById("settings-track-clicks").checked,
        unsubscribe_text: document.getElementById("settings-unsub-text").value.trim(),
        timezone: document.getElementById("settings-timezone").value,
      };

      chrome.runtime.sendMessage(
        { type: "UPDATE_SETTINGS", payload: payload },
        function (resp) {
          btnSaveSettings.textContent = "Ayarlari Kaydet";
          btnSaveSettings.disabled = false;

          if (resp && !resp.error) {
            btnSaveSettings.textContent = "Kaydedildi!";
            setTimeout(function () {
              btnSaveSettings.textContent = "Ayarlari Kaydet";
            }, 2000);
          } else {
            alert("Ayarlar kaydedilemedi: " + (resp ? resp.error : "Bilinmeyen hata"));
          }
        }
      );
    });
  }

  // Upgrade button
  var settingsBtnUpgrade = document.getElementById("settings-btn-upgrade");
  if (settingsBtnUpgrade) {
    settingsBtnUpgrade.addEventListener("click", function () {
      chrome.runtime.sendMessage({ type: "CREATE_CHECKOUT", plan: "standard" }, function (resp) {
        if (resp && resp.data && resp.data.checkout_url) {
          window.open(resp.data.checkout_url, "_blank");
        } else {
          alert("Odeme sayfasi olusturulamadi.");
        }
      });
    });
  }

  // Manage subscription button
  var settingsBtnPortal = document.getElementById("settings-btn-portal");
  if (settingsBtnPortal) {
    settingsBtnPortal.addEventListener("click", function () {
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
            alert("Eklenemedi: " + (resp ? resp.error : "Bilinmeyen hata"));
          }
        }
      );
    });
  }

  // ── Init ──
  function init() {
    log("Sidebar loaded");
    loadQuota();
    updateSendButton();
    loadTemplates();
  }

  init();
})();
