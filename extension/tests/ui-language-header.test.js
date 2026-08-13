/**
 * The panel and the service worker must agree on what language this is.
 *
 * Every outgoing email — welcome, reconnect, quota-cap, upgrade, plan-dropped,
 * account-deleted, three inactivity tiers — is written in whatever
 * users.preferred_language says. That column is filled from one header,
 * X-UI-Language, set in background.js by _uiLanguageTag().
 *
 * The panel decides its own language with getActiveLocale() in i18n.js. The
 * service worker cannot call that function: i18n.js is loaded by the sidebar
 * and popup, never by the worker, and importing it there would pull in the
 * whole translation dictionary and its async init for two lines of logic.
 *
 * So there are two implementations of one rule, which is the exact shape that
 * drifts. If they disagree, someone reads the panel in Turkish and gets email
 * in English, and nothing anywhere fails. This runs both against the same
 * inputs and requires the same answer.
 *
 * One known divergence, deliberate: initI18n() only sets the override locale
 * if the matching _locales/<x>/messages.json actually loads. If that fetch
 * failed the panel would fall back to Chrome's UI language while the worker
 * still reported the override. The fetch is against the extension's own
 * bundle, so it fails only if the file is missing — which locale-consistency
 * already makes impossible.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const EXT = path.join(__dirname, "..");
const BACKEND = path.join(__dirname, "..", "..", "backend");

/** Pull one top-level `function name(...) { ... }` out of a source file. */
function extractFunction(src, name) {
  const start = src.indexOf("function " + name + "(");
  if (start === -1) return null;
  const open = src.indexOf("{", start);
  if (open === -1) return null;
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") {
      depth--;
      if (depth === 0) return src.slice(start, i + 1);
    }
  }
  return null;
}

const CASES = [
  { override: "tr", ui: "en-US", expect: "tr" },
  { override: "zh-CN", ui: "en-US", expect: "zh-CN" },
  { override: "zh_TW", ui: "en-US", expect: "zh-TW" },
  { override: "auto", ui: "de", expect: "de" },
  { override: undefined, ui: "pt-BR", expect: "pt-BR" },
  { override: null, ui: "ja", expect: "ja" },
  { override: "", ui: "ru", expect: "ru" },
  { override: "auto", ui: null, expect: "en" },
];

function run() {
  const failures = [];
  const check = (ok, msg) => { if (!ok) failures.push(msg); };

  const bgSrc = fs.readFileSync(path.join(EXT, "background.js"), "utf8");
  const i18nSrc = fs.readFileSync(path.join(EXT, "i18n.js"), "utf8");

  const workerFn = extractFunction(bgSrc, "_uiLanguageTag");
  const panelFn = extractFunction(i18nSrc, "getActiveLocale");

  // ── The extractor found something ──
  //
  // A source-reading check that matches nothing passes clean, which is the
  // worst of the three outcomes and has already happened once in this repo
  // (the sender detector in no-hardcoded-prices looked for `.post(` while the
  // real senders went through async_post_with_retry). Assert the tools work
  // before trusting what they say.
  check(workerFn !== null, "could not find _uiLanguageTag() in background.js");
  check(panelFn !== null, "could not find getActiveLocale() in i18n.js");
  check(
    extractFunction("function noSuchThing() { return 1; }", "missing") === null,
    "the function extractor claims to find functions that are not there"
  );
  if (!workerFn || !panelFn) return { name: "ui-language-header", failures };

  // ── They agree, on every input ──
  for (const c of CASES) {
    const context = {
      chrome: {
        i18n: {
          getUILanguage() {
            if (!c.ui) throw new Error("unavailable");
            return c.ui;
          },
        },
      },
      navigator: { language: undefined },
      // What initI18n() would have left behind for this override.
      _i18nOverrideLocale:
        c.override && c.override !== "auto" ? c.override : null,
    };
    vm.createContext(context);
    vm.runInContext(`${workerFn}\n${panelFn}`, context);

    const fromWorker = vm.runInContext(
      `_uiLanguageTag(${JSON.stringify(c.override ?? null)})`,
      context
    );
    const fromPanel = vm.runInContext("getActiveLocale()", context);

    const label = `override=${JSON.stringify(c.override)} ui=${c.ui}`;
    check(
      fromWorker === c.expect,
      `${label}: worker said ${fromWorker}, expected ${c.expect}`
    );
    check(
      fromWorker === fromPanel,
      `${label}: worker says ${fromWorker} but the panel renders ${fromPanel} ` +
        `— the user would read one language and be emailed another`
    );
  }

  // ── The header is actually attached ──
  //
  // The function can be perfect and never called. Three guards written on
  // 2026-08-10 passed their unit tests and were dead at the call site.
  check(
    /"X-UI-Language":\s*_uiLanguageTag\(/.test(bgSrc),
    "background.js computes the language tag but no longer sends it as " +
      "X-UI-Language on backendFetch — the column would stay NULL forever"
  );
  check(
    /chrome\.storage\.local\.get\(\[[^\]]*"uiLanguage"/.test(bgSrc),
    "backendFetch no longer reads uiLanguage from storage, so a Settings " +
      "override would be invisible to the worker"
  );

  // ── The backend reads the same header ──
  //
  // FastAPI maps the parameter name x_ui_language onto X-UI-Language. A
  // rename on either side is silent: the header simply never arrives and
  // every email quietly stays English.
  const authPy = fs.readFileSync(path.join(BACKEND, "routers", "auth.py"), "utf8");
  check(
    /x_ui_language\s*:/.test(authPy),
    "backend/routers/auth.py no longer accepts x_ui_language — the header " +
      "the extension sends would be dropped without a trace"
  );
  check(
    /preferred_language\s*=\s*x_ui_language/.test(authPy),
    "auth.py accepts the header but no longer stores it as preferred_language"
  );

  return { name: "ui-language-header", failures };
}

module.exports = { run };
