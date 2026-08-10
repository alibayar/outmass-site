/**
 * The backend names a sign-in failure; the panel has to be able to say it.
 *
 * Since 2026-08-10 the auth settle fragment carries two fields: `error`, an
 * English sentence every shipped client renders verbatim, and `mcode`, the
 * backend's own name for the failure class. A newer client reads `mcode` and
 * looks the sentence up in the user's own panel language.
 *
 * That makes the two sides a contract across a language boundary, and
 * nothing else checks it:
 *
 *   * i18n-usage only sees `t("literalKey")`. The keys here live as VALUES
 *     inside MS_AUTH_MESSAGE_KEYS, so a typo there is invisible to it — and
 *     t() returns the key itself on a miss, so the user would read
 *     "authMsOurFault" as if it were a sentence.
 *   * locale-consistency proves the 14 locales agree with each other. It
 *     cannot know a key was never added in the first place.
 *
 * The failure this prevents is silent by construction: add a class on the
 * server, forget the client, and those users read English forever while
 * every test stays green.
 */

const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");
const BACKEND_AUTH = path.join(EXT, "..", "backend", "routers", "auth.py");

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  const i18nSrc = fs.readFileSync(path.join(EXT, "i18n.js"), "utf8");

  // ── the client's map ──
  const mapMatch = /var MS_AUTH_MESSAGE_KEYS = \{([\s\S]*?)\n\};/.exec(i18nSrc);
  check(mapMatch !== null, "MS_AUTH_MESSAGE_KEYS is gone from i18n.js");
  if (!mapMatch) return { name: "ms-auth-codes", failures };

  const clientCodes = new Map();
  for (const m of mapMatch[1].matchAll(/^\s*([a-z_]+):\s*"([A-Za-z0-9_]+)"/gm)) {
    clientCodes.set(m[1], m[2]);
  }
  check(clientCodes.size > 0, "MS_AUTH_MESSAGE_KEYS parsed as empty");

  // ── the server's classes ──
  if (!fs.existsSync(BACKEND_AUTH)) {
    // The extension ships alone; without the backend checked out the
    // cross-boundary half cannot run. Say so rather than pass quietly.
    failures.push("backend/routers/auth.py not found — cross-boundary check skipped");
    return { name: "ms-auth-codes", failures };
  }
  const pySrc = fs.readFileSync(BACKEND_AUTH, "utf8");
  const settleMatch = /_SETTLE_MESSAGES = \{([\s\S]*?)\n\}/.exec(pySrc);
  check(settleMatch !== null, "_SETTLE_MESSAGES is gone from backend auth.py");
  if (!settleMatch) return { name: "ms-auth-codes", failures };

  const serverCodes = new Set();
  for (const m of settleMatch[1].matchAll(/^\s{4}"([a-z_]+)":/gm)) {
    serverCodes.add(m[1]);
  }
  check(serverCodes.size > 0, "_SETTLE_MESSAGES parsed as empty");

  // Every class the server can send must have a panel sentence. The reverse
  // is not required: a client entry for a class the server retired is dead
  // weight, not a broken promise to a user.
  for (const code of serverCodes) {
    check(
      clientCodes.has(code),
      `backend can send mcode="${code}" but i18n.js has no key for it — ` +
      `those users would read the English fallback forever, silently`
    );
  }

  // ── every key must exist in every locale ──
  const localeDirs = fs
    .readdirSync(path.join(EXT, "_locales"), { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name);

  const wanted = [...new Set(clientCodes.values())];
  for (const dir of localeDirs) {
    const p = path.join(EXT, "_locales", dir, "messages.json");
    if (!fs.existsSync(p)) continue;
    const msgs = JSON.parse(fs.readFileSync(p, "utf8"));
    for (const key of wanted) {
      const entry = msgs[key];
      check(
        entry && typeof entry.message === "string" && entry.message.trim(),
        `${dir}/messages.json is missing ${key}`
      );
      if (!entry || typeof entry.message !== "string") continue;
      // '$' is the i18n substitution marker. A stray one silently eats the
      // rest of the sentence on the override path.
      check(
        !entry.message.includes("$"),
        `${dir}/${key} contains '$', which _applySubs treats as a placeholder`
      );
    }
    // The support address is the only next step several of these offer. A
    // translator "localizing" it leaves the user with nowhere to go.
    for (const key of ["authMsMisconfigured", "authMsOurFault"]) {
      const entry = msgs[key];
      if (!entry || typeof entry.message !== "string") continue;
      check(
        entry.message.includes("support@getoutmass.com"),
        `${dir}/${key} lost support@getoutmass.com — it is the whole action`
      );
    }
  }

  // ── the resolver must not show a raw key ──
  check(
    /msg && msg !== key \? msg : fallbackSentence/.test(i18nSrc),
    "msAuthMessage no longer falls back when the lookup misses. t() returns " +
    "the KEY on a miss, so a locale that has not been updated would print " +
    "'authMsOurFault' at the user instead of the server's English sentence"
  );

  // ── both readers must consult it ──
  for (const file of ["popup.js", "sidebar.js"]) {
    const src = fs.readFileSync(path.join(EXT, file), "utf8");
    check(
      src.includes("msAuthMessage("),
      `${file} does not use msAuthMessage, so the backend's own classification ` +
      `is discarded and the user gets the English sentence`
    );
  }

  // background.js must actually read the field off the fragment.
  const bg = fs.readFileSync(path.join(EXT, "background.js"), "utf8");
  check(
    /params\.get\("mcode"\)/.test(bg),
    "background.js no longer reads mcode from the settle fragment"
  );
  check(
    /msCode: msCode/.test(bg) || /result\.msCode = msCode/.test(bg),
    "background.js reads mcode but never passes it to the UI"
  );

  return { name: "ms-auth-codes", failures };
}

module.exports = { run };
