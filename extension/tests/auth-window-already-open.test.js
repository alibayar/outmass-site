/**
 * A sign-in window that is already open must say so.
 *
 * ravi@quick-hire.com, 2026-09-03. He signed in once at 08:59, then spent
 * three hours unable to get back in, and abandoned a Starter checkout in the
 * middle of it. The events said only "the window closed" — which sent me
 * through a tenant block, a dead refresh token and an expired JWT before the
 * answer turned out to be sitting in a field we already collect:
 *
 *     properties.message = "Only one web auth flow is allowed at a time."
 *
 * Chrome was right. A flight opened at 09:10:25 was still open at 09:12:49,
 * 144 seconds later. `startMSLogin` has a hint for exactly this — "check your
 * other windows or taskbar" — but it fires from OUR bookkeeping and only
 * while the flight is younger than AUTH_FLIGHT_STALE_MS, which is 60 seconds.
 * Past that we assume the window is gone and relaunch. The relaunch lands on
 * Chrome's still-open window and comes back with this string, and the user
 * gets a bare failure.
 *
 * The timer is a guess. The message is ground truth, so classify on it.
 *
 * Then seven of them arrived inside 947 milliseconds, 140ms apart — a key
 * repeating on a focused button, not fingers. The sidebar's sign-in button
 * has disabled itself during the flow since it was written; the popup's never
 * did.
 */
const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");
const BG = fs.readFileSync(path.join(EXT, "background.js"), "utf8");
const POPUP = fs.readFileSync(path.join(EXT, "popup.js"), "utf8");

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  // ── 1. Chrome's message is classified, not swallowed ──

  // Bounded by two stable anchors rather than by counting braces: the lazy
  // `}` this first used stopped at the first `} else if` of the chain, before
  // the branch under test, and the suite failed on correct code.
  const start = BG.indexOf('let errorCode = "auth_failed";');
  const end = BG.indexOf("// Auto-retry ONCE", start);
  check(start > -1 && end > start, "could not find the OAuth error classifier in background.js");

  if (start > -1 && end > start) {
    const block = BG.slice(start, end);
    check(
      /only one web auth flow/i.test(block),
      'the classifier no longer recognises "Only one web auth flow is allowed ' +
        'at a time" — the user gets a bare auth_failed and is never told a ' +
        "window is already open, which is what cost ravi@quick-hire.com three hours"
    );
    check(
      /auth_window_already_open/.test(block),
      "that message is recognised but not mapped to auth_window_already_open, " +
        "so friendlyAuthError() cannot reach the localized hint that already " +
        "exists in all 14 locales"
    );
  }

  // The hint string has to survive too — the classification is worthless if
  // the message it unlocks is gone.
  const en = JSON.parse(
    fs.readFileSync(path.join(EXT, "_locales", "en", "messages.json"), "utf8")
  );
  check(
    !!en.authWindowAlreadyOpen,
    "authWindowAlreadyOpen is gone from en — the classifier now maps to a " +
      "code with no message behind it"
  );
  check(
    /auth_window_already_open/.test(POPUP),
    "popup.js no longer maps auth_window_already_open to a message"
  );

  // ── 2. the popup's button holds one flight ──

  check(
    /_loginInFlight/.test(POPUP),
    "the popup's sign-in button no longer guards against a second launch — a " +
      "held Enter key fires it once per repeat, and every repeat after the " +
      "first lands on Chrome's open window"
  );

  const doLogin = /function doLogin\(\)[\s\S]*?\n  \}/.exec(POPUP);
  check(!!doLogin, "could not find doLogin() in popup.js");
  if (doLogin) {
    const body = doLogin[0];
    check(
      /if \(_loginInFlight\) return;/.test(body),
      "doLogin no longer returns early while a flight is open"
    );
    // The release must happen before ANY branch can return, or one error path
    // leaves the button dead until the popup is reopened — and it would fail
    // on the person already struggling to sign in.
    const guardPos = body.indexOf("_loginInFlight = false");
    const firstReturn = body.indexOf("return;", body.indexOf("function (response)"));
    check(
      guardPos > -1 && (firstReturn === -1 || guardPos < firstReturn),
      "_loginInFlight is released after a branch that can return early, so a " +
        "failed sign-in leaves the button permanently dead"
    );
  }

  // ── 3. the failure event carries our own state ──

  const ctx = /const failureContext = function[\s\S]*?\n  \};/.exec(BG);
  check(!!ctx, "could not find failureContext in background.js");
  if (ctx) {
    for (const field of ["flight_open", "flight_age_seconds", "flight_hinted", "flight_key"]) {
      check(
        ctx[0].includes(field),
        `oauth_failed no longer carries ${field}. Every number needed to ` +
          `explain 2026-09-03 was in memory when the event fired and none of ` +
          `it was recorded; that is why the diagnosis took a morning and three ` +
          `wrong theories.`
      );
    }
  }

  return { name: "auth-window-already-open", failures };
}

module.exports = { run };

if (require.main === module) {
  const r = run();
  r.failures.forEach((f) => console.error("FAIL:", f));
  console.log(r.failures.length ? `${r.name}: ${r.failures.length} failure(s)` : `${r.name}: ok`);
  process.exit(r.failures.length ? 1 : 0);
}
