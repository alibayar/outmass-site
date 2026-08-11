/**
 * OutMass Chrome Extension — Sidebar UI Tests
 *
 * Tests the sidebar HTML/CSS/JS works correctly.
 * Opens sidebar.html directly (no extension context needed for UI tests).
 *
 * Run: npx playwright test
 */

import { test, expect } from "@playwright/test";
import fs from "fs";
import path from "path";
import { installChromeStub } from "./chrome-stub";
import { expectNoHorizontalOverflow } from "./overflow";

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

// ── CSV dropzone: the first gate of the main journey ──
//
// Until 2026-08-04 this gate was `if (name.endsWith(".csv")) handleCSV(file)`
// with NO else. A rejected drop executed zero further statements — and
// preventDefault() runs before the check, so even the browser's own feedback
// was suppressed. The user saw pixel-identical UI and dragged the file again.
// All three csv_upload_failed events live inside handleCSV, past this gate,
// so the population that never got in was invisible in PostHog too.
//
// t() returns the KEY when chrome.i18n yields nothing (i18n.js:144), which is
// what the stub arranges — so asserting on "csvErrNotCsv" pins that the right
// key is used, and locale-consistency separately proves it exists in all 14.

async function dropFile(page, name: string, body = "email\na@example.com\n") {
  const dt = await page.evaluateHandle(
    ([n, b]) => {
      const t = new DataTransfer();
      t.items.add(new File([b], n, { type: "text/plain" }));
      return t;
    },
    [name, body] as const
  );
  await page.dispatchEvent("#csv-dropzone", "drop", { dataTransfer: dt });
}

test("dropping a non-CSV file says so instead of doing nothing", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    d.dismiss();
  });

  await dropFile(page, "Recipients.xlsx");

  expect(dialogs).toEqual(["csvErrNotCsv"]);

  const tracked = await page.evaluate(() => (window as any).__outmassTracked);
  const failed = tracked.filter((e: any) => e.event === "csv_upload_failed");
  expect(failed).toHaveLength(1);
  expect(failed[0].properties.error_code).toBe("unsupported_file_type");
  // The extension is what tells us WHICH format users actually bring. If it
  // turns out to be mostly .xlsx, the fix is an xlsx parser, not a message.
  expect(failed[0].properties.ext).toBe("xlsx");
});

test("an uppercase .CSV is accepted — it used to be silently rejected", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    d.dismiss();
  });

  // A CRM or Outlook contacts export lands as Contacts.CSV on Windows. The
  // old endsWith(".csv") is case-sensitive, so this exact file was rejected
  // by drag-and-drop while working perfectly via the file picker — whose
  // accept=".csv" filters case-insensitively and whose change handler checks
  // nothing at all.
  await dropFile(page, "Contacts.CSV");

  expect(dialogs).toEqual([]);
  const tracked = await page.evaluate(() => (window as any).__outmassTracked);
  expect(tracked.filter((e: any) => e.event === "csv_upload_failed")).toHaveLength(0);
});

test("a dropped file with no extension is rejected loudly, not silently", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    d.dismiss();
  });

  await dropFile(page, "contacts");

  expect(dialogs).toEqual(["csvErrNotCsv"]);
});

/**
 * The consent explainer in the panel.
 *
 * 0.2.0 auto-opens this panel on first run, so a new user may never open the
 * popup — where the only honest description of what Microsoft is about to
 * ask has lived since 0.1.26. The panel showed them a bare "Sign in with
 * Microsoft to start sending." and a button.
 *
 * The funnel says that step is where they go: in the first four days of
 * 0.2.0, twelve people started auth and six finished it.
 *
 * It belongs to a FIRST sign-in only. Someone reconnecting has already read
 * Microsoft's consent screen and decided, so repeating it there would just
 * lengthen an urgent banner. These three tests pin exactly that split.
 */
test.describe("first-sign-in consent explainer", () => {
  const CONSENT = "#reauth-banner-consent";

  test("a user who has never signed in sees why Microsoft will ask", async ({
    page,
  }) => {
    // The default stub store has no backendJwt and no sessionExpired, which
    // is precisely the never-signed-in state.
    await expect(page.locator("#reauth-banner")).toBeVisible();
    await expect(page.locator(CONSENT)).toBeVisible();
    await expect(page.locator(CONSENT)).toHaveAttribute(
      "data-i18n",
      "popupConsentExplainer",
    );
  });

  test("the Sign in button stays on its own line beside the message", async ({
    page,
  }) => {
    // The banner is a flex row; the explainer only works because it wraps to
    // a row of its own. If it ever shared the first row it would squeeze the
    // button, which is the one thing in the banner that must stay reachable.
    //
    // Measured against the REAL sentence, not what the harness renders. The
    // stub's chrome.i18n.getMessage returns "", so t() falls through to
    // returning the key and applyI18n paints "popupConsentExplainer" — 22
    // characters, one line. The shipped string is four lines at this width,
    // and one line is not the geometry worth asserting.
    // The real panel is 380px wide (#outmass-sidebar-wrapper in
    // styles/content.css). Playwright's default viewport is 1280, where the
    // English sentence fits on ONE line and this assertion would be checking
    // a geometry no user ever sees — which is exactly what the first version
    // of this test did.
    await page.setViewportSize({ width: 380, height: 700 });

    // Read on the Node side: a file:// page cannot fetch its own siblings.
    const real = JSON.parse(
      fs.readFileSync(
        path.resolve("extension/_locales/en/messages.json"),
        "utf-8",
      ),
    ).popupConsentExplainer.message as string;
    expect(real.length).toBeGreaterThan(150);

    // Let the page settle FIRST. initI18n().then(applyI18n) resolves on its
    // own schedule and repaints every [data-i18n] node; the first version of
    // this test wrote the text before that landed, applyI18n put the key
    // back, and the measurement silently went back to one line.
    const btn = page.locator("#reauth-banner-btn");
    await expect(btn).toBeVisible();
    await expect(page.locator(CONSENT)).toBeVisible();

    const measured = await page.evaluate((text) => {
      const el = document.getElementById("reauth-banner-consent")!;
      el.textContent = text;
      const b = el.getBoundingClientRect();
      const btnRect = document
        .getElementById("reauth-banner-btn")!
        .getBoundingClientRect();
      // Read back in the same turn nothing else can run in, so the numbers
      // and the text they describe cannot drift apart.
      return {
        len: el.textContent!.length,
        top: b.top, height: b.height,
        btnBottom: btnRect.bottom, btnWidth: btnRect.width,
      };
    }, real);

    // The measurement described the real sentence, not the key placeholder.
    expect(measured.len).toBe(real.length);
    // Below the button, not beside it.
    expect(measured.top).toBeGreaterThanOrEqual(measured.btnBottom);
    // And genuinely wrapping to several lines at this width.
    expect(measured.height).toBeGreaterThan(30);
    // The button keeps its full width; nothing squeezed it.
    expect(measured.btnWidth).toBeGreaterThan(60);
  });

  test("a reconnecting user is not told again what Microsoft asks", async ({
    page,
  }) => {
    await page.addInitScript(installChromeStub, {
      store: { backendJwt: "jwt-token" },
      settings: { requires_reauth: true },
    });
    await page.reload();

    await expect(page.locator("#reauth-banner")).toBeVisible();
    await expect(page.locator(CONSENT)).toBeHidden();
  });

  test("an expired session is not told again either", async ({ page }) => {
    await page.addInitScript(installChromeStub, {
      store: { backendJwt: "jwt-token", sessionExpired: true },
    });
    await page.reload();

    await expect(page.locator("#reauth-banner")).toBeVisible();
    await expect(page.locator(CONSENT)).toBeHidden();
  });
});

/**
 * Nothing may stick out of the panel sideways.
 *
 * The panel is 380px and does not scroll horizontally in any useful sense —
 * a control past the right edge is a control the user has to fight for. This
 * went unnoticed because the suite ran at Playwright's default 1280px, where
 * every row has room to spare; #btn-delete-template sat 53px past the edge
 * at the real width for as long as anyone has measured.
 *
 * Reported with the offending elements named, because "body is 53px too
 * wide" on its own sends you hunting.
 */
for (const tab of ["campaign", "reports", "settings", "account"]) {
  test(`nothing hangs off the side of the panel - ${tab} tab`, async ({
    page,
  }) => {
    // Per tab, because the inactive ones are display:none and measure as
    // zero - a row that overflows in Settings is invisible from Campaign.
    if (tab !== "campaign") await page.click(`[data-tab="${tab}"]`);
    await expectNoHorizontalOverflow(page);
  });
}
