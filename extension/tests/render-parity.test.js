/**
 * The preview and the send must produce the same HTML. Character for
 * character, from one file.
 *
 * They have disagreed twice, in opposite directions, and a customer found it
 * first both times:
 *
 *   2026-09-01 morning — Helene@circularworkplaces.com: "the formating which
 *   was sent for my CBRE campaign did not work and everything sent as a block
 *   even if the preview looked fine." Every scheduled send the product had
 *   ever made was missing the conversion the preview did.
 *
 *   The same day — fixing that moved the server to deciding from the TEMPLATE
 *   while the panel still decided from the merged text, so for one release
 *   they were wrong in the other direction: a plain-text campaign merged with
 *   a row containing <info@example.com> would send correctly and preview as
 *   one block.
 *
 * Comments did not prevent the second one. This does: both suites read
 * backend/tests/fixtures/render_cases.json and assert the same strings, so a
 * change to either implementation that is not made to both fails here.
 *
 * Adding a case: put it in the fixture with the output you intend, then run
 * both suites. If they disagree, one of the two implementations is wrong —
 * work out which before editing the expectation.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const EXT = path.join(__dirname, "..");
const REPO = path.join(EXT, "..");

// Lift the renderer out of sidebar.js rather than duplicating it here. A copy
// would be a third implementation, which is the problem this file exists for.
function loadRenderer() {
  const src = fs.readFileSync(path.join(EXT, "sidebar.js"), "utf8");
  const grab = (re, what) => {
    const m = re.exec(src);
    if (!m) throw new Error(`could not find ${what} in sidebar.js`);
    return m[0];
  };
  const code = [
    grab(/var BLOCK_TAG_RE =[\s\S]*?;\n/, "BLOCK_TAG_RE"),
    grab(/function paragraphs\(text\)[\s\S]*?\n  \}\n/, "paragraphs()"),
    grab(/var URL_RE =[\s\S]*?var SKIP_RE = [^\n]*\n/, "the autolink regexes"),
    grab(/function autolink\(html\)[\s\S]*?\n  \}\n/, "autolink()"),
    grab(/function textToHtml\(template, merged\)[\s\S]*?\n  \}\n/, "textToHtml()"),
  ].join("\n");
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx.textToHtml;
}

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  let textToHtml;
  try {
    textToHtml = loadRenderer();
  } catch (e) {
    return { name: "render-parity", failures: [String(e.message)] };
  }

  const fixturePath = path.join(
    REPO, "backend", "tests", "fixtures", "render_cases.json"
  );
  check(fs.existsSync(fixturePath), `the shared fixture is missing: ${fixturePath}`);
  if (!fs.existsSync(fixturePath)) return { name: "render-parity", failures };

  const cases = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
  check(cases.length > 0, "the shared fixture is empty");

  for (const c of cases) {
    const got = textToHtml(c.template, c.merged);
    check(
      got === c.expected,
      `${c.label}:\n      server: ${JSON.stringify(c.expected)}\n` +
        `      panel:  ${JSON.stringify(got)}`
    );
  }

  // The fixture is only worth as much as its coverage. These are the shapes
  // that have actually gone wrong; losing one silently would leave the file
  // passing while guarding nothing.
  const labels = cases.map((c) => c.label).join(" | ");
  for (const required of [
    "line breaks",       // the original complaint
    "angle brackets",    // the merged-vs-template regression
    "link",              // autolinking, added 2026-09-01
    "block markup",      // authored HTML must be left alone
  ]) {
    check(
      labels.includes(required),
      `the fixture no longer covers "${required}" — that shape has broken in ` +
        `production before`
    );
  }

  return { name: "render-parity", failures };
}

module.exports = { run };

if (require.main === module) {
  const r = run();
  r.failures.forEach((f) => console.error("FAIL:", f));
  console.log(r.failures.length ? `${r.name}: ${r.failures.length} failure(s)` : `${r.name}: ok`);
  process.exit(r.failures.length ? 1 : 0);
}
