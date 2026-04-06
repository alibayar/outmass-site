import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 15_000,
  retries: 0,
  use: {
    headless: true,
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
