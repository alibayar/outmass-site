/**
 * Every host permission must be one the extension actually contacts.
 *
 * 0.2.0 asked for https://graph.microsoft.com/* and
 * https://login.microsoftonline.com/* and used neither. Graph is called
 * exclusively from the backend — the extension never holds a Graph token —
 * and sign-in goes through chrome.identity.launchWebAuthFlow, which needs no
 * host permission for the page it opens. Both were dropped in 0.2.1.
 *
 * This matters at the install prompt, which is the least forgiving screen in
 * the product: Chrome turns host permissions into "Read and change your data
 * on ...", and asking to read Microsoft's LOGIN domain is close to the most
 * alarming thing we could show someone deciding whether to trust a mail-merge
 * tool with their mailbox. Unused breadth is pure cost.
 *
 * A permission is justified by one of two things: the host appears in
 * extension source, or it is a content_scripts match — which is the reason it
 * needs the permission at all. Anything else is unused until proven
 * otherwise, and "proven" means adding the code that uses it, not editing a
 * list here.
 */

const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");

function bareHost(pattern) {
  return pattern.replace(/^https?:\/\//, "").replace(/\/\*$/, "");
}

/**
 * Does the source contact this host?
 *
 * Requires the host in a URL position — preceded by "//" — not merely
 * present. The first draft searched for the bare host anywhere, and
 * "example.com" counted as used because sidebar.js ships sample CSV rows
 * containing john@example.com. An email address is not an endpoint, and a
 * check that cannot tell them apart would wave through any host whose name
 * happens to appear in a placeholder.
 */
function contacts(source, host) {
  return source.includes("//" + host);
}

function run() {
  const failures = [];
  const check = (ok, msg) => { if (!ok) failures.push(msg); };

  const manifest = JSON.parse(
    fs.readFileSync(path.join(EXT, "manifest.json"), "utf8")
  );
  const hosts = manifest.host_permissions || [];

  const sources = fs
    .readdirSync(EXT)
    .filter((f) => f.endsWith(".js") || f.endsWith(".html"))
    .map((f) => fs.readFileSync(path.join(EXT, f), "utf8"));
  const csMatches = (manifest.content_scripts || []).flatMap(
    (c) => c.matches || []
  );

  // ── The matcher can tell an endpoint from an email address ──
  //
  // Self-tested before it is trusted: the version without this distinction
  // reported "used" for a host that only ever appears in a sample CSV row.
  check(
    contacts('fetch("https://api.example.org/x")', "api.example.org"),
    "the host matcher no longer recognises a real URL"
  );
  check(
    !contacts('"john@example.org,John,Smith"', "example.org"),
    "the host matcher counts an email address as a contacted endpoint"
  );

  // ── Every host permission is used ──
  for (const pattern of hosts) {
    const host = bareHost(pattern);
    const used =
      sources.some((s) => contacts(s, host)) || csMatches.includes(pattern);
    check(
      used,
      `host permission ${pattern} is requested but never used — no extension ` +
        `source mentions ${host} and it is not a content_scripts match`
    );
  }

  // ── The two that were dropped stay dropped ──
  for (const gone of ["graph.microsoft.com", "login.microsoftonline.com"]) {
    check(
      !hosts.some((p) => bareHost(p) === gone),
      `${gone} is back in host_permissions — Graph runs server-side and ` +
        `launchWebAuthFlow needs no host permission. If that genuinely ` +
        `changed, drop this check and say why in the commit`
    );
  }

  // ── Both backend hosts stay permitted ──
  //
  // config.js falls back from api.getoutmass.com to the railway host, so
  // dropping either strands whichever clients reach it — which is the entire
  // point of having a fallback.
  for (const required of [
    "api.getoutmass.com",
    "outmass-production.up.railway.app",
  ]) {
    check(
      hosts.some((p) => bareHost(p) === required),
      `${required} is missing from host_permissions but config.js still ` +
        `points at it — requests would fail with no diagnosis`
    );
  }

  // ── API permissions stay minimal too ──
  const EXPECTED = ["storage", "alarms", "identity"];
  const extra = (manifest.permissions || []).filter(
    (p) => !EXPECTED.includes(p)
  );
  check(
    extra.length === 0,
    `new API permissions ${extra.join(", ")} widen the install prompt — ` +
      `confirm each is load-bearing, then add it to EXPECTED here`
  );

  // -- and the certification notes must disclose every one of them --
  //
  // docs/store-listing/certification-notes.txt is what a store reviewer reads
  // to decide whether the permissions we ask for are justified. On 2026-09-01
  // it named five of the six host permissions: the railway fallback host was
  // missing, and an undisclosed host permission is exactly what a reviewer
  // flags. It was caught by reading the file, which is not a method.
  //
  // Checked here rather than in check-limits.js because the source of truth
  // is the manifest, not listings.json.
  const notesPath = path.join(
    EXT, "..", "docs", "store-listing", "certification-notes.txt"
  );
  if (fs.existsSync(notesPath)) {
    const notes = fs.readFileSync(notesPath, "utf8");
    for (const p of hosts) {
      const host = bareHost(p);
      check(
        notes.includes(host),
        `certification-notes.txt does not mention ${host}, which the manifest ` +
          `asks for - a reviewer sees a permission the notes never explain`
      );
    }
    for (const p of manifest.permissions || []) {
      check(
        notes.includes(p),
        `certification-notes.txt does not mention the "${p}" permission`
      );
    }
  }

  return { name: "manifest-permissions", failures };
}

module.exports = { run };
