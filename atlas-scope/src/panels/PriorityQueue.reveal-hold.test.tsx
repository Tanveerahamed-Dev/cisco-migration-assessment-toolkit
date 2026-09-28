/**
 * PriorityQueue.reveal-hold.test.tsx — A4: a revealed row STAYS revealed while the layout around
 * the queue changes, and a selection made on another surface re-aims the queue even when the
 * selected finding is unchanged.
 *
 * The defect this guards, measured at 1920x1080 on `?s=path&f=F099`: tracing a flow selected
 * core1, which added the "N of 146 shown findings name core1" line above the grid. The scroll
 * port's top moved 795 -> 829 px with scrollTop unchanged, and F099 — revealed flush on the
 * port's bottom edge — ended 34 px below the fold: marked, not revealed. The reveal only ran when
 * the revealed ID changed, and neither the device selection nor the resize changed it.
 *
 * jsdom has no layout, so it is supplied: a scroll port whose TOP can move (the sibling line
 * appearing above it), a sticky header riding that top, and uniform rows positioned from their
 * index and the live scrollTop. ResizeObserver is stubbed so a test can deliver the resize the
 * browser would.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useInvestigation } from "../core/store";
import { PriorityQueue } from "./PriorityQueue";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const PORT_BOTTOM = 561;
const HEAD_PX = 40;
const ROW_PX = 47;

let portTop = 0;
const observers: { cb: ResizeObserverCallback; self: ResizeObserver }[] = [];
const mounted: { root: Root; container: HTMLElement }[] = [];
let restore: (() => void) | null = null;

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
    if (this.classList.contains("ag__grid")) return rect(portTop, PORT_BOTTOM);
    if (this.classList.contains("ag__head")) return rect(portTop, portTop + HEAD_PX);
    if (this.classList.contains("ag__row--data")) {
      const owner = this.closest<HTMLElement>(".ag__grid");
      const rows = owner ? [...owner.querySelectorAll<HTMLElement>(".ag__row--data")] : [];
      const top = portTop + HEAD_PX + rows.indexOf(this) * ROW_PX - (owner?.scrollTop ?? 0);
      return rect(top, top + ROW_PX);
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
const activeRow = (c: HTMLElement): HTMLElement => dataRows(c).find((r) => r.getAttribute("data-active") === "yes")!;
const inView = (row: HTMLElement): boolean => {
  const r = row.getBoundingClientRect();
  return r.top >= portTop + HEAD_PX - 1 && r.bottom <= PORT_BOTTOM + 1;
};
/** What the browser does after a layout change: every observer hears about it. */
const deliverResize = (): void => {
  act(() => {
    for (const o of observers) o.cb([], o.self);
  });
};

beforeEach(() => {
  portTop = 0;
  observers.length = 0;
  const Stub = class {
    constructor(cb: ResizeObserverCallback) {
      observers.push({ cb, self: this as unknown as ResizeObserver });
    }
    observe(): void {}
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
  document.body.innerHTML = "";
});

/** Select the last row through the store — the way a URL or another surface does — and prove it
 *  started below the fold and was revealed. */
function revealDeepFinding(c: HTMLElement, grid: HTMLElement): string {
  const deep = dataRows(c).at(-1)!;
  const id = deep.querySelector('[role="rowheader"]')?.textContent?.trim() ?? "";
  expect(id, "the last row must carry a finding id").toMatch(/^F\d+/);
  expect(inView(deep), "the row must start below the fold or this test proves nothing").toBe(false);
  act(() => { useInvestigation.getState().selectFinding(id); });
  expect(grid.scrollTop).toBeGreaterThan(0);
  expect(inView(activeRow(c))).toBe(true);
  return id;
}

describe("A4: a revealed row stays revealed across path-surface selections and resizes", () => {
  it("keeps the selected finding in view through two traces that select a device and shrink the port", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    const id = revealDeepFinding(c, grid);

    /* Trace 1: the path surface selects the deciding hop's device. In the browser that commit also
       adds the "N findings name core1" line above the grid, which pushes the port's top down. */
    portTop = 34;
    act(() => {
      useInvestigation.getState().selectDevice("core1", { surface: "path" });
      useInvestigation.getState().selectHop(0);
    });
    expect(useInvestigation.getState().findingId, "the finding selection must survive the trace").toBe(id);
    expect(inView(activeRow(c)), "trace 1: the active row must be inside the shrunken port").toBe(true);

    /* Trace 2: same device, same hop — no selection field changes — but the path panel grows
       again (a longer verdict), and the only signal the queue gets is a resize. */
    portTop = 80;
    act(() => {
      useInvestigation.getState().selectDevice("core1", { surface: "path" });
      useInvestigation.getState().selectHop(0);
    });
    deliverResize();
    expect(inView(activeRow(c)), "trace 2: the active row must still be inside the port").toBe(true);
  });

  it("keeps the reader's scroll position when a DEVICE, link or hop changes and the finding does not", () => {
    /* A4: "Scroll position … preserved across that change." MEASURED before the fix (1920x1080,
       f=F106): a reader who had scrolled the queue to 1404, 1904, 2604 or 4704 px was thrown back to
       3404 — the row they had scrolled away from — by one device pick from the canvas, the Fabric
       list, the palette, an evidence-chain chip or a hop. Every one of those ends in the store
       calls below, so each is exercised. */
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    const firstId = dataRows(c)[0]!.querySelector('[role="rowheader"]')?.textContent?.trim() ?? "";
    const id = revealDeepFinding(c, grid);
    act(() => {
      // The READER scrolls: a wheel precedes the scroll, as it does in a browser.
      grid.dispatchEvent(new Event("wheel"));
      grid.scrollTop = 47;
      grid.dispatchEvent(new Event("scroll"));
    });
    expect(inView(activeRow(c))).toBe(false);

    const picks: [string, () => void][] = [
      ["fabric canvas", () => useInvestigation.getState().selectDevice("core2", { surface: "fabric" })],
      ["path hop", () => {
        useInvestigation.getState().selectDevice("core1", { surface: "path" });
        useInvestigation.getState().selectHop(0);
      }],
      ["another device", () => useInvestigation.getState().selectDevice("access7")],
    ];
    for (const [where, pick] of picks) {
      /* Inline and block-bodied: a `() => void` type also admits a Promise-returning function, so the
         act() scope is proved synchronous here rather than inferred from the name (source-hygiene). */
      act(() => {
        pick();
      });
      expect(useInvestigation.getState().findingId, `${where}: the finding must be unchanged`).toBe(id);
      expect(grid.scrollTop, `${where}: the reader's scroll position must survive`).toBe(47);
    }

    // The control: a FINDING change still re-aims (the first row sits partly under the header at 47).
    act(() => { useInvestigation.getState().selectFinding(firstId); });
    expect(grid.scrollTop, "a finding selection re-aims the queue").not.toBe(47);
    expect(inView(activeRow(c)), "a finding selection re-aims the queue").toBe(true);
  });

  it("never pulls back a row the reader scrolled away when only the layout changes", () => {
    /* The hold is not a fight with the reader: after they scroll off the row, a resize must leave
       their scroll position exactly where they put it. */
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    revealDeepFinding(c, grid);
    act(() => {
      // The READER scrolls: a wheel precedes the scroll, as it does in a browser.
      grid.dispatchEvent(new Event("wheel"));
      grid.scrollTop = 0;
      grid.dispatchEvent(new Event("scroll"));
    });
    portTop = 34;
    deliverResize();
    expect(grid.scrollTop).toBe(0);
  });

  it("a scroll the BROWSER fires (clamp or anchoring, no reader input) does not release the hold", () => {
    /* Critic A4, 2026-09-21: after a second path trace the active F099 row sat 272 px below the
       port. Any scroll event used to clear the hold, including one the browser fires itself when a
       resize clamps scrollTop or scroll anchoring adjusts it; the next resize then found no hold. */
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    revealDeepFinding(c, grid);
    act(() => {
      grid.scrollTop = 0; // no wheel, touch, pointer or key before it: layout moved it, not the reader
      grid.dispatchEvent(new Event("scroll"));
    });
    expect(inView(activeRow(c)), "a layout-induced scroll is answered by re-revealing").toBe(true);
    portTop = 80;
    deliverResize();
    expect(inView(activeRow(c)), "and the hold survives the next resize").toBe(true);
  });
});

describe("D3/D5 lead: the focused row is never left under an overlay painted over the port's edge", () => {
  it("keyboard focus moving down stops ABOVE a sticky status bar, not under it (measured 390x844)", () => {
    /* MEASURED (2026-09-23, 390x844, ?s=findings, the page scrolls the grid): the status bar wraps to
       85 px (top 759) and is `position: sticky; bottom: 0` over the document. ArrowDown from the first
       row left EVERY focused row from the 17th on at top 788-812, bottom 844 — fully under the bar
       (elementFromPoint at the row's bottom returned the status bar). The reveal's visible band was
       the viewport and every clip, but nothing that PAINTS over it. Here the bar covers the port's
       bottom 85 px, and the hit test answers the way the browser's does. */
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    const BAR_PX = 85;
    const barTop = PORT_BOTTOM - BAR_PX;
    const bar = document.createElement("footer");
    bar.className = "app__status";
    document.body.appendChild(bar);
    const inner = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
      if (this === bar) return rect(barTop, PORT_BOTTOM);
      return inner.call(this) as DOMRect;
    };
    const doc = document as Document & { elementFromPoint?: (x: number, y: number) => Element | null };
    const hadEfp = Object.prototype.hasOwnProperty.call(doc, "elementFromPoint");
    const efp = doc.elementFromPoint;
    doc.elementFromPoint = (_x: number, y: number): Element | null => {
      if (y >= barTop && y < PORT_BOTTOM) return bar;
      if (y < portTop || y >= PORT_BOTTOM) return null;
      if (y < portTop + HEAD_PX) return grid.querySelector(".ag__head");
      const rows = dataRows(c);
      return rows.find((r) => {
        const b = r.getBoundingClientRect();
        return y >= b.top && y < b.bottom;
      }) ?? grid;
    };
    try {
      const cell = dataRows(c)[0]!.querySelector<HTMLElement>('[role="rowheader"]')!;
      act(() => cell.focus());
      const offenders: string[] = [];
      let checked = 0;
      for (let i = 1; i <= 16; i += 1) {
        act(() => {
          document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }));
        });
        const row = (document.activeElement as HTMLElement).closest<HTMLElement>('[role="row"]')!;
        // This layout stub positions DATA rows; a group header row has no box here to judge.
        if (!row.classList.contains('ag__row--data')) continue;
        checked += 1;
        const r = row.getBoundingClientRect();
        if (r.bottom > barTop + 1 || r.top < portTop + HEAD_PX - 1) {
          offenders.push(`ArrowDown ${i}: row ${Math.round(r.top)}-${Math.round(r.bottom)} vs bar top ${barTop}`);
        }
      }
      expect(checked, "most steps must land on data rows").toBeGreaterThan(12);
      expect(grid.scrollTop, "the grid must have scrolled for this to test anything").toBeGreaterThan(0);
      expect(offenders, "a focused row must sit above the status bar (WCAG 2.4.11)").toEqual([]);
    } finally {
      HTMLElement.prototype.getBoundingClientRect = inner;
      if (hadEfp) doc.elementFromPoint = efp;
      else delete (doc as { elementFromPoint?: unknown }).elementFromPoint;
      bar.remove();
    }
  });
});

describe("D3: focus ARRIVING from outside the grid is brought fully into view", () => {
  it("a cell focused from outside (a dialog returning focus, Tab) that sits under an overlay is revealed above it", () => {
    /* MEASURED (2026-09-23, 1000x800, `node review/audit-d3-focus.mjs`, compact/idle): the grid's
       box ran to y=1002 in an 800 px frame and the status bar (774-800) covered its bottom; the
       roving cell focused by Tab or restored by the palette's Escape sat at 763-780, its ring 38 px
       of indicator against a 41 px floor ("clipped by div.ag__grid > div.app"). The browser's own
       focus scroll knows nothing about a bar painted over the grid, and the grid only ran its
       band-aware reveal for focus IT moved. Focus arriving from outside now gets the same reveal. */
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    const BAR_PX = 26;
    const barTop = PORT_BOTTOM - BAR_PX;
    const bar = document.createElement("footer");
    bar.className = "app__status";
    document.body.appendChild(bar);
    const inner = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
      if (this === bar) return rect(barTop, PORT_BOTTOM);
      return inner.call(this) as DOMRect;
    };
    const doc = document as Document & { elementFromPoint?: (x: number, y: number) => Element | null };
    const hadEfp = Object.prototype.hasOwnProperty.call(doc, "elementFromPoint");
    const efp = doc.elementFromPoint;
    doc.elementFromPoint = (_x: number, y: number): Element | null => (y >= barTop && y < PORT_BOTTOM ? bar : y >= portTop && y < PORT_BOTTOM ? grid : null);
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    try {
      /* The row whose box straddles the bar's top edge. */
      const rows = dataRows(c);
      const straddler = rows.find((r) => {
        const b = r.getBoundingClientRect();
        return b.top < barTop && b.bottom > barTop;
      })!;
      expect(straddler, "precondition: a row straddles the bar").toBeTruthy();
      act(() => outside.focus());
      const cell = straddler.querySelector<HTMLElement>('[role="rowheader"]')!;
      act(() => cell.focus());
      expect(document.activeElement).toBe(cell);
      const b = straddler.getBoundingClientRect();
      expect(b.bottom, `the focused row must end above the bar (row ${Math.round(b.top)}-${Math.round(b.bottom)}, bar ${barTop})`).toBeLessThanOrEqual(barTop + 1);
      expect(b.top).toBeGreaterThanOrEqual(portTop + HEAD_PX - 1);
    } finally {
      HTMLElement.prototype.getBoundingClientRect = inner;
      if (hadEfp) doc.elementFromPoint = efp;
      else delete (doc as { elementFromPoint?: unknown }).elementFromPoint;
      bar.remove();
      outside.remove();
    }
  });
});
