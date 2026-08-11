/**
 * Minimal `chrome` stand-in for sidebar.html loaded over file://.
 *
 * In production the sidebar runs as an extension page, so `chrome` always
 * exists. Over file:// it is undefined, and a single init-time reference is
 * enough to throw a ReferenceError that kills the whole IIFE before any tab
 * or button handler binds. Static CSS-visibility assertions still pass, so
 * the suite fails in a way that looks like "the UI is broken" rather than
 * "the harness never booted the UI" — which is how it stayed red on every
 * push from 2026-06-03 (commit 76b6317 added an init-time
 * `if (chrome.storage && chrome.storage.onChanged)`; that guard survives a
 * chrome WITHOUT storage but throws when chrome itself is missing).
 *
 * Test-only scaffolding — never shipped.
 *
 * `onboardingDone` is seeded deliberately: with an empty store the sidebar
 * correctly decides this is a first run and drops the onboarding overlay
 * over the panel, making every tab and toggle unclickable (Playwright then
 * times out waiting for an actionable element) and polluting screenshots.
 */
/**
 * `seed` parameterises the two things the sidebar's auth state is derived
 * from: what is in storage, and what GET_SETTINGS answers. Without it every
 * test runs in the default never-signed-in state, which is fine for most of
 * the suite but makes the reconnect and session-expired banners untestable —
 * and those are exactly the states the first-sign-in consent line must NOT
 * appear in.
 *
 * Playwright passes it through `page.addInitScript(installChromeStub, seed)`.
 * Callers that pass nothing keep the previous behaviour exactly.
 */
export function installChromeStub(seed?: {
  store?: Record<string, unknown>;
  settings?: Record<string, unknown>;
  campaigns?: unknown[];
}) {
  const noop = () => {};
  const store: Record<string, unknown> = {
    onboardingDone: true,
    ...((seed && seed.store) || {}),
  };
  const settings = (seed && seed.settings) || null;
  const campaigns = (seed && seed.campaigns) || null;
  // Every sidebar event goes out as sendMessage({type:"TRACK", ...}), so
  // recording them here is how a test can assert that a failure path REPORTS
  // itself. Without this, a branch that silently does nothing and a branch
  // that correctly emits a *_failed event look identical to the suite —
  // which is the exact blind spot the 2026-08-04 silence audit found.
  (window as unknown as { __outmassTracked: unknown[] }).__outmassTracked = [];
  (window as unknown as { chrome: unknown }).chrome = {
    runtime: {
      id: "test-extension-id",
      lastError: undefined,
      getURL: (p: string) => p,
      // Callbacks fire with undefined so the UI settles deterministically
      // into its signed-out state instead of waiting forever.
      sendMessage: (msg: unknown, cb?: (r: unknown) => void) => {
        const m = msg as { type?: string };
        if (m && m.type === "TRACK") {
          (window as unknown as { __outmassTracked: unknown[] }).__outmassTracked.push(msg);
        }
        if (m && m.type === "GET_SETTINGS" && settings) {
          if (typeof cb === "function") cb({ data: settings });
          return;
        }
        if (m && m.type === "GET_CAMPAIGNS" && campaigns) {
          if (typeof cb === "function") cb({ data: { campaigns } });
          return;
        }
        if (typeof cb === "function") cb(undefined);
      },
      onMessage: { addListener: noop, removeListener: noop },
    },
    storage: {
      local: {
        get: (_keys: unknown, cb?: (r: unknown) => void) => {
          if (typeof cb === "function") cb(store);
        },
        set: (items: Record<string, unknown>, cb?: () => void) => {
          Object.assign(store, items);
          if (typeof cb === "function") cb();
        },
        remove: (_keys: unknown, cb?: () => void) => {
          if (typeof cb === "function") cb();
        },
      },
      onChanged: { addListener: noop, removeListener: noop },
    },
    i18n: {
      getUILanguage: () => "en-US",
      // Callback-only in the real API, and the CSV decoder reads it at load
      // to learn which scripts the user can actually read. Stubbed so that
      // path runs here rather than being swallowed by its own try/catch.
      getAcceptLanguages: (cb?: (l: string[]) => void) => {
        if (typeof cb === "function") cb(["en-US"]);
      },
      // "" makes t() fall through to its own fallback chain, so assertions
      // read the same strings a user would see.
      getMessage: () => "",
    },
    identity: {
      getRedirectURL: (p: string) => `https://test-extension-id.chromiumapp.org/${p}`,
      launchWebAuthFlow: (_opts: unknown, cb?: (u?: string) => void) => {
        if (typeof cb === "function") cb(undefined);
      },
    },
    alarms: { create: noop, onAlarm: { addListener: noop } },
  };
}
