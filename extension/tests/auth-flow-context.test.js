/**
 * Every sign-in flow must say which control started it.
 *
 * oauth_started / oauth_failed / oauth_retry are the sign-in funnel. Until
 * 2026-08-30 they carried no context, so three unrelated populations were
 * indistinguishable inside one number:
 *
 *   1. a tenant or admin blocking consent — the leak we are measuring;
 *   2. someone closing the sign-in window — abandonment;
 *   3. someone opening the "change sender" switcher and backing out — not a
 *      sign-in attempt at all.
 *
 * Chrome labels 2 and 3 identically (`consent_declined` is "window closed
 * without a redirect", not "the user pressed No"), so nothing downstream
 * could split them either. One user on 2026-08-30 produced one of each in
 * forty minutes; both of their "failures" were 2 and 3, and counting those
 * against sign-in intent overstates the leak with people who were never
 * blocked.
 *
 * The fix threads a `context` from each call site into the flight. This
 * suite is what keeps it threaded: a NEW sign-in entry point added later
 * without a label does not break anything visible — it just quietly starts
 * reporting "unspecified", and the funnel decays a little. That is exactly
 * the kind of silent rot these structural suites exist for.
 *
 * Note the deliberate asymmetry between an ABSENT context (a client older
 * than the change) and "unspecified" (this client, at a call site nobody
 * labelled). They are different bugs and must stay distinguishable, so the
 * default is a real string rather than an omitted field.
 */

const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");
const NAME = "auth-flow-context";

// Every file that may ask the service worker to start an OAuth flow.
const SENDERS = ["sidebar.js", "popup.js", "content_script.js"];

function run() {
  const failures = [];
  const check = (cond, label) => {
    if (!cond) failures.push(label);
  };

  // ── every caller labels its flow ──
  const seen = [];
  for (const file of SENDERS) {
    const p = path.join(EXT, file);
    if (!fs.existsSync(p)) continue;
    const src = fs.readFileSync(p, "utf8");

    // Each message object that starts a login, captured whole enough to see
    // whether a context sits beside the type.
    const re = /\{\s*type:\s*"(MS_LOGIN(?:_MAIL_READ|_ONEDRIVE)?)"[^}]*\}/g;
    let m;
    while ((m = re.exec(src)) !== null) {
      seen.push({ file, type: m[1], text: m[0] });
      check(
        /context:\s*"[a-z0-9_]+"/.test(m[0]),
        `${file}: a ${m[1]} is sent without a context — its oauth_started ` +
          `and oauth_failed will report "unspecified" and blur the funnel`
      );
    }
  }

  check(
    seen.length >= 6,
    `only ${seen.length} login call site(s) found — the matcher has probably ` +
      "stopped seeing them, which would make every check below vacuous"
  );

  // ── the worker accepts and forwards it ──
  const bg = fs.readFileSync(path.join(EXT, "background.js"), "utf8");

  check(
    /function startMSLogin\(includeOneDrive, includeMailRead, context\)/.test(bg),
    "startMSLogin no longer takes a context parameter"
  );
  check(
    /_startMSLoginInner\(includeOneDrive, includeMailRead, key, context\)/.test(bg),
    "startMSLogin stopped passing context into the flight — the call sites " +
      "still label their messages and the label is dropped on the floor"
  );
  check(
    /async function _startMSLoginInner\([^)]*\bcontext\b[^)]*\)/.test(bg),
    "_startMSLoginInner no longer accepts a context"
  );

  const handlers = bg.match(/startMSLogin\([^)]*\)\.then/g) || [];
  check(
    handlers.length >= 3,
    `expected 3 message handlers calling startMSLogin, found ${handlers.length}`
  );
  handlers.forEach((h) => {
    check(
      /message\.context/.test(h),
      `a startMSLogin call site in the message router drops the context: ${h}`
    );
  });

  // ── and both ends of the funnel carry it ──
  check(
    /const flowContext = context \|\| "unspecified";/.test(bg),
    "the flowContext fallback is gone — an unlabelled call site would emit " +
      "no context at all, which is how an OLD CLIENT looks; the two must " +
      "stay tellable apart"
  );

  const started = /track\("oauth_started",\s*\{[\s\S]{0,400}?\}\);/.exec(bg);
  check(started !== null, "the oauth_started call could not be located");
  check(
    started === null || /context:\s*flowContext/.test(started[0]),
    "oauth_started no longer carries the context — the funnel can be " +
      "filtered at the failure end but not at the attempt end, so any rate " +
      "computed from it mixes populations again"
  );

  const failureCtx = /const failureContext = function[\s\S]{0,500}?\n  \};/.exec(bg);
  check(failureCtx !== null, "failureContext could not be located");
  check(
    failureCtx === null || /context:\s*flowContext/.test(failureCtx[0]),
    "failureContext no longer carries the context — oauth_failed and " +
      "oauth_retry go back to being unattributable"
  );

  return { name: NAME, failures };
}

module.exports = { run };

if (require.main === module) {
  const { failures } = run();
  failures.forEach((f) => console.error("FAIL:", f));
  console.log(failures.length ? `${NAME} FAILED` : `${NAME} ok`);
  process.exit(failures.length ? 1 : 0);
}
