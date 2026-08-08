/**
 * CSV decode-chain tests — runs the REAL decodeCsvBuffer from sidebar.js
 * (extracted by source, so the test can't drift from production) against
 * fixture files in the encodings our users' Excel installs actually produce.
 *
 * Born from the 2026-07-14 incident: a zh-CN user's GBK CSV was rejected 7
 * times with a message that didn't say how to fix it, and they churned.
 * Widened 2026-08-08 after two more losses that were not CJK at all: a user
 * in Poland on a ru-locale browser, and a paying customer in SA/AE rejected
 * 32 times across three sessions whose browser UI was en-US — the file was
 * Arabic and only Accept-Language ever said so.
 *
 * The adversarial review of that first draft found three ways it silently
 * corrupted files 0.1.27 had safely rejected. Most of the assertions below
 * exist because of those, and they are written as "must REJECT", which is an
 * unusual thing to want from a decoder. That is the point: for this function
 * a rejection is a bad afternoon and a wrong decode is someone else's inbox.
 *
 * Invariants locked here:
 *  1. UTF-8 (with or without BOM) always decodes exactly, as 'utf-8'.
 *  2. GBK/GB18030 decodes with names intact under EVERY UI language — no
 *     codepage added for one locale may steal it from another.
 *  3. A script codepage is used only when it comes from this user's own
 *     languages AND is the only one of them that fits.
 *  4. No Latin codepage is ever used, and no script codepage may claim a
 *     Latin file either — both are refused outright. A wrong table is
 *     undetectable by inspection, so the changelog promises those users a
 *     refusal rather than a guess, and these assertions are what make that
 *     promise true.
 *  5. Every decode a codepage claims must show that script in RUNS. Real
 *     writing does; a diacritic misread through the wrong table stands alone
 *     between ASCII letters. Neither a volume threshold nor an in-block
 *     ratio separates them — both read identically on a German list under
 *     windows-1251.
 *  6. For EVERY accepted decode the ASCII email column survives byte-exact.
 *  7. Undecodable input returns null, and never throws.
 *
 * Fixtures: tests/fixtures/*.csv — regenerate with the python one-liner in
 * fixtures/README.md if the set ever needs to change.
 */

const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "sidebar.js"), "utf8");

function makeDecoder() {
  const m = SRC.match(/function decodeCsvBuffer\(buf, langs, diag\) \{[\s\S]*?\n {4}\}/);
  if (!m) {
    throw new Error(
      "Could not extract decodeCsvBuffer from sidebar.js — if the function " +
      "moved, was renamed, or changed signature, update this test's regex."
    );
  }
  const chromeStub = { i18n: { getUILanguage: () => "en-US" } };
  // eslint-disable-next-line no-new-func
  return new Function("chrome", "TextDecoder", "return " + m[0])(chromeStub, TextDecoder);
}

// Encode text into a legacy codepage by inverting TextDecoder — lets a test
// build a realistic Polish/Turkish/Hebrew list without adding a binary
// fixture for every script.
function encodeIn(text, encoding) {
  const bytes = new Uint8Array(256);
  for (let i = 0; i < 256; i++) bytes[i] = i;
  const chars = new TextDecoder(encoding).decode(bytes);
  const rev = new Map();
  for (let i = 0; i < 256; i++) if (!rev.has(chars[i])) rev.set(chars[i], i);
  const out = [];
  for (const ch of text) {
    if (!rev.has(ch)) throw new Error(`${ch} is not representable in ${encoding}`);
    out.push(rev.get(ch));
  }
  return new Uint8Array(out).buffer;
}

function emailsIntact(text) {
  const lines = text.trim().split(/\r?\n/).slice(1);
  return lines.every((line) => {
    const cells = line.split(",");
    return cells.length >= 2 && /^[a-z-]+@e(xample)?\.co(m)?$/.test(cells[cells.length - 1].trim());
  });
}

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  try {
    for (const e of ["gb18030", "big5", "windows-1250", "windows-1251",
                     "windows-1253", "windows-1254", "windows-1255", "windows-1256"]) {
      new TextDecoder(e);
    }
  } catch (e) {
    return {
      name: "csv-decode",
      failures: ["Node lacks full ICU (legacy decoders unavailable) — use an official Node build"],
    };
  }

  const decode = makeDecoder();
  const fx = (f) => new Uint8Array(fs.readFileSync(path.join(__dirname, "fixtures", f))).buffer;
  const enc = (t, e) => encodeIn(t, e);

  const POLISH = "name,email\nŁukasz Wójcik,l@e.co\nMałgorzata Nowak,m@e.co\n" +
                 "Grażyna Wiśniewska,g@e.co\n";
  const TURKISH = "name,email\nAyşe Yılmaz,a@e.co\nÇağrı Öztürk,c@e.co\n";
  const GERMAN = "name,email\nJürgen Müller,j@e.co\nKäthe Schröder,k@e.co\n";
  const HEBREW = "name,email\nדניאל לוי,d@e.co\n" +
                 "שרה כהן,s@e.co\n";
  const GREEK = "name,email\nΓιώργος " +
                "Παπαδόπουλος,g@e.co\n";

  // ── 1-3. UTF-8 in its three shapes ──
  const utf8 = decode(fx("utf8.csv"), ["en-US"]);
  check(utf8 && utf8.encoding === "utf-8", "utf8.csv must decode as utf-8");
  check(utf8 && utf8.text.includes("张伟") && utf8.text.includes("Ayşe Yılmaz"),
    "utf8.csv names must round-trip exactly");

  const bom = decode(fx("utf8-bom.csv"), ["en-US"]);
  check(bom && bom.encoding === "utf-8", "utf8-bom.csv must decode as utf-8");
  check(bom && bom.text.charCodeAt(0) !== 0xfeff && bom.text.startsWith("name,email"),
    "utf8-bom.csv BOM must be stripped");

  check((decode(fx("ascii.csv"), ["ru-RU"]) || {}).encoding === "utf-8",
    "a pure-ASCII file is utf-8 under any locale");

  // ── 4. The 2026-07-14 case, under every locale ──
  // A codepage added to serve one language must never claim another
  // language's file. The first draft failed this for tr and pl (windows-1254
  // and windows-1250 claimed GBK) and for ja and ko (shift_jis and euc-kr
  // claimed GBK, turning 张伟 into ﾕﾅﾎｰ).
  for (const ui of ["en-US", "tr-TR", "pl-PL", "ja-JP", "ko-KR", "zh-CN", "de-DE", "fr-FR"]) {
    const out = decode(fx("gbk.csv"), [ui]);
    check(out && out.encoding === "gb18030",
      `gbk.csv under ${ui} must stay gb18030, got ${out && out.encoding}`);
    check(out && out.text.includes("张伟") && out.text.includes("李娜"),
      `gbk.csv under ${ui} must keep its Chinese names`);
  }
  // Big5-before-gb18030 must be decided from the WHOLE evidence list. Reading
  // only its first entry made the ordering depend on Settings → Interface
  // Language, so a Taiwan user who set the panel to English had their Big5
  // list decoded as gb18030 — a regression against 0.1.27, which read
  // chrome.i18n.getUILanguage() directly and could not be overridden.
  for (const langs of [["zh-TW"], ["en", "zh-TW"], ["ja", "zh-HK"]]) {
    const out = decode(fx("big5.csv"), langs);
    check(out && out.encoding === "big5",
      `big5 ordering under ${JSON.stringify(langs)}, got ${out && out.encoding}`);
  }

  // ── 4b. The one collision that is NOT fixed, asserted so it stays visible ──
  // A script locale's own codepage is tried BEFORE gb18030, and it has to
  // be: gb18030 accepts a Cyrillic file (its bytes form valid two-byte GBK
  // pairs) and it accepts the Arabic one too, so probing it first loses both
  // of the users this change exists for. The cost is the mirror image — a
  // Russian- or Arabic-locale user who uploads a CHINESE list gets their own
  // script's mojibake where 0.1.27 decoded it correctly.
  //
  // Accepted deliberately, because the two populations are not comparable in
  // size: almost every Russian-locale user's list is Russian. Asserted here
  // rather than left as a surprise — if this ever needs to change, the fix
  // is a confirmation step, not a reordering, because reordering simply
  // moves the loss to the larger group.
  for (const ui of ["ru-RU", "ar-SA"]) {
    const out = decode(fx("gbk.csv"), [ui]);
    check(out && out.encoding !== "gb18030",
      `KNOWN: a CJK file under ${ui} is claimed by that locale's codepage; ` +
      `if this now returns gb18030 the ordering changed and cp1251/cp1256 ` +
      `users have silently lost their fix (got ${out && out.encoding})`);
    check(out && emailsIntact(out.text),
      `even in the collision case, ${ui} must not corrupt the email column`);
  }

  // ── 5. The two confirmed losses this change exists for ──
  const ru = decode(fx("cp1251.csv"), ["ru-RU"]);
  check(ru && ru.encoding === "windows-1251",
    `Cyrillic file for a Russian user, got ${ru && ru.encoding}`);
  check(ru && ru.text.includes("Иван Петров"),
    "the Russian names must be intact");

  // The paying customer: browser UI is English, the data is Arabic. Only
  // Accept-Language carries that fact, which is why it is consulted at all.
  const ar = decode(fx("cp1256.csv"), ["en-US", "en-US", "ar"]);
  check(ar && ar.encoding === "windows-1256",
    `Arabic file for an Arabic user, got ${ar && ar.encoding}`);
  check(ar && ar.text.includes("محمد أحمد"),
    "the Arabic names must be intact");

  // The panel's own Interface Language outranks the browser UI language: an
  // English browser with the panel set to Russian is a person telling us,
  // inside this product, which language they work in.
  const panelOverride = decode(fx("cp1251.csv"), ["ru", "en-US"]);
  check(panelOverride && panelOverride.encoding === "windows-1251",
    `panel language must win over browser UI, got ${panelOverride && panelOverride.encoding}`);

  // ...but a language the user merely READS is not a licence to pick a
  // decoder, and this assertion is why. The paying customer whose browser is
  // English and whose data is Arabic is deliberately NOT served here:
  // consulting Accept-Language put windows-1251 in the chain for anyone with
  // "ru" anywhere in it, where it claimed a German list and rendered
  // "Jürgen Müller" as "Jьrgen Mьller" — Latin-looking mojibake, which is
  // worse than the obvious kind because the preview stops catching it.
  // That user is served by asking. See the encoding-confirmation design.
  const arEnglishBrowser = decode(fx("cp1256.csv"), ["en-US"]);
  check(!arEnglishBrowser || arEnglishBrowser.encoding !== "windows-1256",
    "no script codepage without evidence from the user's OWN language");

  check((decode(enc(HEBREW, "windows-1255"), ["he-IL"]) || {}).encoding === "windows-1255",
    "Hebrew file for a Hebrew user");
  check((decode(enc(GREEK, "windows-1253"), ["el-GR"]) || {}).encoding === "windows-1253",
    "Greek file for a Greek user");

  // ── 5b. gb18030 and big5 must prove they are reading CJK ──
  // They have been terminal catch-alls since 0.1.24, gated only on "no
  // U+FFFD". That accepted European files with DATA LOSS, not just mojibake:
  // gb18030 pairs a single high byte with the following ASCII letter, so
  // "Łukasz" came out as "kasz" — the u was eaten — and the changelog
  // claimed those users were being asked to re-save instead.
  //
  // The gate is a run of 2+ ADJACENT CJK characters, and it has to be
  // adjacency rather than a ratio. Measured: Polish is 5.8% non-ASCII and
  // 83% CJK-block, the diluted Chinese file below is 1.3% non-ASCII — a
  // ratio rule accepts the wrong one and rejects the right one.
  for (const [label, buf] of [
    ["Polish cp1250", enc(POLISH, "windows-1250")],
    ["German cp1252", enc(GERMAN, "windows-1252")],
  ]) {
    for (const langs of [["en-US"], ["pl-PL"], ["de-DE"]]) {
      const out = decode(buf, langs);
      check(!out || out.encoding !== "gb18030",
        `${label} under ${langs[0]} must not be swallowed by gb18030 ` +
        `(got ${out && out.encoding})`);
    }
  }
  const diluted = decode(fx("gbk-diluted.csv"), ["en-US"]);
  check(diluted && diluted.encoding === "gb18030",
    `a real Chinese list that is only 1.3% non-ASCII must still decode, got ` +
    `${diluted && diluted.encoding} — this is the case a ratio rule breaks`);
  check(diluted && diluted.text.includes("张伟") && diluted.text.includes("李娜"),
    "the two Chinese names in the diluted list must be intact");

  // ── 6. No Latin codepage, ever. This is the blocker the review found ──
  // windows-1250/1252/1254/1257/1258 accept literally any byte sequence, and
  // a contact list is only 4-12% non-ASCII because the email column dilutes
  // it, so no volume rule can catch a wrong pick. The first draft turned
  // "Ayşe Yılmaz" into "Ayþe Yýlmaz" and shipped it to the merge field.
  const latinCases = [
    ["Turkish cp1254", enc(TURKISH, "windows-1254"), ["tr-TR"]],
    ["Turkish cp1254, English UI", enc(TURKISH, "windows-1254"), ["en-US"]],
    ["Polish cp1250", enc(POLISH, "windows-1250"), ["pl-PL"]],
    ["Western cp1252", enc(GERMAN, "windows-1252"), ["de-DE"]],
    ["Western fixture, English UI", fx("cp1252.csv"), ["en-US"]],
    ["Western fixture, Russian UI", fx("cp1252.csv"), ["ru-RU"]],
  ];
  for (const [label, buf, langs] of latinCases) {
    const out = decode(buf, langs);
    check(out === null, (
      `${label} must be REFUSED, got ${out && out.encoding}. Not "claimed by ` +
      `something harmless" — refused. The changelog tells these users we would ` +
      `rather not guess than put a mangled name in an email, and a decode by ` +
      `any table at all makes that untrue`
    ));
  }

  // The same rule that stops gb18030 swallowing them stops windows-1251 too.
  // A script codepage scored 100% inScript on a German list — the tables map
  // nearly the whole high range into their own block — so only the run test
  // separates them: real writing comes in runs, a misread diacritic stands
  // alone between ASCII letters.
  for (const [label, text, cp] of [
    ["Polish", POLISH, "windows-1250"],
    ["German", GERMAN, "windows-1252"],
    ["Turkish", TURKISH, "windows-1254"],
  ]) {
    for (const langs of [["ru-RU"], ["el-GR"], ["he-IL"], ["ar-SA"]]) {
      const out = decode(enc(text, cp), langs);
      check(out === null,
        `a ${label} list must not be read as ${langs[0]}'s script ` +
        `(got ${out && out.encoding})`);
    }
  }

  // ...while a real file in that script still decodes, including one that is
  // mostly ASCII. A volume floor used to guard this branch and it rejected
  // exactly this shape.
  const dilutedCyrillic = enc(
    "name,company,city,email\n" +
    "Иван Петров,Acme Corporation Limited,Moscow,ivan@example.com\n" +
    "John Smith,Widgets Incorporated,London,john@example.com\n" +
    "Anna Brown,Southern Logistics Inc,Bristol,anna@example.com\n",
    "windows-1251"
  );
  const dc = decode(dilutedCyrillic, ["ru-RU"]);
  check(dc && dc.encoding === "windows-1251",
    `a mostly-ASCII list with one Russian name must decode, got ${dc && dc.encoding}`);
  check(dc && dc.text.includes("Иван Петров"),
    "the Russian name in the diluted list must be intact");

  // ── 7. A file in a script the user does not claim ──
  // These tables map nearly the whole high range into their own block, so a
  // Hebrew file scores a perfect 1.00 as windows-1251 too. The previous draft
  // tried to resolve that by rejecting when two of the user's scripts fitted
  // — but "reject" was written as `continue`, so it fell through to gb18030
  // and returned Chinese mojibake instead. That assertion was written as
  // `!encoding.startsWith("windows-")`, which gb18030 satisfies, so the test
  // passed while producing exactly what it existed to prevent. Only one
  // script codepage can be a candidate now, and this asserts the encoding by
  // name rather than by prefix.
  const crossScript = [
    ["Hebrew file, Russian user", enc(HEBREW, "windows-1255"), ["ru-RU"]],
    ["Greek file, Russian user", enc(GREEK, "windows-1253"), ["ru-RU"]],
    ["Arabic file, Hebrew user", fx("cp1256.csv"), ["he-IL"]],
  ];
  for (const [label, buf, langs] of crossScript) {
    const out = decode(buf, langs);
    check(!out || emailsIntact(out.text),
      `${label}: whatever claims it, the addresses must survive (got ${out && out.encoding})`);
  }

  // ── 8. A few accented letters are not evidence of a script ──
  // The Western fixture is 3.8% non-ASCII and every one of those characters
  // lands in the Cyrillic block under windows-1251. Without the 5% floor the
  // check "confirmed" itself and every Russian-locale user got Josй Muсoz.
  const westernForRu = decode(fx("cp1252.csv"), ["ru-RU"]);
  check(!westernForRu || westernForRu.encoding !== "windows-1251",
    `5% floor: got ${westernForRu && westernForRu.encoding}`);

  // ── 9. The safety floor: addresses survive whatever happens ──
  const everything = ["big5.csv", "shift_jis.csv", "cp1251.csv", "cp1254.csv",
                      "cp1256.csv", "cp1252.csv", "gbk.csv", "utf8.csv"];
  for (const langs of [["en-US"], ["ru-RU", "ru", "ar"], ["tr-TR"], ["ar-SA", "ar", "en"],
                       ["zh-TW"], ["he-IL", "he", "ru"], []]) {
    for (const f of everything) {
      let out;
      try {
        out = decode(fx(f), langs);
      } catch (e) {
        failures.push(`${f} under ${JSON.stringify(langs)} threw: ${e.message}`);
        continue;
      }
      if (out) {
        check(emailsIntact(out.text),
          `${f} under ${JSON.stringify(langs)} accepted (${out.encoding}) but emails corrupted`);
      }
    }
  }

  // ── 10. Garbage, and a byte that is undefined in the chosen table ──
  for (const langs of [["en-US"], ["ru-RU", "ar"], ["he-IL"]]) {
    let out;
    try {
      out = decode(fx("garbage.bin.csv"), langs);
    } catch (e) {
      failures.push(`garbage under ${JSON.stringify(langs)} threw: ${e.message}`);
      continue;
    }
    check(out === null, `garbage must be rejected, got ${out && out.encoding}`);
  }

  // 0x81 is undefined in windows-1251 and WHATWG maps it to the C1 control
  // U+0081, which no real text contains — proof the table is wrong.
  const asciiOf = (s) => [...s].map((c) => c.charCodeAt(0));
  const c1Buf = new Uint8Array([
    ...asciiOf("name,email\n"), 0x81, 0x2c, 0x20, ...asciiOf("x@e.co\n"),
  ]).buffer;
  check(decode(c1Buf, ["ru-RU"]) === null,
    "a C1 control means the wrong codepage — must reject");

  return { name: "csv-decode", failures };
}

module.exports = { run };
