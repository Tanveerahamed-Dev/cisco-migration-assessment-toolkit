/**
 * DataGrid.reveal-focus.test.tsx — a reveal never scrolls the reader's focus off screen.
 *
 * MEASURED (390x844, 2026-09-25, wave-6 gate; probe `?s=findings&f=F001&d=core1…`): at phone width
 * the queue grid is not its own scroll port, so `revealBelowHeader` hands the distance it cannot
 * absorb to the scrolling ancestors and then the document. Tab to the Evidence pane's "F002 …"
 * button and press Enter: the Evidence pane moves focus to its new title (H2.ev__title, on screen at
 * scrollY 14 080), THEN the queue's selection reveal called `window.scrollBy(0, -5017)` to show the
 * F002 row — leaving the focused title at top 5 383 px with the page at scrollY 9 063, off screen.
 * `review/audit-d3-focus.mjs --self-removing` reported the same shape 24 times at 390 px.
 *
 * The rule under test is the rule, not the one layout: the ancestor/document half of a reveal may
 * move the page only while it keeps as much of the focused element (outside the grid) on screen
 * as before. The controls pin the other half: focus INSIDE the grid, focus on <body>, and a focused
 * element the scroll does not move (a fixed bar) all still let the reveal scroll the page.
 *
 * jsdom lays nothing out, so the page is a small explicit model: every element has a layout top in
 * page coordinates, its viewport rect is that minus `scrollY`, and `window.scrollBy` moves `scrollY`.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { revealBelowHeader } from "./DataGrid";

const VIEW_H = 844;
let scrollY = 0;
let calls: number[] = [];
const originals = {
  scrollBy: window.scrollBy,
  innerHeight: Object.getOwnPropertyDescriptor(window, "innerHeight"),
  scrollY: Object.getOwnPropertyDescriptor(window, "scrollY"),
};

/** Give `el` a box at page-y `top` of height `h`; `fixed` boxes ignore the page scroll. */
function place(el: HTMLElement, top: number, h: number, fixed = false): void {
  el.getBoundingClientRect = () => {
    const y = fixed ? top : top - scrollY;
    return { x: 0, y, width: 390, height: h, top: y, left: 0, right: 390, bottom: y + h, toJSON: () => ({}) } as DOMRect;
  };
}

interface Page {
  grid: HTMLElement;
  row: HTMLElement;
  cell: HTMLElement;
  outside: HTMLButtonElement;
}

/** A grid laid out at full height (not its own port — its scrollTop never moves), a far-away row in
 *  it, and a focusable element elsewhere on the page. */
function page(outsideTop: number, outsideFixed = false): Page {
  const grid = document.createElement("div");
  grid.setAttribute("role", "grid");
  Object.defineProperty(grid, "scrollTop", { get: () => 0, set: () => undefined, configurable: true });
  const row = document.createElement("div");
  row.setAttribute("role", "row");
  const cell = document.createElement("div");
  cell.setAttribute("role", "gridcell");
  cell.tabIndex = -1;
  row.appendChild(cell);
  grid.appendChild(row);
  const outside = document.createElement("button");
  outside.textContent = "F002";
  document.body.append(grid, outside);
  place(grid, 5000, 15_000); // spans the viewport at scrollY 14 080
  place(row, 6000, 34); // 8 080 px above the viewport's top edge
  place(cell, 6000, 34);
  place(outside, outsideTop, 20, outsideFixed);
  return { grid, row, cell, outside };
}

beforeEach(() => {
  scrollY = 14_080;
  calls = [];
  Object.defineProperty(window, "innerHeight", { value: VIEW_H, configurable: true });
  Object.defineProperty(window, "scrollY", { get: () => scrollY, configurable: true });
  window.scrollBy = ((x: number | ScrollToOptions, y?: number) => {
    const dy = typeof x === "number" ? (y ?? 0) : (x.top ?? 0);
    calls.push(dy);
    scrollY = Math.max(0, scrollY + dy);
  }) as typeof window.scrollBy;
});

afterEach(() => {
  window.scrollBy = originals.scrollBy;
  if (originals.innerHeight) Object.defineProperty(window, "innerHeight", originals.innerHeight);
  if (originals.scrollY) Object.defineProperty(window, "scrollY", originals.scrollY);
  else delete (window as { scrollY?: number }).scrollY;
  document.body.replaceChildren();
});

describe("a reveal never scrolls the reader's focus off screen", () => {
  it("keeps a focused element OUTSIDE the grid on screen (the measured 390x844 defect)", () => {
    const { grid, cell, outside } = page(14_080 + 120);
    outside.focus();
    expect(document.activeElement).toBe(outside);
    const before = outside.getBoundingClientRect();
    expect(before.top >= 0 && before.bottom <= VIEW_H).toBe(true);
    revealBelowHeader(grid, null, cell, "centre");
    const after = outside.getBoundingClientRect();
    expect({ top: after.top, bottom: after.bottom }).toEqual({ top: before.top, bottom: before.bottom });
    expect(scrollY).toBe(14_080);
  });

  it("still scrolls the page when focus is INSIDE the grid (keyboard navigation reveals its own row)", () => {
    const { grid, cell } = page(14_080 + 120);
    cell.focus();
    revealBelowHeader(grid, null, cell, "nearest");
    const r = cell.getBoundingClientRect();
    expect(calls.length).toBeGreaterThan(0);
    expect(r.top >= 0 && r.bottom <= VIEW_H).toBe(true);
  });

  it("still scrolls the page when nothing holds focus", () => {
    const { grid, cell } = page(14_080 + 120);
    (document.activeElement as HTMLElement | null)?.blur();
    expect(document.activeElement).toBe(document.body);
    revealBelowHeader(grid, null, cell, "centre");
    const r = cell.getBoundingClientRect();
    expect(r.top >= 0 && r.bottom <= VIEW_H).toBe(true);
  });

  it("still scrolls the page when the focused element does not move with it (a fixed bar)", () => {
    const { grid, cell, outside } = page(10, true);
    outside.focus();
    revealBelowHeader(grid, null, cell, "centre");
    const r = cell.getBoundingClientRect();
    expect(r.top >= 0 && r.bottom <= VIEW_H).toBe(true);
    const f = outside.getBoundingClientRect();
    expect(f.top).toBe(10);
  });

  it("does not scroll an ancestor scroll port that would carry the focused element away", () => {
    // A rail that scrolls (the phone's div.railb__pane) holding both the grid and the focused button.
    const rail = document.createElement("div");
    rail.style.overflowY = "auto";
    let railTop = 5000;
    Object.defineProperty(rail, "scrollHeight", { value: 20_000, configurable: true });
    Object.defineProperty(rail, "clientHeight", { value: VIEW_H, configurable: true });
    Object.defineProperty(rail, "scrollTop", {
      get: () => railTop,
      set: (v: number) => {
        railTop = Math.max(0, Math.min(20_000 - VIEW_H, v));
      },
      configurable: true,
    });
    rail.getBoundingClientRect = () => ({ x: 0, y: 0, width: 390, height: VIEW_H, top: 0, left: 0, right: 390, bottom: VIEW_H, toJSON: () => ({}) }) as DOMRect;
    scrollY = 0;
    const { grid, row, cell, outside } = page(0);
    rail.append(grid, outside);
    document.body.appendChild(rail);
    // Inside the rail: viewport y = content y - rail.scrollTop.
    const inRail = (el: HTMLElement, contentTop: number, h: number): void => {
      el.getBoundingClientRect = () => {
        const y = contentTop - railTop;
        return { x: 0, y, width: 390, height: h, top: y, left: 0, right: 390, bottom: y + h, toJSON: () => ({}) } as DOMRect;
      };
    };
    inRail(grid, 0, 6000);
    inRail(row, 1000, 34);
    inRail(cell, 1000, 34);
    inRail(outside, 5200, 20);
    outside.focus();
    revealBelowHeader(grid, null, cell, "centre");
    expect(railTop).toBe(5000);
    const f = outside.getBoundingClientRect();
    expect(f.top >= 0 && f.bottom <= VIEW_H).toBe(true);
    expect(calls).toEqual([]);
  });
});
