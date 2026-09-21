/**
 * layout-guard.mjs — the layout invariants that jsdom cannot decide.
 *
 * Two acceptance failures here were invisible to the unit suite because both are questions about
 * real layout, and jsdom computes none: every getBoundingClientRect is zero and
 * documentElement.scrollHeight never grows. They need a browser, so they live in their own
 * executable gate rather than in a vitest file that could only pretend to check them.
 *
 * INVARIANT 1 — the page never scrolls.
 *   The shell is a fixed-height simultaneous-surface frame; the header, the scope bar and the
 *   permanent coverage status bar must not be scrollable off screen. Measured before the fix:
 *   documentElement.scrollHeight 3,341px against a 1,080px viewport with a trace open (4,835px at
 *   1440x900), and window.scrollTo(0,500) really moved the frame. The cause was a
 *   position:absolute screen-reader-only box with no offsets escaping its scroller.
 *
 * INVARIANT 2 — the priority queue is never blanked.
 *   The grid's sticky column header is drawn inside its own scroll box. Measured before the fix:
 *   opening a trace collapsed that box to 85px under a 56px header, leaving a 29px strip and 0 of
 *   146 rows hit-testable — clicks aimed at a finding landed on the header's sort button and
 *   silently re-sorted the grid. "Rows exist in the DOM" is not the test; "a row returns ITSELF
 *   from elementFromPoint at its own centre" is, because that is what a click actually does.
 *
 * Run against a dev server or a production preview:
 *   node review/layout-guard.mjs                      # defaults to http://localhost:4180
 *   ATLAS_URL=http://localhost:4181 node review/layout-guard.mjs
 * Exits non-zero on the first violated invariant.
 */
import { chromium } from "@playwright/test";

const APP = process.env["ATLAS_URL"] ?? "http://localhost:4180";
/** A flow that really traces on the shipped snapshot, carried in the URL envelope. */
const SNAP = process.env["ATLAS_SNAP"] ?? "9cc348bd58bb";
const FLOW = encodeURIComponent("10.0.10.50>10.0.30.10>tcp>3389");
/** The grid's own floor: its sticky header plus six rows. Fewer than this is a blanked queue. */
const MIN_HITTABLE_ROWS = 4;
const VIEWPORTS = [
  [1920, 1080],
  [1600, 1000],
  [1440, 900],
  [1280, 800],
];

const probe = () => {
  const de = document.documentElement;
  const rows = [...document.querySelectorAll("#rail-queue .ag__row--data")];
  let hittable = 0;
  const intercepted = [];
  for (const r of rows) {
    const b = r.getBoundingClientRect();
    if (b.width <= 0 || b.height <= 0) continue;
    const el = document.elementFromPoint(
      Math.round(b.left + b.width / 2),
      Math.round(b.top + b.height / 2),
    );
    if (el !== null && r.contains(el)) hittable += 1;
    else if (intercepted.length < 3 && el !== null)
      intercepted.push(`${el.tagName}.${String(el.className).slice(0, 40)}`);
  }
  return {
    docScrollH: de.scrollHeight,
    clientH: de.clientHeight,
    rowsInDom: rows.length,
    hittable,
    intercepted,
    tracePanelPresent: document.querySelector("#rail-path") !== null,
  };
};

const failures = [];
const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });

for (const [w, h] of VIEWPORTS) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  const page = await ctx.newPage();
  for (const [label, url] of [
    ["no trace", `${APP}/`],
    ["with trace", `${APP}/?v=1&snap=${SNAP}&flow=${FLOW}`],
  ]) {
    await page.goto(url, { waitUntil: "load" });
    await page.waitForSelector("#rail-queue .ag__row--data", { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(2500);
    const r = await page.evaluate(probe);
    const at = `${w}x${h} / ${label}`;

    if (r.docScrollH > r.clientH) {
      failures.push(
        `${at}: the page scrolls — documentElement.scrollHeight ${r.docScrollH} > clientHeight ${r.clientH}. ` +
          `The header and the coverage status bar can be scrolled off screen.`,
      );
    }
    if (r.rowsInDom === 0) {
      failures.push(`${at}: no finding rows rendered at all, so the queue could not be checked.`);
    } else if (r.hittable < MIN_HITTABLE_ROWS) {
      failures.push(
        `${at}: only ${r.hittable} of ${r.rowsInDom} finding rows are hit-testable ` +
          `(need >= ${MIN_HITTABLE_ROWS}). Clicks land on ${r.intercepted.join(", ") || "nothing"} instead.`,
      );
    }
    if (label === "with trace" && !r.tracePanelPresent) {
      failures.push(`${at}: the flow did not open the path panel, so this state proves nothing.`);
    }
    console.log(
      `${at}: doc ${r.docScrollH}/${r.clientH}, ${r.hittable}/${r.rowsInDom} rows hit-testable` +
        (label === "with trace" ? `, path panel ${r.tracePanelPresent ? "present" : "ABSENT"}` : ""),
    );
  }
  await ctx.close();
}
await browser.close();

if (failures.length > 0) {
  console.error(`\nlayout-guard: ${failures.length} violation(s)\n` + failures.map((f) => `  - ${f}`).join("\n"));
  process.exit(1);
}
console.log("\nlayout-guard: both invariants hold at every viewport.");
