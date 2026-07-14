/**
 * i18n usage — every literal key the code asks for must exist in en.
 *
 * A typo'd or forgotten key doesn't crash: t() just returns the raw key
 * name, so the user sees "alertQuotaCapped" instead of a sentence. Several
 * call sites carry manual fallbacks for exactly this failure mode — this
 * test makes the whole class impossible instead.
 *
 * Only string LITERALS are checked (t("...") / t('...') / data-i18n="...");
 * dynamic keys (t(someVar)) are outside its reach by design.
 */

const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");

function run() {
  const failures = [];
  const en = JSON.parse(
    fs.readFileSync(path.join(EXT, "_locales", "en", "messages.json"), "utf8")
  );

  const used = new Map(); // key -> first "file" seen

  for (const jsFile of ["sidebar.js", "popup.js", "content_script.js", "background.js", "i18n.js"]) {
    const p = path.join(EXT, jsFile);
    if (!fs.existsSync(p)) continue;
    const src = fs.readFileSync(p, "utf8");
    for (const m of src.matchAll(/\bt\(\s*["']([A-Za-z0-9_]+)["']/g)) {
      if (!used.has(m[1])) used.set(m[1], jsFile);
    }
    for (const m of src.matchAll(/getMessage\(\s*["']([A-Za-z0-9_]+)["']/g)) {
      if (!used.has(m[1])) used.set(m[1], jsFile);
    }
  }

  for (const htmlFile of ["sidebar.html", "popup.html"]) {
    const p = path.join(EXT, htmlFile);
    if (!fs.existsSync(p)) continue;
    const src = fs.readFileSync(p, "utf8");
    for (const m of src.matchAll(/data-i18n(?:-[a-z]+)?=["']([A-Za-z0-9_]+)["']/g)) {
      if (!used.has(m[1])) used.set(m[1], htmlFile);
    }
  }

  for (const [key, file] of used) {
    if (!(key in en)) {
      failures.push(`"${key}" used in ${file} but missing from _locales/en/messages.json`);
    }
  }

  return { name: "i18n-usage", failures };
}

module.exports = { run };
