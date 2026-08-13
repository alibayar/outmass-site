/**
 * A price may never be written into the extension.
 *
 * Until 2026-08-13 it was written in seventy places: popupUpgradeStarter and
 * popupUpgradePro carried "($9/mo)", and the quota-cap modal's three strings
 * spelled out "$9/mo" and "$19/mo" — five keys, each of them fourteen times
 * over, once per locale, plus twice more as pre-i18n text in popup.html.
 * (The commit that removed them said forty-two, which was the modal subtotal
 * with the two popup keys left out of the multiplication. Fitting.)
 * The panel's Account tab meanwhile read the same
 * numbers from Stripe. Two sources for one number is not a style question:
 * docs/terms.html promised a 50-email free tier for months after config.py
 * said 250, and nothing failed, because a stale number is still a number.
 *
 * So the rule is absolute rather than a list of exceptions — an exception
 * list is the thing that rots. Prices come from /billing/status, formatted
 * by Intl in the reader's own locale, or they do not appear at all.
 *
 * Checked on both sides: no literal price anywhere (negative), and the code
 * that formats the real one still exists (positive). The negative alone
 * would pass beautifully on a build that had simply stopped showing prices.
 */

const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");
const LOCALES = path.join(EXT, "_locales");

// In a messages.json value "$1" is a Chrome placeholder and "$$" is an
// escaped literal dollar — only the second can ever be a price. Getting this
// backwards would either miss every price or condemn every placeholder.
const DOLLAR_PRICE = /\$\$\s*\d/;
const OTHER_CURRENCY = /[€£¥₺₹]\s*\d|\d\s*[€£¥₺₹]/;

function hasPrice(message) {
  return DOLLAR_PRICE.test(message) || OTHER_CURRENCY.test(message);
}

function run() {
  const failures = [];
  const check = (ok, msg) => { if (!ok) failures.push(msg); };

  // ── The matcher can tell a price from a placeholder ──
  //
  // Self-tested before it is trusted. A check that cannot make this
  // distinction is worse than none: it would flag alertLimitReached ("$1
  // emails a month") on every run until someone deleted the suite.
  check(hasPrice("Upgrade → Starter ($$9/mo)"), "the matcher no longer sees a literal price");
  check(hasPrice("Pro — 19 €/mois"), "the matcher only understands dollars");
  check(!hasPrice("$1 emails a month"), "the matcher counts a Chrome placeholder as a price");
  check(!hasPrice("2,500 emails a month"), "the matcher counts a quota as a price");
  check(!hasPrice("30-day money-back guarantee"), "the matcher counts a plain number as a price");

  // ── No locale file holds a price ──
  const locales = fs
    .readdirSync(LOCALES)
    .filter((d) => fs.statSync(path.join(LOCALES, d)).isDirectory());

  check(locales.length >= 14, `only ${locales.length} locales found — the scan is looking in the wrong place`);

  for (const locale of locales) {
    const file = path.join(LOCALES, locale, "messages.json");
    const messages = JSON.parse(fs.readFileSync(file, "utf8"));
    for (const [key, entry] of Object.entries(messages)) {
      const message = (entry && entry.message) || "";
      check(
        !hasPrice(message),
        `_locales/${locale} ${key} carries a literal price: ${JSON.stringify(message)} — ` +
          `read it from /billing/status and format it with Intl instead, ` +
          `or the day a price changes this string is silently wrong in ${locales.length} languages`
      );
    }
  }

  // ── Nor any markup ──
  //
  // popup.html shipped "Upgrade → Starter ($9/mo)" as the pre-i18n fallback
  // text, which is the same defect one layer down and invisible to a scan
  // that only reads the message files.
  for (const file of fs.readdirSync(EXT).filter((f) => f.endsWith(".html"))) {
    const source = fs.readFileSync(path.join(EXT, file), "utf8");
    source.split("\n").forEach((line, i) => {
      check(
        !/[$€£¥₺₹]\s?\d/.test(line),
        `${file}:${i + 1} carries a currency amount in markup: ${line.trim().slice(0, 80)}`
      );
    });
  }

  // ── And the path that shows the real one is still there ──
  const sidebar = fs.readFileSync(path.join(EXT, "sidebar.js"), "utf8");
  const popup = fs.readFileSync(path.join(EXT, "popup.js"), "utf8");

  for (const [name, source] of [["sidebar.js", sidebar], ["popup.js", popup]]) {
    check(
      /Intl\.NumberFormat\([^)]*[\s\S]{0,120}?style:\s*["']currency["']/.test(source),
      `${name} no longer formats a currency with Intl — if prices moved ` +
        `somewhere else, point this check at wherever that is`
    );
  }

  check(
    /function buildPlanRows\(/.test(sidebar),
    "buildPlanRows is gone from sidebar.js — the Account tab and the " +
      "quota-cap modal shared it precisely so a second copy could not " +
      "reintroduce a hardcoded plan"
  );

  // ── And it is still wired in at both call sites ──
  //
  // Defining the function and never calling it would satisfy every check
  // above while the product quietly went back to showing no price. Counted,
  // not merely found: one occurrence is the definition.
  const count = (source, needle) => source.split(needle).length - 1;

  check(
    count(sidebar, "GET_BILLING_STATUS") >= 2,
    "sidebar.js asks for the plan catalogue in fewer than two places — the " +
      "Account tab picker and the quota-cap modal each need it"
  );
  check(
    count(popup, "renderPopupPrices") >= 2,
    "renderPopupPrices is defined but never called — the popup buttons would " +
      "show no price at all, which this suite would otherwise call a pass"
  );

  // ── The quota-cap modal's fallback button claims its own click ──
  //
  // It drops its id so the catalogue swap cannot replace it while a checkout
  // is in flight. Without that, a click on the rows that appear underneath
  // opens a SECOND Stripe session for one intent.
  check(
    /this\.disabled = true;\s*\n\s*this\.id = "";/.test(sidebar),
    "the quota-cap modal's Upgrade button no longer claims its click before " +
      "the async catalogue swap — two checkout sessions can be created from " +
      "one upgrade"
  );

  return { name: "no-hardcoded-prices", failures };
}

module.exports = { run };
