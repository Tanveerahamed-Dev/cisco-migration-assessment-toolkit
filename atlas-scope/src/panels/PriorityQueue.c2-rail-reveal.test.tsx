/**
 * PriorityQueue.c2-rail-reveal.test.tsx — C2 through the REAL queue: when the panel above the queue
 * grows inside Rail A and slides the selected finding out of a band that can still hold it, the
 * QUEUE GRID scrolls, and the shared rail (which carries the path panel's tab strip) does not.
 *
 * MEASURED (acceptance report C2, 1440x900, state 06, `?s=path&flow=10.0.10.50>10.0.30.10>tcp>3389&hop=0`):
 * the path panel grew above the queue inside Rail A; F001 (40.4 px) ended at 852.7-893.1, 19 px
 * below the rail's port bottom (874), while the grid's visible band was 822.7-874 (51.3 px). The
 * queue's reveal moved the RAIL 19 px — the whole path panel with it, its "Trace a flow | Verify an
 * intent" strip cut to 13 of 32 px — where scrolling the grid 20 px shows F001 whole.
 *
 * DataGrid.c2-chrome-slice.test.tsx pins `revealBelowHeader` over a geometric model; this file pins
 * the CHAIN a reader actually drives: the real PriorityQueue, a click that selects and holds a row,
 * then the content above growing (the only signal the queue gets is its row's visibility changing),
 * the hold's re-reveal, and the fits-first decision inside it (C2 verifier m4). The control is the
 * R106 shape: a band that cannot hold the row still moves the rail and not the grid.
 *
 * jsdom has no layout, so it is supplied exactly as PriorityQueue.a4-surface-switch.test.tsx does
 * (`mountInRail`): a scrolling rail whose box clips the grid; the grid, its sticky header and uniform
 * rows positioned from the rail's and the grid's scrollTop; stubbed Resize/IntersectionObservers.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";
import { useInvestigation } from "../core/store";
import { PriorityQueue } from "./PriorityQueue";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* The measured 1440x900 geometry: Rail A's port 84-874, the queue grid's 19rem box (300 px here),
   a 30 px sticky header, 40.4 px rows. */
const RAIL = { top: 84, bottom: 874 };
const GRID_H = 300;
const HEAD_PX = 30;
const ROW_PX = 40.4;
/** The path panel's tab strip at the top of the rail: 84-116 while the rail is at 0. */
const STRIP_H = 32;

let portTop = 0;
let portBottom = 0;
let railEl: HTMLElement | null = null;
let stripEl: HTMLElement | null = null;
const railShift = (): number => railEl?.scrollTop ?? 0;
const mounted: { root: Root; container: HTMLElement }[] = [];
const watchers: { cb: IntersectionObserverCallback; self: IntersectionObserver; targets: Set<Element> }[] = [];
let restore: (() => void) | null = null;
let pageScrolls = 0;
const jsdomScrollBy = window.scrollBy;
const jsdomInnerHeight = window.innerHeight;

const rect = (top: number, bottom: number): DOMRect =>
  ({ top, bottom, left: 0, right: 900, width: 900, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;

function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}

/** Rail A in miniature around the real queue, with the path panel's tab strip above it. */
function mountInRail(): { c: HTMLElement; grid: HTMLElement } {
  const c = mount(
    <nav className="rail" style={{ overflowY: "auto" }}>
      <div role="tablist" aria-label="Path mode" className="strip">
        <button role="tab">Trace a flow</button>
      </div>
      <PriorityQueue debounceMs={0} />
    </nav>,
  );
  railEl = c.querySelector<HTMLElement>(".rail")!;
  stripEl = c.querySelector<HTMLElement>(".strip")!;
  let railTop = 0;
  Object.defineProperty(railEl, "scrollTop", {
    configurable: true,
    get: () => railTop,
    set: (v: number) => {
      railTop = Math.max(0, Math.min(3000, v));
    },
  });
  Object.defineProperty(railEl, "scrollHeight", { configurable: true, value: 4000 });
  Object.defineProperty(railEl, "clientHeight", { configurable: true, value: RAIL.bottom - RAIL.top });
  const grid = c.querySelector<HTMLElement>(".ag__grid")!;
  let gridTop = 0;
  Object.defineProperty(grid, "scrollTop", {
    configurable: true,
    get: () => gridTop,
    set: (v: number) => {
      gridTop = Math.max(0, v);
    },
  });
  // The grid is its own scroll port (desktop): 146 rows in a 19rem box.
  Object.defineProperty(grid, "scrollHeight", { configurable: true, value: 9000 });
  Object.defineProperty(grid, "clientHeight", { configurable: true, value: GRID_H });
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 900 });
  const original = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    if (this === railEl) return rect(RAIL.top, RAIL.bottom);
    if (this === stripEl || stripEl?.contains(this)) return rect(RAIL.top - railShift(), RAIL.top - railShift() + STRIP_H);
    if (this.classList.contains("ag__grid")) return rect(portTop - railShift(), portBottom - railShift());
    if (this.classList.contains("ag__head")) return rect(portTop - railShift(), portTop - railShift() + HEAD_PX);
    const row = this.closest<HTMLElement>(".ag__row--data");
    if (row) {
      const owner = row.closest<HTMLElement>(".ag__grid");
      const rows = owner ? [...owner.querySelectorAll<HTMLElement>(".ag__row--data")] : [];
      const top = portTop - railShift() + HEAD_PX + rows.indexOf(row) * ROW_PX - (owner?.scrollTop ?? 0);
      return rect(top, top + ROW_PX);
    }
    return original.call(this) as DOMRect;
  };
  restore = () => {
    HTMLElement.prototype.getBoundingClientRect = original;
  };
  return { c, grid };
}

const dataRows = (c: HTMLElement): HTMLElement[] => [...c.querySelectorAll<HTMLElement>(".ag__row--data")];
/** The queue's visible band: below its header, inside the rail's port. */
const bandOf = (): { top: number; bottom: number } => ({
  top: Math.max(portTop - railShift() + HEAD_PX, RAIL.top),
  bottom: Math.min(portBottom - railShift(), RAIL.bottom),
});
const inBand = (row: HTMLElement): boolean => {
  const r = row.getBoundingClientRect();
  const b = bandOf();
  return r.top >= b.top - 1 && r.bottom <= b.bottom + 1;
};
const where = (row: HTMLElement): string => {
  const r = row.getBoundingClientRect();
  const b = bandOf();
  return `${r.top.toFixed(1)}-${r.bottom.toFixed(1)} in ${b.top.toFixed(1)}-${b.bottom.toFixed(1)}`;
};
/** How much of the tab strip the reader sees through the rail's port. */
const stripSeen = (): number => {
  const r = stripEl!.getBoundingClientRect();
  return Math.max(0, Math.min(r.bottom, RAIL.bottom) - Math.max(r.top, RAIL.top));
};
const deliverIntersection = (): void => {
  act(() => {
    for (const w of watchers) if (w.targets.size > 0) w.cb([], w.self);
  });
};
async function settle(): Promise<void> {
  await actAsync(async () => {
    await new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
}
const readerScroll = (grid: HTMLElement, to: number): void => {
  act(() => {
    grid.dispatchEvent(new Event("wheel"));
    grid.scrollTop = to;
    grid.dispatchEvent(new Event("scroll"));
  });
};
const pointerClick = (grid: HTMLElement, row: HTMLElement): void => {
  const cell = row.querySelector<HTMLElement>('[aria-colindex="3"]') ?? row.querySelector<HTMLElement>('[role="rowheader"]')!;
  act(() => {
    cell.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    cell.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    cell.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    cell.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  act(() => {
    grid.dispatchEvent(new PointerEvent("pointerleave"));
  });
};

/**
 * The reader scrolls the queue so row 20 sits one row below the header (30 px into the rows), and
 * clicks it. Returns the row; the grid's box is at 504-804, wholly inside the rail.
 */
async function clickRow20(c: HTMLElement, grid: HTMLElement): Promise<HTMLElement> {
  portTop = RAIL.top + 420;
  portBottom = portTop + GRID_H;
  readerScroll(grid, 20 * ROW_PX - 30);
  const target = dataRows(c)[20]!;
  expect(target.getBoundingClientRect().top, "precondition: row 20 sits 30 px below the header").toBeCloseTo(portTop + HEAD_PX + 30, 6);
  pointerClick(grid, target);
  await settle();
  expect(target.getAttribute("data-active"), "the click selects the row").toBe("yes");
  expect(inBand(target), `precondition: the selected row is visible (${where(target)})`).toBe(true);
  return target;
}

beforeEach(() => {
  railEl = null;
  stripEl = null;
  watchers.length = 0;
  pageScrolls = 0;
  window.scrollBy = (() => {
    pageScrolls += 1;
  }) as typeof window.scrollBy;
  (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver = class {
    constructor(cb: IntersectionObserverCallback) {
      watchers.push({ cb, self: this as unknown as IntersectionObserver, targets: new Set<Element>() });
    }
    observe(el: Element): void {
      watchers.find((w) => w.self === (this as unknown as IntersectionObserver))?.targets.add(el);
    }
    unobserve(el: Element): void {
      watchers.find((w) => w.self === (this as unknown as IntersectionObserver))?.targets.delete(el);
    }
    disconnect(): void {
      const i = watchers.findIndex((w) => w.self === (this as unknown as IntersectionObserver));
      if (i !== -1) watchers.splice(i, 1);
    }
    takeRecords(): IntersectionObserverEntry[] {
      return [];
    }
  };
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  try {
    localStorage.clear();
  } catch {
    /* preferences are not evidence */
  }
  act(() => { useInvestigation.getState().reset(); });
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  restore?.();
  restore = null;
  delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
  delete (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver;
  window.scrollBy = jsdomScrollBy;
  Object.defineProperty(window, "innerHeight", { configurable: true, value: jsdomInnerHeight });
  document.body.innerHTML = "";
});

describe("C2 through the real queue: the path panel grows above it inside Rail A", () => {
  it("the row slides 19 px out of a 51 px band that still holds it: the GRID scrolls, the rail and the page stay", async () => {
    const { c, grid } = mountInRail();
    const row = await clickRow20(c, grid);
    const gridBefore = grid.scrollTop;
    expect(stripSeen(), "precondition: the tab strip is whole").toBe(STRIP_H);
    // The path panel grows by 288.7 px: the grid's box goes to 792.7-1092.7, its band to 822.7-874.
    portTop += 288.7;
    portBottom += 288.7;
    const b = bandOf();
    expect(b.bottom - b.top, "precondition: the measured 51.3 px band").toBeCloseTo(51.3, 6);
    const r = row.getBoundingClientRect();
    expect(r.bottom - RAIL.bottom, `precondition: the row slid 19 px below the rail (${where(row)})`).toBeCloseTo(19.1, 6);
    expect(inBand(row)).toBe(false);
    deliverIntersection();
    expect(inBand(row), `the row is back in view (${where(row)}; rail ${railShift()}, grid +${grid.scrollTop - gridBefore})`).toBe(true);
    expect(railShift(), "the shared rail did not move: the grid's own band could hold the row").toBe(0);
    expect(grid.scrollTop - gridBefore, "the grid absorbed the reveal (19.1 px, rounded away from the row)").toBe(20);
    expect(stripSeen(), "the path panel's tab strip is whole").toBe(STRIP_H);
    expect(pageScrolls, "the document was never scrolled").toBe(0);
  });

  it("control (R106's reason): a 30 px band cannot hold the 40.4 px row — the rail moves, the grid does not, the strip is whole or gone", async () => {
    const { c, grid } = mountInRail();
    const row = await clickRow20(c, grid);
    const gridBefore = grid.scrollTop;
    // Grown by 310 px: the band is 844-874 (30 px) and the row sits wholly below the rail (874-914.4).
    portTop += 310;
    portBottom += 310;
    expect(bandOf().bottom - bandOf().top, "precondition: a 30 px band").toBeCloseTo(30, 6);
    expect(inBand(row)).toBe(false);
    deliverIntersection();
    expect(inBand(row), `the row is back in view (${where(row)}; rail ${railShift()})`).toBe(true);
    expect(railShift(), "only the rail can show the row").toBeGreaterThan(0);
    expect(grid.scrollTop, "the grid's own port already showed the row: it did not scroll").toBe(gridBefore);
    const seen = stripSeen();
    expect(seen <= 1 || seen >= STRIP_H - 1, `the tab strip is whole or gone, not ${seen} of ${STRIP_H} px`).toBe(true);
    expect(pageScrolls, "the document was never scrolled").toBe(0);
  });
});
