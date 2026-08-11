import { expect } from "@playwright/test";

/**
 * Nothing may stick out of the panel sideways.
 *
 * The panel is 380px and horizontal scroll in it is not a feature — a control
 * past the right edge is one the user has to fight for. This went unmeasured
 * for months because the suite ran at Playwright's default 1280px, where
 * every row has room to spare.
 *
 * Used by BOTH suites, and they are not redundant. extension.spec.ts renders
 * i18n KEYS, because the stub's chrome.i18n returns nothing and t() falls
 * back to the key — so it measures the worst case, a missing translation.
 * i18n-visual.spec.ts renders the real strings in all 10 locales, which is
 * where the genuine breakage lives: #btn-delete-template overflowed by 32px
 * in FRENCH and fitted in English. A guard that only ran on English would
 * have called that row healthy.
 */
export async function expectNoHorizontalOverflow(page, context = "") {
  const width = page.viewportSize()!.width;

  const found = await page.evaluate((limit) => {
    const out: string[] = [];
    document.querySelectorAll("*").forEach((n) => {
      const el = n as HTMLElement;
      const b = el.getBoundingClientRect();
      // Hidden elements collapse to a zero-width rect, so an inactive tab
      // filters itself out — which is why callers must switch tabs and
      // check each one.
      if (b.width > 0 && b.right > limit + 1) {
        const id = el.id
          ? "#" + el.id
          : "." + String(el.className).split(" ")[0];
        out.push(`${id} ends at ${Math.round(b.right)}`);
      }
    });
    return { out, scrollWidth: document.body.scrollWidth };
  }, width);

  expect(
    found.out,
    `${context}panel is ${width}px but body scrolls to ${found.scrollWidth}`,
  ).toEqual([]);
}
