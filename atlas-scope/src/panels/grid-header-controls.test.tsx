/**
 * grid-header-controls.test.tsx — a header cell that paints nothing offers nothing.
 *
 * THE DEFECT THIS PINS, as measured in the running application:
 *
 *   In the queue's comfortable (stacked) layout the metadata columns are demoted: their header
 *   cells are parked on header row 1 and clipped by the stylesheet to 1x1 px, because their values
 *   are rendered as inline chips in the row instead. The grid kept rendering a sort BUTTON inside
 *   that clipped cell anyway. Measured: `button.ag__sortbtn` for "Category" was 1x24 CSS px at
 *   (0, -11) — off the top of the viewport — inside a 1x1 `role=columnheader` with
 *   `overflow: hidden`. A screen-reader user was told a sortable column was there
 *   (`aria-sort="none"`) and could sort it with Enter; a pointer user had no control at all.
 *
 *   The fact was also stated twice: once in PriorityQueue's layout map, and once as a CSS selector
 *   listing by name the four columns that are NOT demoted. That is the shape that let the two
 *   disagree. There is now one flag, `GridColumn.headerHidden`, and the stylesheet reads the
 *   attribute the grid writes from it.
 *
 * What is deliberately KEPT: `aria-sort` when the column IS the one the grid is ordered by. That
 * is a statement about the data, not an offer of a control, and the ordering control that produced
 * it is reachable by pointer and keyboard alike.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataGrid, type GridColumn, type GridNode, type GridSort } from "./DataGrid";

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

interface Row {
  id: string;
  name: string;
  category: string;
}

const rows: Row[] = [
  { id: "r1", name: "alpha", category: "L2" },
  { id: "r2", name: "bravo", category: "L3" },
];

const columns: GridColumn<Row>[] = [
  { id: "id", header: "ID", width: "4rem", rowHeader: true, sortable: true, render: (r) => r.id },
  { id: "name", header: "Name", width: "minmax(0,1fr)", sortable: true, render: (r) => r.name },
  /* Sortable DATA, demoted HEADER: the exact shape of the queue's "Category" column. */
  {
    id: "category",
    header: "Category",
    width: "6rem",
    sortable: true,
    headerHidden: true,
    render: (r) => r.category,
  },
];

const nodes: GridNode<Row>[] = rows.map((r) => ({ kind: "row" as const, id: r.id, item: r }));

const grid = (onSort: (id: string) => void, sort: GridSort | null = null): HTMLElement =>
  mount(
    <DataGrid<Row>
      label="rows"
      columns={columns}
      nodes={nodes}
      template="4rem minmax(0,1fr) 6rem"
      sort={sort}
      onSort={onSort}
    />,
  );

const head = (c: HTMLElement, col: string): HTMLElement =>
  c.querySelector<HTMLElement>(`.ag__cell--head[data-col="${col}"]`)!;

describe("a clipped header cell offers no sort control on any channel", () => {
  it("renders no sort button inside it, while the visible headers keep theirs", () => {
    const c = grid(vi.fn());
    expect(head(c, "id").querySelector("button.ag__sortbtn")).not.toBeNull();
    expect(head(c, "name").querySelector("button.ag__sortbtn")).not.toBeNull();
    expect(
      head(c, "category").querySelector("button.ag__sortbtn"),
      "a button inside a 1x1 clipped cell measures 1px wide and sits off-screen — it is a control " +
        "no pointer user can reach",
    ).toBeNull();
  });

  it("keeps the column's accessible name — demoted is not deleted", () => {
    const c = grid(vi.fn());
    expect(head(c, "category").textContent).toContain("Category");
    expect(head(c, "category").getAttribute("role")).toBe("columnheader");
  });

  it("does not announce aria-sort=none, which advertises a control that is not there", () => {
    const c = grid(vi.fn());
    expect(head(c, "id").getAttribute("aria-sort")).toBe("none");
    expect(head(c, "category").getAttribute("aria-sort")).toBeNull();
  });

  it("DOES state aria-sort when the grid is actually ordered by that column", () => {
    /* The ordering control (a Select naming every sortable field in words) is the control for a
       demoted column, for every reader. What it produces is still a fact about the data, and the
       column header is where ARIA carries it. */
    const c = grid(vi.fn(), { columnId: "category", direction: "asc" });
    expect(head(c, "category").getAttribute("aria-sort")).toBe("ascending");
  });

  it("does not sort on Enter either — the keyboard gets no back door the pointer lacks", () => {
    const onSort = vi.fn();
    const c = grid(onSort);

    const visible = head(c, "id");
    act(() => visible.focus());
    act(() => {
      visible.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    });
    expect(onSort, "the control that IS on screen must still work").toHaveBeenCalledWith("id");

    onSort.mockClear();
    const clipped = head(c, "category");
    act(() => clipped.focus());
    act(() => {
      clipped.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    });
    expect(
      onSort,
      "Enter on a clipped header sorted a column no pointer user could sort",
    ).not.toHaveBeenCalledWith("category");
  });
});

/* D2, 2026-09-21. A clipped header cell measured [0,0,1,1] with position:fixed and
   clip-path:inset(50%), yet ArrowRight x3 along the header row focused it, and because the grid
   roves its tabindex it then became the grid's remembered Tab stop — Shift+Tab, Tab landed on an
   invisible cell. jsdom has no layout, so this pins the STRUCTURAL property the rect follows from:
   no key the grid handles, from any standable cell, ever leaves the roving stop on a cell the grid
   itself marked clipped. (The rect half is checked in the browser, see review notes.) */
describe("a clipped header cell is never a stop in the arrow-key model", () => {
  const KEYS: { key: string; ctrlKey?: boolean }[] = [
    { key: "ArrowRight" },
    { key: "ArrowLeft" },
    { key: "ArrowUp" },
    { key: "ArrowDown" },
    { key: "Home" },
    { key: "End" },
    { key: "Home", ctrlKey: true },
    { key: "End", ctrlKey: true },
    { key: "PageUp" },
    { key: "PageDown" },
  ];

  const roving = (c: HTMLElement): HTMLElement[] => [...c.querySelectorAll<HTMLElement>('[role="grid"] [tabindex="0"]')];
  const press = (k: { key: string; ctrlKey?: boolean }): void => {
    const el = document.activeElement as HTMLElement;
    act(() => {
      el.dispatchEvent(new KeyboardEvent("keydown", { ...k, bubbles: true, cancelable: true }));
    });
  };

  it("ArrowRight along the header row steps OVER the clipped cell, and ArrowLeft back over it", () => {
    /* Put the clipped column in the middle, the shape of the queue's header row. */
    const cols: GridColumn<Row>[] = [columns[0]!, columns[2]!, columns[1]!];
    const c = mount(<DataGrid<Row> label="rows" columns={cols} nodes={nodes} template="4rem 6rem 1fr" onSort={vi.fn()} />);
    act(() => head(c, "id").focus());
    press({ key: "ArrowRight" });
    expect((document.activeElement as HTMLElement).dataset.col).toBe("name");
    press({ key: "ArrowLeft" });
    expect((document.activeElement as HTMLElement).dataset.col).toBe("id");
  });

  it("every key, from every standable cell, leaves focus and the Tab stop on a visible cell", () => {
    const c = grid(vi.fn());
    const starts = [...c.querySelectorAll<HTMLElement>('[role="columnheader"],[role="gridcell"],[role="rowheader"]')].filter(
      (el) => el.dataset.headhidden !== "yes",
    );
    for (const start of starts) {
      for (const k of KEYS) {
        act(() => start.focus());
        press(k);
        const active = document.activeElement as HTMLElement;
        const label = `${k.ctrlKey ? "Ctrl+" : ""}${k.key} from ${start.getAttribute("role")} ${start.dataset.col ?? start.textContent}`;
        expect(active.dataset.headhidden, `${label} focused the clipped header cell`).not.toBe("yes");
        for (const stop of roving(c)) {
          expect(stop.dataset.headhidden, `${label} made the clipped cell the grid's Tab stop`).not.toBe("yes");
        }
      }
    }
  });

  it("focus arriving on the clipped cell from outside is redirected, not adopted as the Tab stop", () => {
    const c = grid(vi.fn());
    act(() => head(c, "category").focus());
    expect((document.activeElement as HTMLElement).dataset.headhidden).not.toBe("yes");
    for (const stop of roving(c)) expect(stop.dataset.headhidden).not.toBe("yes");
  });
});

describe("the demotion is stated once", () => {
  /* Comments out first: this file's own comments quote the selector that was replaced, and a scan
     that cannot tell prose from code would read the explanation as the offence. */
  const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "PriorityQueue.css"), "utf8").replace(
    /\/\*[\s\S]*?\*\//g,
    " ",
  );

  it("clips the header cells the grid marks, not a hand-listed set of column names", () => {
    const rules = css.split("}").filter((r) => r.includes("clip-path") && r.includes(".ag__cell--head"));
    expect(rules.length, "the clipping rule for demoted headers has gone missing").toBe(1);
    const selector = rules[0]!.split("{")[0]!;
    expect(
      selector,
      `this rule decides which header cells are invisible, and the component decides which ones\n` +
        `carry a control. Both must read the same flag, or they drift: ${selector.trim()}`,
    ).toContain("[data-headhidden");
    expect(selector).not.toContain(':not([data-col=');
  });
});
