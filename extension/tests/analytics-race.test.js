/**
 * The analytics queue must survive concurrent writers.
 *
 * _phEnqueue is a read-modify-write over chrome.storage — not atomic. The one
 * moment two writers reliably overlap is SIGN-IN COMPLETION: identify()
 * enqueues $identify while track() enqueues oauth_completed, and before the
 * enqueue was serialized, whichever set() landed second erased the other's
 * event. Because identify() only has work to do on FIRST sign-ins, the race
 * exclusively ate new-user conversion events.
 *
 * This was not theoretical: an Edge 0.1.26 user on 2026-07-30 signed in and
 * sent a real campaign, but their oauth_completed was swallowed ($identify
 * survived — the stream shows $identify + server login + send_completed and
 * no oauth_completed). The resulting "zero Edge completions" figure sent a
 * whole investigation chasing a browser-specific auth bug that did not exist.
 *
 * The stub's storage here resolves through real microtasks, so the interleave
 * that loses an update genuinely occurs with the unserialized code — reverting
 * the _phEnqueueChain serialization in analytics.js turns this suite red.
 */

const { loadAnalytics } = require("./uninstall-stage.test.js");

const ROUNDS = 10;

async function queueEvents(api, store) {
  const q = store[api._PH_QUEUE_KEY] || [];
  return q.map((e) => e.event);
}

async function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  // ── the exact sign-in collision, many rounds (the race is a scheduling
  //    accident — one clean pass proves nothing) ──
  for (let i = 0; i < ROUNDS; i++) {
    const { api, store } = loadAnalytics({});
    await Promise.all([
      api.identify("user-" + i + "@example.com"),
      api.track("oauth_completed", { plan: "free" }),
    ]);
    const events = await queueEvents(api, store);
    if (!events.includes("$identify") || !events.includes("oauth_completed")) {
      failures.push(
        `round ${i}: lost an event to the enqueue race — queue held [${events}] ` +
        `(this is the bug that made a signed-in Edge user look like a failure)`
      );
      break;
    }
  }

  // ── a burst of plain tracks must all land ──
  {
    const { api, store } = loadAnalytics({});
    await Promise.all(
      ["a", "b", "c", "d", "e"].map((n) => api.track("evt_" + n, {}))
    );
    const events = await queueEvents(api, store);
    check(
      events.length === 5,
      `5 concurrent tracks left ${events.length} events in the queue`
    );
  }

  // ── serialization must not break the cap ──
  {
    const { api, store } = loadAnalytics({});
    const names = [];
    for (let i = 0; i < 105; i++) names.push("cap_" + i);
    await Promise.all(names.map((n) => api.track(n, {})));
    const events = await queueEvents(api, store);
    check(events.length <= 100, `queue cap broken: ${events.length} events`);
    check(
      events.includes("cap_104"),
      "the cap must drop the OLDEST events, not the newest"
    );
  }

  return { name: "analytics-race", failures };
}

module.exports = { run };
