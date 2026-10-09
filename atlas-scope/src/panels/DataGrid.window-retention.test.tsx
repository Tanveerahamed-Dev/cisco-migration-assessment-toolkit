/**
 * D2's bounded retained occurrence in the actual DataGrid component. These are synthetic DOM
 * controls with an explicit 320px window, not wheel/pixel/physical-layout evidence. The separate
 * hosted browser witness owns actual grouped-row heights, clipping and scroll geometry.
 * No component/module is mocked and no existing keyboard or windowing criterion is relaxed.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { DataGrid, type GridColumn, type GridNode } from "./DataGrid";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

type Item = { id: string };
const items = Array.from({ length: 400 }, (_, index) => ({ id: `item-${index}` }));
const nodes = (): GridNode<Item>[] => items.map((item) => ({ kind: "row", id: item.id, item }));
const columns: GridColumn<Item>[] = [
  { id: "id", header: "ID", rowHeader: true, width: "8rem", render: (item) => item.id },
  { id: "open", header: "Open", width: "8rem", soleControl: true, interactive: true,
    render: (item, cell) => <button type="button" tabIndex={cell.tabIndex}>{`Open ${item.id}`}</button> },
];
const mounted: { root: Root; host: HTMLElement }[] = [];
afterEach(() => { for (const { root, host } of mounted.splice(0)) { act(() => root.unmount()); host.remove(); } });

function view(rows: readonly GridNode<Item>[]): ReactNode {
  return <><button type="button" data-outside>Outside</button><DataGrid label="Retention fixture" columns={columns} nodes={rows}
    template="8rem 8rem" window={{ rowHeightPx: 32, threshold: 200, viewportPx: 320 }} /></>;
}
function mount(rows = nodes()) {
  const host = document.createElement("div"); document.body.appendChild(host);
  const root = createRoot(host); mounted.push({ root, host });
  act(() => root.render(view(rows)));
  return { host, grid: host.querySelector<HTMLElement>('[role="grid"]')!, body: host.querySelector<HTMLElement>(".ag__body")!,
    outside: host.querySelector<HTMLButtonElement>("[data-outside]")!, render: (next: GridNode<Item>[]) => act(() => root.render(view(next))) };
}
function cell(host: HTMLElement, row: number, col = 1): HTMLElement {
  const value = host.querySelector<HTMLElement>(`[aria-rowindex="${row}"] [aria-colindex="${col}"]`);
  expect(value, `real cell ${row}:${col}`).not.toBeNull(); return value!;
}
const focus = (node: HTMLElement) => act(() => node.focus());
const scroll = (grid: HTMLElement, value: number) => act(() => { grid.scrollTop = value; grid.dispatchEvent(new Event("scroll")); });
const stops = (grid: HTMLElement) => [...grid.querySelectorAll<HTMLElement>('[tabindex],button')].filter((node) => node.tabIndex === 0);
const padding = (body: HTMLElement) => [...body.children].filter((node) => node.getAttribute("role") === "presentation").map((node) => (node as HTMLElement).style.height);
function expectWindow(body: HTMLElement, retainedRow: HTMLElement): void {
  expect(body.style.position).toBe("relative");
  expect(retainedRow.style.position).toBe("absolute");
  expect(padding(body)).toEqual(["2944px", "9024px"]); // ordinary [92,118) window; no subtraction for the retained row
  const normal = [...body.querySelectorAll<HTMLElement>('[role="row"]')].filter((row) => row.style.position !== "absolute");
  expect(normal.map((row) => Number(row.getAttribute("aria-rowindex")))).toEqual(Array.from({ length: 26 }, (_, i) => i + 94));
  expect(body.querySelectorAll('[role="row"]')).toHaveLength(27); // normal window plus exactly one occurrence
}

describe("bounded window retention without wheel reaim", () => {
  it("retention witness: wheel-window updates keep the original roving cell", () => {
    const { host, grid, body } = mount();
    const original = cell(host, 2); focus(original);
    const originalRow = original.closest<HTMLElement>('[role="row"]')!;
    scroll(grid, 3200);
    expect(original.isConnected, "d2 retention").toBe(true);
    expect(cell(host, 2)).toBe(original);
    expect(document.activeElement).toBe(original);
    expect(stops(grid)).toEqual([original]);
    expect(grid.scrollTop).toBe(3200);
    expect(originalRow.style.top).toBe("0px");
    expect(originalRow.style.bottom).toBe("");
    expectWindow(body, originalRow);
    act(() => document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true })));
    expect(document.activeElement).toBe(cell(host, 3));
    expect(stops(grid)).toEqual([cell(host, 3)]);
  });

  it("retains a 30px group occurrence outside the normal window without changing its padding", () => {
    const grouped = nodes(); grouped[0] = { kind: "group", id: "first", label: "First", count: 1, observed: true, collapsed: false };
    const { host, grid, body } = mount(grouped);
    const original = cell(host, 2); focus(original);
    const row = original.closest<HTMLElement>('[role="row"]')!;
    row.style.height = "30px"; // declared synthetic extent; jsdom does not measure the real browser's 30px row
    scroll(grid, 3200);
    expect(original.isConnected).toBe(true);
    expect(cell(host, 2)).toBe(original);
    expect(document.activeElement).toBe(original);
    expect(stops(grid)).toEqual([original]);
    expect(row.style.height).toBe("30px");
    expectWindow(body, row);
    expect(grid.scrollTop).toBe(3200);
  });

  it.each(["data", "group"] as const)("bottom-anchors an off-window %s occurrence without a trailing extent", (kind) => {
    const rows = nodes();
    if (kind === "group") rows[399] = { kind: "group", id: "last", label: "Last", count: 0, observed: true, collapsed: false };
    const { host, grid, body } = mount(rows);
    scroll(grid, 12480);
    const original = cell(host, 401); focus(original);
    const row = original.closest<HTMLElement>('[role="row"]')!;
    row.style.height = kind === "group" ? "30px" : "32px";
    scroll(grid, 0);
    expect(original.isConnected).toBe(true);
    expect(cell(host, 401)).toBe(original);
    expect(document.activeElement).toBe(original);
    expect(stops(grid)).toEqual([original]);
    expect(row.style.position).toBe("absolute");
    expect(row.style.bottom).toBe("0px");
    expect(row.style.top).toBe("");
    expect(row.style.height).toBe(kind === "group" ? "30px" : "32px");
    expect(padding(body)).toEqual(["12224px"]);
    expect(body.querySelectorAll('[role="row"]')).toHaveLength(19);
    expect(grid.scrollTop).toBe(0);
    scroll(grid, 12480);
    expect(cell(host, 401)).toBe(original);
    expect(row.style.position).toBe("");
    expect(body.querySelectorAll('[aria-rowindex="401"]')).toHaveLength(1);
  });

  it.each(["never-entered", "left-body"] as const)("retains the sole entry while %s focus stays outside", (mode) => {
    const { host, grid, outside } = mount();
    const original = cell(host, 2);
    if (mode === "left-body") focus(original);
    focus(outside); scroll(grid, 3200);
    expect(original.isConnected).toBe(true);
    expect(stops(grid)).toEqual([original]);
    expect(document.activeElement).toBe(outside);
    expect(grid.scrollTop).toBe(3200);
  });

  it("keeps a sole-control button as the same connected roving control", () => {
    const { host, grid } = mount();
    const original = cell(host, 2, 2).querySelector<HTMLButtonElement>("button")!; focus(original);
    scroll(grid, 3200);
    expect(original.isConnected).toBe(true);
    expect(cell(host, 2, 2).querySelector("button")).toBe(original);
    expect(document.activeElement).toBe(original);
    expect(stops(grid)).toEqual([original]);
    expect(grid.scrollTop).toBe(3200);
  });

  it("retains the exact keyed occurrence when finding IDs repeat under different groups", () => {
    const rows = nodes(), item = { id: "same-finding" };
    rows[0] = { kind: "row", id: item.id, key: "first-copy", item };
    rows[200] = { kind: "row", id: item.id, key: "second-copy", item };
    const { host, grid } = mount(rows);
    const first = cell(host, 2); focus(first); scroll(grid, 6080);
    const second = cell(host, 202);
    expect(first.isConnected).toBe(true);
    expect(first).not.toBe(second);
    expect(first.textContent).toBe(second.textContent);
    expect(stops(grid)).toEqual([first]);
    focus(second); scroll(grid, 0);
    expect(second.isConnected).toBe(true);
    expect(cell(host, 202)).toBe(second);
    expect(document.activeElement).toBe(second);
    expect(stops(grid)).toEqual([second]);
  });

  it("uses only current nodes after a rowset change and never pins the header as a body row", () => {
    const { host, grid, body, outside, render } = mount();
    const original = cell(host, 2); focus(outside); scroll(grid, 3200);
    expect(original.isConnected).toBe(true);
    const replacement = Array.from({ length: 10 }, (_, index) => ({ id: `replacement-${index}` }));
    render(replacement.map((item) => ({ kind: "row", id: item.id, item })));
    expect(original.isConnected).toBe(false);
    expect(grid.getAttribute("aria-rowcount")).toBe("11");
    expect(body.querySelectorAll('[role="row"]')).toHaveLength(10);
    expect([...body.querySelectorAll<HTMLElement>('[role="row"]')].every((row) => row.style.position === "")).toBe(true);
    expect(stops(grid)).toHaveLength(1);
    expect(document.activeElement).toBe(outside);
    focus(cell(host, 1));
    render(nodes()); scroll(grid, 3200);
    expect(stops(grid)).toEqual([cell(host, 1)]);
    expect([...body.querySelectorAll<HTMLElement>('[role="row"]')].every((row) => row.style.position === "")).toBe(true);
    expect(body.querySelectorAll('[role="row"]')).toHaveLength(26);
  });
});
