/**
 * DataGrid.sticky-bar-reveal.test.tsx — D3 (repair wave 8): a reveal or focus that scrolls the
 * DOCUMENT stops above the sticky status bar, and the focused cell is re-revealed against the
 * SETTLED layout after a change the reader did not make to the grid.
 *
 * THE DEFECT, measured (`node review/audit-d3-focus.mjs --vp=390`, dev server, deterministic, exit 1;
 * acceptance-report.md at `34bd435`, D3 FAIL): phone/inspector (citation), the queue's popover "What
 * the collection gap means for this result" → open → Tab. The Tab-off-last handler closes the popover
 * and focuses the grid's roving cell. That cell ended at [76,754,261,788] under the status bar
 * (`position: sticky; bottom: 0`, 759-844 at 390x844): "0/9 points on the element; the rest on
 * BUTTON.sb__cov". Traced in this wave with an instrumented copy of the audit (focusin, microtask and
 * two frames after it, plus a trap on `window.scrollBy`): at focusin the cell sat at 714-755 — above
 * the bar — with the popover still open over the band (635-833); the grid's own arrival reveal,
 * measuring that still-open popover as an overlay, called `window.scrollBy(0, -37.3)` (stack:
 * onFocus -> revealBelowHeader -> revealThroughAncestors), and once the popover closed the cell sat
 * at 754-788. Reproduced on the checkpointed tree (`fea2037`, served separately) with the same exit
 * and the same rect. A second run of the same state put the next case's cell under the bar the other way: the
 * Escape that follows clears the selection, the rail above the grid re-worded in a deferred commit,
 * and the grid moved 24 px down with no scroll at all (cell 718-751 -> 742-775).
 *
 * Defects of one class — a visibility decision taken against a layout that is still changing, or
 * against an overlay that hides what the decision needs:
 *   1. Focus arriving from outside was revealed once, while the act that moved it was still changing
 *      the layout (the traced case), and nothing re-checked it after: no observer fires when a page
 *      scroll or content above the grid moves it (narrow layouts scroll the grid with the page).
 *   2. `trimOverlays` consulted only the TOPMOST hit at each probe: a box covering the whole remaining
 *      band (an open popover's frame) ended the walk, so a bar beneath it was never trimmed. Modelled
 *      below with the measured boxes; not separately traced in the browser.
 *
 * jsdom lays nothing out, so the page is an explicit model (as DataGrid.reveal-focus.test.tsx): the
 * grid is laid out at full height (not its own port), every box has a page-y top, its viewport rect
 * is that minus `scrollY`, and `window.scrollBy` moves `scrollY`. The bar and the popover are fixed
 * boxes; `document.elementsFromPoint` answers from the same model, top-most first.
 */
import { act, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";
import { DataGrid, revealBelowHeader, type GridColumn, type GridNode } from "./DataGrid";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const VIEW_W = 390;
const VIEW_H = 844;
/** The status bar wraps to 85 px at 390 (measured), `position: sticky; bottom: 0`. */
const BAR_H = 85;
const BAR_TOP = VIEW_H - BAR_H;
/** Its trailing coverage group, a child box starting inside it (measured 820-844). */
const BAR_REST_TOP = 820;
/** The popover measured open over the band (635-833), portalled above the bar. */
const POP = { top: 635, bottom: 833 };
const HEAD = 28;
const ROW = 41;

interface Row {
  id: string;
}
const ROWS: Row[] = Array.from({ length: 60 }, (_, i) => ({ id: `r${i}` }));
const nodes: GridNode<Row>[] = ROWS.map((r) => ({ kind: "row" as const, id: r.id, item: r }));
const columns: GridColumn<Row>[] = [{ id: "id", header: "ID", width: "1fr", rowHeader: true, render: (r) => r.id }];

let scrollY = 0;
/** Page-y of the grid's top edge; content above the grid growing moves it. */
let gridTop = 0;
let popoverOpen = false;
let barInStack = true;
let bar: HTMLElement;
let barRest: HTMLElement;
let popover: HTMLElement;
/** The popover's text block (measured 685-751.3 in the trace), drawn inside its frame. */
let popNote: HTMLElement;
let noteOpen = false;
const NOTE = { top: 685, bottom: 751.3125 };
let root: Root | null = null;
let container: HTMLElement | null = null;
/** Each stubbed observer with the elements it observes: a resize reaches only the observers of the
 *  element that resized, as in a browser. */
const observers: { cb: ResizeObserverCallback; self: ResizeObserver; targets: Set<Element> }[] = [];
const saved = {
  gbcr: HTMLElement.prototype.getBoundingClientRect,
  scrollBy: window.scrollBy,
  innerHeight: Object.getOwnPropertyDescriptor(window, "innerHeight"),
  innerWidth: Object.getOwnPropertyDescriptor(window, "innerWidth"),
  scrollY: Object.getOwnPropertyDescriptor(window, "scrollY"),
};

const rect = (top: number, bottom: number): DOMRect =>
  ({ top, bottom, left: 0, right: VIEW_W, width: VIEW_W, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;

const gridEl = (): HTMLElement => container!.querySelector<HTMLElement>(".ag__grid")!;
const dataRows = (): HTMLElement[] => [...container!.querySelectorAll<HTMLElement>(".ag__row--data")];

function layout(el: HTMLElement): DOMRect | null {
  if (el === bar) return rect(BAR_TOP, VIEW_H);
  if (el === barRest) return rect(BAR_REST_TOP, VIEW_H);
  if (el === popover) return rect(POP.top, POP.bottom);
  if (el === popNote) return rect(NOTE.top, NOTE.bottom);
  if (container === null || !container.contains(el)) return null;
  const top = gridTop - scrollY;
  if (el.classList.contains("ag__grid")) return rect(top, top + HEAD + ROWS.length * ROW);
  if (el.closest(".ag__head")) return rect(top, top + HEAD);
  const row = el.closest<HTMLElement>(".ag__row--data");
  if (row) {
    const i = dataRows().indexOf(row);
    const t = top + HEAD + i * ROW;
    return rect(t, t + ROW);
  }
  return null;
}

/** The hit-test stack at y, top-most first, from the same model. */
function stackAt(_x: number, y: number): Element[] {
  const out: Element[] = [];
  if (noteOpen && y >= NOTE.top && y < NOTE.bottom) out.push(popNote);
  if (popoverOpen && y >= POP.top && y < POP.bottom) out.push(popover);
  if (barInStack && y >= BAR_REST_TOP && y < VIEW_H) out.push(barRest);
  if (barInStack && y >= BAR_TOP && y < VIEW_H) out.push(bar);
  const row = dataRows().find((r) => {
    const b = r.getBoundingClientRect();
    return y >= b.top && y < b.bottom;
  });
  out.push(row ?? gridEl(), document.body);
  return out;
}

function Harness(): ReactElement {
  return <DataGrid<Row> label="Rows" columns={columns} nodes={nodes} template="1fr" />;
}

function mountGrid(): void {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(<Harness />));
  // Not its own port: the page scrolls it.
  Object.defineProperty(gridEl(), "scrollTop", { get: () => 0, set: () => undefined, configurable: true });
}

/** `el` resized: the browser tells the observers of that element only. */
const deliverResize = (el: Element): void => {
  act(() => {
    for (const o of observers) if (o.targets.has(el)) o.cb([], o.self);
  });
};
/** One frame plus one task, twice: what a settle re-check waits for. */
async function frames(): Promise<void> {
  for (let i = 0; i < 2; i += 1) {
    await actAsync(async () => {
      await new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
    });
  }
}
const aboveTheBar = (el: HTMLElement): string | null => {
  const r = (el.closest<HTMLElement>('[role="row"]') ?? el).getBoundingClientRect();
  return r.bottom <= BAR_TOP + 1 && r.top >= 0 ? null : `row ${Math.round(r.top)}-${Math.round(r.bottom)} vs bar ${BAR_TOP}-${VIEW_H}`;
};

beforeEach(() => {
  scrollY = 0;
  gridTop = 1000;
  popoverOpen = false;
  barInStack = true;
  observers.length = 0;
  Object.defineProperty(window, "innerHeight", { value: VIEW_H, configurable: true });
  Object.defineProperty(window, "innerWidth", { value: VIEW_W, configurable: true });
  Object.defineProperty(window, "scrollY", { get: () => scrollY, configurable: true });
  window.scrollBy = ((x: number | ScrollToOptions, y?: number) => {
    const dy = typeof x === "number" ? (y ?? 0) : (x.top ?? 0);
    scrollY = Math.max(0, scrollY + dy);
  }) as typeof window.scrollBy;
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    return layout(this) ?? rect(0, 0);
  };
  (document as Document & { elementsFromPoint: (x: number, y: number) => Element[] }).elementsFromPoint = stackAt;
  (document as Document & { elementFromPoint: (x: number, y: number) => Element | null }).elementFromPoint = (x, y) => stackAt(x, y)[0] ?? null;
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
  bar = document.createElement("footer");
  bar.className = "app__status";
  bar.style.position = "sticky";
  bar.style.bottom = "0px";
  barRest = document.createElement("div");
  barRest.className = "sb__rest";
  bar.appendChild(barRest);
  popover = document.createElement("div");
  popover.className = "ui-popover";
  popNote = document.createElement("p");
  popover.appendChild(popNote);
  noteOpen = false;
  document.body.append(bar, popover);
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  container?.remove();
  container = null;
  HTMLElement.prototype.getBoundingClientRect = saved.gbcr;
  window.scrollBy = saved.scrollBy;
  for (const k of ["innerHeight", "innerWidth", "scrollY"] as const) {
    const d = saved[k];
    if (d) Object.defineProperty(window, k, d);
    else delete (window as unknown as Record<string, unknown>)[k];
  }
  delete (document as { elementsFromPoint?: unknown }).elementsFromPoint;
  delete (document as { elementFromPoint?: unknown }).elementFromPoint;
  delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
  document.body.replaceChildren();
});

/** Scroll the page so row `i` sits at viewport y `top`. */
const placeRow = (i: number, top: number): void => {
  scrollY = gridTop + HEAD + i * ROW - top;
};

describe("a reveal that scrolls the document stops above the sticky status bar", () => {
  it("with a popover frame over the band covering the probe above the bar (modelled on the measured boxes)", () => {
    mountGrid();
    // The grid's header sits below the popover's top edge, so the popover covers the whole band.
    placeRow(3, 780); // 780-821: under the bar
    const row = dataRows()[3]!;
    popoverOpen = true;
    expect(gridEl().getBoundingClientRect().top + HEAD, "precondition: the popover starts above the band").toBeGreaterThan(POP.top);
    revealBelowHeader(gridEl(), gridEl().querySelector(".ag__head"), row, "nearest");
    expect(aboveTheBar(row)).toBeNull();
  });

  it("with the bar alone (the allowance itself; removing it lands the row under the bar)", () => {
    mountGrid();
    placeRow(10, 800); // 800-841
    const row = dataRows()[10]!;
    revealBelowHeader(gridEl(), gridEl().querySelector(".ag__head"), row, "nearest");
    expect(aboveTheBar(row)).toBeNull();
    // The least movement: flush with the bar's top edge, not centred.
    expect(BAR_TOP - row.getBoundingClientRect().bottom).toBeLessThan(1);
  });

  it("control: with no bar painted over the page, the same reveal stops at the viewport's edge", () => {
    barInStack = false;
    mountGrid();
    placeRow(10, 850);
    const row = dataRows()[10]!;
    revealBelowHeader(gridEl(), gridEl().querySelector(".ag__head"), row, "nearest");
    const r = row.getBoundingClientRect();
    expect(r.bottom).toBeLessThanOrEqual(VIEW_H);
    expect(r.bottom, "the bar's height, not something else, is what stopped the reveal above").toBeGreaterThan(BAR_TOP + 1);
  });
});

describe("focus arriving in the grid is re-revealed against the SETTLED layout", () => {
  /** Focus a data cell from a control outside the grid, as the popover's Tab-off handler does. */
  function arrive(i: number, top: number): HTMLElement {
    mountGrid();
    placeRow(i, top);
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    act(() => outside.focus());
    popoverOpen = true;
    const cell = dataRows()[i]!.querySelector<HTMLElement>('[role="rowheader"]')!;
    act(() => cell.focus());
    expect(document.activeElement).toBe(cell);
    expect(aboveTheBar(cell), "precondition: on arrival the cell is above the bar").toBeNull();
    expect(cell.getBoundingClientRect().top, "precondition: the arrival did not move it (measured 714)").toBe(top);
    popoverOpen = false; // the close commits
    return cell;
  }

  it("the page moves in the arrival's own task (no event reaches the grid): the settle re-check restores it", async () => {
    const cell = arrive(0, 714);
    scrollY -= 37; // measured: 62 -> 25 in the same task (the arrival reveal against the still-open popover)
    expect(aboveTheBar(cell), "precondition: the close moved the cell under the bar").not.toBeNull();
    await frames();
    expect(aboveTheBar(cell)).toBeNull();
  });

  it("a page scroll the reader did not make (a scroll event, no input) re-reveals the focused cell", () => {
    const cell = arrive(0, 714);
    scrollY -= 37;
    act(() => {
      document.dispatchEvent(new Event("scroll"));
    });
    expect(aboveTheBar(cell)).toBeNull();
  });

  it("content above the grid grows (the grid MOVES, no scroll): the page-size observer re-reveals it", async () => {
    const cell = arrive(0, 714);
    await frames(); // the arrival's settle has run and found nothing to do
    gridTop += 24; // measured: 718-751 -> 742-775 after the Escape's deferred commit
    expect(aboveTheBar(cell), "precondition: the move put the cell under the bar").not.toBeNull();
    deliverResize(document.body);
    expect(aboveTheBar(cell)).toBeNull();
  });

  it("control: a reader who scrolls the page away from their focus is not pulled back by a later layout change", async () => {
    const cell = arrive(0, 714);
    await frames();
    act(() => {
      document.body.dispatchEvent(new WheelEvent("wheel", { bubbles: true }));
      scrollY += 800; // the first row leaves by the top edge
      document.dispatchEvent(new Event("scroll"));
    });
    const y = scrollY;
    expect(aboveTheBar(cell), "precondition: the reader scrolled the cell off screen").not.toBeNull();
    gridTop += 24;
    deliverResize(document.body);
    await frames();
    expect(scrollY, "the reader's page position is theirs").toBe(y);
  });

  it("the traced case end to end: the arrival reveal, measured against the still-open popover, moves the cell; the settle puts it back", async () => {
    mountGrid();
    placeRow(0, 714);
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    act(() => outside.focus());
    popoverOpen = true;
    noteOpen = true;
    const cell = dataRows()[0]!.querySelector<HTMLElement>('[role="rowheader"]')!;
    const y0 = scrollY;
    act(() => cell.focus());
    // What the trace recorded: the arrival scrolled the page UP by the note's overlap (-37.3).
    expect(scrollY - y0, "the arrival reveal read the open popover as an overlay").toBeLessThan(-30);
    popoverOpen = false; // the close commits
    noteOpen = false;
    expect(aboveTheBar(cell), "precondition: with the popover gone the cell is under the bar").not.toBeNull();
    await frames();
    expect(aboveTheBar(cell)).toBeNull();
  });
});
