import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 15_000,
  retries: 0,
  use: {
    headless: true,
    // The shipped panel is 380px wide (#outmass-sidebar-wrapper in
    // extension/styles/content.css). Playwright's default is 1280, and
    // extension.spec.ts ran there for months — so every layout assertion in
    // it was describing a geometry no user has ever seen. On 2026-08-11 a
    // wrapping assertion passed at 1280 because the sentence it was meant to
    // watch wrap fitted on one line, and a 380px render immediately exposed
    // #btn-delete-template hanging 53px past the panel edge.
    //
    // i18n-visual.spec.ts already set 380 per test; this makes it the floor
    // for everything, so a new spec cannot silently inherit the wrong width.
    // Height is generous on purpose — the panel scrolls vertically, and a
    // short viewport would turn ordinary overflow into false failures.
    viewport: { width: 380, height: 900 },
  },
  projects: [
    {
      name: "extension",
      use: {
        browserName: "chromium",
        // Allow file:// access for sidebar.html testing
        launchOptions: {
          args: ["--allow-file-access-from-files"],
        },
      },
    },
  ],
});
