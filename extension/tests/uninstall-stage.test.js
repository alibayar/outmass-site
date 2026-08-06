/**
 * Uninstall funnel-stage tests — runs the REAL analytics.js against a stubbed
 * chrome, so the ladder can't drift from what ships.
 *
 * Why this exists: Chrome makes us register the uninstall URL in ADVANCE, so
 * the only way it can describe where a user gave up is if we keep re-pointing
 * it as they progress. Every failure mode here is SILENT — a renamed event, a
 * stage that quietly demotes on update, a ladder entry the backend doesn't
 * know — produces a perfectly working extension that simply tells us nothing
 * when someone leaves. That is the exact class of bug that made the 2026-08-03
 * rage-uninstall take log forensics to explain.
 *
 * Invariants locked here:
 *  1. Only ladder events move the stage; ordinary events never touch the URL.
 *  2. The stage is MONOTONIC — signing out can't demote a user who once sent.
 *  3. refreshUninstallUrl() (called on install AND update) restores the stored
 *     stage, so an update doesn't reset a long-time sender to "installed".
 *  4. Every event name in the map is really emitted somewhere in the extension
 *     — a rename would otherwise stop the ladder without any symptom.
 *  5. Every mapped stage exists on the ladder.
 */

const fs = require("fs");
const path = require("path");

const EXT_DIR = path.join(__dirname, "..");

function loadAnalytics(opts) {
  const src = fs.readFileSync(path.join(EXT_DIR, "analytics.js"), "utf8");
  const store = Object.assign({}, (opts && opts.storage) || {});
  const uninstallUrls = [];

  const chromeStub = {
    runtime: {
      getManifest: () => ({ version: "9.9.9" }),
      getPlatformInfo: () => Promise.resolve({ os: "win" }),
      setUninstallURL: (url, cb) => {
        uninstallUrls.push(url);
        if (cb) cb();
      },
      lastError: null,
    },
    i18n: { getUILanguage: () => "en-US" },
    storage: {
      local: {
        get: (keys) => {
          const out = {};
          for (const k of [].concat(keys)) {
            if (Object.prototype.hasOwnProperty.call(store, k)) out[k] = store[k];
          }
          return Promise.resolve(out);
        },
        set: (obj) => {
          Object.assign(store, obj);
          return Promise.resolve();
        },
        remove: (keys) => {
          for (const k of [].concat(keys)) delete store[k];
          return Promise.resolve();
        },
      },
    },
  };

  // console is silenced and setInterval neutered: the flush timer would fire
  // mid-suite and reach for config.js globals that aren't loaded here.
  const quietConsole = { warn: () => {}, log: () => {}, error: () => {} };
  const selfStub = { crypto: { randomUUID: () => "11111111-1111-4111-8111-111111111111" }, navigator: { userAgent: "Chrome" } };

  const exported =
    "\n;return { track, identify, refreshUninstallUrl, _PH_STAGE_LADDER, _PH_STAGE_EVENTS, _PH_STAGE_KEY, _PH_QUEUE_KEY };";
  // eslint-disable-next-line no-new-func
  const api = new Function(
    "chrome",
    "console",
    "self",
    "setInterval",
    "fetch",
    src + exported
  )(chromeStub, quietConsole, selfStub, () => 0, () => Promise.resolve({ ok: true }));

  return { api, store, uninstallUrls };
}

function stageOf(url) {
  const m = /[?&]stage=([^&]*)/.exec(url || "");
  return m ? decodeURIComponent(m[1]) : null;
}

async function behaviourChecks(failures) {
  const check = (cond, label) => { if (!cond) failures.push(label); };

  // ── 1. Ordinary events must not touch the uninstall URL ──
  {
    const { api, uninstallUrls } = loadAnalytics({});
    await api.track("template_saved", {});
    await api.track("reports_view_changed", {});
    check(
      uninstallUrls.length === 0,
      "a non-ladder event re-registered the uninstall URL (churn for nothing)"
    );
  }

  // ── 2. A ladder event records the stage AND the version ──
  {
    const { api, store, uninstallUrls } = loadAnalytics({});
    await api.track("sidebar_opened", {});
    check(
      store[api._PH_STAGE_KEY] === "panel_opened",
      "sidebar_opened did not persist stage=panel_opened"
    );
    check(
      stageOf(uninstallUrls[uninstallUrls.length - 1]) === "panel_opened",
      "uninstall URL missing stage=panel_opened"
    );
    check(
      /[?&]v=9\.9\.9(&|$)/.test(uninstallUrls[uninstallUrls.length - 1]),
      "uninstall URL missing the extension version"
    );
  }

  // ── 3. Monotonic — the whole point ──
  {
    const { api, store, uninstallUrls } = loadAnalytics({});
    await api.track("send_completed", {});
    check(store[api._PH_STAGE_KEY] === "sent", "send_completed should reach stage=sent");
    const afterSent = uninstallUrls.length;

    // A user who signs out and reopens the panel emits these again. If the
    // ladder moved backwards, a customer who has sent thousands of emails
    // would uninstall looking like they never got past the panel.
    await api.track("sidebar_opened", {});
    await api.track("signin_clicked", {});
    check(
      store[api._PH_STAGE_KEY] === "sent",
      "stage moved BACKWARDS — a sender was demoted to an earlier stage"
    );
    check(
      uninstallUrls.length === afterSent,
      "a backwards event still re-registered the uninstall URL"
    );
  }

  // ── 4. Install/update must not demote ──
  {
    const { api, uninstallUrls } = loadAnalytics({
      storage: { outmass_funnel_stage: "recipients_uploaded" },
    });
    await api.refreshUninstallUrl();
    check(
      stageOf(uninstallUrls[0]) === "recipients_uploaded",
      "refreshUninstallUrl reset a known stage — an UPDATE would erase the funnel position"
    );
  }
  {
    const { api, uninstallUrls } = loadAnalytics({});
    await api.refreshUninstallUrl();
    check(
      stageOf(uninstallUrls[0]) === "installed",
      "a fresh install should register stage=installed"
    );
  }

  return failures;
}

async function run() {
  const failures = [];
  const { api } = loadAnalytics({});

  // ── 5. Every mapped stage is on the ladder ──
  for (const [event, stage] of Object.entries(api._PH_STAGE_EVENTS)) {
    if (api._PH_STAGE_LADDER.indexOf(stage) < 0) {
      failures.push(`event ${event} maps to "${stage}", which is not on the ladder`);
    }
  }

  // ── 6. Every mapped event is really emitted somewhere ──
  // A rename in sidebar.js would otherwise freeze the ladder with no symptom:
  // the extension keeps working, the uninstall URL just silently stops
  // advancing and every churned user looks like they stalled early.
  const sources = ["background.js", "sidebar.js", "popup.js", "content_script.js"]
    .map((f) => fs.readFileSync(path.join(EXT_DIR, f), "utf8"))
    .join("\n");
  for (const event of Object.keys(api._PH_STAGE_EVENTS)) {
    if (!sources.includes(`"${event}"`)) {
      failures.push(
        `stage event "${event}" is not emitted anywhere in the extension — ` +
        `renamed? the ladder would stop advancing silently`
      );
    }
  }

  await behaviourChecks(failures);

  return { name: "uninstall-stage", failures };
}

module.exports = { run, behaviourChecks, loadAnalytics };
