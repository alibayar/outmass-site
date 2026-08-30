/**
 * A datetime-local input must never be filled from toISOString().
 *
 * `<input type="datetime-local">` holds a wall-clock string with no zone,
 * and the browser reads it as the user's LOCAL time. toISOString() renders
 * an instant in UTC. Put one in the other and the value arrives shifted by
 * the reader's own offset — silently, and only for people who are not on
 * UTC, which is almost everyone.
 *
 * The scheduled-send default did exactly that from the day it was written.
 * It built "tomorrow 09:00" in local time, converted to UTC, and handed the
 * UTC string to the picker:
 *
 *   UTC      09:00   (the only place it was ever right)
 *   London   08:00
 *   Istanbul 06:00
 *   Beijing  01:00
 *
 * So a Chinese user opening Scheduled sending was offered one in the
 * morning as the obvious choice. A default is a suggestion most people
 * accept, and this one was wrong for every user outside UTC for as long as
 * the feature has existed.
 *
 * Found on 2026-08-30 by an unrelated question — working out which timezone
 * a customer had scheduled her campaign from — which is the kind of luck a
 * test is meant to replace.
 *
 * The reverse direction is correct and must stay: reading the input with
 * `new Date(value).toISOString()` to send to the API turns a local
 * wall-clock into a real instant, which is exactly right. Only the write
 * direction is the trap, so this checks that direction alone.
 */

const fs = require("fs");
const path = require("path");

const EXT = path.join(__dirname, "..");
const NAME = "local-datetime";

const FILES = ["sidebar.js", "popup.js", "content_script.js", "background.js"];

function run() {
  const failures = [];
  const check = (cond, label) => {
    if (!cond) failures.push(label);
  };

  let scanned = 0;

  for (const file of FILES) {
    const p = path.join(EXT, file);
    if (!fs.existsSync(p)) continue;
    const src = fs.readFileSync(p, "utf8");
    scanned += 1;

    // Assignments into a datetime input, anywhere on the right-hand side of
    // which an ISO instant appears. Deliberately generous about the left
    // side (dtInput.value, el.value, foo.value) and strict about the right.
    const lines = src.split("\n");
    lines.forEach((line, i) => {
      const assignsValue = /\.value\s*=/.test(line);
      const hasIso = /toISOString\s*\(\s*\)/.test(line);
      if (assignsValue && hasIso) {
        failures.push(
          `${file}:${i + 1}: an ISO instant is assigned to a .value — if the ` +
            "target is a datetime-local input, every user off UTC gets a time " +
            "shifted by their own offset. Build the string from getFullYear/" +
            "getMonth/getDate/getHours/getMinutes instead: " +
            line.trim().slice(0, 90)
        );
      }
    });

    // The same mistake split over two lines, which is how it would come back
    // after someone "tidied" the one-liner.
    const joined = src.replace(/\n\s*/g, " ");
    const twoLine = joined.match(/\.value\s*=\s*[^;]{0,120}toISOString\s*\(\s*\)/g) || [];
    twoLine.forEach((m) => {
      const flat = m.replace(/\s+/g, " ").trim();
      if (!failures.some((f) => f.includes(flat.slice(0, 40)))) {
        failures.push(
          `${file}: an ISO instant reaches a .value across a line break: ${flat.slice(0, 100)}`
        );
      }
    });
  }

  // The check is worthless if it stopped finding the files.
  check(
    scanned >= 3,
    `only ${scanned} of ${FILES.length} panel files were scanned — the paths ` +
      "have moved and this suite is asserting nothing"
  );

  // And the fixed site must still be building a local wall-clock string.
  const sidebar = fs.readFileSync(path.join(EXT, "sidebar.js"), "utf8");
  check(
    /tomorrow\.getFullYear\(\)/.test(sidebar) &&
      /tomorrow\.getHours\(\)/.test(sidebar),
    "the scheduled-send default no longer builds its value from local " +
      "getters; if it has gone back to an ISO string, the offset bug is back"
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
