/**
 * We may only close a window we actually opened.
 *
 * `_authWindow` is filled by a chrome.windows.onCreated listener that adopts
 * the FIRST popup-type window it sees while a watch is armed — from any
 * source. `launch()` arms that watch before every call to
 * launchWebAuthFlow, including calls Chrome REFUSES, where no window of ours
 * is ever coming. The watch then sits armed for three seconds and takes the
 * next stranger. An Outlook message opened in its own window is a popup-type
 * window.
 *
 * That was harmless for as long as a misadoption only mis-aimed a focus — the
 * note above the listener said so: "both failure modes degrade to exactly the
 * old behaviour." On 2026-09-03 the reclaim added to the "only one web auth
 * flow" branch pointed chrome.windows.remove at the same variable, and the
 * pre-cut review reproduced the consequence against the real file: the user's
 * own Outlook window destroyed, and oauth_window_reclaimed reporting
 * closed:true while doing it.
 *
 * The second half is the mirror image. The 5-minute flight timeout resolves
 * while the Microsoft window is still open — its own comment says "this
 * timeout releases the UI, it does NOT cancel the flow" — but the settle
 * handler dropped _authWindow on every settle. So the one case where an
 * orphan certainly exists was the one case we forgot where it was, and anyone
 * who stepped away for more than five minutes could never be rescued. That is
 * exactly the shape of the user this fix was written for.
 *
 * This runs the real background.js under a chrome mock rather than reading it,
 * because both defects live in the ORDER events arrive, which no regex sees.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const EXT = path.join(__dirname, "..");
const SRC = fs.readFileSync(path.join(EXT, "background.js"), "utf8");

function bootstrap() {
  const removed = [];
  const created = [];
  let onCreated = null;

  const chromeMock = {
    windows: {
      onCreated: { addListener: (fn) => { onCreated = fn; } },
      update: (id, opts, cb) => cb && cb(),
      remove: (id, cb) => { removed.push(id); cb && cb(); },
    },
    runtime: { lastError: null, getManifest: () => ({ version: "0.0.0" }) },
  };

  const ctx = {
    chrome: chromeMock,
    setTimeout: (fn, ms) => { created.push(ms); return { ms }; },
    clearTimeout: () => {},
    console,
  };
  vm.createContext(ctx);

  // Only the pieces under test: the module-level state, the listener, the
  // watch arming and the close helper. Lifting them keeps this independent of
  // the rest of the file, which needs a far larger environment to load.
  const grab = (re, what) => {
    const m = re.exec(SRC);
    if (!m) throw new Error(`could not find ${what} in background.js`);
    return m[0];
  };

  const code = [
    "var _authWindow = null, _authWindowWatchKey = null, _authWindowWatchTimer = null;",
    grab(/var _authWindowOutlived = \{\};/, "_authWindowOutlived"),
    grab(/chrome\.windows\.onCreated\.addListener[\s\S]*?\n\}\);/, "onCreated listener"),
    grab(/function _armAuthWindowWatch[\s\S]*?\n\}/, "_armAuthWindowWatch()"),
    grab(/function _closeAuthWindow[\s\S]*?\n\}\n/, "_closeAuthWindow()"),
    "function log() {}",
  ].join("\n");

  vm.runInContext(code, ctx);
  return { ctx, removed, fire: (w) => onCreated(w) };
}

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  // ── the source-level guards the behaviour rests on ──

  const refusal = SRC.indexOf("function handleResult");
  const refusalEnd = SRC.indexOf("only one web auth flow", refusal);
  const refusalBlock = refusal > -1 && refusalEnd > refusal
    ? SRC.slice(refusal, refusalEnd) : "";
  check(
    /_authWindowWatchKey = null/.test(refusalBlock),
    "a refused launch no longer disarms the window watch, so for three " +
      "seconds the next popup the USER opens is adopted as ours — and the " +
      "reclaim will call chrome.windows.remove on it"
  );

  check(
    /_authWindowOutlived\[flightKey\] = true/.test(SRC),
    "the flight timeout no longer records that its window outlived it, so " +
      "the settle handler forgets the orphan and nobody who waited more than " +
      "five minutes can be rescued"
  );
  check(
    /_authWindowOutlived\[key\]/.test(SRC),
    "the settle handler no longer honours the outlived marker"
  );

  // ── and the behaviour itself, with events in the order that broke it ──

  let boot;
  try {
    boot = bootstrap();
  } catch (e) {
    failures.push("could not load the window helpers: " + e.message);
    return { name: "auth-window-adoption", failures };
  }
  const { ctx, removed, fire } = boot;

  // A watch is armed, then the launch is refused and the code disarms it.
  ctx.chrome.runtime.lastError = null;
  vm.runInContext("_armAuthWindowWatch('signin');", ctx);
  vm.runInContext("_authWindowWatchKey = null;", ctx);  // what the fix does

  // The user now opens an Outlook message in its own window.
  fire({ type: "popup", id: 999 });
  check(
    vm.runInContext("_authWindow === null", ctx),
    "a popup created after a refused launch was adopted as our auth window — " +
      "the next reclaim would close the user's own Outlook window"
  );

  // With the watch genuinely armed, our window IS adopted.
  vm.runInContext("_armAuthWindowWatch('signin');", ctx);
  fire({ type: "popup", id: 100 });
  check(
    vm.runInContext("_authWindow && _authWindow.id === 100", ctx),
    "our own auth window is no longer adopted, so the reclaim has nothing to close"
  );

  // Closing it removes exactly that window, and only for a matching key.
  vm.runInContext("_closeAuthWindow('mailread', function () {});", ctx);
  check(
    removed.length === 0,
    "_closeAuthWindow closed a window belonging to a different flight key"
  );
  vm.runInContext("_closeAuthWindow('signin', function () {});", ctx);
  check(
    removed.length === 1 && removed[0] === 100,
    `expected to close only window 100, closed ${JSON.stringify(removed)}`
  );

  return { name: "auth-window-adoption", failures };
}

module.exports = { run };

if (require.main === module) {
  const r = run();
  r.failures.forEach((f) => console.error("FAIL:", f));
  console.log(r.failures.length ? `${r.name}: ${r.failures.length} failure(s)` : `${r.name}: ok`);
  process.exit(r.failures.length ? 1 : 0);
}
