/**
 * DataGrid.selection-page.test.tsx — a SELECTION reveal never scrolls the document.
 *
 * MEASURED (acceptance A6 refuter, 390x844, release build): "Show the 3-D fabric", then a real canvas
 * click on core2. The queue's selection reveal (the first finding naming core2) could not scroll the
 * grid — at phone width the grid lays out at full height and the PAGE scrolls it — so it handed the
 * whole distance to the document: `window.scrollBy(0, 2264)` then `(0, 61)`, scrollY 0 -> 2325, and
 * 0 px of the fabric stayed on screen. The selection was made ON the fabric, to see its blast radius
 * there; the reveal took the reader away from it. The focus guard did not stop it: the canvas held
 * focus, but the label layer laid over it reads as a cover, so the canvas counted as 0 px seen.
 *
 * The rule under test is the rule, not that one layout: a reveal that follows a selection (and the
 * hold that keeps it) scrolls the grid and its own scrolling ancestors, never the document. The
 * keyboard's own reveal — focus inside the grid moving to a row — still may (the reader is there).
 *
 * jsdom lays nothing out, so the page is a small explicit model: the grid's rows sit at fixed page
 * coordinates, their viewport rect is that minus `scrollY`, and `window.scrollBy` moves `scrollY`.
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

const VIEW_H = 844;
/** The grid's page-y: below the stage, the way the phone layout stacks it, its first rows on screen. */
const GRID_TOP = 600;
const HEAD = 40;
const ROW = 40;

interface Row {
  id: string;
}
const ROWS: Row[] = Array.from({ length: 80 }, (_, i) => ({ id: `m${i}` }));
const columns: GridColumn<Row>[] = [{ id: "id", header: "ID", width: "1fr", rowHeader: true, render: (r) => r.id }];

let root: Root | null = null;
let container: HTMLElement | null = null;
let scrollY = 0;
let calls: number[] = [];
const originals = {
  scrollBy: window.scrollBy,
  innerHeight: Object.getOwnPropertyDescriptor(window, "innerHeight"),
  scrollY: Object.getOwnPropertyDescriptor(window, "scrollY"),
  rect: HTMLElement.prototype.getBoundingClientRect,
};

const rect = (top: number, bottom: number): DOMRect =>
  ({ top, bottom, left: 0, right: 390, width: 390, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;

function Harness({ revealId, revealKey, rows }: { revealId: string | null; revealKey: string; rows: number }): ReactElement {
  const nodes: GridNode<Row>[] = ROWS.slice(0, rows).map((r) => ({ kind: "row" as const, id: r.id, item: r }));
  return <DataGrid<Row> label="Rows" columns={columns} nodes={nodes} template="1fr" revealId={revealId} revealKey={revealKey} />;
}

function render(revealId: string | null, revealKey: string, rows = ROWS.length): void {
  act(() => root!.render(<Harness revealId={revealId} revealKey={revealKey} rows={rows} />));
}

/** Mounts the grid at full height (it is NOT its own scroll port: its scrollTop never moves). */
function mount(): HTMLElement {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  render(null, "none");
  const grid = container.querySelector<HTMLElement>(".ag__grid")!;
  Object.defineProperty(grid, "scrollTop", { configurable: true, get: () => 0, set: () => undefined });
  const indexOf = (el: HTMLElement): number => [...grid.querySelectorAll<HTMLElement>(".ag__row--data")].indexOf(el);
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    const y = GRID_TOP - scrollY;
    if (this.classList.contains("ag__grid")) return rect(y, y + HEAD + ROWS.length * ROW);
    if (this.classList.contains("ag__head")) return rect(y, y + HEAD);
    const row = this.closest<HTMLElement>(".ag__row--data");
    if (row !== null && grid.contains(row)) {
      const top = y + HEAD + indexOf(row) * ROW;
      return rect(top, top + ROW);
    }
    return originals.rect.call(this) as DOMRect;
  };
  return grid;
}

beforeEach(() => {
  scrollY = 0;
  calls = [];
  Object.defineProperty(window, "innerHeight", { value: VIEW_H, configurable: true });
  Object.defineProperty(window, "scrollY", { get: () => scrollY, configurable: true });
  window.scrollBy = ((x: number | ScrollToOptions, y?: number) => {
    const dy = typeof x === "number" ? (y ?? 0) : (x.top ?? 0);
    calls.push(dy);
    scrollY = Math.max(0, scrollY + dy);
  }) as typeof window.scrollBy;
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
  HTMLElement.prototype.getBoundingClientRect = originals.rect;
  window.scrollBy = originals.scrollBy;
  if (originals.innerHeight) Object.defineProperty(window, "innerHeight", originals.innerHeight);
  if (originals.scrollY) Object.defineProperty(window, "scrollY", originals.scrollY);
  else delete (window as { scrollY?: number }).scrollY;
  delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
});

describe("a selection reveal scrolls the grid and its own ports, never the document", () => {
  it("a selection made elsewhere (the canvas; nothing in the grid focused) leaves the page where it is", () => {
    mount();
    (document.activeElement as HTMLElement | null)?.blur();
    render("m60", "device:core2");
    expect(calls, "the reveal called window.scrollBy").toEqual([]);
    expect(scrollY).toBe(0);
  });

  it("the hold that keeps the revealed row does not scroll the document either (the rows re-commit)", () => {
    mount();
    render("m60", "device:core2");
    // Whatever the reveal itself did, the page is the reader's again: the re-commit alone is judged.
    calls = [];
    scrollY = 0;
    render("m60", "device:core2", ROWS.length - 1);
    expect(calls, "the hold called window.scrollBy").toEqual([]);
    expect(scrollY).toBe(0);
  });
});
