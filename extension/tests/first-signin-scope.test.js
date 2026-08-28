/**
 * The narrow first-consent ask, and the three ways it could silently go wrong.
 *
 * Removing Mail.Read from the first consent screen is one Railway variable,
 * FIRST_SIGNIN_INCLUDE_MAIL_READ. The variable is necessarily GLOBAL: the
 * server chooses the scope in /auth/login, which runs before anybody is
 * authenticated, so it cannot tell a first sign-in from a returning user
 * reconnecting. Flipped on its own it would narrow every re-auth, record
 * has_mail_read_scope=false for people who HAD the scope, and stop their reply
 * detection without a word.
 *
 * Only the client knows which kind of sign-in this is, so the client decides,
 * and these are the parts of that decision a future edit could quietly undo.
 * None of it is enforced anywhere else: the backend would keep answering
 * exactly as asked.
 */
const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");
const read = (f) => fs.readFileSync(path.join(EXT, f), "utf8");

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  const background = read("background.js");
  const sidebar = read("sidebar.js");

  // ── the decision itself ──

  check(
    /if \(includeMailRead === undefined\)\s*\{\s*\n\s*includeMailRead = await _mailReadForReauth\(\);/
      .test(background),
    "_startMSLoginInner no longer resolves an unspecified includeMailRead " +
      "from the client's own history — every re-auth would take whatever the " +
      "global server flag says, which is the silent downgrade this exists to " +
      "prevent"
  );

  check(
    /_mailReadForReauth[\s\S]{0,900}msEverConnected/.test(background),
    "_mailReadForReauth no longer consults msEverConnected — `user` alone is " +
      "cleared when a JWT goes stale, which is exactly the population " +
      "re-authenticating"
  );

  check(
    /_mailReadForReauth[\s\S]{0,1800}hadMailRead\s*!==\s*false/.test(background),
    "the unknown case no longer resolves to asking for Mail.Read; an " +
      "unobserved scope would be read as 'narrow' and cost an existing user " +
      "reply detection"
  );

  // ── the durable marker the decision rests on ──

  check(
    /msEverConnected:\s*true/.test(background),
    "login success no longer writes msEverConnected — every returning user " +
      "would look like a first-time one after a stale-JWT sweep"
  );

  const logout = /async function msLogout\(\)[\s\S]{0,1200}?\n\}/.exec(background);
  check(logout !== null, "msLogout could not be located to check what it clears");
  check(
    logout === null || !/msEverConnected\s*:/.test(logout[0]),
    "msLogout now clears msEverConnected — signing out would make the next " +
      "sign-in look like a first one and narrow a user who had the scope"
  );

  check(
    /typeof hasMailRead === "boolean"[\s\S]{0,300}hadMailRead: hasMailRead/
      .test(sidebar),
    "the settings poll no longer caches has_mail_read_scope, so background.js " +
      "has nothing to read; note the boolean guard matters too - an errored " +
      "poll must not be stored as 'narrow'"
  );

  // ── the primer must not promise what the first screen will not ask ──
  //
  // Checked structurally rather than by keyword: thirteen languages make a
  // word list a false-negative machine. The English source is the one a
  // future edit is written in.
  const en = JSON.parse(read("_locales/en/messages.json"));
  const primer = (en.popupConsentExplainer || {}).message || "";
  check(primer.length > 0, "popupConsentExplainer is missing from en");
  check(
    !/ask[^.]{0,80}(repl|read your mail)/i.test(primer),
    "the consent primer says Microsoft will ASK for reply detection. That " +
      "sentence goes false the moment FIRST_SIGNIN_INCLUDE_MAIL_READ flips, " +
      "and before the flip it advertises the alarming permission to someone " +
      "who has not seen the screen yet. Describing what the feature does, " +
      "conditioned on it being on, is fine and is the reassurance that " +
      "permission needs"
  );

  // ── onboarding must not cover the sign-in banner ──

  check(
    /showOnboardingIfFirstRun[\s\S]{0,900}chrome\.storage\.local\.get\(\s*\["onboardingDone", "user"\]/
      .test(sidebar),
    "the onboarding wizard is no longer gated on a stored user — on a fresh " +
      "install it reopens a full-screen CSV tutorial over the sign-in banner"
  );

  // Anchored on init()'s whole body, not on the one line the call used to sit
  // beside. A mutation test on 2026-08-28 put the call back two lines lower
  // and the narrower version of this check passed it.
  const init = /function init\(\)[\s\S]{0,2000}?\n  \}/.exec(sidebar);
  check(init !== null, "init() could not be located to check what it calls");
  check(
    init === null || !/showOnboardingIfFirstRun\(\)/.test(init[0]),
    "showOnboardingIfFirstRun is called from init() again, which runs before " +
      "any session exists"
  );

  check(
    /neverSignedIn && !sessionExpired && !requiresReauth\)\s*\{\s*\n\s*showOnboardingIfFirstRun\(\)/
      .test(sidebar),
    "nothing calls showOnboardingIfFirstRun after sign-in any more — gating " +
      "it without a second caller deletes onboarding for new users entirely"
  );

  return { name: "first-signin-scope", failures };
}

module.exports = { run };
