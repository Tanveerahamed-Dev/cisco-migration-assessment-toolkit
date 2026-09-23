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
 * INVARIANT 3 — every citation in the evidence rail can be clicked.
 *   A citation a pointer user cannot open is an evidence chain that is only half reachable. The
 *   2026-09-21 critic (B6) found one blocked citation on EVERY device Summary tab: the Failure-impact
 *   comparison split the 420px rail into two columns and a neighbouring column's key label covered
 *   the other column's citation. Every visible `button.ui-cite` in #rail-evidence is scrolled into
 *   view and must return ITSELF from elementFromPoint at its centre — the whole class of citations,
 *   not the one that was reported.
 *
 * INVARIANT 4 — every hop header names its host and fits its box.
 *   `.hop__host` was 0 px wide on the denied flow's header and the row overflowed by 174-214 px at
 *   every width (2026-09-23, A2): a verdict with no place attached. Checked on every hop header of
 *   three traced states at 390, 768, 1440 and 1920.
 *
 * Run against a dev server or a production preview:
 *   node review/layout-guard.mjs                      # defaults to http://localhost:4180
 *   ATLAS_URL=http://localhost:4181 node review/layout-guard.mjs
 * Exits non-zero on the first violated invariant.
 */
import { readFileSync } from "node:fs";
import { chromium } from "@playwright/test";

const APP = process.env["ATLAS_URL"] ?? "http://localhost:4180";
/** A flow that really traces on the shipped snapshot, carried in the URL envelope. */
/* The snapshot tag the app writes into its URL envelope, DERIVED — never typed in. It used to be the
   literal `9cc348bd…`, which went stale the moment the compiled source binding changed (O15): every
   run would then have opened a snapshot-mismatch page and measured that instead. The tag is the first
   SNAP_LEN hex characters of fabric.json's meta.sourceSha256, exactly as src/app/urlSync.ts builds it;
   both halves are read from those files, and a missing half stops the run rather than guessing. */
const snapshotTag = () => {
  const fabricMeta = JSON.parse(readFileSync(new URL("../src/data/fabric.json", import.meta.url), "utf8")).meta;
  const sync = readFileSync(new URL("../src/app/urlSync.ts", import.meta.url), "utf8");
  const len = Number(/const SNAP_LEN = (\d+);/.exec(sync)?.[1]);
  const sha = fabricMeta?.sourceSha256;
  if (typeof sha !== "string" || !/^[0-9a-f]{64}$/.test(sha) || !Number.isInteger(len) || len <= 0) {
    throw new Error("layout-guard: cannot derive the snapshot tag from src/data/fabric.json + src/app/urlSync.ts");
  }
  return sha.slice(0, len);
};
const SNAP = process.env["ATLAS_SNAP"] ?? snapshotTag();
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
    /* INVARIANT 2b: the queue never paints under the status bar. Hit-testing alone cannot see
       this: a row under the bar simply is not counted, so 6 rows passed while the grid box ran
       37px past the bar at 1920x1080 with a trace open (2026-09-22 audit, A4). The PAINTED box is
       the grid clipped by every clipping ancestor, which must end at or above the bar. */
    queuePaintBottom: (() => {
      const g = document.querySelector("#rail-queue .ag__grid");
      if (!g) return null;
      let bottom = g.getBoundingClientRect().bottom;
      for (let a = g.parentElement; a; a = a.parentElement) {
        if (getComputedStyle(a).overflowY !== "visible") bottom = Math.min(bottom, a.getBoundingClientRect().bottom);
      }
      return Math.round(bottom);
    })(),
    statusTop: Math.round(document.querySelector(".app__status")?.getBoundingClientRect().top ?? Infinity),
  };
};

/** Device Summary tabs the critic swept, plus one of each kind, so the check spans layouts. */
const CITE_DEVICES = ["core1", "core2", "access13", "wan-edge-rtr1.lab"];

const citeProbe = () => {
  const blocked = [];
  let checked = 0;
  for (const b of document.querySelectorAll("#rail-evidence button.ui-cite")) {
    b.scrollIntoView({ block: "center", inline: "nearest" });
    const r = b.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    checked += 1;
    const el = document.elementFromPoint(Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2));
    if (el === null || !(el === b || b.contains(el)))
      blocked.push(`${(b.getAttribute("aria-label") ?? b.textContent ?? "").slice(0, 60)} covered by ${el === null ? "nothing" : `${el.tagName}.${String(el.className).slice(0, 30)}`}`);
  }
  return { checked, blocked };
};

const failures = [];
const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });

/* `LAYOUT_GUARD_ONLY=hop` runs invariant 4 alone (a fast re-check while fixing a header). The full
   run, which is the gate, runs everything; the verdict line says which was run. */
const ONLY = process.env["LAYOUT_GUARD_ONLY"] ?? null;
for (const [w, h] of ONLY === "hop" ? [] : VIEWPORTS) {
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
    if (r.queuePaintBottom !== null && r.queuePaintBottom > r.statusTop) {
      failures.push(
        `${at}: the findings grid paints to y=${r.queuePaintBottom}, ${r.queuePaintBottom - r.statusTop}px under the status bar (top ${r.statusTop}). ` +
          `Rows there are drawn across the coverage text and a reveal cannot trust the grid box.`,
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
  for (const d of CITE_DEVICES) {
    await page.goto(`${APP}/?v=1&snap=${SNAP}&s=evidence&d=${encodeURIComponent(d)}`, { waitUntil: "load" });
    await page.waitForSelector("#rail-evidence button.ui-cite", { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(1000);
    const c = await page.evaluate(citeProbe);
    const at = `${w}x${h} / ${d} summary`;
    if (c.checked === 0) failures.push(`${at}: no citation rendered in the evidence rail, so it could not be checked.`);
    for (const b of c.blocked) failures.push(`${at}: citation not clickable — ${b}.`);
    console.log(`${at}: ${c.checked - c.blocked.length}/${c.checked} citations hit-testable`);
  }
  await ctx.close();
}
/* INVARIANT 4 — a hop header names its host, and nothing in it runs past its edge.
     Measured 2026-09-23 (acceptance report, A2): on the denied flow's header the verdict badge
     ("denied by ACL PROTECT_SERVERS — reached by routing from an incomplete table") is `flex: none;
     white-space: nowrap`, so it took the whole row and squeezed `.hop__host` to 0 px — the header
     answered "denied" without saying WHERE — and the row overflowed by 174-214 px at every tested
     width. Checked over EVERY hop header of each traced state, at the four widths the ladder spans,
     not over the one header that was reported. */
const HOP_FLOWS = [
  "10.0.10.50>10.0.30.10>tcp>3389",
  "10.0.10.50>10.0.20.10>tcp>443",
  "10.0.40.50>10.0.30.10>tcp>443",
];
const hopProbe = () =>
  [...document.querySelectorAll("#rail-path .hop__head")].map((h) => {
    const host = h.querySelector(".hop__host");
    const hb = host?.getBoundingClientRect();
    return {
      host: host?.textContent ?? "(none)",
      hostW: hb ? Math.round(hb.width) : -1,
      hostClipped: host ? host.scrollWidth - host.clientWidth : 0,
      over: h.scrollWidth - h.clientWidth,
    };
  });
for (const [w, h] of [[390, 844], [768, 1024], [1440, 900], [1920, 1080]]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  const page = await ctx.newPage();
  for (const flow of HOP_FLOWS) {
    await page.goto(`${APP}/?v=1&snap=${SNAP}&s=path&flow=${encodeURIComponent(flow)}`, { waitUntil: "load" });
    await page.waitForSelector("#rail-path .hop__head", { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(500);
    const heads = await page.evaluate(hopProbe);
    const at = `${w}x${h} / ${flow}`;
    if (heads.length === 0) failures.push(`${at}: no hop header rendered, so the header could not be checked.`);
    for (const r of heads) {
      if (r.hostW <= 0) failures.push(`${at}: the hop header's host "${r.host}" is ${r.hostW} px wide — the header does not say where.`);
      else if (r.hostClipped > 0) failures.push(`${at}: the hop header's host "${r.host}" is cut by ${r.hostClipped} px.`);
      if (r.over > 0) failures.push(`${at}: the hop header for "${r.host}" overflows its box by ${r.over} px.`);
    }
    console.log(`${at}: ${heads.map((r) => `${r.host} ${r.hostW}px, overflow ${r.over}px`).join("; ") || "no hop headers"}`);
  }
  await ctx.close();
}

/* INVARIANT 5 — the single-column band (768-1023 px) with no trace open: the queue ends at its
     rail, and focusing a finding never scrolls the frame.
     Measured 2026-09-23 (repair wave 3, R1/R3): `.rail--a` was a flex column with overflow visible
     and the findings grid kept its own 19rem floor, so the grid ran past its rail, under the status
     bar and off screen — 1000x800 grid 698-1002 vs rail 494-774 (status bar 774-800); 900x700 grid
     652-956 vs rail 448-674; 800x600 grid 650-954 vs rail 446-574. At 800x600, focusing the grid's
     first cell scrolled the overflow-hidden `.app` frame itself: the status bar's top moved from 574
     to 220 and the header scrolled away. Invariants 1-2b were checked only at >=1280, where the
     band never runs. */
const bandProbe = () => {
  const app = document.querySelector(".app");
  const rail = document.querySelector(".rail--a")?.getBoundingClientRect();
  const status = document.querySelector(".app__status")?.getBoundingClientRect();
  const header = document.querySelector(".app__header")?.getBoundingClientRect();
  const g = document.querySelector("#rail-queue .ag__grid");
  let paint = g ? g.getBoundingClientRect().bottom : null;
  if (g) for (let a = g.parentElement; a; a = a.parentElement) if (getComputedStyle(a).overflowY !== "visible") paint = Math.min(paint, a.getBoundingClientRect().bottom);
  const f = document.activeElement;
  const fr = f && f !== document.body ? f.getBoundingClientRect() : null;
  return {
    docScrollH: document.documentElement.scrollHeight,
    clientH: document.documentElement.clientHeight,
    appScrollTop: app ? app.scrollTop : -1,
    railBottom: rail ? Math.round(rail.bottom) : null,
    statusTop: status ? Math.round(status.top) : null,
    headerTop: header ? Math.round(header.top) : null,
    paintBottom: paint === null ? null : Math.round(paint),
    focusedInGrid: !!(f && g && g.contains(f)),
    focusTop: fr ? Math.round(fr.top) : null,
    focusBottom: fr ? Math.round(fr.bottom) : null,
  };
};
for (const [w, h] of ONLY === "hop" ? [] : [[1000, 800], [900, 700], [800, 600]]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  const page = await ctx.newPage();
  await page.goto(`${APP}/`, { waitUntil: "load" });
  await page.waitForSelector("#rail-queue .ag__row--data", { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const at = `${w}x${h} / single column, no trace`;
  const before = await page.evaluate(bandProbe);
  if (before.docScrollH > before.clientH) failures.push(`${at}: the page scrolls (${before.docScrollH} > ${before.clientH}).`);
  if (before.paintBottom === null) failures.push(`${at}: no findings grid rendered, so the band could not be checked.`);
  else if (before.paintBottom > before.statusTop)
    failures.push(`${at}: the findings grid paints to y=${before.paintBottom}, ${before.paintBottom - before.statusTop}px under the status bar (top ${before.statusTop}).`);
  /* Reach the grid's one tab stop the way a keyboard reader does: focus it, then a key (Shift binds
     nothing) so :focus-visible and the grid's reveal both run. */
  const reached = await page.evaluate(() => {
    const stop = document.querySelector('#rail-queue [role="grid"] [tabindex="0"]');
    if (!stop) return false;
    stop.focus();
    return document.activeElement === stop;
  });
  await page.keyboard.press("Shift");
  await page.waitForTimeout(500);
  const after = await page.evaluate(bandProbe);
  if (!reached || !after.focusedInGrid) failures.push(`${at}: the grid's tab stop could not be focused, so the reveal was not checked.`);
  else {
    if (after.appScrollTop !== 0 || after.statusTop !== before.statusTop || after.headerTop !== before.headerTop)
      failures.push(
        `${at}: focusing the grid scrolled the frame — .app scrollTop ${after.appScrollTop}, status bar top ${before.statusTop} -> ${after.statusTop}, header top ${before.headerTop} -> ${after.headerTop}.`,
      );
    if (after.focusBottom > after.statusTop || after.focusBottom > after.railBottom)
      failures.push(`${at}: the focused cell (y ${after.focusTop}-${after.focusBottom}) is under the status bar (top ${after.statusTop}) or past its rail (bottom ${after.railBottom}).`);
  }
  console.log(
    `${at}: grid paints to ${before.paintBottom} (status ${before.statusTop}); after focus .app scrollTop ${after.appScrollTop}, ` +
      `status ${after.statusTop}, focused cell ${after.focusTop}-${after.focusBottom}, rail bottom ${after.railBottom}`,
  );
  await ctx.close();
}
await browser.close();

if (failures.length > 0) {
  console.error(`\nlayout-guard: ${failures.length} violation(s)\n` + failures.map((f) => `  - ${f}`).join("\n"));
  process.exit(1);
}
console.log(ONLY === "hop" ? "\nlayout-guard: invariant 4 (hop headers) holds at every width; invariants 1-3 and 5 were NOT run." : "\nlayout-guard: all five invariants hold at every viewport.");
