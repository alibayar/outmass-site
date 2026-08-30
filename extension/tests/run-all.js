/**
 * Extension pre-release checks. Run from anywhere:
 *   node extension/tests/run-all.js
 *
 * Suites:
 *   csv-decode          — real decodeCsvBuffer vs 10 encoding fixtures
 *   locale-consistency  — all locales: key parity + placeholder tokens
 *   i18n-usage          — every literal t()/data-i18n key exists in en
 *   locale-variants     — script/regional purity (zh Simplified, pt_BR vs pt_PT)
 *   uninstall-stage     — funnel stage ladder carried on the uninstall URL
 *   no-silent-dead-ends — rejection branches on the main journey must report
 *   ms-auth-codes       — every failure class the backend can send has a
 *                         panel sentence in every locale (crosses into
 *                         backend/routers/auth.py to compare both sides)
 *   no-hardcoded-prices — no locale or markup holds a literal price, and the
 *                         Intl path that shows the real one still exists
 *   ui-language-header  — the service worker and the panel agree on what
 *                         language this is, and the backend reads the header
 *                         they send (crosses into backend/routers/auth.py)
 *
 * A suite's run() may be sync or async — the result is awaited either way.
 *
 * Part of the release procedure (see CLAUDE.md → Test) and the CI
 * extension-checks job. Exit code 1 on any failure.
 */

const suites = [
  require("./csv-decode.test.js"),
  require("./locale-consistency.test.js"),
  require("./i18n-usage.test.js"),
  require("./locale-variants.test.js"),
  require("./uninstall-stage.test.js"),
  require("./no-silent-dead-ends.test.js"),
  require("./analytics-race.test.js"),
  require("./ms-auth-codes.test.js"),
  require("./manifest-permissions.test.js"),
  require("./no-hardcoded-prices.test.js"),
  require("./ui-language-header.test.js"),
  require("./first-signin-scope.test.js"),
  require("./auth-flight-settle.test.js"),
  require("./auth-flow-context.test.js"),
];

async function main() {
  let failed = 0;
  for (const suite of suites) {
    let result;
    try {
      result = await suite.run();
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
}

main().catch((e) => {
  // An unhandled rejection here would otherwise exit 0 and let a broken
  // release through — the runner failing silently is the one outcome we
  // cannot allow in a release gate.
  console.error("Runner crashed:", e);
  process.exit(1);
});
