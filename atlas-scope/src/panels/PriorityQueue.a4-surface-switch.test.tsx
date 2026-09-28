/**
 * PriorityQueue.a4-surface-switch.test.tsx — A4 (repair wave 8): the SELECTED finding row and the
 * FOCUSED cell stay on screen after any change to the port around the grid that the reader did not
 * make to the grid itself.
 *
 * THE DEFECT, measured (acceptance-report.md at `34bd435`, A4 FAIL, reproduced twice, 1920x1080,
 * light theme, dev server): fresh load, the reader scrolls the queue to scrollTop 1000, orbits, then
 * CLICKS F026 in the queue and picks access5, core1, L33 and access5 on the canvas. F026 is visible
 * at 844-900 in a queue viewport of 389-1054. Then the Path surface button: the path panel takes the
 * top of the rail, the queue's viewport shrinks to 786-1054, scrollTop moves only 1000 -> 1015, and
 * the `data-active` F026 sits at 1241-1297 — off screen, with nothing revealing it. The trace's hop
 * selection (flow submit) and a later double-click on dist1 left it off screen too. After a URL load
 * (`?d=access5&f=F026`) the same switch re-anchored the row.
 *
 * WHY THE TWO PATHS DIFFER (DataGrid.tsx): the port-size ResizeObserver re-reveals only a HELD row,
 * and the hold was armed only by a reveal that SCROLLED. A URL/store selection scrolls (hold armed);
 * a finding the reader CLICKS is already under the pointer, so the reveal is skipped — and with it
 * the hold. The device, link and hop picks after it do not re-key the reveal (A4: a device pick keeps
 * the reader's scroll position), so nothing ever armed it, and the shrinking port had nothing to keep.
 *
 * THE CLASS, as tested here: whichever way the selection was reached (the reader's click, then a
 * device, a link, a hop or a surface switch on another surface), a port that shrinks under it — the
 * only signal the queue gets is a ResizeObserver callback — re-reveals the selected row by the LEAST
 * movement; and the same holds for the focused cell when focus is in the grid. The reader's own
 * scroll away from the row is never fought (the control).
 *
 * E3: the fix must not add a layout read to the click's own (urgent) commit. That is pinned below by
 * counting `getBoundingClientRect` calls inside the click.
 *
 * jsdom has no layout, so it is supplied: a scroll port whose TOP moves (the path panel taking the
 * rail), a sticky header riding that top, and uniform rows positioned from their index and the live
 * scrollTop. ResizeObserver is stubbed so a test can deliver the resize the browser would.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";
import { fabric } from "../core/data";
import { useInvestigation } from "../core/store";
import { PriorityQueue } from "./PriorityQueue";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/* Modelled on the measured viewports. `top` is the port's top edge before the switch, `shrunk` after
   it (the path panel above the queue), `bottom` its fixed bottom edge. */
interface Geometry {
  name: string;
  top: number;
  shrunk: number;
  bottom: number;
  row: number;
  /** The viewport height: the band's last clip (`visibleBand` reads `innerHeight`). */
  vh: number;
}
const GEOMETRIES: Geometry[] = [
  { name: "1920x1080", top: 389, shrunk: 786, bottom: 1054, row: 56, vh: 1080 },
  { name: "1440x900", top: 376, shrunk: 640, bottom: 874, row: 56, vh: 900 },
  { name: "768x1024", top: 744, shrunk: 860, bottom: 1024, row: 47, vh: 1024 },
  { name: "390x844", top: 300, shrunk: 520, bottom: 844, row: 56, vh: 844 },
];
const HEAD_PX = 40;

let portTop = 0;
let portBottom = 0;
let rowPx = 47;
/** Each stubbed observer with the elements it observes: a resize reaches only the observers of the
 *  element that resized, as in a browser. */
const observers: { cb: ResizeObserverCallback; self: ResizeObserver; targets: Set<Element> }[] = [];
const mounted: { root: Root; container: HTMLElement }[] = [];
let restore: (() => void) | null = null;
let rectReads = 0;
const jsdomInnerHeight = window.innerHeight;
/** A scrolling rail around the queue (rail A at desktop widths): when set, the grid, its header and
 *  its rows ride the rail's scrollTop, and the rail's box clips them. */
let railEl: HTMLElement | null = null;
let railBox = { top: 0, bottom: 0 };
const railShift = (): number => railEl?.scrollTop ?? 0;
/** Stubbed IntersectionObservers and what each watches. */
const watchers: { cb: IntersectionObserverCallback; self: IntersectionObserver; targets: Set<Element> }[] = [];
let pageScrolls = 0;
const jsdomScrollBy = window.scrollBy;

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

function installLayout(container: HTMLElement): HTMLElement {
  const grid = container.querySelector<HTMLElement>(".ag__grid")!;
  let scrollTop = 0;
  Object.defineProperty(grid, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (v: number) => {
      scrollTop = Math.max(0, v);
    },
  });
  const original = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    rectReads += 1;
    if (this === railEl) return rect(railBox.top, railBox.bottom);
    if (this.classList.contains("ag__grid")) return rect(portTop - railShift(), portBottom - railShift());
    if (this.classList.contains("ag__head")) return rect(portTop - railShift(), portTop - railShift() + HEAD_PX);
    const row = this.closest<HTMLElement>(".ag__row--data");
    if (row) {
      const owner = row.closest<HTMLElement>(".ag__grid");
      const rows = owner ? [...owner.querySelectorAll<HTMLElement>(".ag__row--data")] : [];
      const top = portTop - railShift() + HEAD_PX + rows.indexOf(row) * rowPx - (owner?.scrollTop ?? 0);
      return rect(top, top + rowPx);
    }
    return original.call(this) as DOMRect;
  };
  const prev = restore;
  restore = () => {
    HTMLElement.prototype.getBoundingClientRect = original;
    prev?.();
  };
  return grid;
}

const dataRows = (c: HTMLElement): HTMLElement[] => [...c.querySelectorAll<HTMLElement>(".ag__row--data")];
const activeRow = (c: HTMLElement): HTMLElement | undefined => dataRows(c).find((r) => r.getAttribute("data-active") === "yes");
const idOf = (row: HTMLElement): string => row.querySelector('[role="rowheader"]')?.textContent?.trim() ?? "";
/** Inside the part of the port below the sticky header — the reader can see all of it. */
const inView = (el: HTMLElement): boolean => {
  const r = el.getBoundingClientRect();
  return r.top >= portTop + HEAD_PX - 1 && r.bottom <= portBottom + 1;
};
const where = (el: HTMLElement): string => {
  const r = el.getBoundingClientRect();
  return `${Math.round(r.top)}-${Math.round(r.bottom)} in ${Math.round(portTop + HEAD_PX)}-${portBottom}`;
};
/** The port (the grid and its sticky header) resized: what the browser delivers, to the observers
 *  of THOSE elements only. */
const deliverResize = (): void => {
  const port = new Set<Element>([...document.querySelectorAll(".ag__grid, .ag__head")]);
  act(() => {
    for (const o of observers) if ([...o.targets].some((t) => port.has(t))) o.cb([], o.self);
  });
};
/** The deferred half of a selection (`deferPastPaint`): one frame plus one task. */
async function settle(): Promise<void> {
  await actAsync(async () => {
    await new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
}
/** The reader's wheel on the grid, then the scroll it causes — as a browser orders them. */
const readerScroll = (grid: HTMLElement, to: number): void => {
  act(() => {
    grid.dispatchEvent(new Event("wheel"));
    grid.scrollTop = to;
    grid.dispatchEvent(new Event("scroll"));
  });
};
/** A pointer click on a row's title cell, the pointer then leaving the grid for another surface. */
const pointerClick = (grid: HTMLElement, row: HTMLElement): number => {
  const cell = row.querySelector<HTMLElement>('[aria-colindex="3"]') ?? row.querySelector<HTMLElement>('[role="rowheader"]')!;
  const before = rectReads;
  act(() => {
    cell.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    cell.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    cell.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    cell.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  const reads = rectReads - before;
  act(() => {
    grid.dispatchEvent(new PointerEvent("pointerleave"));
  });
  return reads;
};

beforeEach(() => {
  railEl = null;
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
  portTop = 0;
  portBottom = 0;
  rowPx = 47;
  rectReads = 0;
  observers.length = 0;
  const Stub = class {
    constructor(cb: ResizeObserverCallback) {
      observers.push({ cb, self: this as unknown as ResizeObserver, targets: new Set<Element>() });
    }
    observe(el: Element): void {
      observers.find((o) => o.self === (this as unknown as ResizeObserver))?.targets.add(el);
    }
    unobserve(): void {}
    disconnect(): void {
      const i = observers.findIndex((o) => o.self === (this as unknown as ResizeObserver));
      if (i !== -1) observers.splice(i, 1);
    }
  };
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = Stub;
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

/** A link that names the clicked finding's first device, so the link pick marks rows (a real pick). */
const linkFor = (host: string | undefined): string => fabric.links.find((l) => l.a === host || l.b === host)?.id ?? fabric.links[0]!.id;

/** Every interactive trigger the app has that re-aims the queue without re-keying its reveal. */
const TRIGGERS: [string, (host: string | undefined) => void][] = [
  ["nothing after the click (the surface switch alone)", () => {}],
  ["a device pick on the canvas", (host) => useInvestigation.getState().selectDevice(host ?? "core1", { surface: "fabric" })],
  ["a link pick", (host) => useInvestigation.getState().selectLink(linkFor(host))],
  ["a hop selection (a trace landing: device + hop)", () => {
    useInvestigation.getState().selectDevice("core1", { surface: "path" });
    useInvestigation.getState().selectHop(0);
  }],
  ["the report's sequence: access5, core1, a link, access5", () => {
    const s = useInvestigation.getState();
    s.selectDevice("access5", { surface: "fabric" });
    s.selectDevice("core1", { surface: "fabric" });
    s.selectLink(linkFor("core1"));
    s.selectDevice("access5", { surface: "fabric" });
  }],
  ["a surface switch in the store", () => useInvestigation.getState().setSurface("path")],
];

/** Scroll like a reader, click a visible row, return it. The row sits mid-port before the switch. */
async function clickVisibleFinding(c: HTMLElement, grid: HTMLElement, g: Geometry): Promise<{ id: string; clickReads: number }> {
  portTop = g.top;
  portBottom = g.bottom;
  rowPx = g.row;
  Object.defineProperty(window, "innerHeight", { configurable: true, value: g.vh });
  // The reader scrolls the queue (the report's scrollTop 1000 at 1920; row-aligned here).
  const scrolled = 18 * g.row;
  readerScroll(grid, scrolled);
  // The row that sits in the lower half of the port — the part the path panel is about to take.
  const rows = dataRows(c);
  const target = rows.find((r) => {
    const b = r.getBoundingClientRect();
    return b.top >= (g.top + g.bottom) / 2 && b.bottom <= g.bottom;
  })!;
  expect(target, `${g.name}: precondition, a row in the lower half of the port`).toBeTruthy();
  const clickReads = pointerClick(grid, target);
  expect(target.getAttribute("data-active"), `${g.name}: the click selects the row`).toBe("yes");
  expect(grid.scrollTop, `${g.name}: a click never moves the list under the pointer`).toBe(scrolled);
  await settle();
  const id = idOf(target);
  expect(useInvestigation.getState().findingId).toBe(id);
  return { id, clickReads };
}

describe("A4 wave 8: a shrinking port re-reveals the selected row, however the selection was reached", () => {
  for (const g of GEOMETRIES) {
    for (const [what, trigger] of TRIGGERS) {
      it(`${g.name}: clicked finding, then ${what}, then the port shrinks`, async () => {
        const c = mount(<PriorityQueue debounceMs={0} />);
        const grid = installLayout(c);
        const { id } = await clickVisibleFinding(c, grid, g);
        const host = fabric.findings.find((f) => f.id === id)?.devices[0];
        act(() => { trigger(host); });
        await settle();
        expect(useInvestigation.getState().findingId, "the finding selection survives every trigger").toBe(id);
        const row = activeRow(c)!;
        expect(inView(row), `${g.name}: before the switch the row is on screen (${where(row)})`).toBe(true);
        const before = grid.scrollTop;

        // The path panel takes the top of the rail: the port shrinks, and the rows ride its top edge.
        portTop = g.shrunk;
        expect(inView(row), `${g.name}: precondition, the shrink pushes the row out (${where(row)})`).toBe(false);
        deliverResize();
        expect(inView(row), `${g.name}: after the shrink the selected row is on screen (${where(row)})`).toBe(true);
        // The LEAST movement: the row lands on the band's bottom edge, not centred.
        const r = row.getBoundingClientRect();
        expect(portBottom - r.bottom, `${g.name}: a nearest reveal, not a centring throw (moved ${grid.scrollTop - before} px)`).toBeLessThan(2);

        // A later selection on the path surface (the flow submit's hop 0) keeps it there.
        act(() => {
          useInvestigation.getState().selectDevice("core1", { surface: "path" });
          useInvestigation.getState().selectHop(0);
        });
        await settle();
        deliverResize();
        expect(inView(row), `${g.name}: after the flow submit (${where(row)})`).toBe(true);
      });
    }
  }

  it("the control: a row the READER scrolled away is not pulled back by a shrink", async () => {
    const g = GEOMETRIES[0]!;
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    await clickVisibleFinding(c, grid, g);
    const row = activeRow(c)!;
    readerScroll(grid, 0);
    expect(inView(row)).toBe(false);
    portTop = g.shrunk;
    deliverResize();
    expect(grid.scrollTop, "the reader's own scroll position is theirs").toBe(0);
  });

  it("E3: the click's own commit reads no more layout than the grid did before this repair", async () => {
    /* Zero is what the queue's click path costs today (the activation skip exists for exactly this:
       acceptance E3, journey 1). The keep-in-view latch must be armed without measuring anything. */
    const g = GEOMETRIES[0]!;
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    const { clickReads } = await clickVisibleFinding(c, grid, g);
    expect(clickReads, "getBoundingClientRect calls inside the click").toBe(0);
  });
});

describe("A4/D3 wave 8: the FOCUSED cell is kept on screen when the port shrinks under it", () => {
  for (const g of GEOMETRIES) {
    it(`${g.name}: focus on a cell in the grid, the port shrinks, the focused cell is revealed`, async () => {
      const c = mount(<PriorityQueue debounceMs={0} />);
      const grid = installLayout(c);
      await clickVisibleFinding(c, grid, g);
      // The reader walks focus two rows down with the keyboard (focus ≠ selection).
      const start = activeRow(c)!.querySelector<HTMLElement>('[role="rowheader"]')!;
      act(() => start.focus());
      for (let i = 0; i < 2; i += 1) {
        act(() => {
          document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }));
        });
      }
      const focused = document.activeElement as HTMLElement;
      expect(grid.contains(focused), "focus stays in the grid").toBe(true);
      const focusRow = focused.closest<HTMLElement>(".ag__row--data")!;
      expect(focusRow, "the focused cell is on a data row").toBeTruthy();
      expect(inView(focusRow), `before: ${where(focusRow)}`).toBe(true);
      portTop = g.shrunk;
      expect(inView(focusRow), `precondition, the shrink pushes the focused row out (${where(focusRow)})`).toBe(false);
      deliverResize();
      expect(inView(focusRow), `${g.name}: the focused cell's row is on screen after the shrink (${where(focusRow)})`).toBe(true);
    });
  }
});

describe("A4 wave 8: the grid MOVED inside a scrolling rail (nothing resized) — the watched row is brought back", () => {
  /* MEASURED (repair wave 8, 1920x1080 and 1440x900, the report's sequence then "Trace this flow"):
     the path panel ABOVE the queue grew inside rail A; the grid kept its 19rem box and slid down, and
     its visible band became 1042-1054 at 1920 (12 px, F026 at 1141-1197) and 751-874 at 1440 (F026
     at 970-1026). No ResizeObserver the grid holds fires for a MOVE, and no scroll event reaches it.
     Modelled: rail A's box clips the grid; content above the grid grows; the only signal is the row's
     own visibility changing (IntersectionObserver). */
  const RAIL = { top: 92, bottom: 874 };
  const GRID_H = 304;
  function mountInRail(): { c: HTMLElement; grid: HTMLElement } {
    const c = mount(
      <div className="rail" style={{ overflowY: "auto" }}>
        <PriorityQueue debounceMs={0} />
      </div>,
    );
    railEl = c.querySelector<HTMLElement>(".rail")!;
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
    railBox = RAIL;
    const grid = installLayout(c);
    // The grid is its own scroll port (desktop): 146 rows in a 19rem box.
    Object.defineProperty(grid, "scrollHeight", { configurable: true, value: 9000 });
    Object.defineProperty(grid, "clientHeight", { configurable: true, value: GRID_H });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 900 });
    return { c, grid };
  }
  const bandOf = (): { top: number; bottom: number } => ({
    top: Math.max(portTop - railShift() + HEAD_PX, RAIL.top),
    bottom: Math.min(portBottom - railShift(), RAIL.bottom),
  });
  const inRailView = (row: HTMLElement): boolean => {
    const r = row.getBoundingClientRect();
    const b = bandOf();
    return r.top >= b.top - 1 && r.bottom <= b.bottom + 1;
  };
  const deliverIntersection = (): void => {
    act(() => {
      for (const w of watchers) if (w.targets.size > 0) w.cb([], w.self);
    });
  };
  async function clickInRail(c: HTMLElement, grid: HTMLElement): Promise<HTMLElement> {
    rowPx = 56;
    portTop = RAIL.top + 420;
    portBottom = portTop + GRID_H;
    readerScroll(grid, 18 * 56);
    const target = dataRows(c).find((r) => {
      const b = r.getBoundingClientRect();
      return b.top >= portTop + HEAD_PX + 60 && b.bottom <= portBottom;
    })!;
    expect(target, "precondition: a visible row").toBeTruthy();
    pointerClick(grid, target);
    await settle();
    expect(target.getAttribute("data-active")).toBe("yes");
    expect(inRailView(target)).toBe(true);
    return target;
  }

  it("content above the grid grows: the row is brought back by scrolling the RAIL, never the page", async () => {
    const { c, grid } = mountInRail();
    const row = await clickInRail(c, grid);
    const gridScroll = grid.scrollTop;
    // The path panel above grows by 280 px: the grid slides down, its band shrinks to 42 px.
    portTop += 280;
    portBottom += 280;
    expect(inRailView(row), "precondition: the move pushed the row out").toBe(false);
    deliverIntersection();
    expect(inRailView(row), `the row is back in view (rail scrolled ${railShift()} px)`).toBe(true);
    expect(railShift(), "the rail moved").toBeGreaterThan(0);
    expect(grid.scrollTop, "the grid's own port already showed the row: it did not scroll").toBe(gridScroll);
    expect(pageScrolls, "the document was never scrolled by a hold").toBe(0);
  });

  it("a press OUTSIDE the grid (a button) does not make the rail's own re-layout scroll the reader's", async () => {
    const { c, grid } = mountInRail();
    const row = await clickInRail(c, grid);
    const button = document.createElement("button");
    c.appendChild(button);
    act(() => {
      button.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    });
    portTop += 280;
    portBottom += 280;
    act(() => {
      railEl!.scrollTop = 4; // the browser nudges the rail (anchoring) — no reader input on it
      railEl!.dispatchEvent(new Event("scroll"));
    });
    deliverIntersection();
    expect(inRailView(row), "the hold survived the button press and the rail's own scroll").toBe(true);
  });

  it("control: the READER scrolls the rail (a wheel over it) away from the row — the hold lets go", async () => {
    const { c, grid } = mountInRail();
    const row = await clickInRail(c, grid);
    act(() => {
      railEl!.dispatchEvent(new WheelEvent("wheel", { bubbles: true }));
      railEl!.scrollTop = 900;
      railEl!.dispatchEvent(new Event("scroll"));
    });
    expect(inRailView(row), "precondition: the reader scrolled it out").toBe(false);
    deliverIntersection();
    expect(railShift(), "the reader's rail position is theirs").toBe(900);
  });
});
