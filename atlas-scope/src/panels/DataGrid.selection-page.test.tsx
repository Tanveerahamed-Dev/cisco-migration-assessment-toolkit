/** Synthetic page/rail controls for selection reveal versus the keyboard's own reveal. */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DataGrid, type GridColumn, type GridNode } from "./DataGrid";

const VIEW = 844;
const ROW_HEIGHT = 40;
const ROWS = Array.from({ length: 80 }, (_, i) => ({ id: `a6-row-${i}` }));
type Row = (typeof ROWS)[number];
const columns: GridColumn<Row>[] = [{ id: "id", header: "ID", width: "1fr", rowHeader: true, render: (row) => row.id }];
const originalRect = HTMLElement.prototype.getBoundingClientRect;
const bodyStyle = document.body.style.cssText;
const htmlStyle = document.documentElement.style.cssText;
const restore: (() => void)[] = [];
let root: Root | null = null;
let container: HTMLElement | null = null;
let scrollY = 0;
let pageWrites: string[] = [];
let frames = new Map<number, FrameRequestCallback>();
let frameId = 0;

function property(target: object, key: string, value: PropertyDescriptor): void {
  const original = Object.getOwnPropertyDescriptor(target, key);
  Object.defineProperty(target, key, { configurable: true, ...value });
  restore.push(() => { if (original) Object.defineProperty(target, key, original); else Reflect.deleteProperty(target, key); });
}
const rect = (top: number, bottom: number): DOMRect => ({ top, bottom, left: 0, right: 390,
  width: 390, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;

function render(revealId: string | null, key: string, rows = ROWS.length): void {
  const nodes: GridNode<Row>[] = ROWS.slice(0, rows).map((row) => ({ kind: "row", id: row.id, item: row }));
  act(() => root!.render(<DataGrid label="A6 rows" columns={columns} nodes={nodes}
    template="1fr" revealId={revealId} revealKey={key} />));
}

function mount(documentPort: "html" | "body" | "body-with-html-scroller", nested = false) {
  const activePort = documentPort === "html" ? document.documentElement : document.body;
  property(document, "scrollingElement", { get: () => documentPort === "body" ? document.body : document.documentElement });
  for (const element of [document.body, document.documentElement]) {
    element.style.overflowY = element === activePort ? "auto" : "visible";
    property(element, "clientHeight", { get: () => VIEW });
    property(element, "scrollHeight", { get: () => 100_000 });
    property(element, "scrollTop", { get: () => scrollY, set: (value: number) => {
      pageWrites.push(element.tagName); scrollY = Math.max(0, value);
    } });
  }
  container = document.createElement("div");
  document.body.appendChild(container);
  let railTop = 0;
  if (nested) {
    container.style.overflowY = "auto";
    property(container, "clientHeight", { get: () => 240 });
    property(container, "scrollHeight", { get: () => 4000 });
    property(container, "scrollTop", { get: () => railTop, set: (value: number) => { railTop = Math.max(0, value); } });
  }
  root = createRoot(container);
  render(null, "none");
  const grid = container.querySelector<HTMLElement>(".ag__grid")!;
  property(grid, "scrollTop", { get: () => 0, set: () => undefined });
  HTMLElement.prototype.getBoundingClientRect = function (): DOMRect {
    const top = 600 - scrollY - railTop;
    if (this === document.body || this === document.documentElement) return rect(0, VIEW);
    if (this === container && nested) return rect(600 - scrollY, 840 - scrollY);
    if (this === grid) return rect(top, top + 40 + ROWS.length * ROW_HEIGHT);
    if (this.classList.contains("ag__head")) return rect(top, top + 40);
    const row = this.closest<HTMLElement>(".ag__row--data");
    if (row !== null && grid.contains(row)) {
      const index = [...grid.querySelectorAll<HTMLElement>(".ag__row--data")].indexOf(row);
      return rect(top + 40 + index * ROW_HEIGHT, top + 40 + (index + 1) * ROW_HEIGHT);
    }
    return originalRect.call(this);
  };
  pageWrites = [];
  return { grid, railTop: () => railTop };
}

beforeEach(() => {
  scrollY = 0; pageWrites = []; frames = new Map(); frameId = 0;
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { const id = ++frameId; frames.set(id, cb); return id; });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  property(window, "innerHeight", { value: VIEW });
  property(window, "scrollY", { get: () => scrollY });
  property(window, "scrollBy", { value: (x: number | ScrollToOptions, y?: number) => {
    pageWrites.push("window"); scrollY = Math.max(0, scrollY + (typeof x === "number" ? y ?? 0 : x.top ?? 0));
  } });
});
afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null; container?.remove(); container = null;
  HTMLElement.prototype.getBoundingClientRect = originalRect;
  for (const undo of restore.splice(0).reverse()) undo();
  document.body.style.cssText = bodyStyle;
  document.documentElement.style.cssText = htmlStyle;
  vi.unstubAllGlobals();
});

describe("A6 selection and hold leave every document scrollport alone", () => {
  it.each(["html", "body", "body-with-html-scroller"] as const)("selection and recommit hold do not move %s", (port) => {
    mount(port);
    (document.activeElement as HTMLElement | null)?.blur();
    render(ROWS[60]!.id, "canvas-selection");
    expect(pageWrites).toEqual([]);
    expect(scrollY).toBe(0);
    render(ROWS[60]!.id, "canvas-selection", ROWS.length - 1);
    expect(pageWrites).toEqual([]);
    expect(scrollY).toBe(0);
  });
  it("still reveals a selection through a nested rail without moving the document", () => {
    const h = mount("html", true);
    render(ROWS[60]!.id, "canvas-selection");
    expect(h.railTop()).toBeGreaterThan(0);
    expect(pageWrites).toEqual([]);
    expect(scrollY).toBe(0);
  });
  it.each(["html", "body", "body-with-html-scroller"] as const)("keyboard focus retains positive document reveal through %s", (port) => {
    const { grid } = mount(port);
    const rows = grid.querySelectorAll<HTMLElement>(".ag__row--data");
    const cell = rows[60]!.querySelector<HTMLElement>('[role="rowheader"]')!;
    act(() => cell.focus());
    act(() => cell.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true })));
    expect(pageWrites.length).toBeGreaterThan(0);
    expect(scrollY).toBeGreaterThan(0);
  });
});
