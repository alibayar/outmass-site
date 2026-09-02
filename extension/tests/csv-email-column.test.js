/**
 * The email column is found by what it holds, not only by what it is called.
 *
 * Until 2026-09-02 the check was `lowerHeaders.indexOf("email") < 0` — an
 * exact match on five letters. "Email Address" was rejected. So were "E-mail",
 * "Work Email", "email_address", and every header written in one of the other
 * twelve languages this product ships in.
 *
 * Dhirender@quick-hire.com signed up on 2026-09-01, sent himself a test
 * within ten minutes, came back the next day with his real list, and hit this
 * twice — 12:00:17 and 12:03:38 — then stopped. He is a recruiter; his list
 * came out of a tool that writes "Email Address", which is what almost every
 * ATS and CRM export writes.
 *
 * He was the second user to be turned away at the CSV. The first churned over
 * an encoding, which is why csv-decode.test.js exists. Same wall, different
 * brick, and this file is the second brick.
 *
 * The content pass is the half that matters most: a column whose values look
 * like addresses is the address column whatever its header says. That is what
 * makes the fix work for the twelve locales nobody here can proofread.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const EXT = path.join(__dirname, "..");

function load() {
  const src = fs.readFileSync(path.join(EXT, "sidebar.js"), "utf8");
  const grab = (re, what) => {
    const m = re.exec(src);
    if (!m) throw new Error(`could not find ${what} in sidebar.js`);
    return m[0];
  };
  const code = [
    grab(/function parseCSVLine[\s\S]*?\n  \}\n/, "parseCSVLine()"),
    grab(/var EMAIL_HEADER_NAMES = \[[\s\S]*?\];\n/, "EMAIL_HEADER_NAMES"),
    grab(/var EMAIL_SHAPE = [^\n]*\n/, "EMAIL_SHAPE"),
    grab(/function normaliseHeader[\s\S]*?\n  \}\n/, "normaliseHeader()"),
    grab(/function findEmailColumn[\s\S]*?\n  \}\n/, "findEmailColumn()"),
  ].join("\n");
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx;
}

// The cases live in backend/tests/fixtures/email_column_cases.json and the
// backend suite reads the same file, so the panel's detector and the server's
// cannot drift. They did drift, for one day: this panel started accepting
// "Email Address" on 2026-09-02 while upload_contacts still demanded a header
// spelled exactly "email", which turned an accepted file into a 400 AFTER the
// campaign row existed. render_cases.json exists for the same reason on the
// body side.
const SHARED = JSON.parse(
  fs.readFileSync(
    path.join(EXT, "..", "backend", "tests", "fixtures", "email_column_cases.json"),
    "utf8"
  )
).cases.map((c) => [c.header, c.rows, c.expect, c.why]);

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  let ctx;
  try {
    ctx = load();
  } catch (e) {
    return { name: "csv-email-column", failures: [String(e.message)] };
  }

  for (const [headerLine, rows, expected, label] of SHARED) {
    const headers = ctx.parseCSVLine(headerLine).map((h) => h.trim());
    let got;
    try {
      got = ctx.findEmailColumn(headers, rows);
    } catch (e) {
      failures.push(`${label}: threw ${e.message}`);
      continue;
    }
    check(
      got === expected,
      `${label}\n      headers: ${headerLine}\n      expected column ${expected}, got ${got}`
    );
  }

  // The content pass must not be quietly deleted: it is the only reason this
  // works for a header nobody here can read.
  const src = fs.readFileSync(path.join(EXT, "sidebar.js"), "utf8");
  check(
    /EMAIL_SHAPE\.test\(/.test(src),
    "the content pass is gone — detection is back to a list of names somebody " +
      "had to think of, in a product shipping in thirteen languages"
  );
  check(
    /var emailIdx = findEmailColumn\(/.test(src),
    "ingestCsvText no longer asks findEmailColumn which column to use"
  );
  check(
    /var em = \(values\[emailIdx\] \|\| ""\)/.test(src),
    "the row loop reads the address by key again, so a column called " +
      "anything but 'email' parses as empty and every row is skipped"
  );

  return { name: "csv-email-column", failures };
}

module.exports = { run };

if (require.main === module) {
  const r = run();
  r.failures.forEach((f) => console.error("FAIL:", f));
  console.log(r.failures.length ? `${r.name}: ${r.failures.length} failure(s)` : `${r.name}: ok`);
  process.exit(r.failures.length ? 1 : 0);
}
