/**
 * A locked-feature wall must offer a plan that actually unlocks the feature.
 *
 * Follow-ups, A/B testing and the AI writer are Pro-only. Until 2026-08-31 all
 * three answered a 402 with a bare alert() naming the plan and offering no way
 * to buy it — a rule with no action, which is what CLAUDE.md forbids for
 * user-visible messages. In five months not one upgrade click in the product's
 * telemetry ever came from a feature wall.
 *
 * They now go through showUpgradeModal(), the dialog the quota wall already
 * uses, which renders the live Stripe catalogue with a Choose button per plan.
 * That introduces a NEW failure mode this file exists to prevent:
 *
 *   buildPlanRows() offers every plan above the user's current one. On a
 *   Pro-only wall a Free user would be shown STARTER. They pay $9 and still
 *   cannot use follow-ups.
 *
 * A silent failure is bad. A billed one is worse — it is strictly worse than
 * the alert() this replaced. The filter, and the fallback button that bypasses
 * the catalogue when the billing call is slow, are the two doors into that
 * failure and both are checked below.
 */
const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");
const read = (f) => fs.readFileSync(path.join(EXT, f), "utf8");

// The two walls raised the moment their 402 lands. Nothing blocking is due to
// run after them, so they open the dialog directly.
const WALLS = [
  { key: "alertFollowupProOnly", context: "wall_followup" },
  { key: "alertAiProOnly", context: "wall_ai" },
];

// A/B is the exception and must stay one. Its 402 arrives BEFORE the send,
// and the send ends in a native alert() that blocks the thread — so a modal
// opened at the 402 would sit underneath a dialog the user has to dismiss
// first. It is held in _pendingFeatureWall and flushed where the follow-up
// wall is already raised, after that alert.
const DEFERRED_WALL = { key: "alertAbTestProOnly", context: "wall_ab" };

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  const sidebar = read("sidebar.js");

  // ── the filter itself ──

  check(
    /function buildPlanRows\(plans, context, afterClick, currentPlan, minPlan\)/
      .test(sidebar),
    "buildPlanRows no longer takes minPlan — every feature wall would fall " +
      "back to offering whatever is above the user's plan, which on a " +
      "Pro-only wall means selling a Free user Starter"
  );

  check(
    /planRank\[p\.key\] !== undefined && planRank\[p\.key\] < minRank\) return;/
      .test(sidebar),
    "the minRank filter is gone from buildPlanRows — the parameter can be " +
      "passed and ignored, which looks correct at every call site"
  );

  check(
    /var minRank = planRank\[minPlan\] !== undefined \? planRank\[minPlan\] : -1;/
      .test(sidebar),
    "minRank no longer defaults to -1 for an absent/unknown minPlan — the " +
      "quota wall passes no minPlan and must keep showing every plan"
  );

  // ── each wall reaches the modal, and asks for Pro ──

  for (const wall of WALLS) {
    // The 402 branch, from the string it shows to the end of that call.
    const site = new RegExp(
      `showUpgradeModal\\(\\{[^}]*t\\("${wall.key}"\\)[^}]*\\}\\)`
    ).exec(sidebar);

    check(
      site !== null,
      `${wall.key} is no longer shown through showUpgradeModal — a bare ` +
        `alert() states the rule and offers no way to act on it, which is ` +
        `the dead end this suite replaced`
    );

    if (site) {
      check(
        /minPlan:\s*"pro"/.test(site[0]),
        `the ${wall.key} wall does not ask for minPlan "pro" — the catalogue ` +
          `would offer Starter for a feature Starter does not unlock`
      );
      check(
        new RegExp(`context:\\s*"${wall.context}"`).test(site[0]),
        `the ${wall.key} wall lost its "${wall.context}" context — upgrade ` +
          `clicks from feature walls become indistinguishable from the ` +
          `account tab, and the one thing September is meant to measure ` +
          `stops being measurable`
      );
    }

    // Nothing may quietly go back to the bare alert.
    check(
      !new RegExp(`alert\\(t\\("${wall.key}"\\)\\)`).test(sidebar),
      `${wall.key} is back inside a bare alert() somewhere in the panel`
    );
  }

  // ── the deferred wall, and the ordering it exists to preserve ──

  const held = new RegExp(
    `_pendingFeatureWall = \\{[^}]*t\\("${DEFERRED_WALL.key}"\\)[^}]*\\}`
  ).exec(sidebar);

  check(
    held !== null,
    "the A/B 402 no longer parks its wall in _pendingFeatureWall — opening " +
      "the modal inline puts it underneath the campaign's blocking success " +
      "alert(), which is the ordering regression this deferral exists for"
  );

  if (held) {
    check(
      /minPlan:\s*"pro"/.test(held[0]),
      "the deferred A/B wall does not ask for minPlan \"pro\" — it would " +
        "offer Starter for a feature Starter does not unlock"
    );
    check(
      new RegExp(`context:\\s*"${DEFERRED_WALL.context}"`).test(held[0]),
      `the deferred A/B wall lost its "${DEFERRED_WALL.context}" context`
    );
  }

  check(
    !new RegExp(`alert\\(t\\("${DEFERRED_WALL.key}"\\)\\)`).test(sidebar),
    `${DEFERRED_WALL.key} is back inside a bare alert() somewhere in the panel`
  );

  // Parking it is only half the mechanism; something has to raise it.
  check(
    /function flushPendingFeatureWall\(\)[\s\S]{0,400}?showUpgradeModal\(wall\)/
      .test(sidebar),
    "flushPendingFeatureWall no longer shows the parked wall — the A/B 402 " +
      "would be recorded and then never mentioned to the user at all, which " +
      "is worse than the alert() it replaced"
  );

  // Anchored on the local, not on "_pendingFeatureWall = null" alone: the
  // declaration a few lines above is also an assignment to null, and a looser
  // window matches it and passes while the clear inside the function is gone.
  check(
    /var wall = _pendingFeatureWall;\s*\n\s*_pendingFeatureWall = null;\s*\n\s*showUpgradeModal\(wall\)/
      .test(sidebar),
    "flushPendingFeatureWall no longer clears _pendingFeatureWall before " +
      "showing it — the same wall would be raised again after the next send"
  );

  // Both send paths must flush. Missing one means the wall is silently
  // dropped for either scheduled or immediate sends, and only one of them
  // is exercised by hand.
  check(
    (sidebar.match(/flushPendingFeatureWall\(\);/g) || []).length === 2,
    "flushPendingFeatureWall is not called from exactly the two send paths " +
      "(scheduled and immediate) — a dropped call loses the A/B wall for " +
      "whichever path lost it, silently"
  );

  // ── the door around the catalogue ──

  // showUpgradeModal renders a default Upgrade button immediately and swaps in
  // the catalogue when GET_BILLING_STATUS returns. That button was hardcoded
  // to Starter. On a Pro wall with a slow or failed billing call, it is the
  // billed failure again — through the one path the filter cannot see.
  check(
    /var offerPlan = \(opts && opts\.minPlan\) \|\| "starter";/.test(sidebar),
    "showUpgradeModal no longer derives offerPlan from opts.minPlan — the " +
      "fallback Upgrade button goes back to buying Starter on a Pro-only wall"
  );

  check(
    /CREATE_CHECKOUT", plan: offerPlan \}/.test(sidebar),
    "the fallback Upgrade button no longer buys offerPlan — a hardcoded plan " +
      "here bypasses the catalogue filter entirely"
  );

  // Every locale spells the plan name into that button ("Upgrade Now —
  // Starter", "Passer à Starter"). Buying Pro under a label that says Starter
  // is the same billed confusion by a third door, and the one the user would
  // actually read before clicking.
  check(
    /t\(offerPlan === "pro" \? "upgradeModalBtnPro" : "upgradeModalBtn"\)/
      .test(sidebar),
    "the fallback Upgrade button's label no longer follows offerPlan — on a " +
      "Pro-only wall it reads 'Starter' in all fourteen languages while " +
      "charging for Pro"
  );

  check(
    /\}, data\.plan, opts && opts\.minPlan\);/.test(sidebar),
    "the catalogue swap no longer forwards opts.minPlan to buildPlanRows — " +
      "the filter exists but nothing asks for it"
  );

  // ── the quota sentence must not appear on a feature wall ──

  // "You've reached your email limit." Someone who clicked a locked feature
  // has reached no limit. Saying so is a false statement in fourteen files.
  check(
    /featureMode \? "" : '<p style="color:#605e5c;font-size:13px;margin-bottom:16px;">' \+ t\("upgradeModalText"\)/
      .test(sidebar),
    "the quota sentence is no longer suppressed in feature mode — every " +
      "locked-feature wall tells the user they have run out of emails"
  );

  check(
    /var featureMode = !!\(opts && opts\.minPlan\);/.test(sidebar),
    "featureMode is no longer derived from opts.minPlan — the three things " +
      "that must move together (quota sentence, catalogue floor, fallback " +
      "plan) can drift apart"
  );

  // ── and it must say what the plan contains ──

  check(
    /t\(featureMode \? "upgradeModalProFeatures" : "upgradeModalFeatures"\)/
      .test(sidebar),
    "the feature list no longer switches on featureMode — a follow-up wall " +
      "sells 'Detailed reports + priority support', which names none of the " +
      "three Pro features and not the one they just clicked"
  );

  // ── the controls have to look locked before they are pressed ──

  const html = read("sidebar.html");

  // Every Pro-gated control, by the id the panel wires a handler to.
  for (const id of ["followup-enabled", "ab-test-enabled", "btn-ai-writer"]) {
    const el = new RegExp(`id="${id}"[^>]*>([\\s\\S]{0,400}?)</(?:label|button)>`)
      .exec(html);
    check(
      el !== null,
      `the ${id} control could not be located in sidebar.html to check its ` +
        `PRO tag`
    );
    check(
      el === null || /class="pro-tag"/.test(el[0]),
      `${id} no longer carries a PRO tag — it reads as free until the user ` +
        `has written the thing and pressed the button, which is how fifteen ` +
        `people opened the AI writer and six were refused at Generate`
    );
    // applyI18n() assigns el.textContent, so a pro-tag nested INSIDE the
    // translated element is deleted on the first render — silently, and only
    // in the browser. It has to be a sibling.
    check(
      el === null ||
        !/data-i18n="[^"]*"[^>]*>\s*[^<]*<span class="pro-tag"/.test(el[0]),
      `${id} puts its PRO tag inside the data-i18n element — applyI18n ` +
        `overwrites textContent and the tag disappears at runtime`
    );
  }

  return { name: "feature-wall-offer", failures };
}

module.exports = { run };

if (require.main === module) {
  const r = run();
  r.failures.forEach((f) => console.error("FAIL:", f));
  console.log(r.failures.length ? `${r.name}: ${r.failures.length} failure(s)` : `${r.name}: ok`);
  process.exit(r.failures.length ? 1 : 0);
}
