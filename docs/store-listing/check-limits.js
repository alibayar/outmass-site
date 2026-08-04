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

// Edge Add-ons search terms, verified against Microsoft's own docs
// (publish-extension + developer-policies 1.1.4, checked 2026-08-04):
// at most 7 terms, 30 characters each, 21 WORDS in total. Chrome has no
// equivalent field — it ranks on title/summary/description alone.
const TERMS_MAX = 7;
const TERM_CHARS_MAX = 30;
const TERMS_WORDS_MAX = 21;

// Another company's brand in our metadata is not "created by us or licensed
// from the rights holder" (Edge policy 2.2) and invites a takedown, however
// tempting the search volume. Ours and the platform we integrate with are
// fine; these are not.
const FOREIGN_BRANDS = [
  /\bgmass\b/i,
  /\bmailmeteor\b/i,
  /\byamm\b/i,
  /\byet another mail merge\b/i,
  /\bmailchimp\b/i,
  /\bsendgrid\b/i,
  /\blemlist\b/i,
  /\bwoodpecker\b/i,
  /\bapollo\.io\b/i,
  /\bsalesforce\b/i,
  /\bhubspot\b/i,
  /\bgmail\b/i,
];

// Words the product cannot deliver — a search term promising them is a
// claims-discipline break, not just a bad keyword.
const UNSUPPORTED = [/\bsmtp\b/i, /\blinkedin\b/i, /\bwhatsapp\b/i, /\bscrap(er|ing)\b/i];
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
  // ── Edge search terms (optional field; validated when present) ──
  const terms = entry.search_terms;
  if (terms) {
    if (!Array.isArray(terms)) {
      err(lang, "search_terms must be an array");
    } else {
      if (terms.length > TERMS_MAX) {
        err(lang, `${terms.length} search terms > ${TERMS_MAX}`);
      }
      const words = terms.join(" ").split(/\s+/).filter(Boolean).length;
      if (words > TERMS_WORDS_MAX) {
        err(lang, `search terms total ${words} words > ${TERMS_WORDS_MAX} (Edge rejects the submission)`);
      }
      const seen = new Set();
      for (const term of terms) {
        const len = [...term].length;
        if (len > TERM_CHARS_MAX) err(lang, `search term "${term}" is ${len} chars > ${TERM_CHARS_MAX}`);
        const key = term.trim().toLowerCase();
        if (seen.has(key)) err(lang, `duplicate search term "${term}" (Edge requires unique terms)`);
        seen.add(key);
        if (!term.trim()) err(lang, "empty search term");
        for (const re of FOREIGN_BRANDS) {
          if (re.test(term)) err(lang, `search term "${term}" contains another company's brand — Edge policy 2.2`);
        }
        for (const re of UNSUPPORTED) {
          if (re.test(term)) err(lang, `search term "${term}" promises something OutMass does not do`);
        }
      }
      console.log(`      search terms: ${terms.length}/${TERMS_MAX}, ${words}/${TERMS_WORDS_MAX} words`);
    }
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

// The paste-ready .txt files are generated from listings.json. They drifted
// three months once and still advertised claims we had removed, so treat any
// divergence as a failure rather than a nuisance.
const { render } = require("./render.js");
const descDir = path.join(__dirname, "descriptions");
if (fs.existsSync(descDir)) {
  for (const [lang, entry] of Object.entries(listings)) {
    const file = path.join(descDir, `${lang}.txt`);
    if (!fs.existsSync(file)) {
      err(lang, `descriptions/${lang}.txt missing — run: node docs/store-listing/render.js`);
      continue;
    }
    if (fs.readFileSync(file, "utf8") !== render(lang, entry)) {
      err(lang, `descriptions/${lang}.txt is out of sync — run: node docs/store-listing/render.js`);
    }
  }
  const extra = fs
    .readdirSync(descDir)
    .filter((f) => f.endsWith(".txt") && !listings[f.replace(/\.txt$/, "")]);
  for (const f of extra) {
    err("descriptions", `${f} has no entry in listings.json (stale copy — delete it)`);
  }
}

if (fail) {
  console.error(`\n${fail} problem(s).`);
  process.exit(1);
}
console.log(`\nAll ${Object.keys(listings).length} entries OK, paste files in sync.`);
