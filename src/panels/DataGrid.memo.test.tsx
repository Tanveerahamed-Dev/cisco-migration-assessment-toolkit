/**
 * DataGrid.memo.test.tsx — a selection change re-renders the rows it changed, not the table.
 *
 * Acceptance E2/E3, journey 1. Selecting a finding used to re-run every column renderer of every
 * row inside the click (1619 ms of 1656 ms DataGrid time over 12 clicks, CPU-profiled), which is
 * what put a long `DIV#root.onclick` task on the interaction path. The rows are now memoised; this
 * pins that by COUNTING renderer calls, so a future inline closure that silently defeats the memo
 * (a fresh `columns` array, a fresh handler per render) turns this red instead of turning J1 slow.
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
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
});

interface Row {
  id: string;
  title: string;
}

describe("DataGrid row memoisation", () => {
  it("re-renders only the rows whose selection state changed", () => {
    let calls = 0;
    const columns: GridColumn<Row>[] = [
      { id: "id", header: "ID", width: "4rem", rowHeader: true, render: (r) => r.id },
      {
        id: "title",
        header: "Title",
        width: "1fr",
        render: (r) => {
          calls += 1;
          return r.title;
        },
      },
    ];
    const items: Row[] = Array.from({ length: 60 }, (_, i) => ({ id: `R${i}`, title: `row ${i}` }));
    const nodes = (): GridNode<Row>[] => items.map((item) => ({ kind: "row", id: item.id, item }));
    const ui = (activeId: string | null, fresh: GridNode<Row>[]): ReactNode => (
      <DataGrid<Row>
        label="rows"
        columns={columns}
        nodes={fresh}
        template="4rem 1fr"
        activeId={activeId}
        onActivate={() => {}}
      />
    );

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mounted.push({ root, container });
    act(() => root.render(ui(null, nodes())));
    expect(calls).toBe(60);

    // Select one row from outside the grid: that row changes, and so does the row that held the
    // grid's single tab stop, because the roving cell follows an external selection (D3 — otherwise
    // focus restored after a palette pick sits on a row thousands of px out of view). Nothing else
    // changes, and the selected row renders ONCE, not once for the selection and again for the tab
    // stop. A caller that rebuilds its node wrappers on every render (fresh objects around the
    // same items) must not defeat the memo.
    calls = 0;
    act(() => root.render(ui("R10", nodes())));
    expect(calls).toBe(2);
    expect(container.querySelectorAll('[tabindex="0"]').length).toBe(1);
    expect(container.querySelector('[tabindex="0"]')?.closest('[role="row"]')?.textContent).toContain("row 10");

    // Move the selection: the row it left and the row it entered.
    calls = 0;
    act(() => root.render(ui("R40", nodes())));
    expect(calls).toBe(2);
    expect(container.querySelectorAll('[aria-current="true"]').length).toBe(1);
    expect(container.querySelector('[aria-current="true"]')?.textContent).toContain("row 40");
  });
});
