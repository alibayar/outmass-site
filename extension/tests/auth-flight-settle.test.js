/**
 * A sign-in flight that already gave up must stay quiet.
 *
 * launchWebAuthFlow answers whenever the user finally closes the auth window
 * — which may be long after our own 5-minute ceiling has resolved the promise
 * and reported oauth_failed(auth_timeout). That late answer used to run the
 * whole error branch a second time.
 *
 * On 2026-08-30 a user opened a window at 12:01, signed in through a SECOND
 * window at 12:03, worked for half an hour, and closed the first one at
 * 12:33. Chrome's error arrived 1,909 seconds into a flight declared dead at
 * 300, and:
 *
 *   * one attempt produced TWO oauth_failed events, so every abandoned
 *     window is double-counted in the sign-in funnel;
 *   * track() stamps the CURRENT distinct_id, and the user had since signed
 *     in under a different account — the failure landed on an account 43
 *     seconds old that had done nothing wrong.
 *
 * The auth_page_failed branch is worse than a wrong number: it calls launch()
 * again, so a zombie flight could put a fresh Microsoft sign-in window on
 * screen minutes after the user walked away from it.
 *
 * Why a STRUCTURAL test. background.js is a service worker built around
 * chrome.identity, chrome.windows and a live fetch; standing it up to drive a
 * real 5-minute timeout is a far larger fixture than the defect deserves.
 * What actually broke was ORDER — a guard missing ahead of two specific call
 * sites — and order is readable in the source. So this asserts placement, not
 * merely presence: a guard that exists but sits after the retry would still
 * open the window it was added to prevent.
 *
 * The success path is deliberately NOT guarded, and that is checked too. A
 * late redirect still carries a real JWT; storing it is the entire reason the
 * timeout only releases the UI instead of cancelling the flow. A future fix
 * that "tidies up" by guarding all of handleResult would silently throw away
 * sign-ins that took longer than five minutes — the MFA case.
 */

const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");
const NAME = "auth-flight-settle";

function run() {
  const failures = [];
  const check = (cond, label) => {
    if (!cond) failures.push(label);
  };

  const src = fs.readFileSync(path.join(EXT, "background.js"), "utf8");

  // ── locate handleResult and its error branch ──
  const hrAt = src.indexOf("function handleResult(");
  check(hrAt !== -1, "handleResult is gone — this suite is measuring nothing");
  if (hrAt === -1) return { name: NAME, failures };

  // The flight body ends where the next top-level function begins; everything
  // this suite reasons about lives between handleResult and the end of file.
  const body = src.slice(hrAt);

  const errBranchAt = body.indexOf("chrome.runtime.lastError");
  check(errBranchAt !== -1, "handleResult no longer inspects chrome.runtime.lastError");

  // ── the guard exists, inside handleResult ──
  const guardAt = body.indexOf("if (settled)");
  check(
    guardAt !== -1,
    "handleResult has no `if (settled)` guard — a timed-out flight will " +
      "report a second oauth_failed under whatever account is current"
  );
  if (guardAt === -1) return { name: NAME, failures };

  // ── and sits ahead of both things it protects ──
  const retryAt = body.indexOf('errorCode === "auth_page_failed" && !retried');
  check(retryAt !== -1, "the auth_page_failed auto-retry branch has moved or gone");
  check(
    retryAt === -1 || guardAt < retryAt,
    "the settled guard is AFTER the auth_page_failed retry — a zombie flight " +
      "can still relaunch a Microsoft window minutes after the user gave up"
  );

  const chromeErrTrackAt = body.indexOf('reason: "chrome_error"');
  check(chromeErrTrackAt !== -1, "the chrome_error oauth_failed has moved or gone");
  check(
    chromeErrTrackAt === -1 || guardAt < chromeErrTrackAt,
    "the settled guard is AFTER the chrome_error oauth_failed — the " +
      "double-count and the cross-account attribution both survive"
  );

  // ── the guard returns; a bare condition would change nothing ──
  const guardTail = body.slice(guardAt, guardAt + 300);
  check(
    /if \(settled\)[\s\S]{0,200}?\breturn\b/.test(guardTail),
    "the settled guard does not return — execution falls through to the " +
      "reporting it was added to skip"
  );

  // ── the success path stays unguarded ──
  //
  // Anchored on the redirect log line, which is the first statement past the
  // error branch. Anything after it belongs to a real sign-in.
  const successAt = body.indexOf('log("Auth redirect received")');
  check(successAt !== -1, "the success path anchor moved — re-anchor this check");
  if (successAt !== -1) {
    const successPath = body.slice(successAt);
    check(
      !/if \(settled\)[\s\S]{0,200}?\breturn\b/.test(successPath),
      "the success path now returns early on `settled` — a sign-in that took " +
        "longer than the 5-minute ceiling would be discarded, JWT and all"
    );
  }

  // ── and the name the guard reads is the flag, not something else ──
  //
  // This is the check the suite did not have, and its absence let the guard
  // ship dead. Everything above asserts POSITION — the guard appears before
  // the retry, before the report, not on the success path — and position is
  // exactly what a scope bug leaves intact.
  //
  // What actually happened: eighty lines below the guard, inside the same
  // function, sat `var settled = String(errorMsg)`. `var` hoists to the top
  // of its function, so from handleResult's first line onwards `settled` was
  // that local, and `undefined` where the guard read it. Five mutations went
  // red against a guard that could never fire once.
  //
  // A single declaration per flag is a crude rule and a sufficient one:
  // these two names exist to be read across the whole flight, so a second
  // binding anywhere in the file is either a shadow or a rename waiting to
  // become one.
  const FLIGHT_FLAGS = ["settled", "retried"];
  for (const flag of FLIGHT_FLAGS) {
    const declared = (
      src.match(new RegExp("\\b(?:var|let|const)\\s+" + flag + "\\b", "g")) || []
    ).length;
    check(
      declared === 1,
      `\`${flag}\` is declared ${declared} times in background.js. The flight ` +
        "reads it across the whole promise; a second declaration shadows the " +
        "first from the top of whichever function holds it, and every read in " +
        "between silently becomes undefined. Rename the other one."
    );
  }

  // ── the timeout still sets the flag the guard reads ──
  const timeoutAt = src.indexOf('reason: "auth_timeout"');
  check(timeoutAt !== -1, "the auth_timeout report is gone");
  if (timeoutAt !== -1) {
    check(
      /settled = true;[\s\S]{0,200}?reason: "auth_timeout"/.test(src),
      "the timeout reports auth_timeout without setting `settled` — the guard " +
        "has nothing to key off and the double-report returns"
    );
  }

  return { name: NAME, failures };
}

module.exports = { run };

if (require.main === module) {
  const { failures } = run();
  failures.forEach((f) => console.error("FAIL:", f));
  console.log(failures.length ? "auth-flight-settle FAILED" : "auth-flight-settle ok");
  process.exit(failures.length ? 1 : 0);
}
