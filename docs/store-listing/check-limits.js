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

// The language count appears in ~24 places (a summary and a bullet per entry)
// and has drifted before — pricing.html once said 11 and 10 on the same page.
// Whatever the number is, every entry must agree on it.
const counts = new Map();
const countOf = (text) => {
  const m = String(text).match(
    /(\d{1,2})\s*(?:UI\s+)?(?:languages|language|dil|dilde|arayüz dili|Sprachen|langues|idiomas|языков|языка|लंगुएज|भाषा|भाषाएँ|种界面语言|種介面語言|种语言|種語言|言語|idioma|لغات|لغة)/i
  );
  return m ? m[1] : null;
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
  const n = countOf(entry.summary) || countOf(entry.description);
  if (n) counts.set(lang, n);
  console.log(
    `  ✓ ${lang}: title ${t}/${TITLE_MAX}, summary ${s}/${SUMMARY_MAX}, ` +
    `desc ${d}${n ? `, languages: ${n}` : ""}`
  );
}

const distinct = [...new Set(counts.values())];
if (distinct.length > 1) {
  const byCount = {};
  for (const [lang, n] of counts) (byCount[n] = byCount[n] || []).push(lang);
  err(
    "all",
    "entries disagree on the language count: " +
      Object.entries(byCount)
        .map(([n, langs]) => `${n} (${langs.join(",")})`)
        .join(" vs ")
  );
}

if (fail) {
  console.error(`\n${fail} problem(s).`);
  process.exit(1);
}
console.log(`\nAll ${Object.keys(listings).length} entries OK.`);
