/**
 * A saved follow-up must never be reported as a scheduled one.
 *
 * From 0.3.1 the server answers a non-Pro follow-up with 200 and
 * `locked: true` instead of 402 — the configuration is kept, inert, and can
 * be started later from the campaign's report.
 *
 * That changes the shape of a SUCCESS response, and the panel's success branch
 * predates it. Without an explicit check, `{followup_id, locked: true}` falls
 * through to `log("Follow-up created")` and the user is told nothing at all —
 * which is exactly the silent failure this feature was built to end, restored
 * by the fix for it. Eight people hit that silence between June and August;
 * one of them was a customer three minutes after paying.
 *
 * The other half is activation. A follow-up is due per recipient at their own
 * send time plus the delay, so on a campaign that finished a while ago every
 * one of those moments has passed and starting it is not scheduling anything:
 * it sends, at once, to everyone. That number has to reach the user before it
 * happens, never after.
 */
const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");
const read = (f) => fs.readFileSync(path.join(EXT, f), "utf8");

const NEW_KEYS = [
  "alertFollowupSavedNeedsPro",
  "reportsFollowupSaved",
  "btnActivateFollowup",
  "alertFollowupActivated",
  "confirmFollowupImmediate",
  "alertFollowupAlreadyRunning",
  "alertFollowupActivateFailed",
];

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  const sidebar = read("sidebar.js");
  const background = read("background.js");

  // ── the success response is no longer one shape ──

  // Anchored on the CREATE_FOLLOWUP message this callback belongs to: there
  // are several `if (resp && !resp.error)` branches in this file, and a
  // looser pattern silently measures the wrong one.
  const success = /type: "CREATE_FOLLOWUP"[\s\S]{0,2600}?log\("Follow-up created[^\n]*\n/
    .exec(sidebar);
  check(success !== null, "the follow-up success branch could not be located");

  if (success) {
    check(
      /_fu\.locked/.test(success[0]),
      "the follow-up success branch no longer checks `locked` — a saved-but-" +
        "not-running follow-up is reported to the user as created, and they " +
        "find out when nobody is followed up"
    );
    check(
      success[0].indexOf("_fu.locked") < success[0].indexOf('log("Follow-up created'),
      "the `locked` check no longer runs BEFORE the created log — order is " +
        "the whole guard here"
    );
    check(
      /track\("feature_locked_followup"\)/.test(success[0]),
      "a locked save no longer records feature_locked_followup — this is the " +
        "only event that measures follow-up demand at the wall"
    );
  }

  // The configuration was KEPT, so clearing the control would misreport it.
  const lockedBranch = /if \(_fu\.locked\) \{[\s\S]{0,700}?\n          \}/.exec(sidebar);
  check(lockedBranch !== null, "the locked branch could not be located");
  check(
    lockedBranch === null || !/_fEnable\.checked = false/.test(lockedBranch[0]),
    "the locked branch unticks the follow-up box again — the configuration " +
      "was saved, and clearing the control says it was not"
  );
  check(
    lockedBranch === null || /minPlan: "pro"/.test(lockedBranch[0]),
    "the locked branch no longer offers Pro specifically — the catalogue " +
      "would sell Starter for a feature Starter does not unlock"
  );

  // ── activation ──

  check(
    /case "ACTIVATE_FOLLOWUP":[\s\S]{0,500}?\/activate\?confirm_immediate=/.test(background),
    "ACTIVATE_FOLLOWUP no longer posts to the activate endpoint with a " +
      "confirm_immediate flag — without the flag the server's safety question " +
      "cannot be answered and activation can never complete"
  );

  const activate = /function activateFollowup\([\s\S]{0,4000}?\n  \}/.exec(sidebar);
  check(activate !== null, "activateFollowup could not be located");

  if (activate) {
    check(
      /if \(handleNetworkFailure\(resp, null\)\) return;/.test(activate[0]),
      "activateFollowup no longer separates a connectivity failure from a " +
        "refusal — a dropped wifi shows 'the follow-up could not be started', " +
        "which reads as the server saying no. Passing null rather than the " +
        "button is deliberate: handleNetworkFailure relabels what it is given " +
        "to 'Send', which this button is not."
    );

    check(
      /message: t\("alertFollowupSavedNeedsPro"\)/.test(activate[0]),
      "the activate 402 is back on alertFollowupProOnly, which ends 'your " +
        "campaign will still be sent - the follow-up was not scheduled'. Here " +
        "the campaign went out days ago and the follow-up is sitting saved; " +
        "that sentence describes neither"
    );

    check(
      /would_send_immediately/.test(activate[0]),
      "activateFollowup no longer handles would_send_immediately — the user " +
        "gets a generic failure for the one case that needs a real answer"
    );
    check(
      /confirm\(t\("confirmFollowupImmediate", \[String\(d\.count\)\]\)\)/.test(activate[0]),
      "the immediate-send warning no longer shows the recipient COUNT — " +
        "'this will send now' without a number is not informed consent"
    );
    check(
      /confirm\([\s\S]{0,120}?\)\) \{[\s\S]{0,200}?activateFollowup\([^)]*true/.test(activate[0]),
      "the retry no longer passes confirm=true only inside the confirm() " +
        "branch — a mass send must never follow a dismissed dialog"
    );
    check(
      !/activateFollowup\([^)]*true[^)]*\);[\s\S]{0,40}\n\s*\}\s*\n\s*return;\s*\n\s*\}\s*\n\s*if \(d\.error === "not_locked"/.test(
        activate[0].replace(/if \(confirm[\s\S]*?\n        \}/, "")
      ),
      "an unconditional confirmed retry appeared outside the confirm() branch"
    );
  }

  // ── every new string exists and is used ──

  const en = JSON.parse(read("_locales/en/messages.json"));
  for (const key of NEW_KEYS) {
    check(
      Object.prototype.hasOwnProperty.call(en, key),
      `${key} is missing from the en locale — the panel would render the ` +
        `raw key name to the user`
    );
    check(
      new RegExp(`["']${key}["']`).test(sidebar),
      `${key} is defined but nothing uses it — a string nobody shows is a ` +
        `string nobody maintains`
    );
  }

  check(
    /\$1/.test(en.confirmFollowupImmediate && en.confirmFollowupImmediate.message),
    "confirmFollowupImmediate lost its $1 placeholder — the warning would " +
      "ask the user to accept an unnamed number of sends"
  );

  // ── every function this flow calls must actually exist ──
  //
  // The first version of activateFollowup called loadCampaignStats(), which is
  // defined nowhere in the extension. sidebar.js runs "use strict" inside an
  // IIFE, so that is a hard ReferenceError on 100% of activations — thrown
  // immediately after the user had authorised a mass send, leaving them
  // looking at "not running yet" beneath an alert saying it had started.
  //
  // All seventeen suites were green. They are regex-over-source and cannot
  // resolve an identifier, so nothing in this repository could have caught it
  // except a check shaped like this one.
  const GLOBALS = new Set([
    "alert", "confirm", "parseInt", "parseFloat", "String", "Number", "Boolean",
    "Array", "Object", "JSON", "Math", "Date", "RegExp", "Error", "isNaN",
    "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "encodeURIComponent", "decodeURIComponent",
    "if", "for", "while", "switch", "catch", "return", "function", "typeof",
    "new", "delete", "void", "in", "of",
  ]);

  // i18n.js defines t(); the panel is more than one file, so the search for a
  // definition has to be too.
  const panelSources = sidebar + "\n" + read("i18n.js");

  // Comments and string literals are stripped first. Without that, the comment
  // above — which names loadCampaignStats to explain the incident — makes this
  // check report the very bug it exists to prevent, out of its own
  // explanation of it.
  const strip = (src) =>
    src
      .replace(/\/\*[\s\S]*?\*\//g, " ")
      .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ")
      .replace(/"(?:[^"\\]|\\.)*"/g, '""')
      .replace(/'(?:[^'\\]|\\.)*'/g, "''");

  for (const fname of ["activateFollowup", "renderLockedFollowup"]) {
    const body = new RegExp("function " + fname + "\\([\\s\\S]{0,4000}?\\n  \\}").exec(sidebar);
    check(
      body !== null,
      fname + " could not be located to check its calls — the window this " +
        "suite reads it through has stopped matching, which silently disables " +
        "every assertion below it"
    );
    if (!body) continue;

    const code = strip(body[0]);
    const called = new Set();
    // Bare `name(` only: a leading dot makes it a method on some object.
    const re = /(^|[^.\w$])([A-Za-z_$][\w$]*)\s*\(/g;
    let m;
    while ((m = re.exec(code)) !== null) {
      const name = m[2];
      if (GLOBALS.has(name)) continue;
      if (new RegExp("function\\s+" + name + "\\s*\\(").test(code)) continue;
      called.add(name);
    }

    check(called.size > 0, fname + " appears to call nothing — the scan broke");

    for (const name of called) {
      const defined =
        new RegExp("function " + name + "\\s*\\(").test(panelSources) ||
        new RegExp("(var|let|const)\\s+" + name + "\\s*=\\s*(async\\s*)?function").test(panelSources) ||
        new RegExp("(var|let|const)\\s+" + name + "\\s*=\\s*\\(").test(panelSources);
      check(
        defined,
        fname + " calls " + name + "(), which is defined nowhere in the " +
          "panel — under \"use strict\" that is a ReferenceError every time " +
          "this path runs, and no source-regex assertion can see it"
      );
    }
  }

  return { name: "locked-followup", failures };
}

module.exports = { run };

if (require.main === module) {
  const r = run();
  r.failures.forEach((f) => console.error("FAIL:", f));
  console.log(r.failures.length ? `${r.name}: ${r.failures.length} failure(s)` : `${r.name}: ok`);
  process.exit(r.failures.length ? 1 : 0);
}
