/**
 * DataGrid.resizer-hidden.test.tsx — a clipped (`headerHidden`) header renders no resize separator.
 *
 * A11Y critic, 2026-09-21 (D5): "Resize Category" was exposed as role=separator at 8x1 px inside a
 * 1x1 clipped header — reachable by neither pointer nor key. Same rule as the sort control: a cell
 * that paints nothing offers nothing.
 */
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataGrid, type GridColumn, type GridNode } from "./DataGrid";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  document.body.innerHTML = "";
});

interface Row {
  id: string;
  cat: string;
}

describe("resizer on a clipped header", () => {
  it("is rendered for a visible resizable header and not for a clipped one", () => {
    const cols: GridColumn<Row>[] = [
      { id: "id", header: "ID", width: "4rem", rowHeader: true, render: (r) => r.id },
      { id: "cat", header: "Category", width: "6rem", resizable: true, render: (r) => r.cat },
      { id: "cat2", header: "Hidden", width: "6rem", resizable: true, headerHidden: true, render: (r) => r.cat },
    ];
    const nodes: GridNode<Row>[] = [{ kind: "row", id: "r1", item: { id: "r1", cat: "L2" } }];
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() =>
      root.render(
        <DataGrid<Row> label="rows" columns={cols} nodes={nodes} template="4rem 6rem 6rem" onResizeColumn={vi.fn()} />,
      ),
    );
    const labels = [...host.querySelectorAll('[role="separator"]')].map((s) => s.getAttribute("aria-label"));
    expect(labels).toEqual(["Resize Category"]);
    act(() => root.unmount());
  });
});
