/**
 * DataGrid.focus-return.test.tsx — acceptance D3: leaving the grid with Escape never drops focus to
 * <body>.
 *
 * `leaveGrid` used to focus `exitFocusRef` when one was given and otherwise call `active.blur()` on
 * the focused cell, which parks focus on <body>. A given exit target was focused without an
 * `isConnected` check, a silent no-op when it had unmounted. Both now go through
 * `src/app/focus-return.ts`, which falls back to the surface's region landmark.
 *
 * Scope, stated rather than implied: the one production host, `PriorityQueue`, currently answers
 * every Escape itself (its `onEscape` returns true), so these paths are the grid's contract for any
 * host that lets Escape through — the shape PriorityQueue had before, with `exitFocusRef` on its
 * filter input — not a path the running queue reaches today. The real-browser grid cases are in
 * review/audit-d3-focus.mjs.
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

const mounted: { root: Root; container: HTMLElement }[] = [];

function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
});

const key = (target: EventTarget, k: string): void => {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
  });
};

interface Row {
  id: string;
  name: string;
}
const rows: Row[] = [
  { id: "r1", name: "alpha" },
  { id: "r2", name: "bravo" },
];
const columns: GridColumn<Row>[] = [
  { id: "id", header: "ID", width: "4rem", rowHeader: true, render: (r) => r.id },
  { id: "name", header: "Name", width: "minmax(0,1fr)", render: (r) => r.name },
];
const nodes: GridNode<Row>[] = rows.map((r) => ({ kind: "row" as const, id: r.id, item: r }));

const firstBodyCell = (c: HTMLElement): HTMLElement =>
  c.querySelector<HTMLElement>('[role="row"][aria-rowindex="2"] [aria-colindex="1"]')!;

describe("D3: Escape out of the grid never lands on <body>", () => {
  it("with no exit target, focus goes to the surface's region landmark (the PriorityQueue shape)", () => {
    const c = mount(
      <section aria-label="Priority queue">
        <DataGrid<Row> label="Rows" columns={columns} nodes={nodes} template="4rem 1fr" />
      </section>,
    );
    const grid = c.querySelector<HTMLElement>('[role="grid"]')!;
    const cell = firstBodyCell(c);
    act(() => cell.focus());
    key(document.activeElement!, "Escape");
    expect(document.activeElement).not.toBe(document.body);
    expect(grid.contains(document.activeElement)).toBe(false);
    expect(document.activeElement).toBe(c.querySelector("section"));
    /* The landmark is programmatically focusable only: it never joins the Tab order (D2's
       one-tabindex=0 invariant counts only tabindex=0). */
    expect(document.activeElement?.getAttribute("tabindex")).toBe("-1");
  });

  it("an exit target that has unmounted falls back instead of dropping focus", () => {
    const gone = document.createElement("button"); // never connected
    const c = mount(
      <section aria-label="Priority queue">
        <DataGrid<Row> label="Rows" columns={columns} nodes={nodes} template="4rem 1fr" exitFocusRef={{ current: gone }} />
      </section>,
    );
    act(() => firstBodyCell(c).focus());
    key(document.activeElement!, "Escape");
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(c.querySelector("section"));
  });

  it("with no landmark anywhere, focus stays on the cell rather than falling to <body>", () => {
    const c = mount(<DataGrid<Row> label="Rows" columns={columns} nodes={nodes} template="4rem 1fr" />);
    const cell = firstBodyCell(c);
    act(() => cell.focus());
    key(document.activeElement!, "Escape");
    expect(document.activeElement).not.toBe(document.body);
  });
});
