/**
 * Locale consistency — every locale must carry every key en has (and no
 * strays), with identical $PLACEHOLDER$ tokens per message.
 *
 * Why: strings are edited 11 times per change; a missed file silently falls
 * back to English for that language's users (chrome.i18n falls back to
 * default_locale). This turns "did we update all 11?" from a manual grep
 * into a failing test.
 */

const fs = require("fs");
const path = require("path");

const LOCALES_DIR = path.join(__dirname, "..", "_locales");
const REFERENCE = "en";

function loadLocale(name) {
  return JSON.parse(
    fs.readFileSync(path.join(LOCALES_DIR, name, "messages.json"), "utf8")
  );
}

function tokensOf(message) {
  return (message.match(/\$[A-Za-z_][A-Za-z0-9_]*\$/g) || []).sort().join(",");
}

function run() {
  const failures = [];
  const en = loadLocale(REFERENCE);
  const enKeys = Object.keys(en);

  const locales = fs
    .readdirSync(LOCALES_DIR)
    .filter((d) => d !== REFERENCE && fs.existsSync(path.join(LOCALES_DIR, d, "messages.json")));

  for (const loc of locales) {
    let msgs;
    try {
      msgs = loadLocale(loc);
    } catch (e) {
      failures.push(`${loc}: messages.json unparseable — ${e.message}`);
      continue;
    }
    const keys = Object.keys(msgs);

    for (const k of enKeys) {
      if (!(k in msgs)) {
        failures.push(`${loc}: missing key "${k}" (falls back to English silently)`);
      } else {
        if (!msgs[k].message || !String(msgs[k].message).trim()) {
          failures.push(`${loc}: key "${k}" has an empty message`);
        }
        if (tokensOf(en[k].message || "") !== tokensOf(msgs[k].message || "")) {
          failures.push(
            `${loc}: key "${k}" placeholder tokens differ from en ` +
            `(en: [${tokensOf(en[k].message || "")}] vs ${loc}: [${tokensOf(msgs[k].message || "")}])`
          );
        }
      }
    }
    for (const k of keys) {
      if (!(k in en)) {
        failures.push(`${loc}: stray key "${k}" not present in en`);
      }
    }
  }

  return { name: "locale-consistency", failures };
}

module.exports = { run };
