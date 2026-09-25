/**
 * DataGrid.test.tsx — the APG data-grid keyboard contract, asserted key by key.
 *
 * This is acceptance criterion D2 and it will be independently re-tested by someone who did not
 * write the grid, so every key in design-brief §7.2 gets its own assertion, including the ones
 * whose correct behaviour is "focus does not move". A clamp that was never exercised is not a
 * clamp — it is an assumption, and the wrapping bug it hides is invisible to a visual review.
 *
 * No testing-library: React's own `act` over a real `createRoot` in jsdom, matching the
 * convention already established in src/ui/primitives.test.tsx.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fabric } from "../core/data";
import type { Finding } from "../core/types";
import { DataGrid, type GridColumn, type GridNode } from "./DataGrid";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted: { root: Root; container: HTMLElement }[] = [];

function mount(ui: ReactNode): { container: HTMLElement; render: (next: ReactNode) => void } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  mounted.push({ root, container });
  return { container, render: (next) => act(() => root.render(next)) };
}

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
});

const key = (target: EventTarget, k: string, init: KeyboardEventInit = {}): void => {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init }));
  });
};

const focus = (el: HTMLElement): void => {
  act(() => el.focus());
};

/* ── a small synthetic model, and a real one ─────────────────────────────────
   The synthetic rows exist to drive edge cases (a null cell, a 1,000-row window) that the real
   snapshot does not happen to contain. Every structural assertion is ALSO run against the real
   compiled findings, so the contract is not proven only against data shaped to satisfy it. */

interface Row {
  id: string;
  name: string;
  /** null means NOT OBSERVED; the grid must never render it as an empty cell. */
  score: number | null;
}

const rows: Row[] = [
  { id: "r1", name: "alpha", score: 3 },
  { id: "r2", name: "bravo", score: null },
  { id: "r3", name: "charlie", score: 1 },
  { id: "r4", name: "delta", score: 9 },
  { id: "r5", name: "echo", score: 4 },
  { id: "r6", name: "foxtrot", score: 2 },
  { id: "r7", name: "golf", score: 7 },
  { id: "r8", name: "hotel", score: 5 },
];

/** Enough rows that a measured page step has somewhere to land without clamping at the end. */
const manyRows: Row[] = Array.from({ length: 40 }, (_, i) => ({
  id: `m${i + 1}`,
  name: `row ${i + 1}`,
  score: i % 5 === 0 ? null : i,
}));

const columns: GridColumn<Row>[] = [
  { id: "id", header: "ID", width: "4rem", rowHeader: true, sortable: true, render: (r) => r.id },
  { id: "name", header: "Name", width: "minmax(0,1fr)", sortable: true, render: (r) => r.name },
  // Not sortable on purpose: aria-sort must be ABSENT here, not "none".
  { id: "score", header: "Score", width: "4rem", unobservedWhat: "score", render: (r) => r.score },
];

const dataNodes = (rs: readonly Row[] = rows): GridNode<Row>[] =>
  rs.map((r) => ({ kind: "row" as const, id: r.id, item: r }));

const TEMPLATE = "4rem minmax(0,1fr) 4rem";

const cellsOf = (c: HTMLElement): HTMLElement[] =>
  [...c.querySelectorAll<HTMLElement>('[role="gridcell"],[role="rowheader"],[role="columnheader"]')];

const focusedCell = (c: HTMLElement): HTMLElement | null =>
  c.querySelector<HTMLElement>('[role="gridcell"][tabindex="0"],[role="rowheader"][tabindex="0"],[role="columnheader"][tabindex="0"]');

const at = (c: HTMLElement, rowIndex: number, colIndex: number): HTMLElement => {
  const row = c.querySelector<HTMLElement>(`[role="row"][aria-rowindex="${rowIndex}"]`);
  const cell = row?.querySelector<HTMLElement>(`[aria-colindex="${colIndex}"]`);
  if (!cell) throw new Error(`no cell at row ${rowIndex} col ${colIndex}`);
  return cell;
};

/** Where the roving tabindex currently sits, as (aria-rowindex, aria-colindex). */
const position = (c: HTMLElement): [number, number] => {
  const cell = focusedCell(c);
  if (!cell) throw new Error("no cell carries tabindex=0");
  const row = cell.closest('[role="row"]');
  return [Number(row?.getAttribute("aria-rowindex")), Number(cell.getAttribute("aria-colindex"))];
};

/* ══ structure and ARIA ════════════════════════════════════════════════════ */

describe("grid structure", () => {
  it("is a grid of rowgroups, rows, columnheaders, rowheaders and gridcells", () => {
    const { container } = mount(<DataGrid<Row> label="Rows" columns={columns} nodes={dataNodes()} template={TEMPLATE} />);
    const grid = container.querySelector('[role="grid"]');
    expect(grid).not.toBeNull();
    expect(grid?.getAttribute("aria-label")).toBe("Rows");
    expect(container.querySelectorAll('[role="rowgroup"]').length).toBe(2);
    expect(container.querySelectorAll('[role="columnheader"]').length).toBe(columns.length);
    expect(container.querySelectorAll('[role="rowheader"]').length).toBe(rows.length);
    expect(container.querySelectorAll('[role="gridcell"]').length).toBe(rows.length * (columns.length - 1));
  });

  it("carries LOGICAL aria-rowcount / aria-colcount and 1-based indices", () => {
    const { container } = mount(<DataGrid<Row> label="Rows" columns={columns} nodes={dataNodes()} template={TEMPLATE} />);
    const grid = container.querySelector('[role="grid"]');
    // header row + every data row
    expect(grid?.getAttribute("aria-rowcount")).toBe(String(rows.length + 1));
    expect(grid?.getAttribute("aria-colcount")).toBe(String(columns.length));
    expect(container.querySelector('[role="row"]')?.getAttribute("aria-rowindex")).toBe("1");
    expect(at(container, 2, 1).textContent).toContain("r1");
    expect(at(container, 9, 1).textContent).toContain("r8");
  });

  it("is ONE tab stop: exactly one cell carries tabindex=0 and the container is not focusable", () => {
    const { container } = mount(<DataGrid<Row> label="Rows" columns={columns} nodes={dataNodes()} template={TEMPLATE} />);
    const zero = cellsOf(container).filter((c) => c.getAttribute("tabindex") === "0");
    expect(zero).toHaveLength(1);
    expect(cellsOf(container).filter((c) => c.getAttribute("tabindex") === "-1")).toHaveLength(
      cellsOf(container).length - 1,
    );
    expect(container.querySelector('[role="grid"]')?.hasAttribute("tabindex")).toBe(false);
  });

  it("parks the roving cell on the first DATA row, not the header", () => {
    const { container } = mount(<DataGrid<Row> label="Rows" columns={columns} nodes={dataNodes()} template={TEMPLATE} />);
    expect(position(container)).toEqual([2, 1]);
  });

  it("aria-sort is present on sortable columns and ABSENT on the rest", () => {
    const { container } = mount(
      <DataGrid<Row>
        label="Rows"
        columns={columns}
        nodes={dataNodes()}
        template={TEMPLATE}
        sort={{ columnId: "name", direction: "desc" }}
        onSort={() => undefined}
      />,
    );
    const heads = [...container.querySelectorAll('[role="columnheader"]')];
    expect(heads[0]?.getAttribute("aria-sort")).toBe("none");
    expect(heads[1]?.getAttribute("aria-sort")).toBe("descending");
    expect(heads[2]?.hasAttribute("aria-sort")).toBe(false);
  });

  /* A11Y critic, D2: with no single-column sort every header said aria-sort="none" while the rows
     were in a composite ranked order. The order must be determinable from the grid itself. */
  it("states the current order in the grid's description, alongside the caller's own", () => {
    const { container } = mount(
      <>
        <p id="caller-desc">caller</p>
        <DataGrid<Row>
          label="Rows"
          columns={columns}
          nodes={dataNodes()}
          template={TEMPLATE}
          onSort={() => undefined}
          describedBy="caller-desc"
          orderDescription="Order: ranked by severity, then priority."
        />
      </>,
    );
    const ids = container.querySelector('[role="grid"]')?.getAttribute("aria-describedby")?.split(" ") ?? [];
    expect(ids[0]).toBe("caller-desc");
    const text = ids.map((id) => document.getElementById(id)?.textContent);
    expect(text).toContain("Order: ranked by severity, then priority.");
  });

  /* A11Y critic, D8: the related-row mark was a trailing-edge line only; the relation must be
     exposed per row, and ONLY on related rows. */
  it("exposes a related row's relation per row, in words, and nowhere else", () => {
    const { container } = mount(
      <DataGrid<Row>
        label="Rows"
        columns={columns}
        nodes={dataNodes()}
        template={TEMPLATE}
        relatedIds={new Set(["r2"])}
        relatedDescription="names the selected device core1"
      />,
    );
    const related = container.querySelector<HTMLElement>('[data-related="yes"]');
    expect(related?.getAttribute("aria-description")).toBe("names the selected device core1");
    expect(related?.querySelector('[role="rowheader"]')?.textContent).toContain("names the selected device core1");
    const plain = [...container.querySelectorAll<HTMLElement>(".ag__row--data")].filter((r) => r !== related);
    expect(plain).toHaveLength(rows.length - 1);
    for (const r of plain) {
      expect(r.hasAttribute("aria-description")).toBe(false);
      expect(r.textContent).not.toContain("selected device");
    }
  });

  /* ── D2: nothing focusable may be hidden from assistive technology ──────────
     The sort button used to carry a permanent `aria-hidden="true"` while F2 raised its tabindex
     to 0, so focus landed somewhere with no name, no role and no state (axe `aria-hidden-focus`).
     Both halves are asserted: that the control is exposed and named, and — as a structural
     backstop for any future cell control — that cell mode refuses to enter an AT-hidden one. */
  it("exposes the sort control to assistive technology, named for what it does", () => {
    const { container } = mount(
      <DataGrid<Row> label="Rows" columns={columns} nodes={dataNodes()} template={TEMPLATE} onSort={() => undefined} />,
    );
    const head = container.querySelector<HTMLElement>('[role="columnheader"][data-col="id"]')!;
    const btn = head.querySelector<HTMLElement>("button.ag__sortbtn")!;
    expect(btn.hasAttribute("aria-hidden")).toBe(false);
    expect(btn.getAttribute("aria-label")).toBe("Sort by ID");
    // The header keeps its own name; it must not inherit the control's.
    expect(head.getAttribute("aria-label")).toBe("ID");
    expect(container.querySelectorAll('[aria-hidden="true"] button, button[aria-hidden="true"]').length).toBe(0);
  });

  it("F2 reaches the sort control, and refuses any control hidden from AT", () => {
    const { container } = mount(
      <DataGrid<Row> label="Rows" columns={columns} nodes={dataNodes()} template={TEMPLATE} onSort={() => undefined} />,
    );
    const head = container.querySelector<HTMLElement>('[role="columnheader"][data-col="id"]')!;
    focus(head);
    key(document.activeElement!, "F2");
    const active = document.activeElement as HTMLElement;
    expect(active.className).toContain("ag__sortbtn");
    expect(active.closest('[aria-hidden="true"]')).toBeNull();

    // Now hide it the way the old code did: cell mode must decline rather than focus it.
    key(document.activeElement!, "F2"); // exit
    head.querySelector("button.ag__sortbtn")!.setAttribute("aria-hidden", "true");
    focus(head);
    key(document.activeElement!, "F2");
    expect(document.activeElement).toBe(head);
  });

  /* ── D2: the app's own "selection" must be programmatically determinable ──── */
  it("marks the active row aria-current, independently of the batch's aria-selected", () => {
    const { container } = mount(
      <DataGrid<Row>
        label="Rows"
        columns={columns}
        nodes={dataNodes()}
        template={TEMPLATE}
        activeId="r3"
        batchIds={new Set(["r5"])}
        onToggleBatch={() => undefined}
      />,
    );
    const rowOf = (id: string): HTMLElement =>
      [...container.querySelectorAll<HTMLElement>('[role="row"].ag__row--data')].find(
        (r) => r.querySelector('[role="rowheader"]')?.textContent === id,
      )!;
    // The active row is current but NOT batch-selected...
    expect(rowOf("r3").getAttribute("aria-current")).toBe("true");
    expect(rowOf("r3").getAttribute("aria-selected")).toBe("false");
    // ...and the batched row is selected but not current. The two states never stand in for
    // each other, which is the whole defect: `aria-selected` was spoken for by the batch.
    expect(rowOf("r5").getAttribute("aria-selected")).toBe("true");
    expect(rowOf("r5").hasAttribute("aria-current")).toBe(false);
    expect(rowOf("r1").hasAttribute("aria-current")).toBe(false);
  });
});

/* ══ the keyboard contract, key by key ═════════════════════════════════════ */

describe("APG keyboard contract", () => {
  const setup = (extra: Partial<Parameters<typeof DataGrid<Row>>[0]> = {}) => {
    const { container } = mount(
      <DataGrid<Row> label="Rows" columns={columns} nodes={dataNodes()} template={TEMPLATE} {...extra} />,
    );
    const first = at(container, 2, 1);
    focus(first);
    return { container, first };
  };

  it("ArrowRight moves one cell right and DOES NOT MOVE at the right-most cell", () => {
    const { container } = setup();
    key(document.activeElement!, "ArrowRight");
    expect(position(container)).toEqual([2, 2]);
    key(document.activeElement!, "ArrowRight");
    expect(position(container)).toEqual([2, 3]);
    key(document.activeElement!, "ArrowRight");
    expect(position(container)).toEqual([2, 3]);
  });

  it("ArrowLeft moves one cell left and DOES NOT MOVE at the left-most cell", () => {
    const { container } = setup();
    key(document.activeElement!, "ArrowRight");
    key(document.activeElement!, "ArrowLeft");
    expect(position(container)).toEqual([2, 1]);
    key(document.activeElement!, "ArrowLeft");
    expect(position(container)).toEqual([2, 1]);
  });

  it("ArrowDown moves one row down and DOES NOT MOVE at the last row", () => {
    const { container } = setup();
    key(document.activeElement!, "ArrowDown");
    expect(position(container)).toEqual([3, 1]);
    for (let i = 0; i < 20; i++) key(document.activeElement!, "ArrowDown");
    expect(position(container)).toEqual([rows.length + 1, 1]);
  });

  it("ArrowUp moves one row up, reaches the header row, and then DOES NOT MOVE", () => {
    const { container } = setup();
    key(document.activeElement!, "ArrowUp");
    expect(position(container)).toEqual([1, 1]);
    key(document.activeElement!, "ArrowUp");
    expect(position(container)).toEqual([1, 1]);
  });

  it("arrows CLAMP rather than wrap — the bottom row does not land on the top one", () => {
    const { container } = setup();
    for (let i = 0; i < 50; i++) key(document.activeElement!, "ArrowDown");
    expect(position(container)[0]).toBe(rows.length + 1);
    for (let i = 0; i < 50; i++) key(document.activeElement!, "ArrowRight");
    expect(position(container)[1]).toBe(columns.length);
  });

  it("Home and End move within the row that contains focus", () => {
    const { container } = setup();
    key(document.activeElement!, "ArrowDown");
    key(document.activeElement!, "ArrowRight");
    expect(position(container)).toEqual([3, 2]);
    key(document.activeElement!, "End");
    expect(position(container)).toEqual([3, 3]);
    key(document.activeElement!, "Home");
    expect(position(container)).toEqual([3, 1]);
  });

  it("Ctrl+Home goes to the first cell of the grid and Ctrl+End to the last", () => {
    const { container } = setup();
    key(document.activeElement!, "ArrowDown");
    key(document.activeElement!, "End", { ctrlKey: true });
    expect(position(container)).toEqual([rows.length + 1, columns.length]);
    key(document.activeElement!, "Home", { ctrlKey: true });
    expect(position(container)).toEqual([1, 1]);
  });

  /* The page step is MEASURED (visible rows − 1) and only falls back to five when there is
     nothing to measure, which in jsdom is always. A test run entirely in the fallback would
     assert the fallback and call it the contract, so the measured path is given real geometry
     here and asserted on its own. 12 visible rows over a 600px port ⇒ a step of 11. */
  const withGeometry = (container: HTMLElement, portPx: number, headPx: number, rowPx: number): void => {
    const grid = container.querySelector<HTMLElement>('[role="grid"]')!;
    Object.defineProperty(grid, "clientHeight", { value: portPx, configurable: true });
    const stub = (el: Element, h: number): void => {
      el.getBoundingClientRect = () => ({ x: 0, y: 0, width: 200, height: h, top: 0, left: 0, right: 200, bottom: h, toJSON: () => ({}) }) as DOMRect;
    };
    /* The page is the VISIBLE band (the grid's box below its header, inside every clip and the
       viewport), read from layout rects rather than clientHeight — so the port gets a box too. */
    stub(grid, portPx);
    stub(container.querySelector(".ag__head")!, headPx);
    for (const r of container.querySelectorAll(".ag__row--data")) stub(r, rowPx);
  };

  it("PageDown and PageUp step by the MEASURED page, keeping one row of context", () => {
    const { container } = setup({ nodes: dataNodes(manyRows) });
    withGeometry(container, 600, 50, 50);
    // (600 - 50) / 50 = 11 visible rows, minus one for context = a step of 10.
    key(document.activeElement!, "PageDown");
    expect(position(container)).toEqual([12, 1]);
    key(document.activeElement!, "PageDown");
    expect(position(container)).toEqual([22, 1]);
    key(document.activeElement!, "PageUp");
    expect(position(container)).toEqual([12, 1]);
  });

  it("falls back to five rows when the viewport cannot be measured", () => {
    const { container } = setup();
    key(document.activeElement!, "PageDown");
    expect(position(container)).toEqual([7, 1]);
    key(document.activeElement!, "PageDown");
    expect(position(container)).toEqual([rows.length + 1, 1]);
    key(document.activeElement!, "PageDown");
    expect(position(container)).toEqual([rows.length + 1, 1]);
    key(document.activeElement!, "PageUp");
    expect(position(container)).toEqual([4, 1]);
    key(document.activeElement!, "PageUp");
    expect(position(container)).toEqual([1, 1]);
    key(document.activeElement!, "PageUp");
    expect(position(container)).toEqual([1, 1]);
  });

  it("Enter and Space activate the row's primary action", () => {
    const onActivate = vi.fn();
    setup({ onActivate });
    key(document.activeElement!, "Enter");
    expect(onActivate).toHaveBeenCalledTimes(1);
    expect(onActivate.mock.calls[0]?.[1]).toBe("r1");
    key(document.activeElement!, " ");
    expect(onActivate).toHaveBeenCalledTimes(2);
  });

  it("Enter on a header cell sorts that column", () => {
    const onSort = vi.fn();
    const { container } = setup({ onSort });
    key(document.activeElement!, "ArrowUp");
    expect(position(container)).toEqual([1, 1]);
    key(document.activeElement!, "Enter");
    expect(onSort).toHaveBeenCalledWith("id");
  });

  it("X toggles the row's batch selection WITHOUT moving focus", () => {
    const onToggleBatch = vi.fn();
    const { container } = setup({ onToggleBatch });
    key(document.activeElement!, "ArrowDown");
    const before = position(container);
    key(document.activeElement!, "x");
    expect(onToggleBatch).toHaveBeenCalledTimes(1);
    expect(onToggleBatch.mock.calls[0]?.[1]).toBe("r2");
    expect(position(container)).toEqual(before);
  });

  it("Shift+Space selects the focused row; Ctrl+A selects everything matching the filter", () => {
    const onToggleBatch = vi.fn();
    const onSelectAll = vi.fn();
    setup({ onToggleBatch, onSelectAll });
    key(document.activeElement!, " ", { shiftKey: true });
    expect(onToggleBatch).toHaveBeenCalledTimes(1);
    key(document.activeElement!, "a", { ctrlKey: true });
    expect(onSelectAll).toHaveBeenCalledTimes(1);
  });

  it("Ctrl+Space marks the focused column as selected", () => {
    const { container } = setup();
    key(document.activeElement!, "ArrowRight");
    key(document.activeElement!, " ", { ctrlKey: true });
    const marked = [...container.querySelectorAll('[aria-colindex="2"][aria-selected="true"]')];
    expect(marked.length).toBe(rows.length + 1);
  });

  it("Escape leaves the grid when the host does not handle it", () => {
    const { container, first } = setup();
    /* The grid sits in a host surface, as it does in production (PriorityQueue's labelled
       section). This fixture used to mount the grid straight under <body> with nothing else
       focusable, so the ONLY way the assertion below could pass was focus dropping to <body> —
       the acceptance D3 defect was what made it green. Leaving now lands on the host's region
       landmark (src/app/focus-return.ts), and the added assertion pins that it is not <body>. */
    const host = document.createElement("section");
    host.setAttribute("aria-label", "Host surface");
    document.body.appendChild(host);
    host.appendChild(container);
    focus(first); // re-parenting a focused node blurs it
    expect(container.contains(document.activeElement)).toBe(true);
    key(document.activeElement!, "Escape");
    expect(container.contains(document.activeElement)).toBe(false);
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(host);
  });

  it("Escape keeps focus in the grid when the host handles it", () => {
    const onEscape = vi.fn(() => true);
    const { container } = setup({ onEscape });
    key(document.activeElement!, "Escape");
    expect(onEscape).toHaveBeenCalled();
    expect(container.contains(document.activeElement)).toBe(true);
  });

  it("Escape moves focus to the declared exit target when one is given", () => {
    const outside = document.createElement("input");
    document.body.appendChild(outside);
    setup({ exitFocusRef: { current: outside } });
    key(document.activeElement!, "Escape");
    expect(document.activeElement).toBe(outside);
    outside.remove();
  });
});

/* ══ the pointer hit area is the same shape as the hover affordance ════════
 *
 * The brief says "Row click selects" (§ the findings grid) and lists "making the whole grid row
 * clickable for DRILL-DOWN" as the anti-pattern — drill-down keeps its own glyph. Activation used
 * to be wired on the gridcell only, which left the row's `column-gap` and its `padding-inline`
 * dead: measured 2026-09-21 on the release build, clicking any of a row's six cells set `?f=F004`
 * while clicking the same row's geometric CENTRE — which falls in a gap — changed nothing, though
 * the row had highlighted under the pointer the whole time. */
describe("clicking a row selects it, anywhere on the row", () => {
  const clickOn = (el: Element): void => {
    act(() => el.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  };

  it("activates when the click lands on the row itself rather than on a cell", () => {
    const onActivate = vi.fn();
    const { container } = mount(
      <DataGrid<Row>
        label="Rows"
        columns={columns}
        nodes={dataNodes()}
        template={TEMPLATE}
        onActivate={onActivate}
      />,
    );
    // The gap between two cells has the ROW as its event target — which is exactly what a click in
    // `column-gap` or in the row's inline padding produces in a browser.
    const row = container.querySelector<HTMLElement>('[role="row"][aria-rowindex="2"]')!;
    expect(row.className).toContain("ag__row--data");
    clickOn(row);
    expect(onActivate).toHaveBeenCalledTimes(1);
    expect(onActivate.mock.calls[0]?.[1]).toBe("r1");
  });

  it("activates exactly once when the click lands on a cell, not twice", () => {
    const onActivate = vi.fn();
    const { container } = mount(
      <DataGrid<Row>
        label="Rows"
        columns={columns}
        nodes={dataNodes()}
        template={TEMPLATE}
        onActivate={onActivate}
      />,
    );
    clickOn(at(container, 3, 2));
    expect(onActivate).toHaveBeenCalledTimes(1);
    expect(onActivate.mock.calls[0]?.[1]).toBe("r2");
    // And it moved the roving cell to the cell that was clicked.
    expect(position(container)).toEqual([3, 2]);
  });

  it("does NOT activate from a cell that owns its own control — drill stays separate", () => {
    const onActivate = vi.fn();
    const withDrill: GridColumn<Row>[] = [
      ...columns,
      { id: "drill", header: "Evidence", width: "2rem", interactive: true, render: () => <button type="button">cite</button> },
    ];
    const { container } = mount(
      <DataGrid<Row>
        label="Rows"
        columns={withDrill}
        nodes={dataNodes()}
        template={`${TEMPLATE} 2rem`}
        onActivate={onActivate}
      />,
    );
    clickOn(at(container, 2, 4));
    expect(onActivate).not.toHaveBeenCalled();
  });
});

/* ══ groups ════════════════════════════════════════════════════════════════ */

describe("group rows", () => {
  const grouped: GridNode<Row>[] = [
    { kind: "group", id: "g1", label: "Alpha group", count: 2, observed: true, collapsed: false },
    { kind: "row", id: "r1", item: rows[0]! },
    { kind: "row", id: "r2", item: rows[1]! },
    { kind: "group", id: "g2", label: "Not observed", count: 0, observed: false, collapsed: true },
  ];

  it("is one spanning cell carrying aria-expanded on the CELL, never on the plain-grid row", () => {
    const { container } = mount(<DataGrid<Row> label="Rows" columns={columns} nodes={grouped} template={TEMPLATE} />);
    const groupRow = container.querySelector<HTMLElement>('[role="row"][aria-rowindex="2"]');
    /* An expandable ROW is treegrid semantics (A11Y critic, D2); no row in a role=grid carries it. */
    expect(container.querySelectorAll('[role="grid"] [role="row"][aria-expanded]').length).toBe(0);
    expect(groupRow?.querySelectorAll('[role="gridcell"]').length).toBe(1);
    const cell = groupRow?.querySelector('[role="gridcell"]');
    expect(cell?.getAttribute("aria-expanded")).toBe("true");
    expect(cell?.getAttribute("aria-colspan")).toBe(String(columns.length));
    expect(
      container.querySelector<HTMLElement>('[role="row"][aria-rowindex="5"] [role="gridcell"]')?.getAttribute("aria-expanded"),
    ).toBe("false");
  });

  it("t collapses and expands the focused group, and passing through it keeps the travelled column", () => {
    const onToggleGroup = vi.fn();
    const { container } = mount(
      <DataGrid<Row> label="Rows" columns={columns} nodes={grouped} template={TEMPLATE} onToggleGroup={onToggleGroup} />,
    );
    focus(at(container, 3, 3));
    expect(position(container)).toEqual([3, 3]);
    key(document.activeElement!, "ArrowUp");
    // A group row has one cell, so the column clamps to 1 on the way through...
    expect(position(container)).toEqual([2, 1]);
    key(document.activeElement!, "t");
    expect(onToggleGroup).toHaveBeenCalledWith("g1");
    key(document.activeElement!, "ArrowDown");
    // ...and is restored on the way out.
    expect(position(container)).toEqual([3, 3]);
  });
});

/* ══ absence ═══════════════════════════════════════════════════════════════ */

describe("absence is never an empty cell", () => {
  it("renders the not-observed treatment when a column renderer produces nothing", () => {
    const { container } = mount(<DataGrid<Row> label="Rows" columns={columns} nodes={dataNodes()} template={TEMPLATE} />);
    const cell = at(container, 3, 3); // r2.score === null
    expect(cell.textContent ?? "").toContain("not observed");
    expect(cell.querySelector("[data-unobserved='true']")).not.toBeNull();
    // and the observed neighbour is a real value, so the treatment is not applied to everything
    expect(at(container, 2, 3).textContent).toContain("3");
    expect(at(container, 2, 3).querySelector("[data-unobserved='true']")).toBeNull();
  });

  it("an empty grid explains itself outside the row model rather than faking a row", () => {
    const { container } = mount(
      <DataGrid<Row> label="Rows" columns={columns} nodes={[]} template={TEMPLATE} empty={<p>nothing matched, and here is why</p>} />,
    );
    expect(container.querySelector('[role="grid"]')?.getAttribute("aria-rowcount")).toBe("1");
    expect(container.querySelectorAll('[role="gridcell"]').length).toBe(0);
    expect(container.textContent).toContain("nothing matched");
  });
});

/* ══ windowing ═════════════════════════════════════════════════════════════ */

describe("windowing declares itself through ARIA", () => {
  const many: Row[] = Array.from({ length: 1000 }, (_, i) => ({
    id: `w${i + 1}`,
    name: `row ${i + 1}`,
    score: i % 7 === 0 ? null : i,
  }));

  it("renders a slice but reports the LOGICAL totals and indices", () => {
    const { container } = mount(
      <DataGrid<Row>
        label="Many"
        columns={columns}
        nodes={dataNodes(many)}
        template={TEMPLATE}
        window={{ rowHeightPx: 32, threshold: 100, viewportPx: 320 }}
      />,
    );
    const grid = container.querySelector<HTMLElement>('[role="grid"]')!;
    expect(grid.getAttribute("aria-rowcount")).toBe("1001");
    const body = container.querySelector<HTMLElement>(".ag__body")!;
    const rendered = body.querySelectorAll('[role="row"][aria-rowindex]').length;
    expect(rendered).toBeLessThan(200);
    expect(rendered).toBeGreaterThan(1);
    expect(at(container, 2, 1).textContent).toContain("w1");

    act(() => {
      grid.scrollTop = 32 * 500;
      grid.dispatchEvent(new Event("scroll"));
    });
    // The rendered window moved; the announced position is still the logical one, so a screen
    // reader is never told "row 12" while the user sits at logical row 500.
    const firstRendered = body.querySelector<HTMLElement>('[role="row"][aria-rowindex]');
    expect(Number(firstRendered?.getAttribute("aria-rowindex"))).toBeGreaterThan(480);
    expect(container.querySelector('[role="grid"]')?.getAttribute("aria-rowcount")).toBe("1001");
  });

  it("renders every row when there is no usable viewport measurement — it fails OPEN", () => {
    const { container } = mount(
      <DataGrid<Row>
        label="Many"
        columns={columns}
        nodes={dataNodes(many)}
        template={TEMPLATE}
        window={{ rowHeightPx: 32, threshold: 100 }}
      />,
    );
    // jsdom reports clientHeight 0. Showing too many rows is slow; showing too few hides evidence.
    expect(container.querySelectorAll('[role="rowheader"]').length).toBe(many.length);
  });

  it("does not window below the threshold", () => {
    const { container } = mount(
      <DataGrid<Row>
        label="Many"
        columns={columns}
        nodes={dataNodes()}
        template={TEMPLATE}
        window={{ rowHeightPx: 32, threshold: 200, viewportPx: 64 }}
      />,
    );
    expect(container.querySelectorAll('[role="rowheader"]').length).toBe(rows.length);
  });
});

/* ══ the real compiled data ════════════════════════════════════════════════ */

describe("the same contract over the real snapshot", () => {
  const findingColumns: GridColumn<Finding>[] = [
    { id: "id", header: "ID", width: "4rem", rowHeader: true, sortable: true, render: (f) => f.id },
    { id: "title", header: "Finding", width: "minmax(0,1fr)", render: (f) => f.title },
    { id: "wave", header: "Wave", width: "6rem", unobservedWhat: "migration wave", render: (f) => f.wave },
  ];

  it("navigates the real findings and renders every unobserved wave as not observed", () => {
    const nodes: GridNode<Finding>[] = fabric.findings.map((f) => ({ kind: "row" as const, id: f.id, item: f }));
    const { container } = mount(
      <DataGrid<Finding> label="Findings" columns={findingColumns} nodes={nodes} template={TEMPLATE} />,
    );
    expect(container.querySelector('[role="grid"]')?.getAttribute("aria-rowcount")).toBe(
      String(fabric.findings.length + 1),
    );
    const waveCells = [...container.querySelectorAll('[aria-colindex="3"][role="gridcell"]')];
    const unobserved = fabric.findings.filter((f) => f.wave === null).length;
    expect(waveCells.filter((c) => c.querySelector("[data-unobserved='true']") !== null)).toHaveLength(unobserved);
    // Not a single one of those cells is empty.
    expect(waveCells.every((c) => (c.textContent ?? "").trim().length > 0)).toBe(true);

    focus(at(container, 2, 1));
    key(document.activeElement!, "PageDown");
    expect(position(container)).toEqual([7, 1]);
  });
});

/* ══ an external selection carries the tab stop (D3) ═══════════════════════
   MEASURED by an independent critic: picking F099 from the command palette while focus sat on the
   F001 cell revealed F099, but the dialog then restored focus to the F001 cell — 4,007 px above
   the scroll port, no visible focus — and the next ArrowDown scrolled the queue back to the top. */

describe("an external selection moves the roving cell with the reveal", () => {
  const ui = (activeId: string | null): ReactNode => (
    <>
      <button type="button" id="outside">
        outside
      </button>
      <DataGrid<Row> label="Rows" columns={columns} nodes={dataNodes(manyRows)} template={TEMPLATE} activeId={activeId} />
    </>
  );

  it("puts the single tab stop on the selected row, keeping the reader's column", () => {
    const { container, render } = mount(ui(null));
    focus(at(container, 3, 2));
    focus(container.querySelector<HTMLElement>("#outside")!);
    render(ui("m30"));
    expect(container.querySelectorAll('[tabindex="0"]').length).toBe(1);
    expect(position(container)).toEqual([31, 2]);
  });

  it("redirects focus restored to the stale invoker cell onto the selected row", () => {
    const { container, render } = mount(ui(null));
    const invoker = at(container, 3, 1);
    focus(invoker);
    focus(container.querySelector<HTMLElement>("#outside")!); // the palette takes focus
    render(ui("m30")); // the palette commits a selection
    focus(invoker); // the dialog restores focus to whatever opened it
    const active = document.activeElement as HTMLElement;
    expect(active.closest('[role="row"]')?.getAttribute("aria-rowindex")).toBe("31");
    key(active, "ArrowDown");
    expect(position(container)).toEqual([32, 1]);
  });

  it("does not override a cell the reader clicks after the selection", () => {
    const { container, render } = mount(ui(null));
    focus(at(container, 3, 1));
    focus(container.querySelector<HTMLElement>("#outside")!);
    render(ui("m30"));
    const target = at(container, 5, 1);
    act(() => {
      target.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
      target.focus();
    });
    expect(document.activeElement).toBe(target);
    expect(position(container)).toEqual([5, 1]);
  });
});

/* The render-time aim used to fire only when the aim TARGET changed. A filter edit that keeps the
   selection but moves it to another row index left the tab stop on whatever row now occupied the
   old index, so Tab entered the grid on a stranger (W6-a4; PriorityQueue worked around it for its
   own widen control by withdrawing `revealId` for one commit). The aim now follows the row while
   the reader has not moved the roving cell since the aim placed it; once they have, their place
   is theirs and the pre-existing clamp keeps its index. */
describe("the tab stop follows the selected row when the rows re-order", () => {
  const ui = (rs: readonly Row[], activeId: string | null): ReactNode => (
    <>
      <button type="button" id="outside">
        outside
      </button>
      <DataGrid<Row> label="Rows" columns={columns} nodes={dataNodes(rs)} template={TEMPLATE} activeId={activeId} />
    </>
  );
  const evens = manyRows.filter((r) => Number(r.id.slice(1)) % 2 === 0);
  const stopId = (c: HTMLElement): string | undefined =>
    focusedCell(c)?.closest('[role="row"]')?.querySelector('[role="rowheader"]')?.textContent ?? undefined;

  it("re-aims when the same selected id moves to a new row index", () => {
    const { container, render } = mount(ui(manyRows, "m30"));
    expect(stopId(container)).toBe("m30");
    render(ui(evens, "m30")); // m30: index 29 -> 14
    expect(container.querySelectorAll('[tabindex="0"]').length).toBe(1);
    expect(stopId(container)).toBe("m30");
    render(ui([...evens].reverse(), "m30")); // and again, on a re-sort
    expect(stopId(container)).toBe("m30");
  });

  it("leaves the reader's own place alone once they have moved the roving cell", () => {
    const { container, render } = mount(ui(manyRows, "m30"));
    const cell = focusedCell(container)!;
    focus(cell);
    key(cell, "ArrowDown");
    key(document.activeElement!, "ArrowDown");
    expect(stopId(container)).toBe("m32");
    focus(container.querySelector<HTMLElement>("#outside")!);
    render(ui(evens, "m30"));
    // The index is kept (clamped to the 20 remaining rows), as before: not dragged back to m30.
    expect(stopId(container)).toBe("m40");
  });
});
