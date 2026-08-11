/**
 * OutMass Chrome Extension — i18n Visual Regression Tests
 *
 * Renders the sidebar in each of 10 supported languages and takes
 * screenshots of Campaign, Settings, and Account tabs.
 *
 * Screenshots are saved to `e2e/screenshots/` (gitignored) — use to manually
 * check for RTL/CJK layout issues in Arabic, Chinese, Japanese especially.
 *
 * Run: npx playwright test i18n-visual.spec.ts --project=extension
 * View: open e2e/screenshots/ directory
 */

import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";
import { installChromeStub } from "./chrome-stub";
import { expectNoHorizontalOverflow } from "./overflow";

const SIDEBAR_URL = `file:///${path.resolve("extension/sidebar.html").replace(/\\/g, "/")}`;
const SCREENSHOT_DIR = path.resolve("e2e/screenshots");

// Ensure screenshots dir exists
if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

const LOCALES = [
  { code: "en", name: "English" },
  { code: "tr", name: "Turkish" },
  { code: "de", name: "German" },
  { code: "fr", name: "French" },
  { code: "es", name: "Spanish" },
  { code: "ru", name: "Russian" },
  { code: "ar", name: "Arabic" }, // RTL
  { code: "hi", name: "Hindi" },
  { code: "zh_CN", name: "Chinese" }, // CJK
  { code: "ja", name: "Japanese" }, // CJK
];

/**
 * Inject messages.json content as an override into the page before i18n runs.
 * Since chrome.i18n is unavailable in file:// context, we simulate the override
 * by inlining the locale's messages and patching the t() function.
 */
// Campaign rows are where the Reports tab's real width lives. With an empty
// list the tab is two buttons and a heading, so the overflow check below was
// measuring nothing — and the row it does not measure overflowed a 380px
// panel by ~120px for every user who had campaigns.
const SEED_CAMPAIGNS = [
  { id: "c1", name: "Stalled outreach", status: "failed_auth",
    sent_count: 0, open_count: 0, click_count: 0,
    created_at: "2026-08-01T10:00:00Z" },
  { id: "c2", name: "Normal campaign", status: "sent",
    sent_count: 120, open_count: 48, click_count: 12,
    created_at: "2026-08-02T10:00:00Z" },
];

async function loadLocaleAndApply(page: any, locale: string) {
  const messagesPath = path.resolve(`extension/_locales/${locale}/messages.json`);
  const messages = JSON.parse(fs.readFileSync(messagesPath, "utf-8"));

  // Without this the page has no `chrome`, the sidebar script dies at init,
  // and no tab handler ever binds — every test here that clicks a tab then
  // times out. (Same root cause that kept CI red from 2026-06-03.)
  await page.addInitScript(installChromeStub, { campaigns: SEED_CAMPAIGNS });

  await page.addInitScript((msgs: any) => {
    // Override i18n BEFORE scripts run
    (window as any).__OUTMASS_LOCALE_MESSAGES__ = msgs;
  }, messages);

  await page.goto(SIDEBAR_URL);

  // Inject override into i18n helpers
  await page.evaluate((loc: string) => {
    const msgs = (window as any).__OUTMASS_LOCALE_MESSAGES__;
    if (!msgs) return;

    // Override t() function result by replacing _i18nOverride
    (window as any)._i18nOverride = msgs;
    (window as any)._i18nOverrideLocale = loc;

    // Re-apply i18n to DOM
    if (typeof (window as any).applyI18n === "function") {
      (window as any).applyI18n();
    }
  }, locale);

  // Small wait for layout to settle
  await page.waitForTimeout(100);
}

test.describe("i18n visual regression", () => {
  for (const locale of LOCALES) {

    // The labels that just fit in English are longer in German and Russian.
    // #btn-export-list was 4px past the edge in English before 2026-08-11,
    // which is the margin a translation erases.
    test(`${locale.name} (${locale.code}) - nothing overflows the panel`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: 380, height: 900 });
      await loadLocaleAndApply(page, locale.code);
      for (const tab of ["campaign", "reports", "settings", "account"]) {
        if (tab !== "campaign") await page.click(`[data-tab="${tab}"]`);
        // Reports loads its rows through a sendMessage callback. Measuring
        // straight after the click measured an EMPTY list, which is how the
        // first version of this passed while the campaign row overflowed by
        // ~120px in every locale.
        if (tab === "reports") {
          await page.locator(".campaign-row").first().waitFor();
        }
        await expectNoHorizontalOverflow(page, `${locale.code} ${tab}: `);
      }
    });

    test(`${locale.name} (${locale.code}) — Campaign tab`, async ({ page }) => {
      await page.setViewportSize({ width: 380, height: 900 });
      await loadLocaleAndApply(page, locale.code);

      // Campaign tab is active by default
      await expect(page.locator("#tab-campaign")).toBeVisible();

      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, `${locale.code}-campaign.png`),
        fullPage: true,
      });

      // Sanity check: no empty labels (unless intentional)
      const abLabel = await page.locator('[data-i18n="abTestLabel"]').textContent();
      expect(abLabel?.trim().length).toBeGreaterThan(0);
    });

    test(`${locale.name} (${locale.code}) — Settings tab`, async ({ page }) => {
      await page.setViewportSize({ width: 380, height: 1600 });
      await loadLocaleAndApply(page, locale.code);

      await page.click('[data-tab="settings"]');

      // Force show settings-content (normally loads async via chrome.runtime which is unavailable)
      await page.evaluate(() => {
        const loading = document.getElementById("settings-loading");
        const content = document.getElementById("settings-content");
        if (loading) loading.style.display = "none";
        if (content) content.style.display = "block";
      });

      await expect(page.locator("#tab-settings")).toBeVisible();

      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, `${locale.code}-settings.png`),
        fullPage: true,
      });
    });

    test(`${locale.name} (${locale.code}) — Account tab`, async ({ page }) => {
      await page.setViewportSize({ width: 380, height: 800 });
      await loadLocaleAndApply(page, locale.code);

      await page.click('[data-tab="account"]');

      // Force show account-content (normally loads async)
      await page.evaluate(() => {
        const loading = document.getElementById("account-loading");
        const content = document.getElementById("account-content");
        if (loading) loading.style.display = "none";
        if (content) content.style.display = "block";
      });

      await expect(page.locator("#tab-account")).toBeVisible();

      await page.screenshot({
        path: path.join(SCREENSHOT_DIR, `${locale.code}-account.png`),
        fullPage: true,
      });
    });
  }

  test("Arabic has RTL direction set", async ({ page }) => {
    await loadLocaleAndApply(page, "ar");
    const dir = await page.evaluate(() => document.documentElement.getAttribute("dir"));
    expect(dir).toBe("rtl");
  });

  test("Non-RTL languages have LTR direction", async ({ page }) => {
    await loadLocaleAndApply(page, "ja");
    const dir = await page.evaluate(() => document.documentElement.getAttribute("dir"));
    expect(dir).toBe("ltr");
  });
});
