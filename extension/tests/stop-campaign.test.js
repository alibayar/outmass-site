/**
 * A user must be able to stop their own campaign.
 *
 * Until 2026-09-01 there was no way to. No button, no endpoint, nothing behind
 * a menu. Helene@circularworkplaces.com found that out five recipients into a
 * 66-person send and wrote: "Now I see nowhere to edit the campaign or even
 * stop it! Please could you let me know how to do that or I will have to close
 * the account to stop it."
 *
 * Revoking OAuth was accurately her only lever. Her campaign was stopped by
 * hand with a database UPDATE while she waited.
 *
 * The thing most worth guarding here is not the button — it is that the panel
 * and the server agree on WHEN to offer it. Showing Stop for a status the
 * endpoint refuses would put a second dead end on top of the first, at the
 * same moment, for the same person.
 */
const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");
const REPO = path.join(EXT, "..");
const read = (f) => fs.readFileSync(path.join(EXT, f), "utf8");

const KEYS = [
  "stopHint",
  "btnStopCampaign",
  "confirmStopCampaign",
  "alertCampaignStopped",
  "alertCampaignNotStoppable",
  "alertCampaignStopFailed",
];

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  const sidebar = read("sidebar.js");
  const html = read("sidebar.html");
  const background = read("background.js");

  // ── the control exists and is reachable ──

  check(
    /id="btn-stop-campaign"/.test(html),
    "the Stop button is gone from sidebar.html — a campaign becomes " +
      "unstoppable again, which is the fault this suite exists for"
  );
  check(
    /id="stop-section"/.test(html),
    "the stop section is gone from sidebar.html"
  );
  check(
    /case "STOP_CAMPAIGN":[\s\S]{0,300}?"\/campaigns\/" \+ message\.campaignId \+ "\/stop"/
      .test(background),
    "STOP_CAMPAIGN no longer posts to the stop endpoint"
  );

  // ── the count goes in the QUESTION, not just the answer ──

  check(
    /confirm\(t\("confirmStopCampaign", \[String\(_stopSentCount\)\]\)\)/.test(sidebar),
    "the stop confirmation no longer names how many have already been " +
      "reached — that number is the one part of this nobody can take back, " +
      "so it belongs in front of the decision rather than after it"
  );
  check(
    /alert\(t\("alertCampaignStopped", \[/.test(sidebar),
    "the result no longer reports the reached and spared counts"
  );

  // ── the two sides must agree on when it is offered ──

  const panelList = /var stoppable = \[([\s\S]{0,400}?)\];/.exec(sidebar);
  check(panelList !== null, "the panel's stoppable-status list could not be found");

  const py = fs.readFileSync(
    path.join(REPO, "backend", "routers", "campaigns.py"), "utf8"
  );
  const serverList = /STOPPABLE_STATUSES = \{([\s\S]{0,400}?)\}/.exec(py);
  check(serverList !== null, "STOPPABLE_STATUSES could not be found in campaigns.py");

  if (panelList && serverList) {
    const parse = (s) => new Set((s.match(/"[a-z_]+"/g) || []).map((x) => x.slice(1, -1)));
    const inPanel = parse(panelList[1]);
    const inServer = parse(serverList[1]);

    const panelOnly = [...inPanel].filter((s) => !inServer.has(s));
    const serverOnly = [...inServer].filter((s) => !inPanel.has(s));

    check(
      panelOnly.length === 0,
      `the panel offers Stop for ${panelOnly.join(", ")}, which the server " +
        "refuses — the user presses a button and is told no, which is worse ` +
        `than no button`
    );
    check(
      serverOnly.length === 0,
      `the server would stop ${serverOnly.join(", ")} but the panel hides the ` +
        `button for it — a running campaign with no visible brake`
    );
    check(
      inPanel.has("sending") && inPanel.has("scheduled") && inPanel.has("partial"),
      "the panel does not offer Stop for sending/scheduled/partial — those " +
        "are precisely the states someone is looking at when they want it to " +
        "stop"
    );
  }

  // ── nothing it calls may be undefined ──
  //
  // The 0.3.1 blocker was a call to a function that did not exist; under
  // "use strict" that throws, and no source-regex assertion can see it.

  const GLOBALS = new Set([
    "alert", "confirm", "parseInt", "String", "Number", "Boolean", "Array",
    "Object", "JSON", "Math", "Date", "RegExp", "Error", "isNaN", "setTimeout",
    "clearTimeout", "if", "for", "while", "switch", "catch", "return",
    "function", "typeof", "new",
  ]);
  const panelSources = sidebar + "\n" + read("i18n.js");
  const strip = (src) =>
    src
      .replace(/\/\*[\s\S]*?\*\//g, " ")
      .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ")
      .replace(/"(?:[^"\\]|\\.)*"/g, '""')
      .replace(/'(?:[^'\\]|\\.)*'/g, "''");

  const handler = /btnStopCampaign\.addEventListener\("click",[\s\S]{0,3000}?\n  \}/.exec(sidebar);
  check(handler !== null, "the Stop click handler could not be located");
  if (handler) {
    const code = strip(handler[0]);
    const re = /(^|[^.\w$])([A-Za-z_$][\w$]*)\s*\(/g;
    let m;
    while ((m = re.exec(code)) !== null) {
      const name = m[2];
      if (GLOBALS.has(name)) continue;
      const defined =
        new RegExp("function " + name + "\\s*\\(").test(panelSources) ||
        new RegExp("(var|let|const)\\s+" + name + "\\s*=\\s*(async\\s*)?function").test(panelSources) ||
        new RegExp("(var|let|const)\\s+" + name + "\\s*=\\s*\\(").test(panelSources);
      check(
        defined,
        `the Stop handler calls ${name}(), which is defined nowhere in the ` +
          `panel — a ReferenceError every time somebody tries to stop a send`
      );
    }
  }

  // ── strings ──

  const en = JSON.parse(read("_locales/en/messages.json"));
  for (const key of KEYS) {
    check(
      Object.prototype.hasOwnProperty.call(en, key),
      `${key} is missing from the en locale`
    );
    check(
      new RegExp(`["']${key}["']`).test(sidebar) || new RegExp(`"${key}"`).test(html),
      `${key} is defined but nothing uses it`
    );
  }
  check(
    /\$1/.test(en.confirmStopCampaign && en.confirmStopCampaign.message),
    "confirmStopCampaign lost its $1 — the user is asked to accept an " +
      "unnamed number of already-sent emails"
  );
  check(
    /\$1/.test(en.alertCampaignStopped && en.alertCampaignStopped.message) &&
      /\$2/.test(en.alertCampaignStopped && en.alertCampaignStopped.message),
    "alertCampaignStopped lost one of its counts"
  );

  // ── Stop must be disarmed when the view it belongs to fails to load ──
  //
  // _stopCampaignId and _stopSentCount are assigned only in the success
  // branch. A failed stats load used to return early leaving the PREVIOUS
  // campaign's button on screen and armed against the previous campaign — and
  // stopping is one-way. A stats load failing on an expired session is what
  // Helene hit seconds before she went looking for a way to stop something.
  const detail = /function showCampaignDetail\([\s\S]{0,1200}?resp\.error\) \{[\s\S]{0,2000}?return;\s*\}/
    .exec(sidebar);
  check(detail !== null, "showCampaignDetail's error branch could not be located");
  if (detail) {
    check(
      /_stopCampaignId = null/.test(detail[0]),
      "the failed-stats branch no longer clears _stopCampaignId — Stop stays " +
        "armed against whichever campaign was rendered last"
    );
    check(
      /stop-section[\s\S]{0,120}display = "none"/.test(detail[0]),
      "the failed-stats branch no longer hides the Stop button, so it stays " +
        "on screen over an error message"
    );
  }
  check(
    /if \(currentDetailCampaignId !== campaignId\) return;/.test(sidebar),
    "showCampaignDetail no longer drops a stats reply for a campaign the user " +
      "has navigated away from — one campaign's numbers can render under " +
      "another's name"
  );

  // ── the preview must decide from the TEMPLATE, like the server ──

  check(
    /function textToHtml\(template, merged\)/.test(sidebar),
    "textToHtml no longer takes the template separately — it decides from the " +
      "text it converts, which is what the server stopped doing on 2026-09-01"
  );
  // Both detections must read `tpl` — the TEMPLATE. Reading the merged text
  // is the original bug: a CSV value in angle brackets flips the preview and
  // the send disagrees again, in the other direction.
  check(
    /var tpl = template \|\| "";/.test(sidebar),
    "textToHtml no longer binds the template separately before deciding"
  );
  check(
    /if \(BLOCK_TAG_RE\.test\(tpl\)\) return body;/.test(sidebar),
    "the block-markup branch does not test the template"
  );
  check(
    /if \(\/<\[a-z!\/\]\[\^>\]\*>\/i\.test\(tpl\)\) return paragraphs\(body\);/.test(sidebar),
    "the inline-markup branch is gone, or does not test the template — one " +
      "<a href> in a signature collapses the whole email into a block again, " +
      "which is the bug Helene reported on the morning of 2026-09-01"
  );
  // The panel's three modes must be the server's three modes.
  const emailBody = fs.readFileSync(
    path.join(REPO, "backend", "utils", "email_body.py"), "utf8"
  );
  const tagsOf = (src, re) => {
    const m = re.exec(src);
    return m ? new Set((m[1].match(/[a-z][a-z0-9]*(?:\[1-6\])?/gi) || [])) : null;
  };
  const serverBlock = /BLOCK_TAG_RE = re\.compile\(\s*r"([\s\S]*?)",/.exec(emailBody);
  const panelBlock = /var BLOCK_TAG_RE =\s*\/([\s\S]*?)\/i;/.exec(sidebar);
  check(serverBlock !== null, "BLOCK_TAG_RE could not be found in email_body.py");
  check(panelBlock !== null, "BLOCK_TAG_RE could not be found in sidebar.js");
  if (serverBlock && panelBlock) {
    const norm = (s) =>
      s.replace(/\\b|\\\//g, "").replace(/[()?:^$]/g, "").replace(/<\/?/g, "")
       .replace(/\s|"|r"/g, "");
    check(
      norm(serverBlock[1]) === norm(panelBlock[1]),
      `the panel and the server disagree about which tags are block-level:\n` +
        `      server: ${norm(serverBlock[1])}\n      panel:  ${norm(panelBlock[1])}\n` +
        `      preview and send would format the same email differently`
    );
  }
  check(
    /textToHtml\(body, previewBody\)/.test(sidebar),
    "the preview call no longer passes the raw template alongside the merged " +
      "text"
  );

  check(
    /track\("campaign_stopped"/.test(sidebar),
    "stopping records no event — the only signal that would say whether " +
      "anyone uses this, or whether the mid-batch overshoot matters"
  );

  // -- a number the server could not work out must not render as 0 --
  //
  // The stats endpoint returns null for engaged/replied when the read failed
  // or came back truncated. `x || 0` turns that into a confident zero, and for
  // "Replied" the confident zero says "nobody answered you" - produced by a
  // read that never happened. miriam is the standing example of what a
  // confident wrong number costs at the moment of maximum distrust.
  check(
    /function num\(v\) \{ return v === null \|\| v === undefined \? "/.test(sidebar),
    "the null-safe stat renderer is gone from showCampaignDetail"
  );
  check(
    /engagedEl\.textContent = num\(stats\.engaged_count\)/.test(sidebar) &&
      /repliedEl\.textContent = num\(stats\.replied_count\)/.test(sidebar),
    "engaged/replied are rendered with `|| 0` again - an unavailable count " +
      "displays as a definitive zero"
  );
  check(
    /replyRateEl\.textContent = pct\(stats\.reply_rate\)/.test(sidebar),
    "the reply rate falls back to 0% instead of a dash"
  );
  check(
    /stats\.delivered_count !== undefined/.test(sidebar),
    "the Sent figure no longer prefers delivered_count - it shows emails " +
      "sent, which a follow-up inflates, above rates divided by people reached"
  );

  return { name: "stop-campaign", failures };
}

module.exports = { run };

if (require.main === module) {
  const r = run();
  r.failures.forEach((f) => console.error("FAIL:", f));
  console.log(r.failures.length ? `${r.name}: ${r.failures.length} failure(s)` : `${r.name}: ok`);
  process.exit(r.failures.length ? 1 : 0);
}
