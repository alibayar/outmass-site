/**
 * CSV decode-chain tests — runs the REAL decodeCsvBuffer from sidebar.js
 * (extracted by source, so the test can't drift from production) against
 * fixture files in the encodings our users' Excel installs actually produce.
 *
 * Born from the 2026-07-14 incident: a zh-CN user's GBK CSV was rejected 7
 * times with a message that didn't say how to fix it, and they churned.
 * Widened 2026-08-08 after two more confirmed losses that were not CJK at
 * all: a user in Poland on a ru-locale browser, and a PAYING customer in
 * SA/AE rejected ~40 times across three sessions whose browser UI language
 * was en-US — the file was Arabic and only Accept-Language ever said so.
 *
 * Invariants locked here:
 *  1. UTF-8 (with or without BOM) always decodes exactly, as 'utf-8'.
 *  2. GBK/GB18030 files decode with names intact — under ANY UI language,
 *     because a Latin catch-all placed too early would silently undo it.
 *  3. A codepage the UI language names decodes that language's file.
 *  4. A codepage taken from Accept-Language is used ONLY when the decode
 *     really lands in that script — reading Arabic must not corrupt a
 *     French file.
 *  5. For EVERY accepted decode, the ASCII email column survives byte-exact —
 *     a wrong codepage guess may garble display names (visible in preview),
 *     but it must never corrupt addresses.
 *  6. Undecodable garbage returns null (→ the "save as CSV UTF-8" alert),
 *     and never throws.
 *
 * Fixtures: tests/fixtures/*.csv — regenerate with the python one-liner in
 * fixtures/README.md if the set ever needs to change.
 */

const fs = require("fs");
const path = require("path");

function extractDecoder(uiLanguage) {
  const src = fs.readFileSync(path.join(__dirname, "..", "sidebar.js"), "utf8");
  const m = src.match(/function decodeCsvBuffer\(buf, extraLangs\) \{[\s\S]*?\n {4}\}/);
  if (!m) {
    throw new Error(
      "Could not extract decodeCsvBuffer from sidebar.js — if the function " +
      "moved, was renamed, or changed signature, update this test's regex."
    );
  }
  const chromeStub = { i18n: { getUILanguage: () => uiLanguage || "en-US" } };
  // eslint-disable-next-line no-new-func
  return new Function("chrome", "TextDecoder", "return " + m[0])(
    chromeStub,
    TextDecoder
  );
}

function emailsIntact(text) {
  // Every data row's email cell must be pure, uncorrupted ASCII.
  const lines = text.trim().split(/\r?\n/).slice(1);
  return lines.every((line) => {
    const cells = line.split(",");
    return cells.length >= 2 && /^[a-z-]+@example\.com$/.test(cells[cells.length - 1].trim());
  });
}

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  // Node must have full ICU for the non-Latin decoders (official builds do).
  try {
    for (const enc of ["gb18030", "big5", "windows-1251", "windows-1256", "windows-1254"]) {
      new TextDecoder(enc);
    }
  } catch (e) {
    return {
      name: "csv-decode",
      failures: ["Node lacks full ICU (legacy decoders unavailable) — use an official Node build"],
    };
  }

  const decode = extractDecoder("en-US");
  const fx = (f) => new Uint8Array(fs.readFileSync(path.join(__dirname, "fixtures", f))).buffer;

  // 1. Plain UTF-8: exact round-trip, correct label.
  const utf8 = decode(fx("utf8.csv"));
  check(utf8 && utf8.encoding === "utf-8", "utf8.csv must decode as utf-8");
  check(utf8 && utf8.text.includes("张伟") && utf8.text.includes("Ayşe Yılmaz"),
    "utf8.csv names must round-trip exactly");

  // 2. UTF-8 with BOM: decodes, BOM never leaks into the header row.
  const bom = decode(fx("utf8-bom.csv"));
  check(bom && bom.encoding === "utf-8", "utf8-bom.csv must decode as utf-8");
  check(bom && bom.text.charCodeAt(0) !== 0xfeff && bom.text.startsWith("name,email"),
    "utf8-bom.csv BOM must be stripped");

  // 3. Pure ASCII: trivially utf-8.
  const ascii = decode(fx("ascii.csv"));
  check(ascii && ascii.encoding === "utf-8", "ascii.csv must decode as utf-8");

  // 4. GBK (Chinese Excel default): THE 2026-07-14 case — must decode with
  //    names intact via the gb18030 superset, under the DEFAULT en-US UI.
  //    This is the regression guard for the whole 2026-08-08 widening: any
  //    Latin fallback that drifts ahead of gb18030 breaks it here first.
  const gbk = decode(fx("gbk.csv"));
  check(!!gbk, "gbk.csv must decode (was rejected pre-0.1.24)");
  check(gbk && gbk.encoding === "gb18030", "gbk.csv must be labeled gb18030");
  check(gbk && gbk.text.includes("张伟") && gbk.text.includes("李娜"),
    "gbk.csv Chinese names must decode exactly");

  // 5. Western European with a few stray high bytes — accented names and a
  //    Word smart quote. Rejected outright until 0.1.28: UTF-8 fails on the
  //    lone high byte and both CJK probes fail on the trail byte.
  const cp1252 = decode(fx("cp1252.csv"));
  check(cp1252 && cp1252.encoding === "windows-1252",
    "cp1252.csv must decode as windows-1252, got " + (cp1252 && cp1252.encoding));
  check(cp1252 && cp1252.text.includes("José Muñoz") && cp1252.text.includes("Zoë O’Brien"),
    "cp1252.csv accented names and smart quote must decode exactly");

  // 6. The user's own UI language names the codepage. Each of these was a
  //    hard invalid_encoding rejection before 0.1.28.
  const localeCases = [
    ["ru-RU", "cp1251.csv", "windows-1251", ["Иван Петров"]],
    ["tr-TR", "cp1254.csv", "windows-1254", ["Ayşe Yılmaz", "Çağrı Öztürk"]],
    ["ar-SA", "cp1256.csv", "windows-1256", ["محمد أحمد"]],
  ];
  for (const [ui, file, expected, names] of localeCases) {
    const out = extractDecoder(ui)(fx(file));
    check(out && out.encoding === expected,
      file + " under " + ui + " must decode as " + expected + ", got " + (out && out.encoding));
    for (const n of names) {
      check(out && out.text.includes(n), file + " under " + ui + " must contain " + n);
    }
  }

  // 7. Accept-Language rescues the case the UI language cannot see: the
  //    paying customer running Chrome in English and uploading Arabic.
  const arViaAccept = extractDecoder("en-US")(fx("cp1256.csv"), ["en-US", "ar"]);
  check(arViaAccept && arViaAccept.encoding === "windows-1256",
    "cp1256.csv with Accept-Language ar must decode as windows-1256, got " +
    (arViaAccept && arViaAccept.encoding));
  check(arViaAccept && arViaAccept.text.includes("محمد أحمد"),
    "Accept-Language decode must produce the real Arabic names");

  // 8. …and must not COST anything to a bilingual user with a Western file.
  //    windows-1256 keeps é/à/ç where windows-1252 has them and turns the
  //    rest into Arabic letters, so without the script check it would claim
  //    this file and quietly mangle two of the four names.
  const frViaAr = extractDecoder("en-US")(fx("cp1252.csv"), ["en-US", "ar"]);
  check(frViaAr && frViaAr.encoding === "windows-1252",
    "a Western file must stay windows-1252 for an Arabic-reading user, got " +
    (frViaAr && frViaAr.encoding));
  check(frViaAr && frViaAr.text.includes("José Muñoz"),
    "the Arabic-reading user's Western names must be intact");

  // 9. A Latin-locale user must not lose the 2026-07-14 fix. windows-1254
  //    and windows-1250 accept any byte sequence, so placed ahead of the
  //    CJK probes they claimed EVERY fixture — GBK included — for Turkish
  //    and Polish users. This is the assertion that caught that.
  for (const ui of ["tr-TR", "pl-PL", "en-US"]) {
    const out = extractDecoder(ui)(fx("gbk.csv"));
    check(out && out.encoding === "gb18030",
      "gbk.csv under " + ui + " must stay gb18030, got " + (out && out.encoding));
    check(out && out.text.includes("张伟"),
      "gbk.csv under " + ui + " must keep its Chinese names");
  }

  // 10. Four accented letters are not evidence of a script. The Western
  //     fixture is 3.8% non-ASCII and every one of those characters lands
  //     in the Cyrillic block under windows-1251, so without a minimum
  //     volume of evidence the coherence check "confirmed" it and every
  //     Russian-locale user got Josй Muсoz.
  const westernForRu = extractDecoder("ru-RU")(fx("cp1252.csv"));
  check(westernForRu && westernForRu.encoding === "windows-1252",
    "a Western file must stay windows-1252 for a Russian user, got " +
    (westernForRu && westernForRu.encoding));
  check(westernForRu && westernForRu.text.includes("José Muñoz"),
    "the Russian user's Western names must be intact");

  // 11. Two branches no fixture can reach, so they are built here.
  //
  //     (a) Heavily non-Latin bytes that every multi-byte decoder must
  //         reject (each high byte is followed by a comma, which is not a
  //         valid trail byte). The Latin codepages would happily claim it —
  //         windows-1254 renders it "À, Á, Â, Ã…" — and only the
  //         mostly-ASCII rule stops them.
  const asciiOf = (s) => [...s].map((c) => c.charCodeAt(0));
  const cyrillicHeavy = [...asciiOf("name,email\n")];
  for (const b of [0xc0, 0xc1, 0xc2, 0xc3, 0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9]) {
    cyrillicHeavy.push(b, 0x2c, 0x20);
  }
  cyrillicHeavy.push(...asciiOf("x@e.co\n"));
  const cyrBuf = new Uint8Array(cyrillicHeavy).buffer;

  check(extractDecoder("ru-RU")(cyrBuf) !== null,
    "a Cyrillic-reading user must be able to read a Cyrillic file");
  for (const ui of ["tr-TR", "pl-PL", "en-US"]) {
    const out = extractDecoder(ui)(cyrBuf);
    check(out === null,
      "a 40%-non-ASCII file must be rejected under " + ui +
      ", not claimed by a Latin codepage (got " + (out && out.encoding) + ")");
  }

  //     (b) A byte that is UNDEFINED in windows-1252 (0x81). WHATWG maps it
  //         to the C1 control U+0081, which no real text contains — so its
  //         presence proves the table is wrong. The file is otherwise
  //         mostly ASCII, so the volume rule alone would have accepted it.
  const c1Buf = new Uint8Array(
    [...asciiOf("name,email\n"), 0x81, 0x2c, 0x20, ...asciiOf("x@e.co\n")]
  ).buffer;
  for (const ui of ["en-US", "tr-TR"]) {
    check(extractDecoder(ui)(c1Buf) === null,
      "a C1 control means the wrong codepage — must reject under " + ui);
  }

  // 12. The safety floor, stated as a rule rather than a hope: whatever any
  //    of these files is claimed by, under any UI language, addresses are
  //    untouched and nothing throws.
  const files = ["big5.csv", "shift_jis.csv", "cp1251.csv", "cp1254.csv", "cp1256.csv", "cp1252.csv"];
  for (const ui of ["en-US", "ru-RU", "tr-TR", "ar-SA", "zh-CN", "zh-TW"]) {
    const d = extractDecoder(ui);
    for (const f of files) {
      let out;
      try {
        out = d(fx(f), ["en-US", "ar", "ru"]);
      } catch (e) {
        failures.push(f + " under " + ui + " threw: " + e.message);
        continue;
      }
      if (out) {
        check(emailsIntact(out.text),
          f + " under " + ui + " accepted (" + out.encoding + ") but emails corrupted");
      }
      // null is acceptable: the user gets the actionable save-as-UTF-8 alert.
    }
  }

  // 13. Garbage bytes: must not throw, and must not be claimed by the Latin
  //     fallback either — 200 random high bytes are not a Western CSV.
  for (const ui of ["en-US", "ru-RU", "ar-SA"]) {
    let out;
    try {
      out = extractDecoder(ui)(fx("garbage.bin.csv"), ["ar", "ru"]);
    } catch (e) {
      failures.push("garbage.bin.csv under " + ui + " threw: " + e.message);
      continue;
    }
    check(!out || out.encoding !== "windows-1252",
      "garbage must never be claimed as windows-1252 (got " + (out && out.encoding) + ")");
  }

  return { name: "csv-decode", failures };
}

module.exports = { run };
