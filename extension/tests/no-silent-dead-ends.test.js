/**
 * Guards against the silence class specifically — dead ends that produce no
 * message, no event and no log.
 *
 * These are source-level assertions on purpose. The bugs they pin cannot be
 * reproduced in a unit test or in Playwright: the popup only misbehaves in a
 * real browser whose extension has just auto-updated, and the give-up branch
 * only fires after 24 seconds of a real tab never answering. But every one of
 * them regressed by DELETION — someone removed a reporting line, or wrote a
 * new branch and forgot one — and a grep catches exactly that.
 *
 * The rule these encode, from the 2026-08-04 silence audit:
 *
 *   Every rejection branch on a primary-journey gate emits a *_failed event
 *   before it returns. "Benign for the code" is never a reason to be silent
 *   to the user.
 *
 * Add an entry here whenever a new silent dead end is found and fixed.
 */

const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");
const read = (f) => fs.readFileSync(path.join(EXT, f), "utf8");

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  // ── popup: "Open Campaign Panel" into a tab that predates this build ──
  //
  // Chrome kills the content script in every already-open tab when the
  // extension updates and never re-injects one (no "scripting" permission),
  // so sendMessage rejects with "Receiving end does not exist". That used to
  // hit an empty catch with window.close() on the very next line: the panel
  // never opened, nothing was said, nothing was recorded. Ten versions
  // shipped 0.1.18 → 0.1.27, each minting that state in every long-lived
  // Outlook tab.
  const popup = read("popup.js");
  // A fixed window after each call rather than brace matching: the reporting
  // body itself contains "});" (the track() call's object literal), so a
  // non-greedy match to the first "});" stops BEFORE the very lines this
  // guard exists to check — which is how the first version of this test
  // passed on panel_open_failed and failed on showError.
  const showSidebarSends = popup
    .split("chrome.tabs.sendMessage(")
    .slice(1)
    .filter((chunk) => chunk.slice(0, 120).includes("SHOW_SIDEBAR"))
    .map((chunk) => chunk.slice(0, 600));
  check(
    showSidebarSends.length === 2,
    `expected 2 SHOW_SIDEBAR tab sends in popup.js, found ${showSidebarSends.length} — ` +
    `if a branch was added or removed, this guard needs updating with it`
  );
  showSidebarSends.forEach((snippet, i) => {
    check(
      snippet.includes("panel_open_failed"),
      `popup.js SHOW_SIDEBAR branch #${i + 1} no longer reports the failure — ` +
      `a deaf tab would go back to being a dead click with no event`
    );
    check(
      snippet.includes("showError"),
      `popup.js SHOW_SIDEBAR branch #${i + 1} no longer tells the user anything — ` +
      `only reloading the Outlook tab fixes this and nothing else says so`
    );
  });
  check(
    !/SHOW_SIDEBAR[\s\S]{0,200}\.catch\(function \(\) \{\}\)/.test(popup),
    "popup.js has an EMPTY catch on a SHOW_SIDEBAR path — that is the exact " +
    "shape of the bug: benign for the code, total failure for the user"
  );

  // ── background: the open-Outlook retry loop giving up ──
  const background = read("background.js");
  const giveUp = /attempts > 16\)\s*\{([\s\S]{0,600}?)\}/.exec(background);
  check(giveUp !== null, "could not find the OPEN_OUTLOOK_WITH_SIDEBAR give-up branch");
  if (giveUp) {
    check(
      giveUp[1].includes("panel_open_gave_up"),
      "the retry loop gives up silently again — 24s of asking, the user is " +
      "left on a plain Outlook tab, and it looks like they never clicked"
    );
  }

  // ── sidebar: the CSV dropzone, first gate of the main journey ──
  const sidebar = read("sidebar.js");
  const drop = /addEventListener\("drop",[\s\S]{0,1600}?\n {2}\}\);/.exec(sidebar);
  check(drop !== null, "could not find the CSV drop handler");
  if (drop) {
    check(
      drop[0].includes("unsupported_file_type"),
      "a rejected drop is silent again — preventDefault() already killed the " +
      "browser's own feedback, so the user sees pixel-identical UI"
    );
    check(
      drop[0].includes("csvErrNotCsv"),
      "a rejected drop no longer tells the user what to do about it"
    );
    check(
      /\/\\\.csv\$\/i/.test(drop[0]),
      "the extension check is case-SENSITIVE again — a CRM export named " +
      "Contacts.CSV works via the file picker and dies on drag-and-drop"
    );
  }
  check(
    sidebar.includes("reader.onerror"),
    "FileReader has no error handler — an unreadable file (network share, " +
    "pulled USB stick) leaves the user waiting for a preview that never comes"
  );
  // ── content script: the first-run auto-open must be a ONE-SHOT ──
  //
  // Not a silence bug but the same "cannot be reproduced in a harness" class:
  // this only runs inside a real Outlook page on a real first install. The
  // invariant is that the flag is cleared BEFORE the panel is shown. Get it
  // backwards — or clear it in a callback that never fires — and the panel
  // reopens on every single page load, forever, with no way for the user to
  // make it stop. That is far worse than the missed first run it fixes.
  const contentScript = read("content_script.js");
  const autoOpen = /firstRunAutoOpen[\s\S]{0,400}/.exec(contentScript);
  check(autoOpen !== null, "the first-run auto-open block is gone");
  if (autoOpen) {
    const clearAt = contentScript.indexOf("firstRunAutoOpen: false");
    const showAt = contentScript.indexOf("showSidebar()", clearAt);
    check(
      clearAt > -1,
      "the first-run flag is never cleared — the panel would reopen on every " +
      "page load, forever, and the user could not stop it"
    );
    check(
      clearAt > -1 && showAt > clearAt,
      "the panel is shown BEFORE the one-shot flag is cleared — if the write " +
      "fails or the page unloads first, auto-open becomes permanent"
    );
  }
  check(
    contentScript.includes("outlook_reached"),
    "the arrival milestone is gone — 32 of 97 installs stall before the panel " +
    "and this event is the only thing that says whether they reached Outlook"
  );

  check(
    sidebar.includes("reports_load_failed"),
    "the Reports load-failure branch is unreported again — a backend fault " +
    "that hides every user's campaigns would look like a quiet week"
  );

  // ── Mail.Read: the recovery path that has to exist before the flag flips ──
  //
  // Declining Mail.Read fails SILENTLY: follow-ups keep chasing people who
  // already answered and Reports shows a 0.0% reply rate, which reads as a
  // result rather than a missing permission. The panel banner is the only
  // thing that names it and offers a way back, and the server-side flag is
  // what decides who lands in that state — so if the banner regresses, the
  // flip becomes a silent downgrade for every new user.
  check(
    /var show = hasMailRead === false && !reauthShowing;/.test(sidebar),
    "the reply-detection banner no longer tests for an EXPLICIT false. A " +
    "truthy check shows it whenever the field is missing — an older backend, " +
    "a failed poll, a pre-split row — sending users who already granted " +
    "Mail.Read to Microsoft to grant it again"
  );
  check(
    sidebar.includes("MS_LOGIN_MAIL_READ"),
    "the banner's CTA no longer starts the Mail.Read consent flow, so the " +
    "banner states a problem it cannot fix"
  );
  check(
    background.includes("MS_LOGIN_MAIL_READ") &&
      background.includes("include_mail_read=true"),
    "the service worker no longer asks Microsoft for Mail.Read, so the " +
    "consent screen would grant nothing and the banner would never clear"
  );
  check(
    /var key = includeOneDrive \? "onedrive" : includeMailRead \? "mailread"/.test(background),
    "the Mail.Read flow shares a single-flight key with another scope — a " +
    "user granting Mail.Read would silently join a flow asking for something " +
    "else and get a window that grants the wrong permission"
  );

  // ── The encoding picker: the dead end it replaced, and the XSS it must not become ──
  check(
    sidebar.includes("openEncodingPicker(buf, diag)"),
    "a CSV the decoder refuses no longer reaches the picker. That branch was " +
    "an alert and a dropped file — the exact dead end two confirmed losses " +
    "walked into"
  );
  check(
    !/if \(!decoded\) \{\s*alert\(/.test(sidebar),
    "the refusal branch is back to a bare alert, so the file is dropped with " +
    "no way forward"
  );
  check(
    /preview\.innerHTML = ""/.test(sidebar) &&
      !/preview\.innerHTML\s*=\s*[^"'\s]/.test(sidebar),
    "the encoding preview is being built with innerHTML from file content. " +
    "That content is a customer's CSV — it renders as markup in the panel"
  );
  check(
    sidebar.includes("a.textContent = cells[0]"),
    "the preview no longer writes cells with textContent"
  );
  check(
    /var known = ENCODING_OPTIONS\.some/.test(sidebar),
    "the server's suggestion is applied without checking it is one of the " +
    "offered options — a label the picker cannot show would leave the select " +
    "and the decode disagreeing about what the user chose"
  );
  check(
    background.includes("DETECT_CSV_ENCODING") && background.includes("silent: true"),
    "the detection call is no longer silent. A 401 while the user stares at " +
    "the upload dialog would wipe their session over an OPTIONAL suggestion"
  );

  return { name: "no-silent-dead-ends", failures };
}

module.exports = { run };
