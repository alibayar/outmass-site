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

// [header line, data lines, expected index, what it is]
const CASES = [
  ["email,firstName", ["a@b.com,Ada"], 0,
   "the plain case that already worked — it must keep working"],

  ["Email Address,First Name", ["a@b.com,Ada", "c@d.com,Bo", "e@f.com,Cy"], 0,
   "what an ATS or CRM export writes, and what turned Dhirender away twice"],
  ["First Name,E-mail", ["Ada,a@b.com", "Bo,c@d.com", "Cy,e@f.com"], 1,
   "hyphenated, and not the first column"],
  ["name,work_email", ["Ada,a@b.com", "Bo,c@d.com", "Cy,e@f.com"], 1,
   "underscored"],
  ["Name,EMAIL ADDRESS", ["Ada,a@b.com", "Bo,c@d.com", "Cy,e@f.com"], 1,
   "shouting, with a space"],

  ["Ad,Soyad,Eposta", ["Ada,X,a@b.com", "Bo,Y,c@d.com", "Cy,Z,e@f.com"], 2,
   "Turkish header — no name list would have had this"],
  ["姓名,邮箱", ["Ada,a@b.com", "Bo,c@d.com", "Cy,e@f.com"], 1,
   "Chinese header, found from the data"],
  ["الاسم,البريد", ["Ada,a@b.com", "Bo,c@d.com", "Cy,e@f.com"], 1,
   "Arabic header, found from the data"],

  ["name,note", ["Ada,hello", "Bo,world", "Cy,test"], -1,
   "no email column at all — this must still be refused"],
  ["name,note", ["Ada,ask info@x.com", "Bo,world", "Cy,test"], -1,
   "one stray address in a notes field is not an email column"],
  ["name,email", ["Ada,", "Bo,", "Cy,"], 1,
   "named correctly but empty — the name pass answers before the data does"],

  // These three exist because the content pass shadowed the name pass: every
  // header case was being solved by the data, so a mutation gutting the name
  // list changed nothing any test could see. Each of these has data the
  // content pass cannot read, so only the name pass can answer.
  ["name,E-mail", ["Ada,", "Bo,", "Cy,"], 1,
   "hyphenated AND empty — only header normalisation can find this"],
  ["First Name,Email Address", ["Ada,", "Bo,", "Cy,"], 1,
   "the ATS spelling with no data to fall back on"],

  // And this one exists because "most of the column" was untested: a single
  // address among several values must not win the column.
  ["name,notes", ["Ada,a@b.com", "Bo,called them", "Cy,no answer", "Dee,left vm"],
   -1, "one address in four is a notes field, not an email column"],

  // The content pass needs something to corroborate. With one or two rows a
  // single address could equally be a note, a referrer or an assistant's
  // address, and guessing wrong sends the campaign to the wrong column. Two
  // rows with an unrecognised header is therefore refused ON PURPOSE — the
  // name list covers the spellings people actually use, and the user gets the
  // "no email column" message with the example CSV rather than a silent
  // mis-parse. Pinned so the floor is a decision rather than a leftover.
  ["name,contacto", ["Ada,a@b.com", "Bo,c@d.com"], -1,
   "two rows is not enough to name a column from its contents"],
  ["name,contacto", ["Ada,a@b.com", "Bo,c@d.com", "Cy,e@f.com"], 1,
   "three is — the row above and this one are the boundary"],
];

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  let ctx;
  try {
    ctx = load();
  } catch (e) {
    return { name: "csv-email-column", failures: [String(e.message)] };
  }

  for (const [headerLine, rows, expected, label] of CASES) {
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
