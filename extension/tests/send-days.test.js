/**
 * The day picker means what it says, and reaches the server.
 *
 * Hélène Carpentier asked for this on 2026-09-02: "I do not need to send
 * emails on saturdays and sundays." Her campaign is cold outreach to workplace
 * leads at large corporates, where a Sunday-morning send reads as machinery.
 *
 * Two ways to get it wrong, neither of which any existing suite can see, and
 * both of which were in the first cut:
 *
 *  1. The labels came from Intl without timeZone:"UTC" while the dates are UTC
 *     midnights. West of UTC every label slid back one day, so the boxes read
 *     Sun..Sat while carrying ISO 1..7. A New York user unticking "Sat" and
 *     "Sun" would have switched off Sunday and MONDAY, and the campaign would
 *     have sent on Saturday — the exact day the feature exists to avoid. It
 *     would have looked correct in Paris, where the person who asked for it
 *     lives, and wrong for the users in the US.
 *
 *  2. readSendDays() was called inside `if (dailyCap > 0 && scheduledFor)`, so
 *     scheduling without a daily limit showed the picker, accepted the ticks
 *     and threw them away. The worker honours send_days with or without a cap.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const EXT = path.join(__dirname, "..");
const SRC = fs.readFileSync(path.join(EXT, "sidebar.js"), "utf8");

// ISO weekday -> the English short name it must be labelled with.
const ISO_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function renderIn(timeZoneOffsetLabel) {
  /* Build the checkbox rows the way renderSendDays does, under a formatter
     pinned to a specific zone — standing in for a viewer in that zone. */
  const grab = (re, what) => {
    const m = re.exec(SRC);
    if (!m) throw new Error(`could not find ${what} in sidebar.js`);
    return m[0];
  };
  const fn = grab(/function renderSendDays[\s\S]*?\n  \}\n/, "renderSendDays()");

  const rows = [];
  const ctx = {
    Intl,
    Date,
    getActiveLocale: () => "en",
    document: {
      getElementById: () => ({
        childElementCount: 0,
        appendChild: (el) => rows.push(el),
      }),
      createElement: (tag) => ({
        tag,
        children: [],
        appendChild(c) { this.children.push(c); },
        set className(v) { this._class = v; },
        get className() { return this._class; },
      }),
      createTextNode: (t) => ({ text: t }),
    },
  };
  vm.createContext(ctx);
  vm.runInContext(fn + "\nrenderSendDays();", ctx);

  return rows.map((row) => {
    const box = row.children.find((c) => c.tag === "input");
    const text = row.children.find((c) => c.text !== undefined);
    return { iso: Number(box.value), label: (text.text || "").trim() };
  });
}

function run() {
  const failures = [];
  const check = (cond, label) => { if (!cond) failures.push(label); };

  // ── 1. the label on a box must name the day that box stores ──

  // Run the real function under a process pinned west of UTC. That is where
  // the bug lives; in Istanbul (UTC+3) it is invisible.
  const original = process.env.TZ;
  let rows;
  try {
    process.env.TZ = "America/New_York";
    rows = renderIn("America/New_York");
  } catch (e) {
    return { name: "send-days", failures: ["renderSendDays threw: " + e.message] };
  } finally {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  }

  check(rows.length === 7, `expected 7 day boxes, got ${rows.length}`);

  rows.forEach((row, i) => {
    check(
      row.iso === i + 1,
      `box ${i} carries ISO ${row.iso}, expected ${i + 1}`
    );
    check(
      row.label === ISO_NAMES[i],
      `in New York, the box storing ISO ${row.iso} (${ISO_NAMES[i]}) is ` +
        `labelled "${row.label}". A user unticking the boxes marked Sat and ` +
        `Sun would switch off different days than they read, and the ` +
        `campaign would send on a weekend.`
    );
  });

  // ── 2. the ticks have to reach the payload ──

  check(
    !/if \(dailyCap > 0 && scheduledFor\) \{[\s\S]{0,400}?readSendDays\(\)/.test(SRC),
    "readSendDays() is inside the daily-cap branch again, so scheduling " +
      "without a daily limit shows the picker and discards the answer"
  );
  check(
    /if \(scheduledFor\) \{[\s\S]{0,600}?var chosenDays = readSendDays\(\)/.test(SRC),
    "the day picker is no longer read on the plain scheduled path"
  );

  // ── 3. the guard that keeps the payload backward-compatible ──

  check(
    /chosenDays\.length < 7/.test(SRC),
    "all seven days ticked now sends send_days explicitly — same meaning, " +
      "but it stops being a payload older backends have always accepted"
  );

  return { name: "send-days", failures };
}

module.exports = { run };

if (require.main === module) {
  const r = run();
  r.failures.forEach((f) => console.error("FAIL:", f));
  console.log(r.failures.length ? `${r.name}: ${r.failures.length} failure(s)` : `${r.name}: ok`);
  process.exit(r.failures.length ? 1 : 0);
}
