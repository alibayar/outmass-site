/**
 * OutMass Chrome Extension — Sidebar UI Tests
 *
 * Tests the sidebar HTML/CSS/JS works correctly.
 * Opens sidebar.html directly (no extension context needed for UI tests).
 *
 * Run: npx playwright test
 */

import { test, expect } from "@playwright/test";
import path from "path";
import { installChromeStub } from "./chrome-stub";

const SIDEBAR_URL = `file:///${path.resolve("extension/sidebar.html").replace(/\\/g, "/")}`;

test.beforeEach(async ({ page }) => {
  await page.addInitScript(installChromeStub);
  await page.goto(SIDEBAR_URL);
});

test("sidebar loads with correct header", async ({ page }) => {
  await expect(page.locator("h1")).toHaveText("OutMass");
});

test("all three tabs are visible", async ({ page }) => {
  await expect(page.locator('[data-tab="campaign"]')).toBeVisible();
  await expect(page.locator('[data-tab="reports"]')).toBeVisible();
  await expect(page.locator('[data-tab="settings"]')).toBeVisible();
});

test("campaign tab is active by default", async ({ page }) => {
  await expect(page.locator("#tab-campaign")).toBeVisible();
  await expect(page.locator("#tab-reports")).not.toBeVisible();
  await expect(page.locator("#tab-settings")).not.toBeVisible();
});

test("campaign tab has all key elements", async ({ page }) => {
  await expect(page.locator("#csv-dropzone")).toBeVisible();
  await expect(page.locator("#subject")).toBeVisible();
  await expect(page.locator("#body")).toBeVisible();
  await expect(page.locator("#btn-send")).toBeVisible();
  await expect(page.locator("#btn-preview")).toBeVisible();
  await expect(page.locator("#btn-ai-writer")).toBeVisible();
});

test("tab switching works — reports", async ({ page }) => {
  await page.click('[data-tab="reports"]');
  await expect(page.locator("#tab-reports")).toBeVisible();
  await expect(page.locator("#tab-campaign")).not.toBeVisible();
});

test("tab switching works — settings", async ({ page }) => {
  await page.click('[data-tab="settings"]');
  await expect(page.locator("#tab-settings")).toBeVisible();
  await expect(page.locator("#tab-campaign")).not.toBeVisible();
});

test("tab switching works — back to campaign", async ({ page }) => {
  await page.click('[data-tab="settings"]');
  await page.click('[data-tab="campaign"]');
  await expect(page.locator("#tab-campaign")).toBeVisible();
  await expect(page.locator("#tab-settings")).not.toBeVisible();
});

test("A/B test toggle shows/hides fields", async ({ page }) => {
  await expect(page.locator("#ab-test-fields")).not.toBeVisible();
  await page.click("#ab-test-enabled");
  await expect(page.locator("#ab-test-fields")).toBeVisible();
  await expect(page.locator("#ab-subject-b")).toBeVisible();
  await expect(page.locator("#ab-test-pct")).toBeVisible();
  await page.click("#ab-test-enabled");
  await expect(page.locator("#ab-test-fields")).not.toBeVisible();
});

test("schedule toggle shows/hides fields", async ({ page }) => {
  await expect(page.locator("#schedule-fields")).not.toBeVisible();
  await page.click("#schedule-enabled");
  await expect(page.locator("#schedule-fields")).toBeVisible();
  await expect(page.locator("#schedule-datetime")).toBeVisible();
});

test("follow-up toggle shows/hides fields", async ({ page }) => {
  await expect(page.locator("#followup-fields")).not.toBeVisible();
  await page.click("#followup-enabled");
  await expect(page.locator("#followup-fields")).toBeVisible();
  await expect(page.locator("#followup-delay")).toBeVisible();
  await expect(page.locator("#followup-subject")).toBeVisible();
  await expect(page.locator("#followup-body")).toBeVisible();
});

test("send button is disabled without CSV", async ({ page }) => {
  await expect(page.locator("#btn-send")).toBeDisabled();
});

test("form inputs accept text", async ({ page }) => {
  await page.fill("#subject", "Test Subject {{firstName}}");
  await page.fill("#body", "Hello {{firstName}}, welcome!");
  await expect(page.locator("#subject")).toHaveValue("Test Subject {{firstName}}");
  await expect(page.locator("#body")).toHaveValue("Hello {{firstName}}, welcome!");
});

test("template section exists", async ({ page }) => {
  await expect(page.locator("#template-select")).toBeVisible();
  await expect(page.locator("#btn-save-template")).toBeVisible();
});

test("settings tab has all sections", async ({ page }) => {
  await page.click('[data-tab="settings"]');
  await expect(page.locator("#tab-settings")).toBeVisible();

  // Assert the structure the tab promises. This used to assert that
  // #settings-loading was VISIBLE, which only held because the page had no
  // `chrome` global: the script died at init, the request was never made, and
  // the spinner stayed up forever. With the stub the request completes, so
  // the spinner resolving is the correct behaviour — pinning it visible was
  // pinning the bug.
  for (const id of [
    "#settings-content",
    "#settings-sender-name",
    "#settings-sender-position",
    "#settings-sender-company",
    "#settings-language",
  ]) {
    await expect(page.locator(id)).toBeAttached();
  }
});

test("reports tab has list and detail areas", async ({ page }) => {
  await page.click('[data-tab="reports"]');
  await expect(page.locator("#tab-reports")).toBeVisible();
  await expect(page.locator("#reports-list")).toBeVisible();
  // Campaign list is attached (empty until API loads data)
  await expect(page.locator("#campaign-list")).toBeAttached();
});

test("quota bar is visible", async ({ page }) => {
  await expect(page.locator("#quota-text")).toBeVisible();
  await expect(page.locator("#quota-fill")).toBeVisible();
});
