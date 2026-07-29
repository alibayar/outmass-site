#!/usr/bin/env node
// Store-listing sanity check: valid JSON, char limits, claim tripwires.
// Run: node docs/store-listing/check-limits.js
const fs = require("fs");
const path = require("path");

const file = path.join(__dirname, "listings.json");
const listings = JSON.parse(fs.readFileSync(file, "utf8"));

const TITLE_MAX = 45;
const SUMMARY_MAX = 132;
const DESC_MAX = 16000;
// Claims that were killed in audits and must never come back.
const BANNED = [
  /across time zones/i,
  /zaman dilim/i, // tr timezone claim
  /Zeitzonen/i,
  /fuseaux horaires/i,
  /zonas horarias/i,
  /часовы[ех] пояс/i,
  /المناطق الزمنية/,
  /टाइम ज़ोन/,
  /时区/,
  /タイムゾーン/,
  /fusos hor[aá]rios/i,
  /Claude/, // model name genericized 2026-07-29
];

let fail = 0;
const err = (lang, msg) => {
  console.error(`  ✗ [${lang}] ${msg}`);
  fail++;
};

for (const [lang, entry] of Object.entries(listings)) {
  for (const key of ["title", "summary", "description"]) {
    if (!entry[key] || typeof entry[key] !== "string") err(lang, `missing ${key}`);
  }
  const t = [...(entry.title || "")].length;
  const s = [...(entry.summary || "")].length;
  const d = [...(entry.description || "")].length;
  if (t > TITLE_MAX) err(lang, `title ${t} > ${TITLE_MAX} chars`);
  if (s > SUMMARY_MAX) err(lang, `summary ${s} > ${SUMMARY_MAX} chars`);
  if (d > DESC_MAX) err(lang, `description ${d} > ${DESC_MAX} chars`);
  const all = `${entry.title}\n${entry.summary}\n${entry.description}`;
  for (const re of BANNED) {
    if (re.test(all)) err(lang, `banned claim matches ${re}`);
  }
  console.log(`  ✓ ${lang}: title ${t}/${TITLE_MAX}, summary ${s}/${SUMMARY_MAX}, desc ${d}`);
}

if (fail) {
  console.error(`\n${fail} problem(s).`);
  process.exit(1);
}
console.log(`\nAll ${Object.keys(listings).length} entries OK.`);
