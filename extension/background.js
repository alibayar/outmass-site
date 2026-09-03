/**
 * OutMass — Background Service Worker
 * Microsoft OAuth 2.0 flow, token management, Graph API, alarms
 */

// ── Azure Config (user must fill in Client ID) ──
// Only the redirect URI survives, and only because two log lines print it —
// it is what has to be registered in Azure, so having it in the console has
// saved an hour more than once.
//
// The client id, the Microsoft authorize/token endpoints and the scope list
// left with graph_api.js on 2026-08-08. They belonged to a SECOND,
// client-side implementation of token refresh and email sending that nothing
// called: its three message types (GET_AUTH_TOKEN, GET_USER_INFO, SEND_EMAIL)
// had zero senders anywhere in the extension or the e2e suite. Worse than
// unused, it contradicted the architecture — sending goes through the backend
// via Graph, never from the client — so it sat there as a working-looking
// trap for whoever debugged the send path next.
const AZURE_REDIRECT_URI = chrome.identity.getRedirectURL("auth");

// ── Import modules ──
importScripts("config.js");
importScripts("analytics.js");

// Override backend URL from storage (set during install or via settings)
chrome.storage.local.get(["backendUrl", "debug"], function (result) {
  if (result.backendUrl) {
    OUTMASS_BACKEND_URL = result.backendUrl;
  }
  if (result.debug) {
    _debugEnabled = true;
  }
});

const LOG_PREFIX = "[OutMass-BG]";
var _debugEnabled = false;

function log(...args) {
  if (!_debugEnabled) return;
  console.log(LOG_PREFIX, ...args);
}

// ── Error Reporting ──
// Browser-internal warnings that are harmless but noisy (a ResizeObserver
// reflow loop, message-port/bfcache teardown, extension-context-invalidated
// after a reload). They flooded error tracking and drowned the real signal,
// so we drop them before the network round-trip. The backend filters the
// same list as a backstop for older clients.
var BENIGN_ERROR_PATTERNS = [
  "resizeobserver loop",
  "could not establish connection. receiving end does not exist",
  "the message channel closed before a response was received",
  "extension context invalidated",
];

function isBenignError(message) {
  var msg = String(message || "").toLowerCase();
  for (var i = 0; i < BENIGN_ERROR_PATTERNS.length; i++) {
    if (msg.indexOf(BENIGN_ERROR_PATTERNS[i]) !== -1) return true;
  }
  return false;
}

function reportError(message, stack, context) {
  if (isBenignError(message)) return; // harmless browser-internal noise
  try {
    fetch(_backendBases()[0] + "/api/error-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: message,
        source: "extension-bg",
        stack: stack || "",
        context: context || {},
      }),
    }).catch(function () {}); // Fire and forget
  } catch (e) {
    // Silent
  }
}

// Global error handler
self.addEventListener("error", function (event) {
  reportError(event.message, event.filename + ":" + event.lineno, {});
});

self.addEventListener("unhandledrejection", function (event) {
  var msg = event.reason ? event.reason.message || String(event.reason) : "Unhandled rejection";
  var stack = event.reason ? event.reason.stack || "" : "";
  reportError(msg, stack, {});
});

// ── Installation ──
chrome.runtime.onInstalled.addListener(function (details) {
  if (details.reason === "install") {
    log("First install — initializing storage");
    chrome.storage.local.set({
      user: null,
      plan: "free",
      emailsSentThisMonth: 0,
      accessToken: null,
      refreshToken: null,
      expiresAt: null,
      // Arms the one-shot auto-open in content_script.js: the first Outlook
      // tab this install sees opens the panel by itself. Set ONLY on a real
      // first install — an update must never reopen the panel on someone who
      // deliberately keeps it closed.
      firstRunAutoOpen: true,
    });
    // First-run welcome tab: without it a fresh install is pure silence —
    // the user must guess to open Outlook Web and find the round button.
    // One prospect reinstalled 9 times without ever finding sign-in
    // (2026-07-08), and a paying customer emailed support to ask where
    // the panel was. The page walks the 3 steps to a first campaign.
    try {
      chrome.tabs.create({ url: "https://getoutmass.com/welcome.html" });
    } catch (e) {
      log("Welcome tab failed:", e);
    }
  }
  log("Extension installed/updated:", details.reason);
  log("Redirect URI:", AZURE_REDIRECT_URI);

  // Set the URL Chrome opens when the user uninstalls the extension.
  // Best-effort: it requires a network connection and an open browser,
  // so it isn't guaranteed. We use it to (a) surface a reminder that
  // paid subscriptions are separate from the extension, and (b) collect
  // feedback on why the user left.
  //
  // Must run inside onInstalled because manifest.json doesn't support
  // a declarative uninstall URL in MV3. Re-setting on updates is cheap
  // and keeps us covered if the URL ever changes.
  //
  // The URL carries the funnel stage the user has reached (see analytics.js);
  // refreshUninstallUrl reads the stored stage rather than assuming a fresh
  // install, so an UPDATE does not demote a long-time sender back to
  // "installed". From here on analytics.js re-registers it on every advance.
  refreshUninstallUrl();

  // Telemetry: install vs update
  if (details.reason === "install") {
    track("ext_installed", { version: chrome.runtime.getManifest().version });
  } else if (details.reason === "update") {
    track("ext_updated", {
      from_version: details.previousVersion || "unknown",
      to_version: chrome.runtime.getManifest().version,
    });
  }
});

// ── Microsoft OAuth 2.0 Flow (Web Auth — backend does code exchange) ──

/**
 * Start the Microsoft OAuth login flow (Web Auth Flow).
 * Opens MS auth page with backend callback URL. Backend does the code
 * exchange with client_secret, then redirects back to extension with
 * OutMass JWT in the URL fragment.
 */
// Single-flight guard for the OAuth flow. Rapid re-clicks on "Sign in" or a
// reconnect banner must NOT spawn multiple launchWebAuthFlow popups — we saw
// real users fire 6+ oauth_started in ~10s, stacking auth windows and logging
// spurious "did not approve" failures from the ones they closed. While a flow
// is in progress, every new request joins the SAME in-flight promise instead
// of launching another window. Keyed by flow type so a OneDrive incremental-
// consent flow and a plain sign-in don't return each other's result. The key
// is cleared when the flow settles (success OR cancel/error), so the next
// deliberate sign-in always starts fresh.
//
// STALENESS (2026-08-03 uninstall incident): a launchWebAuthFlow that never
// settles — auth window lost behind Outlook, wedged on a blank page, left on
// another monitor — used to hold the single-flight key FOREVER, because the
// pending API call also keeps this service worker alive. Every later
// "Sign in" click then joined the dead flight and visibly did NOTHING. A US
// user with a 447-recipient list clicked Sign in six times over three hours
// against one such zombie flight, got not_authenticated on every send, and
// uninstalled with the feedback "GARBAGE. DOES NOT WORK". Two guards now:
//   1. joins are honored only while the flight is younger than
//      AUTH_FLIGHT_STALE_MS — after that, a new click abandons the zombie
//      and opens a FRESH window (the click finally does something visible);
//   2. the flight itself resolves with auth_timeout after
//      AUTH_FLIGHT_TIMEOUT_MS, so sidebar buttons waiting on its callback
//      are never disabled forever. If the user completes the old window
//      even later, handleResult still stores the JWT — the late resolve()
//      is a no-op but the sign-in itself is kept.
var _authFlightByKey = {};
var _authFlightStartedAt = {};
// Normal sign-ins settle in 6-30s, so a flight past a minute is already far
// outside the successful range. The threshold only matters when the user
// RE-CLICKS — and a re-click means they can't see the window, so whatever
// progress that window holds is unreachable to them anyway. (This was 2 min
// at first, sized to MFA duration; that protected a user who, being mid-MFA
// in a visible window, never re-clicks in the first place.)
var AUTH_FLIGHT_STALE_MS = 60 * 1000;
var AUTH_FLIGHT_TIMEOUT_MS = 5 * 60 * 1000;
// Below this age a re-click joins silently — that's the accidental
// double-click the single-flight guard was built for. Above it, the user is
// deliberately clicking again because they can't SEE the window, so telling
// them where to look beats doing nothing.
var AUTH_FLIGHT_SILENT_JOIN_MS = 10 * 1000;
// One hint per flight. If the user re-clicks AFTER being told where to look,
// they looked and couldn't find it — repeating the hint would just be the
// dead-click problem wearing a message; open a fresh window instead.
var _authFlightHinted = {};

// ── Auth window tracking (for focus-on-re-click) ──
//
// launchWebAuthFlow never hands back its window, so we catch it the only way
// available: arm a short watch right before launching, and take the first
// popup-type window that appears. On a re-click while the flight is pending
// we can then FOCUS the real window instead of only describing it — the
// 2026-08-05 Vietnam user re-clicked while their auth window sat parked for
// 28 minutes; a hint tells them where to look, a focus puts it in their face.
//
// Best-effort by design: a service-worker restart loses the id (fine — a
// pending launchWebAuthFlow keeps this worker alive, so flight and id die
// together), and if some other extension opens a popup in the same instant
// we focus the wrong window once. Both failure modes degrade to exactly the
// old behaviour.
var _authWindow = null; // { key, id }
var _authWindowWatchKey = null;
var _authWindowWatchTimer = null;

chrome.windows.onCreated.addListener(function (w) {
  if (_authWindowWatchKey === null || !w || w.type !== "popup") return;
  _authWindow = { key: _authWindowWatchKey, id: w.id };
  _authWindowWatchKey = null;
  clearTimeout(_authWindowWatchTimer);
});

function _armAuthWindowWatch(key) {
  _authWindowWatchKey = key;
  clearTimeout(_authWindowWatchTimer);
  // The auth window appears within milliseconds of launchWebAuthFlow; if
  // nothing came in 3s, stop watching so an unrelated later popup (print
  // dialog, OAuth window of another product) is never mistaken for ours.
  _authWindowWatchTimer = setTimeout(function () {
    _authWindowWatchKey = null;
  }, 3000);
}

function _focusAuthWindow(key) {
  if (!_authWindow || _authWindow.key !== key) return;
  try {
    chrome.windows.update(
      _authWindow.id,
      { focused: true, drawAttention: true },
      function () {
        if (chrome.runtime.lastError) {
          // Window already gone — the flight will settle on its own.
          log("Auth window focus failed:", chrome.runtime.lastError.message);
        }
      }
    );
  } catch (e) {
    log("Auth window focus threw:", e);
  }
}

// How many sign-in attempts this service-worker life has seen, so a report
// can tell one abandoned attempt apart from someone fighting the flow. A
// real user managed five failures in twenty minutes on 2026-06-23.
var _authAttemptCount = 0;

/**
 * Opaque per-attempt id. Travels to the backend on /auth/login and comes
 * back inside the OAuth `state`, so a sign-in that dies on Microsoft's side
 * (where the extension sees nothing but a closed window) can be tied to the
 * `oauth_started` this attempt began with.
 *
 * Random, not derived from the user: the id ends up in a URL and therefore
 * in server access logs, so it must never carry an email or account id.
 */
function _newAuthAttemptId() {
  try {
    var bytes = new Uint8Array(12);
    crypto.getRandomValues(bytes);
    return Array.from(bytes)
      .map(function (b) { return b.toString(16).padStart(2, "0"); })
      .join("");
  } catch (e) {
    return "a" + Math.floor(Math.random() * 1e15).toString(16);
  }
}

function startMSLogin(includeOneDrive, includeMailRead, context) {
  // Three flights, three keys. They must not share one: a user who is
  // granting Mail.Read from the Reports banner while a plain sign-in is
  // somehow open should get their own window, not silently join a flow
  // asking for different scopes.
  var key = includeOneDrive ? "onedrive" : includeMailRead ? "mailread" : "signin";
  var existing = _authFlightByKey[key];
  if (existing) {
    var age = Date.now() - (_authFlightStartedAt[key] || 0);
    if (age < AUTH_FLIGHT_SILENT_JOIN_MS) {
      log("MS OAuth already in progress (" + key + ") — joining existing flow");
      // A double-click within seconds usually means the window opened
      // behind something. Bring it forward; the join stays silent.
      _focusAuthWindow(key);
      return existing;
    }
    if (!_authFlightHinted[key] && age < AUTH_FLIGHT_STALE_MS) {
      // The window is open but the user clearly can't see it, or they
      // wouldn't be clicking Sign in again. Point them at it instead of
      // silently joining — the 2026-08-03 uninstall was six of these dead
      // clicks in a row. The original flight keeps running; if they find
      // and finish the window, storage.onChanged delivers the sign-in.
      log("MS OAuth window already open (" + Math.round(age / 1000) + "s) — telling the user where to look");
      track("oauth_already_open_hint", { flow: key, age_seconds: Math.round(age / 1000) });
      _authFlightHinted[key] = true;
      // The hint says "check your other windows" — do them one better and
      // bring the window forward too. Focus can fail (other desktop, other
      // monitor's minimized group); the hint text still covers that case.
      _focusAuthWindow(key);
      return Promise.resolve({
        error: "A Microsoft sign-in window is already open. Check your other windows or taskbar.",
        errorCode: "auth_window_already_open",
      });
    }
    // Abandon the flight and open a fresh window — either it aged past the
    // stale threshold, or the user already got the hint, looked, and still
    // couldn't find the window. The old window (wherever it is) stays
    // functional; if the user completes it later, its handleResult still
    // stores the tokens.
    log("MS OAuth flight abandoned after " + Math.round(age / 1000) + "s — opening a fresh window");
    track("oauth_stale_relaunch", {
      flow: key,
      stale_seconds: Math.round(age / 1000),
      after_hint: !!_authFlightHinted[key],
    });
    delete _authFlightByKey[key];
    delete _authFlightStartedAt[key];
    delete _authFlightHinted[key];
  }

  // The flight key travels WITH the flight. _startMSLoginInner may widen
  // includeMailRead for a returning user (see _mailReadForReauth), and
  // deriving the window-watch key from the widened value there would arm
  // "mailread" for a flight registered under "signin": _focusAuthWindow
  // would then refuse to raise the window on a second click, and the
  // cleanup below would leave a stale window id behind. Window identity
  // belongs to the flight the CALLER started, not to the scopes it ended
  // up requesting. Found by the 0.3.0 release review.
  // `context` rides along for the same reason `key` does — so the events
  // this flight emits can say which control started it. A re-click that
  // JOINS this flight keeps the first click's context, which is correct:
  // the window belongs to whoever opened it.
  var flight = _startMSLoginInner(includeOneDrive, includeMailRead, key, context);
  _authFlightByKey[key] = flight;
  _authFlightStartedAt[key] = Date.now();
  // Only the flight that OWNS the key may clear it — a zombie settling late
  // must not evict the fresh flight that replaced it.
  var clear = function () {
    if (_authFlightByKey[key] === flight) {
      delete _authFlightByKey[key];
      delete _authFlightStartedAt[key];
      delete _authFlightHinted[key];
      if (_authWindow && _authWindow.key === key) _authWindow = null;
    }
  };
  flight.then(clear, clear);
  return flight;
}

/**
 * Should THIS sign-in ask for Mail.Read, when the caller did not say?
 *
 * The server cannot answer it. /auth/login runs before anyone is
 * authenticated, so FIRST_SIGNIN_INCLUDE_MAIL_READ is necessarily global: flip
 * it off and every re-authentication gets the narrow ask too — the reconnect
 * banner, an expired session, a dead Microsoft connection coming back. The
 * callback then records has_mail_read_scope=false for somebody who HAD it and
 * their refresh narrows to match, so reply detection stops without a word.
 *
 * The client is the only side that knows. Three states:
 *
 *   never connected here   -> narrow. A first-time user should not be asked to
 *                             read their mail before sending anything.
 *   connected, had it      -> ask. Preserving what they already granted is not
 *                             a new permission prompt; Microsoft skips consent
 *                             for scopes already authorised.
 *   connected, narrow user -> narrow. Someone who signed in after the flip
 *                             never granted it, and re-asking would put "Read
 *                             your mail" back in front of exactly the person
 *                             the change exists for.
 *
 * `hadMailRead` is written by the sidebar's /settings poll. Absent means "not
 * observed yet", and for an install that has connected before, the safe
 * reading of unknown is TODAY'S behaviour — ask — because over-asking an
 * existing user changes nothing, while under-asking silently costs them a
 * feature. Any failure resolves the same way.
 */
function _mailReadForReauth() {
  return new Promise(function (resolve) {
    try {
      chrome.storage.local.get(
        ["msEverConnected", "user", "hadMailRead", "sessionExpired"],
        function (r) {
          // Four ways to know this install has connected before, because no
          // one of them survives every path. `user` is cleared when a JWT
          // goes stale — the exact population re-authenticating here.
          // `msEverConnected` is new in 0.3.0, so an install that UPDATES to
          // it and then re-auths has never written one. `hadMailRead === true`
          // could only have been observed by a signed-in session, and
          // `sessionExpired` is set by the very expiry that dropped `user`.
          // Missing all four is what a genuinely new install looks like.
          var everConnected = !!(
            r &&
            (r.msEverConnected ||
              r.user ||
              r.hadMailRead === true ||
              r.sessionExpired)
          );
          var hadMailRead = r ? r.hadMailRead : undefined;
          resolve(everConnected && hadMailRead !== false);
        }
      );
    } catch (e) {
      resolve(true);
    }
  });
}

async function _startMSLoginInner(includeOneDrive, includeMailRead, flightKey, context) {
  // Undefined means "caller has no opinion" — a plain sign-in or the OneDrive
  // flow. An explicit true is the Reports banner asking for Mail.Read on
  // purpose, and must not be second-guessed.
  if (includeMailRead === undefined) {
    includeMailRead = await _mailReadForReauth();
  }
  log("Starting MS OAuth flow (Web)...",
    includeOneDrive ? "with OneDrive scope" : includeMailRead ? "with Mail.Read scope" : "");

  const attemptId = _newAuthAttemptId();
  const startedAt = Date.now();
  _authAttemptCount += 1;
  const attemptNo = _authAttemptCount;

  // Seconds the auth window stayed open. Successful sign-ins take 6-30s;
  // the failures cluster far higher and run to 18 minutes, which is the
  // signature of someone stuck (wrong account, admin-approval wall), not
  // of someone reading the permission list and declining.
  const elapsed = function () {
    return Math.round((Date.now() - startedAt) / 1000);
  };
  // Which control started this flight. Until 2026-08-30 only
  // signin_clicked carried it, and the OAuth events did not — so a funnel
  // built on oauth_started/oauth_failed could not tell three very
  // different populations apart:
  //
  //   1. a tenant or admin genuinely blocking consent — the leak we are
  //      trying to measure;
  //   2. someone closing the sign-in window — abandonment;
  //   3. someone opening the "change sender" switcher out of curiosity and
  //      backing out — not a sign-in attempt at all.
  //
  // All three land as oauth_failed, and Chrome labels 2 and 3 identically
  // (`consent_declined` means "window closed without a redirect", not "the
  // user pressed No" — see handleResult). On 2026-08-30 a single user
  // produced one of each in forty minutes, and both of their "failures"
  // were 2 and 3. Counting those against sign-in intent overstates the
  // leak with people who were never blocked.
  //
  // "unspecified" rather than omitting the field: an ABSENT context means
  // a client older than this change, a present-but-unspecified one means a
  // call site we forgot to label. Those are different bugs.
  const flowContext = context || "unspecified";

  const failureContext = function (extra) {
    // What OUR bookkeeping believed at the moment it failed.
    //
    // On 2026-09-03 a user could not sign in for three hours, and working out
    // why took most of a morning and three wrong theories — a tenant block, a
    // dead refresh token, an expired JWT — because the events said only that
    // a window had closed. The answer was that a flight opened 144 seconds
    // earlier was still open, and AUTH_FLIGHT_STALE_MS (60s) had already
    // written it off, so we relaunched into it.
    //
    // Every one of those numbers was in memory when the event fired. None of
    // it was recorded. These four fields turn that morning into one query,
    // and they describe our own state, not anything the person did.
    var flightAge = _authFlightStartedAt[flightKey]
      ? Date.now() - _authFlightStartedAt[flightKey]
      : null;
    return Object.assign(
      {
        attempt_id: attemptId,
        attempt_no: attemptNo,
        seconds: elapsed(),
        context: flowContext,
        flight_key: flightKey,
        // Whether we thought a window was open, and for how long. A failure
        // with a live flight older than the stale threshold is the shape that
        // cost us this morning.
        flight_open: !!_authFlightByKey[flightKey],
        flight_age_seconds: flightAge === null ? null : Math.round(flightAge / 1000),
        flight_hinted: !!_authFlightHinted[flightKey],
      },
      extra
    );
  };

  track("oauth_started", {
    with_onedrive: !!includeOneDrive,
    with_mail_read: !!includeMailRead,
    attempt_id: attemptId,
    attempt_no: attemptNo,
    context: flowContext,
  });

  // Extension tells backend where to redirect at the end (passed via state)
  const extRedirectUri = chrome.identity.getRedirectURL("auth");

  // Pass our own extension ID so the backend routes the final
  // chromiumapp.org redirect back to us (not to whatever AZURE_EXTENSION_ID
  // happens to be set to on Railway). The backend allowlists accepted
  // IDs — unknown IDs fall back to the env default.
  // `include_onedrive=true` triggers incremental consent: Microsoft
  // shows the consent screen only for the OneDrive scopes (the Mail
  // scopes are already approved from the original sign-in), and the
  // resulting token covers everything.
  const extId = chrome.runtime.id;
  // Sticky base: if the primary host is blocked on this network, the OAuth
  // flow must start from the base that actually answers.
  let authUrl =
    _backendBases()[0] +
    "/auth/login?ext=" +
    encodeURIComponent(extId) +
    "&aid=" +
    encodeURIComponent(attemptId);
  if (includeOneDrive) {
    authUrl += "&include_onedrive=true";
  }
  // Same incremental-consent mechanism, for the scope that reply detection
  // needs. Microsoft shows a screen for Mail.Read alone — the send scopes
  // are already granted — which is the entire reason it can be asked for
  // later instead of at first sign-in, where "Read your mail" is the most
  // alarming line on the screen for someone who has not sent anything yet.
  if (includeMailRead) {
    authUrl += "&include_mail_read=true";
  }
  // Which build is asking. /auth/login runs before anyone is authenticated
  // and opens in a browser window, so the X-Extension-Version header that
  // backendFetch sends everywhere else cannot reach it — it rides on the URL
  // instead, like ext and aid.
  //
  // The server uses it to tell a client that can decide for itself whether
  // to request Mail.Read from one that cannot. Without it, "a new build
  // asking for the narrow first-time consent" and "an old build that has
  // never heard of the question" look identical: both simply omit
  // include_mail_read. Handing the narrow consent to the second kind would
  // strip reply detection from a returning user and leave their next
  // refresh asking for a scope they no longer hold.
  authUrl += "&v=" + encodeURIComponent(chrome.runtime.getManifest().version);

  return new Promise((resolve) => {
    // One-shot auto-retry guard. The auth window's first navigation is our own
    // backend (/auth/login on Railway), so a cold / restarting / just-deployed
    // backend can make Chrome report "Authorization page could not be loaded."
    // We warm the backend and relaunch ONCE before giving up.
    let retried = false;

    // Hard ceiling on the whole flight. A window that never settles used to
    // leave every sidebar button that awaits this promise disabled forever
    // (the reauth banner showed "…" until the iframe was reloaded). Resolving
    // with a timeout gives the UI closure; if the user completes the zombie
    // window afterwards, handleResult below still stores the tokens — the
    // second resolve() is simply a no-op.
    let settled = false;
    const finish = (value) => {
      settled = true;
      clearTimeout(timeoutHandle);
      resolve(value);
    };
    const timeoutHandle = setTimeout(() => {
      if (settled) return;
      settled = true;
      track("oauth_failed", failureContext({ reason: "auth_timeout" }));
      // The old text here said "timed out, please try again", which was
      // simply untrue: this timeout releases the UI, it does NOT cancel the
      // flow. The Microsoft window is still open and still works — finishing
      // in it lands the tokens through handleResult below. Telling the user
      // to "try again" pushed them away from a session that was fine.
      // The localized key says both options; the English string stays as the
      // fallback for a t() that somehow returns nothing.
      resolve({
        error: "The Microsoft sign-in window is still open. Finish signing in there, or close it and start again.",
        errorCode: "auth_timeout",
      });
    }, AUTH_FLIGHT_TIMEOUT_MS);

    function launch() {
      // Catch the popup this call is about to create, so a later re-click
      // can focus it (see _armAuthWindowWatch). Armed per launch: the
      // auto-retry path re-launches and gets a NEW window.
      _armAuthWindowWatch(
        flightKey ||
          (includeOneDrive ? "onedrive" : includeMailRead ? "mailread" : "signin")
      );
      chrome.identity.launchWebAuthFlow(
        { url: authUrl, interactive: true },
        handleResult
      );
    }

    function handleResult(redirectUrl) {
      if (chrome.runtime.lastError) {
        const m = String(chrome.runtime.lastError.message || "");
        log("Auth flow error:", m);

        // A flight that already timed out has nothing left to report.
        //
        // The 5-minute ceiling above resolves the promise and fires
        // oauth_failed(auth_timeout). Chrome, meanwhile, answers only when
        // the user finally closes the abandoned window — which can be much
        // later. On 2026-08-30 a user opened a window at 12:01, signed in
        // through a SECOND window at 12:03, worked for half an hour, and
        // closed the first one at 12:33: chrome.runtime.lastError arrived
        // 1,909 seconds into a flight that had been declared dead at 300.
        // Two things went wrong when that answer landed:
        //
        //   * it fired a SECOND oauth_failed for one attempt, so every
        //     abandoned window is counted twice in the funnel — and the
        //     consent-leak measurement reads those counts;
        //   * track() stamps the CURRENT distinct_id, and by then the user
        //     had signed in under a different account. The failure was
        //     recorded against an account 43 seconds old that had done
        //     nothing wrong.
        //
        // The auth_page_failed branch below is worse than a bad number: it
        // calls launch() again, so a zombie flight could open a fresh
        // Microsoft sign-in window minutes after the user gave up on it.
        //
        // The SUCCESS path deliberately does not get this guard. A late
        // redirect still carries a real JWT, and storing it is the entire
        // reason the timeout only releases the UI instead of cancelling the
        // flow — see the comment on `settled` above.
        if (settled) {
          log("Auth error arrived after the flight settled — ignoring:", m);
          return;
        }

        // Classify the Chrome WebAuthFlow error so the UI can show a helpful,
        // localized message instead of a raw string. The big one is
        // consent-declined: work/school (M365) tenants block end-user consent
        // for unverified multitenant apps, so the flow returns "did not
        // approve" — users need to know their org may require admin approval.
        let errorCode = "auth_failed";
        if (/did not approve|access was denied|consent_required/i.test(m)) {
          errorCode = "consent_declined";
        } else if (/could not be loaded|failed to load|page could not/i.test(m)) {
          errorCode = "auth_page_failed";
        } else if (/only one web auth flow/i.test(m)) {
          // Chrome is telling us a window is open. Believe it.
          //
          // startMSLogin already has a hint for this — "check your other
          // windows or taskbar" — but it fires from OUR bookkeeping, and only
          // while the flight is younger than AUTH_FLIGHT_STALE_MS. Past that
          // we assume the window is gone and relaunch, which is a guess from a
          // timer. Chrome's window outlives our 60 seconds, so the relaunch
          // lands on top of it and returns this string, and the user gets a
          // bare failure with no idea where to look.
          //
          // ravi@quick-hire.com, 2026-09-03: a flight opened at 09:10:25 was
          // still open at 09:12:49, 144 seconds later. He clicked seven times
          // in one second and got seven of these. He never sent a campaign and
          // abandoned a Starter checkout in the middle of it.
          //
          // The timer is a guess; this message is ground truth.
          errorCode = "auth_window_already_open";
          // flightKey, not `key` — that name belongs to startMSLogin, one
          // function out, and reading it here would throw under "use strict"
          // while every suite stayed green, which is exactly how 0.3.1
          // shipped a panel that did not run.
          _focusAuthWindow(flightKey);
        }

        // Auto-retry ONCE when the authorization PAGE failed to load — almost
        // always a transient backend blip (cold start / restart / fresh deploy).
        // Wake the backend, then relaunch. Never retry consent declines: that's
        // a user/tenant decision, and reopening the window would only annoy.
        if (errorCode === "auth_page_failed" && !retried) {
          retried = true;
          log("Auth page failed to load — warming backend, retrying once");
          track("oauth_retry", failureContext({ after: "auth_page_failed" }));
          warmBackend(20000).then(launch);
          return;
        }

        finish({ error: m, errorCode: errorCode });
        // NOTE on reading this event: `consent_declined` is Chrome's label for
        // "auth window closed without a successful redirect" — it does NOT
        // mean the user pressed No. A tenant block (AADSTS90094) leaves the
        // user on our error page until they close the window, and lands here
        // wearing the same label. The backend's ms_auth_failed event carries
        // the real reason; join on attempt_id.
        track(
          "oauth_failed",
          failureContext({
            reason: "chrome_error",
            message: m.slice(0, 256),
            code: errorCode,
          })
        );
        return;
      }

      if (!redirectUrl) {
        finish({ error: "No redirect URL received" });
        track("oauth_failed", failureContext({ reason: "no_redirect" }));
        return;
      }

      log("Auth redirect received");

      // Parse URL fragment (#jwt=...&email=...&name=...&plan=...)
      let fragment = "";
      try {
        const u = new URL(redirectUrl);
        fragment = u.hash.startsWith("#") ? u.hash.substring(1) : u.hash;
      } catch (e) {
        finish({ error: "Invalid redirect URL" });
        track("oauth_failed", failureContext({ reason: "invalid_redirect" }));
        return;
      }

      const params = new URLSearchParams(fragment);
      const jwtToken = params.get("jwt");
      const email = params.get("email");
      const name = params.get("name");
      const plan = params.get("plan") || "free";
      const errorMsg = params.get("error");

      if (errorMsg) {
        // The backend now settles its error pages through this path (it used
        // to leave the window open), so this branch carries real Microsoft
        // failure classes like "AADSTS90094: admin consent required" instead
        // of only our own server errors.
        //
        // Recover an errorCode from the class string. Without it the sidebar
        // and popup fall through to showing the raw English sentence, and the
        // localized guidance we already ship in 14 locales — "your org may
        // need an admin to approve OutMass" — never appears, even though it
        // is exactly what that user needs. Consent walls are the single
        // biggest sign-in leak we have measured.
        // Named for what it holds, not for a state. It used to be called
        // `settled`, which is also the name of the flight-completion flag in
        // the enclosing scope — and `var` hoists, so from the top of
        // handleResult onwards this local shadowed it. The settle guard
        // added earlier the same day therefore read `undefined` and never
        // fired once. Its test could not see that: the test asserts the
        // guard's POSITION in the source, and position is exactly what a
        // scope bug leaves intact.
        var backendError = String(errorMsg);
        // The backend's own name for this failure class, added 2026-08-10.
        // It saw Microsoft's actual response; everything below is inference
        // from the sentence it produced. Absent when the backend predates
        // the change, which is why the sniffing stays.
        var msCode = params.get("mcode") || "";
        // errorCode is set ONLY for classes that have localized guidance —
        // friendlyAuthError falls through to the raw string for anything
        // else, so an unmapped code would just look handled without being.
        // Consent (65001/65004/90094) is the one with real text, and it is
        // also the single biggest sign-in leak we have measured.
        var isConsent = /AADSTS(65001|65004|90094)\b/.test(backendError) ||
          /consent/i.test(backendError);
        // The AADSTS number is the stable grouping key regardless.
        var aadsts = (backendError.match(/AADSTS\d+/) || [null])[0];

        // Auto-retry ONCE when Microsoft was still provisioning us.
        //
        // AADSTS650051 means the service principal already exists in the
        // user's tenant while Entra has not finished setting it up. It clears
        // on retry — both users who hit it on 2026-08-27 retried by hand and
        // were in within eight and thirty seconds. They happened to try
        // again; a first-time visitor has no reason to.
        //
        // Keyed on the backend's own class name, not on sniffing the
        // sentence, and deliberately only this class. Microsoft's 5xx
        // classes say "wait a minute" in their own message, and retrying
        // instantly would contradict the advice we just gave. Consent
        // declines are untouchable for the older reason: reopening the
        // window on someone who said no is harassment, not recovery.
        if (msCode === "tenant_provisioning_race" && !retried) {
          retried = true;
          log("Microsoft was still provisioning the app — retrying once");
          track("oauth_retry", failureContext({ after: msCode }));
          setTimeout(launch, 1500);
          return;
        }

        var result = { error: backendError };
        if (msCode) result.msCode = msCode;
        if (isConsent) result.errorCode = "consent_declined";
        finish(result);
        track(
          "oauth_failed",
          failureContext({
            reason: "backend_error",
            code: backendError.slice(0, 64),
            aadsts: aadsts,
            // Correlates the client's view with ms_auth_failed's `meaning`,
            // so a funnel breakdown no longer has to parse an English
            // sentence to know what happened.
            mcode: msCode,
          })
        );
        return;
      }

      if (!jwtToken || !email) {
        finish({ error: "Incomplete auth response from backend" });
        track("oauth_failed", failureContext({ reason: "incomplete_response" }));
        return;
      }

      const user = { email: email, name: name || email };

      // Save auth state. The plan's quota siblings are cleared ONLY when the
      // signed-in account actually changed: this same write also runs for
      // the two incremental-consent flows (the OneDrive picker, the
      // Mail.Read banner) on the SAME account, and wiping the cached limit
      // and count there made the quota bar paint a fabricated fresh
      // allowance the server never agreed to — the exact defect class the
      // account-switch clearing was added to prevent, from the other side.
      // Found by the 0.2.2 release review.
      chrome.storage.local.get(["user"], function (prev) {
        const sameAccount =
          prev && prev.user && prev.user.email &&
          String(prev.user.email).toLowerCase() === String(email).toLowerCase();
        const authState = {
          backendJwt: jwtToken,
          user: user,
          plan: plan,
          // Durable on purpose: never cleared by msLogout or by the stale-JWT
          // sweep, both of which drop `user`. It answers "has this install
          // ever completed a Microsoft consent", which is what decides
          // whether a later sign-in is a FIRST one — see _mailReadForReauth.
          msEverConnected: true,
          // Fresh JWT → clear any pending session-expired flag so the
          // sidebar banner hides on next poll.
          sessionExpired: false,
          // accessToken is managed server-side now; extension no longer needs it
          accessToken: null,
          refreshToken: null,
          expiresAt: null,
        };
        if (!sameAccount) {
          // Cleared with the plan on a real account switch, never left
          // behind: a plan sitting beside the previous account's limit and
          // count is both a wrong quota bar and a cross-account leak.
          // msLogout already clears all three together; this matches it.
          authState.monthlyLimit = null;
          authState.emailsSentThisMonth = 0;
          // Same reasoning, one release later: hadMailRead is stored per
          // install but answers a per-ACCOUNT question, and carrying the
          // previous account's answer into the new one decides the next
          // consent screen for somebody it was never observed on. Absent
          // means "ask", which is the safe direction.
          authState.hadMailRead = null;
        }
        chrome.storage.local.set(authState, function () {
          log("LOGIN_SUCCESS:", email);
          // Backend doesn't return user_id in the redirect fragment today, so
          // we identify by email — PostHog accepts any string as distinct_id.
          //
          // Chained, not fire-and-forget: launched side by side these two
          // raced inside the analytics queue and the loser's event vanished
          // (see _phEnqueue in analytics.js — the enqueue is serialized now,
          // but $identify arriving before oauth_completed is also what lets
          // PostHog attach the event to the aliased person). The UI never
          // waits on telemetry: finish() runs immediately.
          identify(email).then(function () {
            return track("oauth_completed", { plan: plan });
          });
          finish({ error: null, user: user });
        });
      });
    }

    launch();
  });
}

/**
 * Best-effort warm-up of the OutMass backend before retrying the OAuth flow.
 *
 * The Railway web service can be momentarily unavailable — a cold start, a
 * crash-restart, or a fresh deploy with no readiness gate — during which the
 * auth window's first navigation (/auth/login) fails with "Authorization page
 * could not be loaded." Hitting the lightweight "/" health route wakes the
 * instance and blocks until it answers (or we time out), so the retried
 * launchWebAuthFlow lands on a backend that's actually ready. Never throws.
 */
async function warmBackend(timeoutMs) {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(function () { ctrl.abort(); }, timeoutMs || 15000);
    await fetch(_backendBases()[0] + "/", { method: "GET", cache: "no-store", signal: ctrl.signal });
    clearTimeout(timer);
    log("warmBackend: backend responded, retrying auth");
  } catch (e) {
    // Network error or timeout — relaunch anyway; the retry is still worthwhile.
    log("warmBackend: warm-up failed, retrying anyway:", e && e.message);
  }
}

/**
 * Make an authenticated request to the OutMass backend.
 */
// Track last successful backend contact for health check optimization
var _lastBackendOk = 0;
var HEALTH_CHECK_FRESHNESS_MS = 30000; // 30 seconds

// Which backend base answered last. Primary is api.getoutmass.com; some
// networks block one host or the other (railway.app is filtered outright in
// places), so whichever base works becomes sticky for this service-worker
// lifetime — users behind a blocked host pay the 20s timeout once, not on
// every request. MV3 restarts the worker often, so stickiness self-heals.
var _activeBackendBase = null;

function _backendBases() {
  var all = [OUTMASS_BACKEND_URL, OUTMASS_BACKEND_FALLBACK_URL].filter(
    function (b, i, arr) { return b && arr.indexOf(b) === i; }
  );
  if (_activeBackendBase && all.indexOf(_activeBackendBase) > -1) {
    return [_activeBackendBase].concat(all.filter(function (b) {
      return b !== _activeBackendBase;
    }));
  }
  return all;
}

/**
 * The language the panel is rendering in, as a BCP-47 tag.
 *
 * Mirrors getActiveLocale() in i18n.js on purpose: that file is loaded by the
 * sidebar and popup, never by this service worker, and importing it here to
 * share one function would pull in the whole translation dictionary and its
 * async init for the sake of two lines. tests/ui-language-header.test.js
 * asserts the two agree on every input, because two implementations of one
 * rule is exactly the shape that drifts.
 *
 * navigator.language is not consulted: chrome.i18n.getUILanguage() is always
 * available in a service worker, so the branch would be unreachable.
 */
function _uiLanguageTag(override) {
  var lang = override && override !== "auto" ? override : null;
  if (!lang && typeof chrome !== "undefined" && chrome.i18n && chrome.i18n.getUILanguage) {
    try { lang = chrome.i18n.getUILanguage(); } catch (e) {}
  }
  return (lang || "en").replace("_", "-");
}

async function backendFetch(endpoint, options) {
  // uiLanguage rides along on a read we already do — no extra storage hit.
  let storage = await chrome.storage.local.get(["backendJwt", "uiLanguage"]);

  if (!storage.backendJwt) {
    // auth_required routes this to the sidebar's sign-in banner + a
    // localized "sign in first" alert. The raw English fallback string
    // cost us a zh-CN user who couldn't read it for two days (2026-07-14).
    return { error: "Not authenticated. Please login.", auth_required: true };
  }

  const headers = {
    "Content-Type": "application/json",
    Authorization: "Bearer " + storage.backendJwt,
    "X-Extension-Version": chrome.runtime.getManifest().version,
    // What language to write to this person in. The backend stores it on the
    // user row when it changes and every outgoing email reads it; a build
    // that never sends it leaves the column NULL, which means English.
    "X-UI-Language": _uiLanguageTag(storage.uiLanguage),
    ...(options?.headers || {}),
  };

  // Try each base in order; fall through to the next ONLY on fetch-level
  // (network:true) failures — an HTTP error is a real server answer and
  // must be surfaced, not retried against the other host.
  const bases = _backendBases();
  let result;
  for (const base of bases) {
    result = await _backendFetchOnce(base, endpoint, headers, options);
    if (!result.network) {
      _activeBackendBase = base;
      return result;
    }
  }
  return result; // every base unreachable → last network-failure shape
}

async function _backendFetchOnce(base, endpoint, headers, options) {
  // A request that can't reach the server otherwise hangs at the browser's
  // mercy (a zh-CN user watched Send spin ~8s per click against a network
  // that blocked our host, 2026-07-14). Cap it so callers fail fast and can
  // tell the user it's a CONNECTION problem.
  const controller = new AbortController();
  const timeoutTimer = setTimeout(() => controller.abort(), 20000);

  try {
    const resp = await fetch(base + endpoint, {
      method: options?.method || "GET",
      headers: headers,
      // Never serve authenticated API responses from the HTTP cache: the URL
      // is identical across users and Authorization isn't a cache key, so a
      // cached GET (e.g. /announcements, /settings) could leak the previous
      // account's data after switching accounts in the same browser.
      cache: "no-store",
      body: options?.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });

    // Sliding session: past half its 24h life, a valid JWT comes back
    // refreshed in this header (any response the auth dependency ran for,
    // including 4xx like quota/merge-tag errors). Storing it means active
    // users never hit the daily "sign in again" wall (a GB user lost a
    // send to exactly that on 2026-07-17). Absent on old backends.
    // Guard: only overwrite if the token this request was sent with is
    // STILL the stored one — a slow response landing after a logout (or
    // a re-login) must not resurrect/clobber auth state.
    const refreshedJwt = resp.headers.get("X-Refresh-JWT");
    if (refreshedJwt) {
      const current = await chrome.storage.local.get(["backendJwt"]);
      if (
        current.backendJwt &&
        "Bearer " + current.backendJwt === headers.Authorization
      ) {
        await chrome.storage.local.set({ backendJwt: refreshedJwt });
      }
    }

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      // FastAPI puts our structured errors under errData.detail. For 402 we
      // want to preserve the actual `error` code (e.g. "feature_locked" vs
      // "limit_exceeded") so the frontend can show the right upgrade prompt
      // — not hardcode to "limit_exceeded".
      const detail = errData && errData.detail ? errData.detail : errData;
      if (resp.status === 402) {
        const code = (detail && typeof detail === "object" && detail.error) || "limit_exceeded";
        return { error: code, status: 402, detail: detail };
      }
      // Any endpoint can return {detail: {error: "<code>", message: "..."}}
      // and we'll surface the code to callers so they can show a
      // localized message. This replaces the old 402-only and 409-only
      // special cases with a general pattern.
      if (detail && typeof detail === "object" && detail.error) {
        return { error: detail.error, status: resp.status, detail: detail };
      }
      // 401 means our JWT is expired or invalid. Clear it and raise the
      // session-expired flag so the sidebar can show its reconnect banner
      // instead of a raw "Invalid or expired token" alert. The flag is
      // cleared by msLogin() on a successful re-auth.
      //
      // EXCEPT for `silent` (background/refresh) calls: a routine plan-refresh
      // on popup-open must never wipe auth on a single transient/edge 401 —
      // that dropped the popup to a hard login screen and re-prompted sign-in
      // in a loop. Silent callers just get the error; genuine expiry is still
      // caught by user-initiated calls and the sidebar's reconnect poll.
      if (resp.status === 401) {
        if (!options || !options.silent) {
          await chrome.storage.local.set({
            backendJwt: null,
            sessionExpired: true,
          });
        }
        return { error: "session_expired", status: 401 };
      }
      return { error: (detail && typeof detail === "string" ? detail : null) || `HTTP ${resp.status}` };
    }

    _lastBackendOk = Date.now();
    return { data: await resp.json(), error: null };
  } catch (err) {
    // fetch() rejecting means NO HTTP response ever arrived — offline, DNS
    // failure, a firewall/VPN/national filter blocking our host, or the 20s
    // timeout above. Flag it so the UI can say "connection problem, not your
    // account/plan" — a real user misread this exact failure as a paywall,
    // clicked Upgrade, then deleted their account.
    const timedOut = err && err.name === "AbortError";
    return {
      error: timedOut ? "network_timeout" : "network_unreachable",
      network: true,
      detail: String((err && err.message) || err),
    };
  } finally {
    clearTimeout(timeoutTimer);
  }
}

/**
 * Logout: clear all auth state.
 */
async function msLogout() {
  await chrome.storage.local.set({
    accessToken: null,
    refreshToken: null,
    expiresAt: null,
    user: null,
    backendJwt: null,
    // A deliberate sign-out must not leave the prior 401's session-expired
    // flag set, otherwise the reauth poll shows a wrong "session expired —
    // reconnect" banner. Clear it plus cached plan state so the next account
    // starts clean.
    sessionExpired: false,
    // Per-account, like the plan beside it. msEverConnected is NOT
    // cleared here on purpose — it records that this install has
    // completed a consent at some point, which signing out does not undo.
    hadMailRead: null,
    plan: "free",
    monthlyLimit: null,
    emailsSentThisMonth: 0,
  });
  log("User logged out, storage cleared");
}

// ── Outlook host resolution ──
// Which Outlook Web host to open for "Open Campaign Panel" when the user has no
// Outlook tab open. Hardcoding outlook.live.com (the PERSONAL host) bounced
// work/school (M365) accounts — whose mailbox lives on outlook.office.com — to
// a Microsoft sign-in page that they read as an endless OutMass login loop.
var VALID_OUTLOOK_ORIGINS = [
  "https://outlook.live.com",
  "https://outlook.office.com",
  "https://outlook.office365.com",
  // Microsoft is migrating work/school Outlook Web here tenant-by-tenant
  // (rollout started Nov 2025); office.com redirects to it for moved tenants.
  "https://outlook.cloud.microsoft",
];

var PERSONAL_OUTLOOK_DOMAINS = [
  "outlook.com", "hotmail.com", "live.com", "msn.com", "passport.com",
  "hotmail.co.uk", "live.co.uk", "outlook.co.uk",
];

function isPersonalOutlookEmail(email) {
  var domain = String(email || "").toLowerCase().split("@")[1] || "";
  return PERSONAL_OUTLOOK_DOMAINS.indexOf(domain) !== -1;
}

async function resolveOutlookMailUrl() {
  var s = await chrome.storage.local.get(["lastOutlookOrigin", "user"]);
  // 1) Reopen the exact host the user actually uses (content_script records it
  //    on every Outlook page load) — the most reliable signal.
  if (s.lastOutlookOrigin && VALID_OUTLOOK_ORIGINS.indexOf(s.lastOutlookOrigin) !== -1) {
    return s.lastOutlookOrigin + "/mail/";
  }
  // 2) No prior host yet: infer from the signed-in account. Personal Microsoft
  //    accounts use outlook.live.com; work/school (custom domain) use
  //    outlook.office.com. Default to office.com when unknown — work accounts
  //    are exactly the ones the old hardcode broke.
  var email = s.user && s.user.email;
  return isPersonalOutlookEmail(email)
    ? "https://outlook.live.com/mail/"
    : "https://outlook.office.com/mail/";
}

// ── Message Handler ──
chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  log("Message received:", message.type);

  switch (message.type) {
    case "MS_LOGIN":
      startMSLogin(false, undefined, message.context).then(function (result) {
        sendResponse(result);
      });
      return true; // async

    case "MS_LOGOUT":
      msLogout().then(function () {
        sendResponse({ success: true });
      });
      return true;

    case "GET_USER_STATE":
      chrome.storage.local.get(
        ["user", "plan", "emailsSentThisMonth", "backendJwt"],
        function (result) {
          var hasValidAuth = !!(result.user && result.backendJwt);

          if (!hasValidAuth) {
            sendResponse({
              user: null,
              plan: "free",
              emailsSentThisMonth: 0,
            });
            if (result.user && !result.backendJwt) {
              log("Stale user data found without JWT, clearing...");
              chrome.storage.local.remove(["user"]);
            }
            return;
          }

          // Refresh plan from backend (catches Stripe upgrades).
          // `silent`: a 401 on this background refresh must NOT clear the JWT
          // or it would log the user out on a mere popup-open (see backendFetch).
          if (result.backendJwt) {
            backendFetch("/settings", { silent: true }).then(function (resp) {
              if (resp && resp.data && resp.data.plan) {
                var freshPlan = resp.data.plan;
                // Cache the backend-derived monthly limit so the sidebar reads
                // it instead of hardcoding — raising a limit needs no extension
                // update. Stored alongside plan.
                var freshLimit = resp.data.monthly_limit;
                // Persist the real monthly count from the backend so the sidebar
                // quota bar + pre-send guard (which read storage) see the true
                // value instead of a stale 0 — a returning user was otherwise
                // ambushed by a 402 after creating a campaign.
                var freshSent = resp.data.emails_sent_this_month || 0;
                // All three, unconditionally, in one write.
                //
                // They used to be written separately: the count always, the
                // plan only `if (freshPlan !== result.plan)`, the limit only
                // `if (freshLimit)`. Two conditionals on three fields that
                // describe ONE account, and `result.plan` was read before the
                // network round trip — so a second refresh in flight (the
                // popup, the sidebar, a second Outlook tab) could leave the
                // plan untouched while the limit moved. The panel then showed
                // "250/250 emails remaining (Pro Plan)": the number from one
                // account state, the label from another. Reported 2026-08-14.
                //
                // The saved conditional bought nothing. chrome.storage.local
                // is not a database; writing an unchanged string costs less
                // than the class of bug it created.
                var _set = {
                  plan: freshPlan,
                  monthlyLimit: freshLimit || null,
                  emailsSentThisMonth: freshSent,
                };
                // Respond AFTER the write commits. MV3 makes no ordering
                // guarantee between a set() here and a get() in the sidebar's
                // own context, and the sidebar used to re-read storage in this
                // very callback — reading, sometimes, what was there before.
                chrome.storage.local.set(_set, function () {
                  log("Plan/limit/count refreshed from backend:", freshPlan, freshLimit, freshSent);
                  sendResponse({
                    user: result.user,
                    plan: freshPlan,
                    emailsSentThisMonth: freshSent,
                    monthlyLimit: freshLimit,
                    // The one field that lets a caller tell a live answer from
                    // a cached one. Absent on every degraded branch below.
                    fresh: true,
                  });
                });
              } else {
                sendResponse({
                  user: result.user,
                  plan: result.plan || "free",
                  emailsSentThisMonth: result.emailsSentThisMonth || 0,
                });
              }
            }).catch(function () {
              sendResponse({
                user: result.user,
                plan: result.plan || "free",
                emailsSentThisMonth: result.emailsSentThisMonth || 0,
              });
            });
          } else {
            sendResponse({
              user: result.user,
              plan: result.plan || "free",
              emailsSentThisMonth: result.emailsSentThisMonth || 0,
            });
          }
        }
      );
      return true;

    case "SYNC_AUTH":
      chrome.storage.local.get(["accessToken", "user"], function (storage) {
        if (!storage.accessToken || !storage.user) {
          sendResponse({ error: "Not logged in" });
          return;
        }
        syncAuthWithBackend(storage.accessToken, storage.user).then(function () {
          sendResponse({ success: true });
        });
      });
      return true;

    case "CREATE_CAMPAIGN":
      backendFetch("/campaigns", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "UPLOAD_CONTACTS":
      backendFetch("/campaigns/" + message.campaignId + "/contacts", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "SEND_CAMPAIGN":
      backendFetch("/campaigns/" + message.campaignId + "/send", {
        method: "POST",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_CAMPAIGNS":
      backendFetch("/campaigns" + (message.archived ? "?archived=true" : "")).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "TEST_SEND":
      // Legacy path (kept for older sidebar builds that still pre-create a campaign).
      backendFetch("/campaigns/" + message.campaignId + "/test-send", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "TEST_SEND_STATELESS":
      // Preferred: backend validates subject+body directly, no DB write.
      backendFetch("/campaigns/test-send", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "VALIDATE_TAGS":
      // Validate-only (no send) — used by Preview so it shows the same
      // merge-tag errors as Send/Test Send before opening the modal.
      backendFetch("/campaigns/validate-tags", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ARCHIVE_CAMPAIGN":
      backendFetch("/campaigns/" + message.campaignId + "/archive", {
        method: "POST",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "UNARCHIVE_CAMPAIGN":
      backendFetch("/campaigns/" + message.campaignId + "/unarchive", {
        method: "POST",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "EXPORT_CAMPAIGN_LIST":
      backendFetch("/campaigns/export-list").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_CAMPAIGN_STATS":
      backendFetch("/campaigns/" + message.campaignId + "/stats").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "EXPORT_CAMPAIGN_CSV":
      backendFetch("/campaigns/" + message.campaignId + "/export").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ACTIVATE_FOLLOWUP":
      backendFetch(
        "/campaigns/" + message.campaignId + "/followups/" +
          message.followupId + "/activate?confirm_immediate=" +
          (message.confirmImmediate ? "true" : "false"),
        { method: "POST" }
      ).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "STOP_CAMPAIGN":
      backendFetch("/campaigns/" + message.campaignId + "/stop", {
        method: "POST",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "CREATE_FOLLOWUP":
      backendFetch("/campaigns/" + message.campaignId + "/followups", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "CREATE_AB_TEST":
      backendFetch("/campaigns/" + message.campaignId + "/ab-test", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_AB_TEST":
      backendFetch("/campaigns/" + message.campaignId + "/ab-test").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "SAVE_TEMPLATE":
      backendFetch("/templates", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_TEMPLATES":
      backendFetch("/templates").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "DELETE_TEMPLATE":
      backendFetch("/templates/" + message.templateId, {
        method: "DELETE",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_SETTINGS":
      backendFetch("/settings").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "UPDATE_SETTINGS":
      backendFetch("/settings", {
        method: "PUT",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_ANNOUNCEMENTS":
      backendFetch("/announcements").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ANNOUNCEMENT_READ":
      backendFetch("/announcements/" + message.id + "/read", {
        method: "POST",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ANNOUNCEMENT_DISMISS":
      backendFetch("/announcements/" + message.id + "/dismiss", {
        method: "POST",
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_SUPPRESSION_LIST":
      backendFetch("/settings/suppression").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ADD_SUPPRESSION":
      backendFetch("/settings/suppression", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "REMOVE_SUPPRESSION":
      backendFetch("/settings/suppression", {
        method: "DELETE",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "REPORT_ERROR":
      reportError(
        message.payload ? message.payload.message : "Unknown",
        message.payload ? message.payload.stack : "",
        { source: message.payload ? message.payload.source : "unknown" }
      );
      sendResponse({ status: "reported" });
      return false;

    case "AI_GENERATE_EMAIL":
      backendFetch("/ai/generate-email", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "SEND_FEEDBACK":
      backendFetch("/api/feedback", {
        method: "POST",
        body: message.payload,
      }).then(function (result) {
        sendResponse(result);
      }).catch(function () {
        // Fallback: try without auth (feedback should work even if not logged in)
        fetch(_backendBases()[0] + "/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(message.payload),
        }).then(function () {
          sendResponse({ data: { status: "received" } });
        }).catch(function () {
          sendResponse({ error: "Failed to send feedback" });
        });
      });
      return true;

    case "CREATE_CHECKOUT":
      backendFetch("/billing/create-checkout", {
        method: "POST",
        body: { plan: message.plan || "pro" },
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "OPEN_PORTAL":
      backendFetch("/billing/portal").then(function (result) {
        sendResponse(result);
      });
      return true;

    case "RESUME_CAMPAIGN":
      backendFetch("/campaigns/" + encodeURIComponent(message.campaignId) + "/resume", {
        method: "POST",
        body: {},
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ONEDRIVE_SHARE_LINK":
      backendFetch("/api/onedrive/share-link", {
        method: "POST",
        body: message.payload || {},
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "ONEDRIVE_BROWSE":
      // Custom file picker fetches the user's OneDrive folder contents
      // through our backend (we hold the MS token server-side).
      var folderId =
        (message.payload && message.payload.folder_id) || "root";
      backendFetch(
        "/api/onedrive/browse?folder_id=" + encodeURIComponent(folderId)
      ).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "DETECT_CSV_ENCODING":
      // A second opinion for a CSV the sidebar's own rules refused. Only the
      // first 64 KB is ever sent — that is all the server samples, and it
      // keeps a customer's contact list from crossing the wire in full for
      // a question that a slice answers just as well.
      //
      // Any failure is answered with "no opinion" rather than an error: the
      // picker works without a suggestion, it just costs the user one more
      // click, and a network fault must not turn into a dialog they cannot
      // dismiss.
      (async function () {
        try {
          // `silent: true` — a 401 here must not wipe the session. This runs
          // while the user is staring at an upload dialog, and dropping them
          // to a sign-in screen over an optional suggestion would be a far
          // worse bug than having no suggestion.
          const r = await backendFetch("/campaigns/detect-encoding", {
            method: "POST",
            body: { sample_b64: message.sample || "" },
            silent: true,
          });
          const data = r && (r.data || r);
          sendResponse({
            encoding: r && !r.error && data && data.encoding ? data.encoding : null,
          });
        } catch (e) {
          sendResponse({ encoding: null });
        }
      })();
      return true;

    case "MS_LOGIN_MAIL_READ":
      // Turns reply detection back on for a user who signed in without
      // Mail.Read. Same incremental consent as OneDrive above.
      startMSLogin(false, true, message.context).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "MS_LOGIN_ONEDRIVE":
      // Incremental consent flow: launches OAuth with the OneDrive
      // scopes added on top of the existing Mail grant. Microsoft
      // shows the consent screen for ONLY the new scopes (scopes
      // the user already approved are skipped automatically).
      startMSLogin(true, undefined, message.context).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "TRACK":
      track(message.event, message.properties || {});
      sendResponse({ ok: true });
      return false; // sync, no async response

    case "TRACK_ANONYMOUS":
      // Clear the user_id alias FIRST, then track — so the event attaches
      // to the anonymous distinct_id, not the signed-in email. Used for
      // account_deleted: we keep the churn signal (count) without tying it
      // to the identity the user just asked us to erase (GDPR-cleaner).
      resetIdentity().then(function () {
        track(message.event, message.properties || {});
      });
      sendResponse({ ok: true });
      return false; // sync ack; track runs async after reset

    case "DELETE_ACCOUNT":
      // backendFetch extracts the structured 409 code (e.g.
      // "active_subscription") into result.error, so the sidebar can
      // branch on it for a localized message.
      backendFetch("/account/delete", {
        method: "POST",
        body: message.payload || {},
      }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "GET_BILLING_STATUS":
      // silent: this call's only consumer is the price catalogue, every
      // caller degrades to "no plans" on any error, and two of the three
      // callers fire automatically (popup open, Account tab open). A price
      // refresh must never be the thing that clears the JWT — the same rule
      // GET_USER_STATE already follows a few lines above.
      backendFetch("/billing/status", { silent: true }).then(function (result) {
        sendResponse(result);
      });
      return true;

    case "OPEN_POPUP":
      chrome.action.openPopup();
      sendResponse({ success: true });
      break;

    case "COMPOSE_OPENED":
      log("Compose window opened in tab:", sender.tab?.id);
      sendResponse({ ack: true });
      break;

    case "SIDEBAR_TOGGLE":
      log("Sidebar toggled:", message.visible ? "open" : "closed");
      sendResponse({ ack: true });
      break;

    case "HEALTH_CHECK":
      // Skip ping if a backend call succeeded recently
      if (Date.now() - _lastBackendOk < HEALTH_CHECK_FRESHNESS_MS) {
        sendResponse({ ok: true });
        break;
      }
      // "Reachable" means ANY base answers — the fallback host counts, and
      // whichever responds becomes the sticky base for real API calls too.
      (async function () {
        var bases = _backendBases();
        for (var i = 0; i < bases.length; i++) {
          try {
            var resp = await fetch(bases[i] + "/", { method: "GET" });
            if (resp.ok) {
              _lastBackendOk = Date.now();
              _activeBackendBase = bases[i];
              sendResponse({ ok: true });
              return;
            }
          } catch (e) { /* try the next base */ }
        }
        sendResponse({ ok: false });
      })();
      return true; // async sendResponse

    case "OPEN_OUTLOOK_WITH_SIDEBAR":
      // Open the user's REAL Outlook host (work=office.com, personal=live.com),
      // not a hardcoded guess — see resolveOutlookMailUrl.
      resolveOutlookMailUrl().then(function (mailUrl) {
        chrome.tabs.create({ url: mailUrl }, function (newTab) {
          // Outlook boots slowly and may redirect across hosts mid-load
          // (office.com → cloud.microsoft for migrated tenants), so a single
          // post-"complete" message can fire while no content script exists
          // and the sidebar never opens. Retry until the content script acks.
          var attempts = 0;
          var timer = setInterval(function () {
            attempts++;
            if (attempts > 16) {
              // 24 seconds of asking and no content script ever answered. The
              // user asked for the panel and is now looking at a plain Outlook
              // tab. Common cause: the tab is parked on login.microsoftonline
              // .com for MFA, which is not in content_scripts.matches, so
              // nothing can ever ack. Giving up silently made this identical
              // to never having clicked.
              track("panel_open_gave_up", { attempts: attempts - 1 });
              clearInterval(timer);
              return;
            }
            chrome.tabs.sendMessage(newTab.id, { type: "SHOW_SIDEBAR" })
              .then(function (resp) {
                if (resp && resp.ack) clearInterval(timer);
              })
              .catch(function () {
                /* content script not ready yet (or tab closed) — keep trying */
              });
          }, 1500);
        });
      });
      sendResponse({ ack: true });
      break;

    default:
      log("Unknown message type:", message.type);
      sendResponse({ error: "Unknown message type" });
  }
});

// ── Alarms ──
// Follow-up email sending is handled server-side by Celery beat (hourly).
// This alarm refreshes campaign stats so the UI reflects follow-up results.
chrome.alarms.onAlarm.addListener(function (alarm) {
  log("Alarm fired:", alarm.name);

  if (alarm.name.startsWith("followup_")) {
    var campaignId = alarm.name.replace("followup_", "");
    log("Follow-up stats refresh for campaign:", campaignId);
    backendFetch("/campaigns/" + campaignId + "/stats").then(function (result) {
      if (result && result.data) {
        log("Campaign stats refreshed:", result.data);
      }
    }).catch(function (err) {
      log("Failed to refresh follow-up stats:", err);
    });
  }
});

log("Service worker started");
log("Redirect URI for Azure registration:", AZURE_REDIRECT_URI);
