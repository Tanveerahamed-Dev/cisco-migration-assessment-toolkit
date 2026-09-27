/**
 * DataGrid.c2-chrome-slice.test.tsx — a grid reveal never slices a navigation strip that shares a
 * scroll container with the grid (acceptance C2).
 *
 * MEASURED (acceptance report C2, 1440x900, both themes, `?s=path&flow=10.0.10.50>10.0.30.10>tcp>3389&hop=0`):
 * the path panel's "Trace a flow | Verify an intent" tab strip was cut by the top edge of Rail A,
 * `visibleFrac 0.40625` under `scrollTop 19`. The rail was not scrolled by the reader or by the path
 * panel: the priority queue's act-view restore called `revealBelowHeader(..., "nearest")` for F001,
 * whose row had slid 19 px below the rail's visible bottom (row 852.7-893.1, port bottom 874), and
 * the NESTED PORTS branch moved the RAIL first although the grid's own visible band (822.7-874,
 * 51.3 px) could show the 40.4 px row by scrolling the grid 20 px. The rail carries the path panel,
 * so the whole panel, tab strip included, moved up 19 px under the rail's top edge.
 *
 * Two rules under test, both stated over the class rather than over that one panel:
 *   1. FITS FIRST. The outer scroller moves first only when the grid's own visible band cannot hold
 *      the row (R106's own reason: a 56 px row in a 12 px band). When it can, the grid scrolls and
 *      no shared ancestor moves.
 *   2. NAVIGATION IS WHOLE OR ABSENT. Whatever part of a reveal does move an ancestor (a rail, a pane,
 *      the document), it never leaves a `[role=tablist]`, `[role=toolbar]` or `[role=menubar]`
 *      outside the grid PARTIALLY visible when it was wholly visible before: the scroll either takes
 *      the strip wholly out of view (when that keeps the row as visible) or stops where the strip is
 *      still whole. A sticky strip never moves with its scroller, so it is never newly cut and is
 *      untouched by the rule.
 * Rule 2 is exercised over a generated family of geometries (band height x row height x align x
 * strip position), not over the one measured layout, and over the three shapes the layout ladder
 * produces: the grid as its own port inside a scrolling rail (>= 48rem), the grid at full height
 * inside a scrolling rail, and the grid at full height in a scrolling document (< 48rem).
 *
 * jsdom lays nothing out, so the page is an explicit model: every element has a content position in
 * its scroll parent, and its viewport rect is derived from every scrollTop above it.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { revealBelowHeader } from "./DataGrid";

interface Box {
  top: number;
  bottom: number;
  height: number;
}

let scrollY = 0;
let maxScrollY = 0;
let viewH = 900;
const originals = {
  scrollBy: window.scrollBy,
  innerHeight: Object.getOwnPropertyDescriptor(window, "innerHeight"),
  scrollY: Object.getOwnPropertyDescriptor(window, "scrollY"),
};

beforeEach(() => {
  scrollY = 0;
  maxScrollY = 0;
  viewH = 900;
  Object.defineProperty(window, "innerHeight", { get: () => viewH, configurable: true });
  Object.defineProperty(window, "scrollY", { get: () => scrollY, configurable: true });
  window.scrollBy = ((x: number | ScrollToOptions, y?: number) => {
    const dy = typeof x === "number" ? (y ?? 0) : (x.top ?? 0);
    scrollY = Math.max(0, Math.min(maxScrollY, Math.round(scrollY + dy)));
  }) as typeof window.scrollBy;
});

afterEach(() => {
  window.scrollBy = originals.scrollBy;
  if (originals.innerHeight) Object.defineProperty(window, "innerHeight", originals.innerHeight);
  if (originals.scrollY) Object.defineProperty(window, "scrollY", originals.scrollY);
  else delete (window as { scrollY?: number }).scrollY;
  document.body.replaceChildren();
});

function rect(top: number, h: number): DOMRect {
  return { x: 0, y: top, width: 400, height: h, top, left: 0, right: 400, bottom: top + h, toJSON: () => ({}) } as DOMRect;
}

/** A scroll port whose scrollTop the browser snaps to whole pixels and clamps to its range. */
function scrollable(el: HTMLElement, clientH: number, scrollH: number): { top: () => number } {
  let t = 0;
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    get: () => t,
    set: (v: number) => {
      t = Math.max(0, Math.min(scrollH - clientH, Math.round(v)));
    },
  });
  Object.defineProperty(el, "scrollHeight", { configurable: true, value: scrollH });
  Object.defineProperty(el, "clientHeight", { configurable: true, value: clientH });
  return { top: () => t };
}

interface RailWorld {
  rail: HTMLElement;
  strip: HTMLElement;
  grid: HTMLElement;
  head: HTMLElement;
  row: HTMLElement;
  railTop: () => number;
  gridTop: () => number;
  band: () => { top: number; bottom: number };
}

interface RailSpec {
  /** Rail A's port in viewport px. */
  portTop: number;
  portH: number;
  /** How far Rail A can scroll at most. */
  railRange: number;
  /** The navigation strip's content position inside the rail. */
  stripAt: number;
  stripH: number;
  /** The grid's box: content position inside the rail, and height. */
  gridAt: number;
  gridH: number;
  /** True: the grid scrolls its own rows (>= 48rem). False: it lays out at full height. */
  ownPort: boolean;
  headH: number;
  /** The row's position inside the grid's rows (below the head), and height. */
  rowAt: number;
  rowH: number;
  role?: "tablist" | "toolbar" | "menubar";
}

/** Rail A in miniature: a scrolling rail holding a panel with a navigation strip and the queue grid. */
function railWorld(s: RailSpec): RailWorld {
  const rail = document.createElement("nav");
  rail.style.overflowY = "scroll";
  const panel = document.createElement("section");
  const strip = document.createElement("div");
  strip.setAttribute("role", s.role ?? "tablist");
  const tab = document.createElement("button");
  tab.setAttribute("role", "tab");
  tab.textContent = "Trace a flow";
  strip.appendChild(tab);
  panel.appendChild(strip);
  const grid = document.createElement("div");
  grid.setAttribute("role", "grid");
  const head = document.createElement("div");
  head.setAttribute("role", "rowgroup");
  const row = document.createElement("div");
  row.setAttribute("role", "row");
  const cell = document.createElement("div");
  cell.setAttribute("role", "gridcell");
  row.appendChild(cell);
  grid.append(head, row);
  rail.append(panel, grid);
  document.body.appendChild(rail);

  const railPort = scrollable(rail, s.portH, s.portH + s.railRange);
  const gridPort = s.ownPort ? scrollable(grid, s.gridH, s.gridH + 5000) : scrollable(grid, s.gridH, s.gridH);
  const inRail = (at: number): number => s.portTop - scrollY + at - railPort.top();
  rail.getBoundingClientRect = () => rect(s.portTop - scrollY, s.portH);
  panel.getBoundingClientRect = () => rect(inRail(s.stripAt), s.stripH);
  strip.getBoundingClientRect = () => rect(inRail(s.stripAt), s.stripH);
  tab.getBoundingClientRect = () => rect(inRail(s.stripAt), s.stripH);
  grid.getBoundingClientRect = () => rect(inRail(s.gridAt), s.gridH);
  head.getBoundingClientRect = () => rect(inRail(s.gridAt), s.headH);
  const rowBox = (): DOMRect => rect(inRail(s.gridAt) + s.headH + s.rowAt - gridPort.top(), s.rowH);
  row.getBoundingClientRect = rowBox;
  cell.getBoundingClientRect = rowBox;
  const band = (): { top: number; bottom: number } => {
    const g = grid.getBoundingClientRect();
    return { top: Math.max(g.top + s.headH, s.portTop - scrollY, 0), bottom: Math.min(g.bottom, s.portTop - scrollY + s.portH, viewH) };
  };
  return { rail, strip, grid, head, row: cell, railTop: railPort.top, gridTop: gridPort.top, band };
}

/** How much of `el` the reader sees through `port` (and the viewport). */
function seenThrough(el: HTMLElement, port: { top: number; bottom: number }): number {
  const r = el.getBoundingClientRect();
  return Math.max(0, Math.min(r.bottom, port.bottom, viewH) - Math.max(r.top, port.top, 0));
}

/** Whole (within a pixel of its height) or absent (under a pixel on screen): never in between. */
function wholeOrAbsent(el: HTMLElement, port: { top: number; bottom: number }): { ok: boolean; seen: number; of: number } {
  const seen = seenThrough(el, port);
  const of = el.getBoundingClientRect().height;
  return { ok: seen <= 1 || seen >= of - 1, seen, of };
}

const inBand = (w: RailWorld): boolean => {
  const r = w.row.getBoundingClientRect() as Box;
  const b = w.band();
  return r.top >= b.top - 1 && r.bottom <= b.bottom + 1;
};

/* The measured 06 layout at 1440x900: rail port 84-874, rail scrollHeight 1015 (range 225), the tab
   strip at the top of the path slot, the grid's band 822.7-874 under a 30 px sticky head, F001 at
   852.7-893.1 (40.4 px). */
const AT_1440: RailSpec = {
  portTop: 84,
  portH: 790,
  railRange: 225,
  stripAt: 0,
  stripH: 32,
  gridAt: 708.7,
  gridH: 300,
  ownPort: true,
  headH: 30,
  rowAt: 30,
  rowH: 40.4,
};

describe("C2: fits first — the grid moves before a shared rail when its own band can hold the row", () => {
  it("the measured 06 layout at 1440: the grid scrolls 20 px, Rail A stays at 0, the tab strip stays whole", () => {
    const w = railWorld(AT_1440);
    const port = { top: 84, bottom: 874 };
    expect(wholeOrAbsent(w.strip, port).seen, "precondition: the tab strip is whole").toBe(32);
    expect(inBand(w), "precondition: F001 has slid below the band").toBe(false);
    revealBelowHeader(w.grid, w.head, w.row, "nearest");
    expect(w.railTop(), "the shared rail did not move (the grid could show the row itself)").toBe(0);
    expect(w.gridTop(), "the grid absorbed the reveal").toBe(20);
    expect(inBand(w), "F001 is whole inside the band").toBe(true);
    expect(wholeOrAbsent(w.strip, port)).toEqual({ ok: true, seen: 32, of: 32 });
    expect(scrollY, "the document never moved").toBe(0);
  });

  it("control (R106 at 1920): a 56 px row in a 12 px band still moves the rail, and the strip leaves whole", () => {
    viewH = 1080;
    const w = railWorld({ ...AT_1440, portTop: 92, portH: 962, railRange: 3000, gridAt: 920, gridH: 600, rowAt: 99, rowH: 56 });
    const port = { top: 92, bottom: 1054 };
    revealBelowHeader(w.grid, w.head, w.row, "nearest");
    expect(w.railTop(), "only the rail can show the row").toBeGreaterThan(0);
    expect(w.gridTop(), "the grid's own port already showed the row: it did not scroll").toBe(0);
    expect(inBand(w)).toBe(true);
    expect(wholeOrAbsent(w.strip, port).ok).toBe(true);
  });
});

describe("C2: navigation is whole or absent after any ancestor half of a reveal", () => {
  it("a row that cannot fit the grid's band, with a small rail move: the strip is taken wholly out, the row stays whole", () => {
    // Band 844-874 (30 px) cannot hold a 40 px row: the rail must move 16 px, which alone cuts the strip in half.
    const w = railWorld({ ...AT_1440, gridAt: 730, rowAt: 6, rowH: 40 });
    const port = { top: 84, bottom: 874 };
    revealBelowHeader(w.grid, w.head, w.row, "nearest");
    const s = wholeOrAbsent(w.strip, port);
    expect(s.ok, `the strip is whole or gone, not ${s.seen} of ${s.of} px`).toBe(true);
    expect(inBand(w), "the row is whole").toBe(true);
  });

  it("where the rail cannot move far enough to take the strip out, it stops where the strip is still whole", () => {
    // Same, but the rail can scroll only 20 px: 16 px would cut the strip, 32 px is out of reach.
    const w = railWorld({ ...AT_1440, railRange: 20, gridAt: 730, rowAt: 6, rowH: 40 });
    const port = { top: 84, bottom: 874 };
    revealBelowHeader(w.grid, w.head, w.row, "nearest");
    const s = wholeOrAbsent(w.strip, port);
    expect(s.ok, `the strip is whole or gone, not ${s.seen} of ${s.of} px`).toBe(true);
    expect(w.railTop()).toBe(0);
  });

  it("a toolbar below the grid is not cut by the rail's bottom edge when a reveal scrolls the rail up", () => {
    // Grid at full height inside the rail (a narrow layout); the row sits partly above the port's top.
    const w = railWorld({
      portTop: 0,
      portH: 400,
      railRange: 4000,
      stripAt: 880,
      stripH: 30,
      gridAt: 0,
      gridH: 860,
      ownPort: false,
      headH: 0,
      rowAt: 500,
      rowH: 60,
      role: "toolbar",
    });
    w.rail.scrollTop = 530; // the row at -30..30, the toolbar at 350-380: whole
    const port = { top: 0, bottom: 400 };
    expect(wholeOrAbsent(w.strip, port).seen).toBe(30);
    viewH = 900;
    revealBelowHeader(w.grid, null, w.row, "nearest");
    const s = wholeOrAbsent(w.strip, port);
    expect(s.ok, `the toolbar is whole or gone, not ${s.seen} of ${s.of} px`).toBe(true);
    const r = w.row.getBoundingClientRect();
    expect(r.top >= 0 && r.bottom <= 400, "the row is whole").toBe(true);
  });

  it("the phone shape: the document scrolls the grid, and a tab strip above is not cut by the viewport's edge", () => {
    viewH = 844;
    maxScrollY = 20_000;
    scrollY = 990;
    const strip = document.createElement("div");
    strip.setAttribute("role", "tablist");
    const grid = document.createElement("div");
    grid.setAttribute("role", "grid");
    Object.defineProperty(grid, "scrollTop", { get: () => 0, set: () => undefined, configurable: true });
    const row = document.createElement("div");
    row.setAttribute("role", "row");
    grid.appendChild(row);
    document.body.append(strip, grid);
    const at = (el: HTMLElement, pageTop: number, h: number): void => {
      el.getBoundingClientRect = () => rect(pageTop - scrollY, h);
    };
    at(strip, 1020, 40); // 30-70: whole; a 50 px page scroll alone leaves 20 of its 40 px
    at(grid, 1100, 6000);
    at(row, 1850, 34); // 860-894: below the fold
    revealBelowHeader(grid, null, row, "nearest");
    const s = wholeOrAbsent(strip, { top: 0, bottom: viewH });
    expect(s.ok, `the strip is whole or gone, not ${s.seen} of ${s.of} px`).toBe(true);
    const r = row.getBoundingClientRect();
    expect(r.top >= 0 && r.bottom <= viewH, "the row is on screen").toBe(true);
  });

  it("a strip taken out past the row's remainder hands the outer scrollers nothing (no scroll back)", () => {
    /* The full-height shape inside a SCROLLED document (C2 verifier V2): the rail moves 16 px to
       show the row, which cuts the 32 px strip at its top edge; the take-out moves on to 32 px. That
       overshoot already revealed the row, so the document — the next scroller out — must not move.
       Before the fix the remainder went to -16 and the document scrolled BACK 16 px. */
    viewH = 900;
    maxScrollY = 1000;
    scrollY = 500;
    const w = railWorld({
      portTop: 84 + 500,
      portH: 790,
      railRange: 400,
      stripAt: 0,
      stripH: 32,
      gridAt: 400,
      gridH: 500,
      ownPort: false,
      headH: 0,
      rowAt: 790 - 400 - 32 + 16, // 774-806 in the rail: 16 px below its bottom edge (790)
      rowH: 32,
    });
    const port = { top: 84, bottom: 874 };
    expect(wholeOrAbsent(w.strip, port).seen, "precondition: the strip is whole").toBe(32);
    expect(inBand(w), "precondition: the row is below the rail's bottom edge").toBe(false);
    revealBelowHeader(w.grid, null, w.row, "nearest");
    expect(scrollY, "the document must not move when the rail alone showed the row").toBe(500);
    const s = wholeOrAbsent(w.strip, port);
    expect(s.ok, `the strip is whole or gone, not ${s.seen} of ${s.of} px`).toBe(true);
    expect(w.railTop(), "the rail took the strip wholly out").toBe(32);
    expect(inBand(w), "the row is whole").toBe(true);
  });
});

/* The class, generated: every band height from 4 to 120 px against three row heights, both aligns,
   the strip at three positions in the rail, the three strip roles, and both rail shapes of the
   ladder (the grid as its own port, >= 48rem; the grid at full height inside the rail) — all inside a
   document that is itself scrolled and CAN scroll either way, so "the document never moved" is an
   assertion that can fail. Whatever the reveal does, the strip is whole or absent afterwards, the
   document never moves (the rail can always show the row), and the row is at least as visible as it
   was before the reveal.

   One test per (role, strip position, row height, rail shape) — a group is a few dozen reveals — so
   no single test's unit of work races the runner's hang limit (vitest.config.ts: a large unit of
   work is split one record per test, not given a bigger limit). The family's DENOMINATORS are then
   asserted over the same generator by the last test, from memoized group results, so the family
   cannot silently shrink: run alone (`-t`), that test runs every group itself. */
const DOC_Y = 500;
interface Tally {
  cases: number;
  railMoves: number;
  takenOut: number;
  bad: string[];
}
interface Group {
  key: string;
  role: "tablist" | "toolbar" | "menubar";
  stripAt: number;
  rowH: number;
  ownPort: boolean;
}
const GROUPS: Group[] = [];
for (const role of ["tablist", "toolbar", "menubar"] as const)
  for (const stripAt of [0, 120, 400])
    for (const rowH of [24, 40.4, 56])
      for (const ownPort of [true, false])
        GROUPS.push({ key: `${role}@${stripAt} row ${rowH} ${ownPort ? "own port" : "full height"}`, role, stripAt, rowH, ownPort });

const tallies = new Map<string, Tally>();
function runGroup(g: Group): Tally {
  const done = tallies.get(g.key);
  if (done !== undefined) return done;
  const t: Tally = { cases: 0, railMoves: 0, takenOut: 0, bad: [] };
  for (let bandH = 4; bandH <= 120; bandH += 4) {
    for (const align of ["nearest", "centre"] as const) {
      document.body.replaceChildren();
      viewH = 900;
      maxScrollY = 2 * DOC_Y;
      scrollY = DOC_Y;
      const portTop = 84;
      const portH = 790;
      // The grid's head bottom sits bandH above the rail's bottom edge; the row just below the band.
      const headBottom = portTop + portH - bandH;
      const gridAt = headBottom - 30 - portTop;
      if (g.stripAt + 32 > gridAt) continue; // the strip must sit above the grid
      const w = railWorld({
        ...AT_1440,
        portTop: portTop + DOC_Y,
        ownPort: g.ownPort,
        role: g.role,
        stripAt: g.stripAt,
        gridAt,
        /* Half the row below the band; never above the first row slot (a row cannot sit above the
           grid's own content start, under the sticky head, in any real layout). */
        rowAt: Math.max(0, bandH - g.rowH / 2),
        rowH: g.rowH,
      });
      const port = { top: portTop, bottom: portTop + portH };
      const seenBefore = seenThrough(w.row, w.band());
      revealBelowHeader(w.grid, w.head, w.row, align);
      t.cases += 1;
      if (w.railTop() > 0) t.railMoves += 1;
      const s = wholeOrAbsent(w.strip, port);
      if (s.ok && s.seen <= 1) t.takenOut += 1;
      const seenAfter = seenThrough(w.row, w.band());
      const tag = `${g.key} band ${bandH} ${align}`;
      if (!s.ok) t.bad.push(`${tag}: strip ${s.seen.toFixed(1)} of ${s.of} px (rail ${w.railTop()})`);
      if (seenAfter + 0.5 < Math.min(seenBefore, g.rowH)) t.bad.push(`${tag}: row lost visibility ${seenBefore.toFixed(1)} -> ${seenAfter.toFixed(1)}`);
      if (scrollY !== DOC_Y) t.bad.push(`${tag}: the document moved ${scrollY - DOC_Y}`);
    }
  }
  tallies.set(g.key, t);
  return t;
}

describe("C2: over a generated family of rail geometries, no reveal leaves a strip partly visible", () => {
  it.each(GROUPS.map((g) => [g.key, g] as const))("%s", (_key, g) => {
    const t = runGroup(g);
    expect(t.cases, "the group is not empty").toBeGreaterThan(0);
    expect(t.bad).toEqual([]);
  });

  it("the family's denominators: every group ran, and the family exercises rail moves and take-outs", () => {
    let cases = 0;
    let railMoves = 0;
    let takenOut = 0;
    let fullHeightMoves = 0;
    for (const g of GROUPS) {
      const t = runGroup(g);
      cases += t.cases;
      railMoves += t.railMoves;
      takenOut += t.takenOut;
      if (!g.ownPort) fullHeightMoves += t.railMoves;
    }
    expect(GROUPS.length, "3 roles x 3 strip positions x 3 row heights x 2 rail shapes").toBe(54);
    expect(cases, "the family is not empty").toBeGreaterThan(600);
    expect(railMoves, "the family includes reveals that must move the rail (a band shorter than the row)").toBeGreaterThan(100);
    expect(fullHeightMoves, "the full-height shape moves the rail inside a scrollable document").toBeGreaterThan(50);
    expect(takenOut, "the family includes strips a rail move takes wholly out of view").toBeGreaterThan(0);
  });
});
