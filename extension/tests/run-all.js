/**
 * Extension pre-release checks. Run from anywhere:
 *   node extension/tests/run-all.js
 *
 * Suites:
 *   csv-decode          — real decodeCsvBuffer vs 10 encoding fixtures
 *   locale-consistency  — 11 locales: key parity + placeholder tokens
 *   i18n-usage          — every literal t()/data-i18n key exists in en
 *
 * Part of the release procedure (see CLAUDE.md → Test) and the CI
 * extension-checks job. Exit code 1 on any failure.
 */

const suites = [
  require("./csv-decode.test.js"),
  require("./locale-consistency.test.js"),
  require("./i18n-usage.test.js"),
];

let failed = 0;
for (const suite of suites) {
  let result;
  try {
    result = suite.run();
  } catch (e) {
    result = { name: "unknown", failures: ["suite crashed: " + e.stack] };
  }
  if (result.failures.length === 0) {
    console.log(`PASS  ${result.name}`);
  } else {
    failed += result.failures.length;
    console.log(`FAIL  ${result.name} (${result.failures.length})`);
    for (const f of result.failures) console.log(`      - ${f}`);
  }
}

if (failed > 0) {
  console.log(`\n${failed} failure(s).`);
  process.exit(1);
}
console.log("\nAll extension checks passed.");
