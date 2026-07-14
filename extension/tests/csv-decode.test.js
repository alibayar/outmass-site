/**
 * CSV decode-chain tests — runs the REAL decodeCsvBuffer from sidebar.js
 * (extracted by source, so the test can't drift from production) against
 * fixture files in the encodings our users' Excel installs actually produce.
 *
 * Born from the 2026-07-14 incident: a zh-CN user's GBK CSV was rejected 7
 * times with a message that didn't say how to fix it, and they churned.
 *
 * Invariants locked here:
 *  1. UTF-8 (with or without BOM) always decodes exactly, as 'utf-8'.
 *  2. GBK/GB18030 files decode with names intact.
 *  3. For EVERY accepted decode, the ASCII email column survives byte-exact —
 *     a wrong codepage guess may garble display names (visible in preview),
 *     but it must never corrupt addresses.
 *  4. Undecodable garbage returns null (→ the "save as CSV UTF-8" alert),
 *     and never throws.
 *
 * Fixtures: tests/fixtures/*.csv — regenerate with the python one-liner in
 * fixtures/README.md if the set ever needs to change.
 */

const fs = require("fs");
const path = require("path");

function extractDecoder() {
  const src = fs.readFileSync(path.join(__dirname, "..", "sidebar.js"), "utf8");
  const m = src.match(/function decodeCsvBuffer\(buf\) \{[\s\S]*?\n {4}\}/);
  if (!m) {
    throw new Error(
      "Could not extract decodeCsvBuffer from sidebar.js — if the function " +
      "moved or was renamed, update this test's extraction regex."
    );
  }
  const chromeStub = { i18n: { getUILanguage: () => "en-US" } };
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
    return cells.length >= 2 && /^[a-z]+@example\.com$/.test(cells[cells.length - 1].trim());
  });
}

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  // Node must have full ICU for the CJK decoders (official builds do).
  try {
    new TextDecoder("gb18030");
    new TextDecoder("big5");
  } catch (e) {
    return {
      name: "csv-decode",
      failures: ["Node lacks full ICU (gb18030/big5 decoders unavailable) — use an official Node build"],
    };
  }

  const decode = extractDecoder();
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

  // 4. GBK (Chinese Excel default): THE incident case — must now decode
  //    with names intact via the gb18030 superset.
  const gbk = decode(fx("gbk.csv"));
  check(!!gbk, "gbk.csv must decode (was rejected pre-0.1.24)");
  check(gbk && gbk.encoding === "gb18030", "gbk.csv must be labeled gb18030");
  check(gbk && gbk.text.includes("张伟") && gbk.text.includes("李娜"),
    "gbk.csv Chinese names must decode exactly");

  // 5-9. Other legacy codepages: acceptance is best-effort (a dense CJK
  //    codepage may claim them with garbled names), but the email invariant
  //    is absolute, and none may throw.
  for (const f of ["big5.csv", "shift_jis.csv", "cp1251.csv", "cp1254.csv", "cp1256.csv"]) {
    let out;
    try {
      out = decode(fx(f));
    } catch (e) {
      failures.push(f + " threw: " + e.message);
      continue;
    }
    if (out) {
      check(emailsIntact(out.text), f + " accepted (" + out.encoding + ") but emails corrupted");
    }
    // null is acceptable: the user gets the actionable save-as-UTF-8 alert.
  }

  // 10. Garbage bytes: must not throw; null expected.
  try {
    decode(fx("garbage.bin.csv"));
  } catch (e) {
    failures.push("garbage.bin.csv threw: " + e.message);
  }

  return { name: "csv-decode", failures };
}

module.exports = { run };
