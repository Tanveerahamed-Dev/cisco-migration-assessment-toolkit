/**
 * DataGrid.c2-overlay-slice.test.tsx — NAVIGATION IS WHOLE OR ABSENT counts what PAINTS OVER a strip,
 * not only what clips it (C2 verifier m3).
 *
 * The C2 guard (`keepNavWhole`, fed by `onScreenExtent`) measured a navigation strip's on-screen
 * extent by intersecting its box with the viewport and every clipping ancestor. An OVERLAY is not a
 * clip: below 48rem the status bar is `position: sticky; bottom: 0` (shell.css, `.app__status`; 85 px
 * tall at 390x844, measured D3 wave 8), and a strip the reveal slides partly under it is cut for the
 * reader exactly as if the viewport's edge had cut it — yet the guard read it as whole and let the
 * reveal leave it sliced. The grid's own band has trimmed overlays since D3 (`trimOverlays`); the
 * strip's extent now answers the same question, with one difference that matters for a small strip:
 * an overlay covering ALL of what the clips leave makes the strip absent (0 px seen), not whole.
 *
 * One test per rung of the layout ladder, each with the overlay where that rung can have one:
 *   - < 48rem: the document scrolls a full-height grid; the sticky status bar covers the viewport's
 *     bottom; a reveal that scrolls the page UP slides a toolbar below the row under the bar.
 *   - the grid at full height inside a scrolling rail; a footer painted over the rail's bottom.
 *   - >= 48rem: the grid is its own port inside a scrolling rail whose band cannot hold the row, so the
 *     rail moves; a bar painted over the rail's top edge.
 * Whatever the reveal does, the strip is whole or absent against clips AND overlays, and the row is
 * on screen and uncovered afterwards.
 *
 * jsdom lays nothing out and has no hit testing, so both are an explicit model: every element has a
 * content position in its scroll parent, its viewport rect derives from every scrollTop above it, and
 * `document.elementsFromPoint` answers from the same boxes, top-most (the overlay) first.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { revealBelowHeader } from "./DataGrid";

let scrollY = 0;
let maxScrollY = 0;
let viewH = 900;
const originals = {
  scrollBy: window.scrollBy,
  innerHeight: Object.getOwnPropertyDescriptor(window, "innerHeight"),
  scrollY: Object.getOwnPropertyDescriptor(window, "scrollY"),
};
type Doc = Document & { elementsFromPoint?: (x: number, y: number) => Element[]; elementFromPoint?: (x: number, y: number) => Element | null };
/** The modelled paint order, top-most first: each element with its current viewport box. */
let paint: { el: Element; box: () => { top: number; bottom: number } }[] = [];

beforeEach(() => {
  scrollY = 0;
  maxScrollY = 0;
  viewH = 900;
  paint = [];
  Object.defineProperty(window, "innerHeight", { get: () => viewH, configurable: true });
  Object.defineProperty(window, "scrollY", { get: () => scrollY, configurable: true });
  window.scrollBy = ((x: number | ScrollToOptions, y?: number) => {
    const dy = typeof x === "number" ? (y ?? 0) : (x.top ?? 0);
    scrollY = Math.max(0, Math.min(maxScrollY, Math.round(scrollY + dy)));
  }) as typeof window.scrollBy;
  const doc = document as Doc;
  doc.elementsFromPoint = (_x: number, y: number): Element[] => {
    const out: Element[] = [];
    for (const p of paint) {
      const b = p.box();
      if (y >= b.top && y < b.bottom) out.push(p.el);
    }
    out.push(document.body, document.documentElement);
    return out;
  };
  doc.elementFromPoint = (x: number, y: number): Element | null => doc.elementsFromPoint!(x, y)[0] ?? null;
});

afterEach(() => {
  window.scrollBy = originals.scrollBy;
  if (originals.innerHeight) Object.defineProperty(window, "innerHeight", originals.innerHeight);
  if (originals.scrollY) Object.defineProperty(window, "scrollY", originals.scrollY);
  else delete (window as { scrollY?: number }).scrollY;
  delete (document as { elementsFromPoint?: unknown }).elementsFromPoint;
  delete (document as { elementFromPoint?: unknown }).elementFromPoint;
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

/** A strip of one control, with a role from the navigation class. */
function stripOf(role: "tablist" | "toolbar" | "menubar", label: string): { strip: HTMLElement; control: HTMLElement } {
  const strip = document.createElement("div");
  strip.setAttribute("role", role);
  const control = document.createElement("button");
  if (role === "tablist") control.setAttribute("role", "tab");
  control.textContent = label;
  strip.appendChild(control);
  return { strip, control };
}

/** A box painted over everything else (a sticky or fixed bar that is not part of the grid). */
function overlayAt(top: number, bottom: number): HTMLElement {
  const bar = document.createElement("footer");
  document.body.appendChild(bar);
  bar.getBoundingClientRect = () => rect(top, bottom - top);
  paint.unshift({ el: bar, box: () => ({ top, bottom }) });
  return bar;
}

/** How much of a box the reader SEES: inside the port and the viewport, and not under the overlay. */
function readerSees(b: { top: number; bottom: number }, port: { top: number; bottom: number }, cover: { top: number; bottom: number }): number {
  let top = Math.max(b.top, port.top, 0);
  let bottom = Math.min(b.bottom, port.bottom, viewH);
  if (bottom <= top) return 0;
  if (cover.top <= top && cover.bottom >= bottom) return 0;
  if (cover.top > top && cover.top < bottom) bottom = cover.top;
  if (cover.bottom > top && cover.bottom < bottom && cover.top <= top) top = cover.bottom;
  return Math.max(0, bottom - top);
}

function wholeOrAbsent(el: HTMLElement, port: { top: number; bottom: number }, cover: { top: number; bottom: number }): { ok: boolean; seen: number; of: number } {
  const r = el.getBoundingClientRect();
  const seen = readerSees(r, port, cover);
  return { ok: seen <= 1 || seen >= r.height - 1, seen, of: r.height };
}

describe("C2 m3: an overlay that covers part of a navigation strip cuts it, at every rung of the layout ladder", () => {
  it("< 48rem: the page scrolls the grid up and a toolbar below the row slides under the sticky status bar", () => {
    /* 390x844: the status bar covers 759-844. The row sits 30 px above the viewport's top edge; the
       reveal scrolls the document UP 30 px, which moves a toolbar at 700-740 to 730-770 — inside the
       viewport (a clip-only extent calls it whole) but 11 px under the bar. */
    viewH = 844;
    maxScrollY = 20_000;
    scrollY = 1000;
    const BAR = { top: 759, bottom: 844 };
    const { strip } = stripOf("toolbar", "Zoom");
    const grid = document.createElement("div");
    grid.setAttribute("role", "grid");
    Object.defineProperty(grid, "scrollTop", { get: () => 0, set: () => undefined, configurable: true });
    const row = document.createElement("div");
    row.setAttribute("role", "row");
    grid.appendChild(row);
    document.body.append(grid, strip);
    const pageBox = (el: HTMLElement, pageTop: number, h: number): void => {
      el.getBoundingClientRect = () => rect(pageTop - scrollY, h);
      paint.push({ el, box: () => ({ top: pageTop - scrollY, bottom: pageTop - scrollY + h }) });
    };
    pageBox(row, 970, 34); // -30..4 on screen
    pageBox(grid, 400, 1100); // the grid lays out at full height; the page scrolls it
    pageBox(strip, 1700, 40); // 700-740 on screen: whole, above the bar
    overlayAt(BAR.top, BAR.bottom);
    const port = { top: 0, bottom: viewH };
    expect(wholeOrAbsent(strip, port, BAR), "precondition: the toolbar is whole").toEqual({ ok: true, seen: 40, of: 40 });
    revealBelowHeader(grid, null, row, "nearest");
    const s = wholeOrAbsent(strip, port, BAR);
    expect(s.ok, `the toolbar is whole or gone, not ${s.seen} of ${s.of} px seen past the status bar (scrollY ${scrollY})`).toBe(true);
    const r = row.getBoundingClientRect();
    expect(r.top >= 0 && r.bottom <= BAR.top, `the row is on screen above the bar (${r.top}-${r.bottom})`).toBe(true);
  });

  it("the grid at full height in a scrolling rail: a footer painted over the rail's bottom", () => {
    /* Rail port 0-400, a footer over 365-400. The row sits 30 px above the rail's top; the rail scrolls
       up 30 px and the toolbar under the grid moves from 330-360 to 360-390 — whole to the rail's clip,
       5 px under the footer. */
    const COVER = { top: 365, bottom: 400 };
    const rail = document.createElement("nav");
    rail.style.overflowY = "scroll";
    const grid = document.createElement("div");
    grid.setAttribute("role", "grid");
    const row = document.createElement("div");
    row.setAttribute("role", "row");
    grid.appendChild(row);
    const { strip } = stripOf("toolbar", "Zoom");
    rail.append(grid, strip);
    document.body.appendChild(rail);
    const railPort = scrollable(rail, 400, 4400);
    scrollable(grid, 860, 860);
    const inRail = (at: number): number => at - railPort.top();
    rail.getBoundingClientRect = () => rect(0, 400);
    const railBox = (el: HTMLElement, at: number, h: number): void => {
      el.getBoundingClientRect = () => rect(inRail(at), h);
      paint.push({ el, box: () => ({ top: inRail(at), bottom: inRail(at) + h }) });
    };
    railBox(row, 500, 60);
    railBox(grid, 0, 860);
    railBox(strip, 860, 30);
    overlayAt(COVER.top, COVER.bottom);
    rail.scrollTop = 530; // the row at -30..30, the toolbar at 330-360
    const port = { top: 0, bottom: 400 };
    expect(wholeOrAbsent(strip, port, COVER).seen, "precondition: the toolbar is whole").toBe(30);
    revealBelowHeader(grid, null, row, "nearest");
    const s = wholeOrAbsent(strip, port, COVER);
    expect(s.ok, `the toolbar is whole or gone, not ${s.seen} of ${s.of} px seen past the footer (rail ${railPort.top()})`).toBe(true);
    const r = row.getBoundingClientRect();
    expect(r.top >= 0 && r.bottom <= COVER.top, `the row is on screen above the footer (${r.top}-${r.bottom})`).toBe(true);
  });

  it(">= 48rem: the grid is its own port, the rail must move, and a bar painted over the rail's top covers the tab strip", () => {
    /* Rail port 84-874; a bar over 84-100. The tab strip sits at 104-136 below it. The grid's band
       (844-874, 30 px) cannot hold the 40 px row, so the rail moves 16 px: the strip goes to 88-120 —
       inside the rail's clip, 12 px under the bar. */
    const COVER = { top: 84, bottom: 100 };
    const rail = document.createElement("nav");
    rail.style.overflowY = "scroll";
    const panel = document.createElement("section");
    const { strip } = stripOf("tablist", "Trace a flow");
    panel.appendChild(strip);
    const grid = document.createElement("div");
    grid.setAttribute("role", "grid");
    const head = document.createElement("div");
    head.setAttribute("role", "rowgroup");
    const row = document.createElement("div");
    row.setAttribute("role", "row");
    grid.append(head, row);
    rail.append(panel, grid);
    document.body.appendChild(rail);
    const railPort = scrollable(rail, 790, 790 + 225);
    const gridPort = scrollable(grid, 300, 5300);
    const inRail = (at: number): number => 84 + at - railPort.top();
    rail.getBoundingClientRect = () => rect(84, 790);
    const railBox = (el: HTMLElement, at: () => number, h: number): void => {
      el.getBoundingClientRect = () => rect(at(), h);
      paint.push({ el, box: () => ({ top: at(), bottom: at() + h }) });
    };
    railBox(row, () => inRail(730) + 30 + 6 - gridPort.top(), 40); // 850-890: 16 px below the rail
    railBox(head, () => inRail(730), 30);
    railBox(grid, () => inRail(730), 300);
    railBox(panel, () => inRail(20), 32);
    railBox(strip, () => inRail(20), 32);
    overlayAt(COVER.top, COVER.bottom);
    const port = { top: 84, bottom: 874 };
    expect(wholeOrAbsent(strip, port, COVER).seen, "precondition: the tab strip is whole below the bar").toBe(32);
    revealBelowHeader(grid, head, row, "nearest");
    const s = wholeOrAbsent(strip, port, COVER);
    expect(s.ok, `the tab strip is whole or gone, not ${s.seen} of ${s.of} px seen past the bar (rail ${railPort.top()})`).toBe(true);
    const r = row.getBoundingClientRect();
    const g = grid.getBoundingClientRect();
    expect(r.top >= g.top + 30 - 0.5 && r.bottom <= 874 + 0.5, `the row is whole in the grid's band (${r.top}-${r.bottom})`).toBe(true);
  });

  it("control: an overlay that covers none of the strip changes nothing (the measured 06 layout, a bar clear of the strip)", () => {
    /* The same >= 48rem shape with the row fitting the band: fits first scrolls the grid, the rail
       stays at 0 — an overlay elsewhere on the page must not make the guard move anything. */
    const COVER = { top: 0, bottom: 40 };
    const rail = document.createElement("nav");
    rail.style.overflowY = "scroll";
    const { strip } = stripOf("tablist", "Trace a flow");
    const grid = document.createElement("div");
    grid.setAttribute("role", "grid");
    const head = document.createElement("div");
    head.setAttribute("role", "rowgroup");
    const row = document.createElement("div");
    row.setAttribute("role", "row");
    grid.append(head, row);
    rail.append(strip, grid);
    document.body.appendChild(rail);
    const railPort = scrollable(rail, 790, 1015);
    const gridPort = scrollable(grid, 300, 5300);
    const inRail = (at: number): number => 84 + at - railPort.top();
    rail.getBoundingClientRect = () => rect(84, 790);
    const railBox = (el: HTMLElement, at: () => number, h: number): void => {
      el.getBoundingClientRect = () => rect(at(), h);
      paint.push({ el, box: () => ({ top: at(), bottom: at() + h }) });
    };
    railBox(row, () => inRail(708.7) + 30 + 30 - gridPort.top(), 40.4);
    railBox(head, () => inRail(708.7), 30);
    railBox(grid, () => inRail(708.7), 300);
    railBox(strip, () => inRail(0), 32);
    overlayAt(COVER.top, COVER.bottom);
    revealBelowHeader(grid, head, row, "nearest");
    expect(railPort.top(), "the rail did not move").toBe(0);
    expect(gridPort.top(), "the grid absorbed the reveal").toBe(20);
    expect(wholeOrAbsent(strip, { top: 84, bottom: 874 }, COVER)).toEqual({ ok: true, seen: 32, of: 32 });
  });
});

/**
 * R9 verifier V1 (2026-09-27): a cover is what a hit PAINTS at the probe point, not its layout box.
 *
 * MEASURED (release build, 1440x900 and 768x1024, state 06): the path panel's mode strip sits at
 * 84-117 with `.pt-panel` (its own scroll port, scrolled to 8 273) directly below it. Chrome's hit
 * test half a pixel inside the strip's bottom edge answers with that panel's CONTENT, not the strip:
 * `div.hop__fact 116.81-243.69`, then `div.hop__fact -159.19-116.81`, a box the panel scrolled away and
 * clips (the same stack at 116.4, 116.5 and 116.8; at 768 the flip sits 0.6 px inside the strip).
 * Taken as covers by their layout boxes, the second one "spans" the strip, so the guard read a wholly
 * visible strip as 0 px on screen, marked it not whole, and never protected it again.
 *
 * The model reproduces that stack: within 1.5 px above the neighbour port's top edge the hit test
 * returns the port's content first. How wide that zone is depends on fractional offsets the code cannot
 * know, so the model makes it wider than any reasonable probe inset: only discarding what a hit does
 * not paint at the probe point (its box inside its own clip chain) passes.
 */
describe("R9 V1: a scrolled neighbour's clipped-away content is not a cover", () => {
  it(">= 48rem: the mode strip over a scrolled answer panel is still guarded when the rail must move", () => {
    const rail = document.createElement("nav");
    rail.style.overflowY = "scroll";
    const section = document.createElement("section");
    const { strip } = stripOf("tablist", "Trace a flow");
    const ptPanel = document.createElement("div");
    ptPanel.style.overflowY = "auto";
    const factA = document.createElement("div");
    const factB = document.createElement("div");
    ptPanel.append(factA, factB);
    section.append(strip, ptPanel);
    const grid = document.createElement("div");
    grid.setAttribute("role", "grid");
    const head = document.createElement("div");
    head.setAttribute("role", "rowgroup");
    const row = document.createElement("div");
    row.setAttribute("role", "row");
    grid.append(head, row);
    rail.append(section, grid);
    document.body.appendChild(rail);
    const railPort = scrollable(rail, 790, 790 + 225);
    const gridPort = scrollable(grid, 300, 5300);
    scrollable(ptPanel, 180, 9000);
    const inRail = (at: number): number => 84 + at - railPort.top();
    rail.getBoundingClientRect = () => rect(84, 790);
    const railBox = (el: HTMLElement, at: () => number, h: number): void => {
      el.getBoundingClientRect = () => rect(at(), h);
      paint.push({ el, box: () => ({ top: at(), bottom: at() + h }) });
    };
    railBox(row, () => inRail(730) + 30 + 6 - gridPort.top(), 40); // 850-890: 16 px below the rail
    railBox(head, () => inRail(730), 30);
    railBox(grid, () => inRail(730), 300);
    railBox(ptPanel, () => inRail(33), 180);
    railBox(section, () => inRail(0), 213);
    railBox(strip, () => inRail(0), 33); // 84-117: 32 px of tabs and a 1 px bottom border
    const ptTop = (): number => inRail(33);
    /* The panel's content, positioned by its own scroll: A ends 0.19 px above the panel's top edge
       (scrolled away and clipped), B starts there. Neither is painted over the strip. */
    factA.getBoundingClientRect = () => rect(ptTop() - 276.19, 276);
    factB.getBoundingClientRect = () => rect(ptTop() - 0.19, 126.88);
    const doc = document as Doc;
    const measured = doc.elementsFromPoint!;
    doc.elementsFromPoint = (x: number, y: number): Element[] =>
      y >= ptTop() - 1.5 && y < ptTop() ? [factB, factA, ptPanel, section, rail, document.body, document.documentElement] : measured(x, y);
    doc.elementFromPoint = (x: number, y: number): Element | null => doc.elementsFromPoint!(x, y)[0] ?? null;
    const port = { top: 84, bottom: 874 };
    const none = { top: -1, bottom: -1 };
    expect(wholeOrAbsent(strip, port, none), "precondition: the strip is whole on screen").toEqual({ ok: true, seen: 33, of: 33 });
    revealBelowHeader(grid, head, row, "nearest");
    const s = wholeOrAbsent(strip, port, none);
    expect(s.ok, `the mode strip is whole or gone, not ${s.seen} of ${s.of} px seen (rail ${railPort.top()})`).toBe(true);
    const r = row.getBoundingClientRect();
    expect(r.top >= inRail(730) + 30 - 0.5 && r.bottom <= 874 + 0.5, `the row is whole in the grid's band (${r.top}-${r.bottom})`).toBe(true);
  });
});

/**
 * R9 verifier V3: what a cover that reaches past BOTH edges of what the clips leave means. It hides
 * the element: absent, 0 px seen, never "whole" (trimOverlays' strict-inside rule, which suits a whole
 * grid band, would skip such a cover and read the element as whole). Two outcomes that choice decides:
 */
describe("R9 V3: an element wholly under a cover is absent, not whole", () => {
  it("a strip whose clip remainder lies wholly under a bar is gone: the rail moves no further for it", () => {
    /* Rail port 0-400 with a bar painted over 0-30. The strip (34-66) is whole below the bar. The row
       sits 50 px below the rail; the rail scrolls 50 and the strip goes to -16..16: the rail's clip
       leaves 0-16 of it, all of it under the bar, so the reader sees none of it. Read as whole there,
       the guard would call it cut (16 of 32) and scroll the rail 16 px more to take out a strip nobody
       can see. */
    const COVER = { top: 0, bottom: 30 };
    const rail = document.createElement("nav");
    rail.style.overflowY = "scroll";
    const { strip } = stripOf("toolbar", "Zoom");
    const grid = document.createElement("div");
    grid.setAttribute("role", "grid");
    const row = document.createElement("div");
    row.setAttribute("role", "row");
    grid.appendChild(row);
    rail.append(strip, grid);
    document.body.appendChild(rail);
    const railPort = scrollable(rail, 400, 4400);
    scrollable(grid, 860, 860);
    const inRail = (at: number): number => at - railPort.top();
    rail.getBoundingClientRect = () => rect(0, 400);
    const railBox = (el: HTMLElement, at: number, h: number): void => {
      el.getBoundingClientRect = () => rect(inRail(at), h);
      paint.push({ el, box: () => ({ top: inRail(at), bottom: inRail(at) + h }) });
    };
    railBox(row, 390, 60);
    railBox(grid, 100, 860);
    railBox(strip, 34, 32);
    overlayAt(COVER.top, COVER.bottom);
    const port = { top: 0, bottom: 400 };
    expect(wholeOrAbsent(strip, port, COVER).seen, "precondition: the strip is whole below the bar").toBe(32);
    revealBelowHeader(grid, null, row, "nearest");
    expect(wholeOrAbsent(strip, port, COVER).seen, "the strip is wholly hidden (clip + bar)").toBe(0);
    expect(railPort.top(), "the rail moved exactly what the row needed, nothing for a strip nobody sees").toBe(50);
    const r = row.getBoundingClientRect();
    expect(r.top >= COVER.bottom && r.bottom <= 400, `the row is on screen (${r.top}-${r.bottom})`).toBe(true);
  });

  it("a FIXED cover authored inside a scrolled sibling panel still covers: only its containing-block chain clips it", () => {
    /* The same rail and strip, with no bar in the page: the cover is a popover `position: fixed` at
       0-30, authored inside a scrolling side panel whose own box (66-266 at rest, 16-216 after the
       reveal) lies BELOW the strip. A fixed box escapes that panel's clip, so it paints over the
       strip's clip remainder (0-16) exactly as the bar above did: the strip is absent and the rail
       moves no further. Clipped by every ancestor instead, the popover would paint only 16-30, the
       strip's remainder would read as cut, and the rail would move 16 px more. */
    const rail = document.createElement("nav");
    rail.style.overflowY = "scroll";
    const { strip } = stripOf("toolbar", "Zoom");
    const side = document.createElement("aside");
    side.style.overflowY = "auto";
    const popover = document.createElement("div");
    popover.setAttribute("role", "dialog");
    popover.style.position = "fixed";
    side.appendChild(popover);
    const grid = document.createElement("div");
    grid.setAttribute("role", "grid");
    const row = document.createElement("div");
    row.setAttribute("role", "row");
    grid.appendChild(row);
    rail.append(strip, side, grid);
    document.body.appendChild(rail);
    const railPort = scrollable(rail, 400, 4400);
    scrollable(grid, 860, 860);
    scrollable(side, 200, 2000);
    const inRail = (at: number): number => at - railPort.top();
    rail.getBoundingClientRect = () => rect(0, 400);
    const railBox = (el: HTMLElement, at: number, h: number): void => {
      el.getBoundingClientRect = () => rect(inRail(at), h);
      paint.push({ el, box: () => ({ top: inRail(at), bottom: inRail(at) + h }) });
    };
    railBox(row, 390, 60);
    railBox(grid, 300, 860);
    railBox(side, 66, 200);
    railBox(strip, 34, 32);
    popover.getBoundingClientRect = () => rect(0, 30);
    paint.unshift({ el: popover, box: () => ({ top: 0, bottom: 30 }) });
    const COVER = { top: 0, bottom: 30 };
    const port = { top: 0, bottom: 400 };
    expect(wholeOrAbsent(strip, port, COVER).seen, "precondition: the strip is whole below the popover").toBe(32);
    revealBelowHeader(grid, null, row, "nearest");
    expect(wholeOrAbsent(strip, port, COVER).seen, "the strip is wholly hidden (clip + popover)").toBe(0);
    expect(railPort.top(), "the rail moved exactly what the row needed, nothing for a strip nobody sees").toBe(50);
  });

  it("a focused control the reader cannot see (wholly under the status bar) does not veto the reveal", () => {
    /* 390x844, the status bar over 759-844. The focused "Copy" button (outside the grid) sits at
       770-800, wholly under the bar: the reader sees none of it. The row sits at 740-774, 15 px under
       the bar; the reveal scrolls the page 15 px, which lifts the button to 755-785, 4 px of it now
       above the bar. The reader lost nothing, so the reveal stands. Had the covered button read as
       whole (30 px), the 4 px after would read as a loss and the reveal would be undone, leaving the
       row under the bar. */
    viewH = 844;
    maxScrollY = 20_000;
    scrollY = 1000;
    const BAR = { top: 759, bottom: 844 };
    const grid = document.createElement("div");
    grid.setAttribute("role", "grid");
    Object.defineProperty(grid, "scrollTop", { get: () => 0, set: () => undefined, configurable: true });
    const row = document.createElement("div");
    row.setAttribute("role", "row");
    grid.appendChild(row);
    const copy = document.createElement("button");
    copy.textContent = "Copy";
    document.body.append(grid, copy);
    const pageBox = (el: HTMLElement, pageTop: number, h: number): void => {
      el.getBoundingClientRect = () => rect(pageTop - scrollY, h);
      paint.push({ el, box: () => ({ top: pageTop - scrollY, bottom: pageTop - scrollY + h }) });
    };
    pageBox(row, 1740, 34); // 740-774 on screen: 15 px under the bar
    pageBox(copy, 1770, 30); // 770-800: wholly under the bar
    pageBox(grid, 400, 1500);
    overlayAt(BAR.top, BAR.bottom);
    copy.focus();
    expect(document.activeElement, "precondition: the button holds focus").toBe(copy);
    revealBelowHeader(grid, null, row, "nearest");
    const r = row.getBoundingClientRect();
    expect(r.bottom <= BAR.top + 0.5, `the row is above the status bar (${r.top}-${r.bottom}, scrollY ${scrollY})`).toBe(true);
    expect(scrollY, "the page scrolled the 15 px the row needed").toBe(1015);
  });
});
