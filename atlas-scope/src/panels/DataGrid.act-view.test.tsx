/**
 * DataGrid.act-view.test.tsx — an "is it already on screen?" decision is taken against what the
 * reader could see WHEN THEY ACTED (`actKey`), not against a layout the act itself has since moved.
 *
 * THE DEFECT CLASS (A4, measured 1920x1080): the queue's "N of 146 shown findings name access13"
 * sentence mounts above the grid in the pick's URGENT commit and moves the port's top 352 -> 389.7;
 * the DEFERRED reveal then asked `revealUnlessVisible` whether an answer was on screen, found the
 * only visible naming row (F099, 13 px above the old bottom edge) 38 px under the new one, and
 * threw the list 4777 -> 0. Nothing about the grid is specific to that sentence: any content an act
 * puts above the port, in the act's own commit or in the reveal's, moves the band before the
 * decision. So these tests drive the grid directly, with an arbitrary element above it whose height
 * the test sets, and pin:
 *   · a row visible at the act and pushed out afterwards is brought back by the LEAST movement;
 *   · the record is taken BEFORE the act's commit mutates the DOM — the shift and the decision in
 *     ONE commit is answered too (a layout effect would already see the moved layout);
 *   · the selection itself, visible at the act, is restored by nearest movement, not re-centred;
 *   · the reader's own input, or any scroll, after the act voids the record (their newer view
 *     counts), and a first-naming reveal still happens when nothing was visible.
 */
import { act, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { DataGrid, type GridColumn, type GridNode } from "./DataGrid";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const BASE_TOP = 100;
const PORT_BOTTOM = 600;
const HEAD = 40;
const ROW = 40;
/** The layout the stub draws. The sweep below swaps in each viewport's measured geometry. */
const DEFAULT_G = { top: BASE_TOP, bottom: PORT_BOTTOM, head: HEAD, row: ROW };
let G = { ...DEFAULT_G };
const SHIFT = 38;

interface Row {
  id: string;
}
const ROWS: Row[] = Array.from({ length: 80 }, (_, i) => ({ id: `m${i}` }));
const nodes: GridNode<Row>[] = ROWS.map((r) => ({ kind: "row" as const, id: r.id, item: r }));
const columns: GridColumn<Row>[] = [{ id: "id", header: "ID", width: "1fr", rowHeader: true, render: (r) => r.id }];

interface Props {
  above: number;
  actKey?: string;
  revealKey: string;
  revealId: string | null;
  unless?: ReadonlySet<string>;
  related?: ReadonlySet<string>;
}

let root: Root | null = null;
let container: HTMLElement | null = null;
let restore: (() => void) | null = null;
/** A browser snaps scrollTop to device pixels (integers at DPR 1); jsdom keeps any number. */
let snapScroll = false;

function Harness(p: Props): ReactElement {
  return (
    <div>
      <p className="above" data-h={p.above} />
      <DataGrid<Row>
        label="Rows"
        columns={columns}
        nodes={nodes}
        template="1fr"
        revealId={p.revealId}
        revealKey={p.revealKey}
        {...(p.unless ? { revealUnlessVisible: p.unless } : {})}
        {...(p.related ? { relatedIds: p.related } : {})}
        {...(p.actKey !== undefined ? { actKey: p.actKey } : {})}
      />
    </div>
  );
}

const rect = (top: number, bottom: number): DOMRect =>
  ({ top, bottom, left: 0, right: 900, width: 900, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;

function render(p: Props): void {
  act(() => root!.render(<Harness {...p} />));
}

/** Mounts, then installs a layout in which the element above the grid pushes the port's top down. */
function mount(p: Props): HTMLElement {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  render(p);
  const grid = container.querySelector<HTMLElement>(".ag__grid")!;
  let scrollTop = 0;
  Object.defineProperty(grid, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (v: number) => {
      scrollTop = Math.max(0, snapScroll ? Math.round(v) : v);
    },
  });
  const portTop = (): number => G.top + Number(container?.querySelector<HTMLElement>(".above")?.dataset.h ?? 0);
  const original = HTMLElement.prototype.getBoundingClientRect;
  const indexOf = new WeakMap<HTMLElement, number>();
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    if (this.classList.contains("ag__grid")) return rect(portTop(), G.bottom);
    if (this.classList.contains("ag__head")) return rect(portTop(), portTop() + G.head);
    if (this.classList.contains("ag__row--data")) {
      // The row set never changes after mount here, so each row's index is looked up once.
      let at = indexOf.get(this);
      if (at === undefined) {
        [...grid.querySelectorAll<HTMLElement>(".ag__row--data")].forEach((r, i) => indexOf.set(r, i));
        at = indexOf.get(this) ?? -1;
      }
      const top = portTop() + G.head + at * G.row - grid.scrollTop;
      return rect(top, top + G.row);
    }
    return original.call(this) as DOMRect;
  };
  restore = () => {
    HTMLElement.prototype.getBoundingClientRect = original;
  };
  return grid;
}

const rowEl = (i: number): HTMLElement => container!.querySelectorAll<HTMLElement>(".ag__row--data")[i]!;
const fullyVisible = (i: number): boolean => {
  const r = rowEl(i).getBoundingClientRect();
  const top = G.top + Number(container!.querySelector<HTMLElement>(".above")!.dataset.h) + G.head;
  return r.top >= top - 0.01 && r.bottom <= G.bottom + 0.01;
};

function readerScrollsTo(grid: HTMLElement, y: number): void {
  act(() => {
    grid.dispatchEvent(new Event("wheel"));
    grid.scrollTop = y;
    grid.dispatchEvent(new Event("scroll"));
  });
}

/** scrollTop that puts row `i`'s bottom `gap` px above the port's bottom edge, with nothing above. */
const bottomBand = (i: number, gap: number): number => i * ROW + ROW - (PORT_BOTTOM - gap - BASE_TOP - HEAD);

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  container?.remove();
  container = null;
  restore?.();
  restore = null;
  snapScroll = false;
  G = { ...DEFAULT_G };
  delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
});

/** The representative-reveal shape: m0 is the "first naming row", m40 the one the reader sees. */
const NAMING = new Set(["m0", "m40"]);

describe("an 'already visible?' decision is taken against what the reader saw when they acted", () => {
  for (const gap of [0, 1, 13, 25, SHIFT - 1]) {
    it(`two commits (act, then reveal): the answer ${gap} px above the bottom edge is kept, by the least movement`, () => {
      const grid = mount({ above: 0, actKey: "a0", revealKey: "k0", revealId: null });
      const start = bottomBand(40, gap);
      readerScrollsTo(grid, start);
      expect(fullyVisible(40) && !fullyVisible(0), "precondition").toBe(true);
      render({ above: SHIFT, actKey: "a1", revealKey: "k0", revealId: null }); // the act: content above
      expect(fullyVisible(40), "the act has pushed the answer out of the band").toBe(false);
      render({ above: SHIFT, actKey: "a1", revealKey: "k1", revealId: "m0", unless: NAMING }); // the reveal
      expect(fullyVisible(40), "the answer the reader was looking at is fully visible").toBe(true);
      expect(Math.abs(grid.scrollTop - start), `scrollTop ${start} -> ${grid.scrollTop}`).toBeLessThanOrEqual(SHIFT);
    });
  }

  it("ONE commit (act, content and reveal together): the record predates the commit's own DOM changes", () => {
    const grid = mount({ above: 0, actKey: "a0", revealKey: "k0", revealId: null });
    const start = bottomBand(40, 13);
    readerScrollsTo(grid, start);
    render({ above: SHIFT, actKey: "a1", revealKey: "k1", revealId: "m0", unless: NAMING });
    expect(fullyVisible(40)).toBe(true);
    expect(Math.abs(grid.scrollTop - start), `scrollTop ${start} -> ${grid.scrollTop}`).toBeLessThanOrEqual(SHIFT);
  });

  it("the selection itself, visible at the act and pushed partly out, is restored by nearest movement, not re-centred", () => {
    const grid = mount({ above: 0, actKey: "a0", revealKey: "k0", revealId: null });
    const start = bottomBand(40, 13);
    readerScrollsTo(grid, start);
    render({ above: SHIFT, actKey: "a1", revealKey: "k0", revealId: null });
    render({ above: SHIFT, actKey: "a1", revealKey: "k1", revealId: "m40" });
    expect(fullyVisible(40)).toBe(true);
    expect(Math.abs(grid.scrollTop - start), `scrollTop ${start} -> ${grid.scrollTop}`).toBeLessThanOrEqual(SHIFT);
  });

  it("the reader's own input after the act voids the record: their newer view (no answer) gets the first naming row", () => {
    const grid = mount({ above: 0, actKey: "a0", revealKey: "k0", revealId: null });
    readerScrollsTo(grid, bottomBand(40, 13));
    render({ above: SHIFT, actKey: "a1", revealKey: "k0", revealId: null });
    readerScrollsTo(grid, bottomBand(40, 13)); // same offset, but the reader touched the grid
    render({ above: SHIFT, actKey: "a1", revealKey: "k1", revealId: "m0", unless: NAMING });
    expect(fullyVisible(0), "m0 revealed").toBe(true);
  });

  it("a scroll after the act (no input — a clamp, another script) voids the record too", () => {
    const grid = mount({ above: 0, actKey: "a0", revealKey: "k0", revealId: null });
    readerScrollsTo(grid, bottomBand(40, 13));
    render({ above: SHIFT, actKey: "a1", revealKey: "k0", revealId: null });
    act(() => {
      grid.scrollTop = 20 * ROW; // no naming row in view now
    });
    render({ above: SHIFT, actKey: "a1", revealKey: "k1", revealId: "m0", unless: NAMING });
    expect(fullyVisible(0), "m0 revealed").toBe(true);
  });

  it("negative control: no answer visible at the act — the first naming row is revealed", () => {
    const grid = mount({ above: 0, actKey: "a0", revealKey: "k0", revealId: null });
    readerScrollsTo(grid, 20 * ROW);
    render({ above: SHIFT, actKey: "a1", revealKey: "k0", revealId: null });
    render({ above: SHIFT, actKey: "a1", revealKey: "k1", revealId: "m0", unless: NAMING });
    expect(fullyVisible(0)).toBe(true);
  });

  it("a fractional shift under a device-pixel scrollTop: the restore lands the row fully inside, so the hold never re-centres it", () => {
    /* MEASURED (dev build, 1920x1080) after the act record existed: the sentence moved the port by
       37.7 px, `scrollTop += 37.7` snapped to the device pixel short of it, F099 sat 0.3 px under
       the edge, and the hold — which answers any row not fully inside — CENTRED it on the next
       commit: 4777 -> 5099. The model's 37.3 px shift leaves the same 0.3 px fraction, so a
       round-to-nearest scrollTop falls short exactly as Chrome's did. */
    snapScroll = true;
    const grid = mount({ above: 0, actKey: "a0", revealKey: "k0", revealId: null });
    const start = bottomBand(40, 13);
    readerScrollsTo(grid, start);
    // The reader's pointer leaves the grid for the canvas, where they pick.
    act(() => {
      grid.dispatchEvent(new Event("pointerleave"));
    });
    render({ above: 37.3, actKey: "a1", revealKey: "k0", revealId: null });
    render({ above: 37.3, actKey: "a1", revealKey: "k1", revealId: "m0", unless: NAMING });
    // The browser reports the programmatic scroll; a later commit (the marks) re-runs the hold.
    act(() => {
      grid.dispatchEvent(new Event("scroll"));
    });
    render({ above: 37.3, actKey: "a1", revealKey: "k1", revealId: "m0", unless: NAMING, related: NAMING });
    expect(fullyVisible(40)).toBe(true);
    expect(Math.abs(grid.scrollTop - start), `scrollTop ${start} -> ${grid.scrollTop}`).toBeLessThanOrEqual(38);
  });

  it("a sub-pixel sliver under the header is still an answer on screen (the band's TOP edge)", () => {
    /* MEASURED (browser band sweep, 1920x1080): F012 scrolled flush to the header sat 0.25 px under
       it — scrollTop snaps to whole pixels, rows sit on fractions — and the strict predicate called it
       hidden: the pick threw the list 645 px to F002. */
    const grid = mount({ above: 0, actKey: "a0", revealKey: "k0", revealId: null });
    const start = 40 * ROW + 0.25; // m40's top 0.25 px under the header's lower edge
    readerScrollsTo(grid, start);
    render({ above: 0, actKey: "a1", revealKey: "k1", revealId: "m0", unless: NAMING });
    expect(grid.scrollTop, `scrollTop ${start} -> ${grid.scrollTop}`).toBe(start);
  });

  it("an act that pushes the answer less than a pixel out still gets it back fully (the band's BOTTOM edge)", () => {
    /* MEASURED (browser band sweep, 1920x1080, after the sliver slack): F026 flush on the bottom edge,
       the pick's sentence moved the port 37.7 px, and the row ended 0.8 px under the edge — "seen"
       by the slack, so nothing restored it. The act made it worse than the reader left it, so the
       least movement brings it back; a sliver the reader's own scroll left is not touched (above). */
    const grid = mount({ above: 0, actKey: "a0", revealKey: "k0", revealId: null });
    const start = bottomBand(40, 0);
    readerScrollsTo(grid, start);
    render({ above: 0.8, actKey: "a1", revealKey: "k0", revealId: null });
    render({ above: 0.8, actKey: "a1", revealKey: "k1", revealId: "m0", unless: NAMING });
    expect(fullyVisible(40)).toBe(true);
    expect(Math.abs(grid.scrollTop - start), `scrollTop ${start} -> ${grid.scrollTop}`).toBeLessThanOrEqual(1);
  });

  it("…but a row with a whole pixel or more hidden is not: the first naming row is revealed", () => {
    const grid = mount({ above: 0, actKey: "a0", revealKey: "k0", revealId: null });
    readerScrollsTo(grid, 40 * ROW + 2);
    render({ above: 0, actKey: "a1", revealKey: "k1", revealId: "m0", unless: NAMING });
    expect(fullyVisible(0)).toBe(true);
  });

  it("control: an answer still fully visible after the shift does not move the list at all", () => {
    const grid = mount({ above: 0, actKey: "a0", revealKey: "k0", revealId: null });
    const start = bottomBand(40, SHIFT + 5);
    readerScrollsTo(grid, start);
    render({ above: SHIFT, actKey: "a1", revealKey: "k0", revealId: null });
    render({ above: SHIFT, actKey: "a1", revealKey: "k1", revealId: "m0", unless: NAMING });
    expect(grid.scrollTop).toBe(start);
  });
});

/* ── The whole band, every pixel, at each measured viewport ─────────────────────────────────────
 *
 * The geometry of the queue's scroll port as MEASURED in the running app (Playwright, 2026-09-25,
 * light theme, nothing selected): the port's top and bottom (the bottom is whichever of the grid's
 * box, the viewport and the status bar cuts first), the sticky header, a data row, and how far the
 * pick's sentence moves the port — split into the URGENT commit's line ("— marking the rows.") and
 * the DEFERRED commit's re-wrap ("— marked on the row's trailing edge." is two lines in the 338 px
 * rail). 390 is page-scrolled in the browser (scroll anchoring absorbs the sentence there — the
 * browser sweep measured 0 of 33 failures); its band is modelled here as a port the size of the
 * viewport above the status bar so the grid's own decision is still swept at that height.
 *
 * For EVERY whole-pixel offset of the only visible naming row, from flush under the header to flush
 * on the bottom edge: pick (the urgent commit moves the port), then mark (the deferred commit re-wraps
 * and decides). The row must end fully visible, and the list may move by no more than the port did. */
const VIEWPORTS = [
  { name: "1920x1080", vh: 1080, top: 352, bottom: 1054, head: 28, row: 56, urgent: 22.8, deferred: 14.9 },
  { name: "1440x900", vh: 900, top: 376, bottom: 874, head: 28, row: 56, urgent: 22.8, deferred: 14.9 },
  { name: "768x1024", vh: 1024, top: 744, bottom: 998, head: 28, row: 32, urgent: 22.8, deferred: 14.9 },
  { name: "390x844", vh: 844, top: 0, bottom: 759, head: 28, row: 41.375, urgent: 44, deferred: 0 },
] as const;

describe("the whole band, every pixel: the only visible naming row keeps the reader's place", () => {
  for (const v of VIEWPORTS) {
    it(`${v.name}: every offset from the top edge to the bottom edge`, () => {
      G = { top: v.top, bottom: v.bottom, head: v.head, row: v.row };
      const vh = Object.getOwnPropertyDescriptor(window, "innerHeight");
      Object.defineProperty(window, "innerHeight", { configurable: true, value: v.vh });
      try {
        // m0 is the first naming row; the reader looks at m40, the only other one, far below it.
        const grid = mount({ above: 0, actKey: "none", revealKey: "none", revealId: null });
        const band = v.bottom - v.top - v.head;
        const failures: string[] = [];
        let n = 0;
        for (let o = 0; o <= Math.floor(band - v.row); o += 1) {
          render({ above: 0, actKey: `none${o}`, revealKey: `none${o}`, revealId: null }); // nothing selected
          const start = 40 * v.row - o;
          readerScrollsTo(grid, start);
          if (!fullyVisible(40) || fullyVisible(0)) throw new Error(`precondition at offset ${o}`);
          render({ above: v.urgent, actKey: `pick${o}`, revealKey: `none${o}`, revealId: null }); // urgent commit
          render({ above: v.urgent + v.deferred, actKey: `pick${o}`, revealKey: `pick${o}`, revealId: "m0", unless: NAMING }); // deferred
          const moved = Math.abs(grid.scrollTop - start);
          n += 1;
          if (!fullyVisible(40) || moved > v.urgent + v.deferred + 1) failures.push(`offset ${o}: scrollTop ${start} -> ${grid.scrollTop}`);
        }
        expect(n).toBeGreaterThan(150);
        expect(failures, `${failures.length} of ${n} offsets lost the reader's place:\n${failures.slice(0, 8).join("\n")}`).toEqual([]);
      } finally {
        if (vh) Object.defineProperty(window, "innerHeight", vh);
      }
    }, 120_000);
  }
});
