/**
 * PriorityQueue.folded-columns.test.tsx — in the comfortable density every GRID column has a real,
 * visible header; the columns a reader adds through Display are folded into the title cell.
 *
 * A11Y critic, 2026-09-21 (D2 + D5): the line-2 metadata columns used to stay in the grid's column
 * model under a header clipped to 1x1 px. ArrowRight along the header skipped that column, ArrowUp
 * from one of its cells landed on a different column, its resize separator was exposed at 8x1 px,
 * and aria-colcount counted a column no sighted reader could find. The structural fix removes the
 * column from the model; this pins that no demoted header can come back, for any Display choice.
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

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(ui: ReactNode): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return container;
}

beforeEach(() => {
  localStorage.clear();
  act(() => useInvestigation.getState().reset());
});
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
  localStorage.clear();
});

/* Every Display choice from "nothing extra" to "everything on": none may produce a clipped header. */
const HIDDEN_SETS = ["wave,priority,rank,devices,hosts", "wave,priority,rank,hosts", "rank,hosts", ""];

describe("comfortable density column model", () => {
  for (const hidden of HIDDEN_SETS) {
    it(`hidden=[${hidden}]: no header is demoted, and aria-colcount counts only real headers`, () => {
      localStorage.setItem("atlas-scope.queue.hiddenColumns", hidden);
      const c = mount(<PriorityQueue debounceMs={0} />);
      const grid = c.querySelector<HTMLElement>('[role="grid"]')!;
      const heads = [...grid.querySelectorAll<HTMLElement>('[role="columnheader"]')];
      expect(heads.filter((h) => h.dataset.headhidden === "yes").map((h) => h.dataset.col)).toEqual([]);
      expect(Number(grid.getAttribute("aria-colcount"))).toBe(heads.length);

      /* Every separator belongs to a header that is really there. */
      for (const sep of grid.querySelectorAll('[role="separator"]')) {
        expect(sep.closest('[role="columnheader"]')?.getAttribute("data-headhidden")).not.toBe("yes");
      }

      /* A data row has exactly one cell per header, so Up/Down can keep the column. */
      const row = [...grid.querySelectorAll('[role="row"]')].find((r) => r.querySelector('[role="rowheader"]'))!;
      expect(row.querySelectorAll('[role="gridcell"],[role="rowheader"]').length).toBe(heads.length);
    });
  }

  it("a folded column still shows its values, named, inside the title cell", () => {
    localStorage.setItem("atlas-scope.queue.hiddenColumns", "rank,hosts");
    const c = mount(<PriorityQueue debounceMs={0} />);
    const titleCell = c.querySelector('[role="grid"] [role="gridcell"][data-col="title"]')!;
    const keys = [...titleCell.querySelectorAll(".pq-fold__key")].map((k) => k.textContent);
    expect(keys).toEqual(expect.arrayContaining(["Devices", "Wave", "Priority"]));
  });
});
