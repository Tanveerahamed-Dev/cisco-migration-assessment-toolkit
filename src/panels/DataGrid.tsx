/**
 * DataGrid.tsx — the dense grid every table in this application is built from.
 *
 * It implements the APG data-grid keyboard contract literally (design-brief §7.2), because the
 * contract is the product: a 189-row queue that costs 189 Tab presses to walk past is not a
 * professional tool, and a grid that announces "row 12 of 30" while the user sits at logical row
 * 118 of 146 is actively lying about the data — the same defect class this application exists to
 * eliminate everywhere else.
 *
 * Three properties hold and are tested key by key in DataGrid.test.tsx:
 *
 *   1. ONE TAB STOP. Exactly one cell in the grid carries tabindex="0"; every other cell carries
 *      tabindex="-1". The grid container itself is not focusable.
 *   2. LOGICAL ARIA INDICES. aria-rowcount / aria-colcount are the totals, and aria-rowindex /
 *      aria-colindex are 1-based logical positions — independent of how many rows the windowing
 *      hook chose to put in the DOM.
 *   3. ARROWS CLAMP, NEVER WRAP. Wrapping is layout-grid behaviour; importing it into a data grid
 *      destroys the positional model an engineer builds while scanning.
 *
 * Absence: a column renderer that returns `null`/`undefined` is rendered through the NotObserved
 * primitive rather than left as an empty cell. A blank cell in a dense grid reads as zero, and the
 * caller cannot be relied on to remember that at every call site.
 */
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { IconChevronDown, IconChevronRight, IconSortAsc, IconSortDesc, IconSortNone } from "../ui/icons";
import { LiveRegion, NotObserved } from "../ui/primitives";
import "./DataGrid.css";

/* ── column model ───────────────────────────────────────────────────────────── */

export interface GridColumn<T> {
  id: string;
  /** Visible header text. */
  header: string;
  /** Full header text when `header` is abbreviated to fit; becomes the accessible name. */
  headerLabel?: string;
  /** CSS track size contributed to grid-template-columns. */
  width: string;
  /** Explicit `grid-area` for the data cell, when the row is laid out on more than one line. */
  place?: string;
  /** Explicit `grid-area` for the header cell. Defaults to `place`. */
  headerPlace?: string;
  /**
   * The header CELL is clipped to its accessible name and paints nothing — the caller has demoted
   * this column's label out of the header row (see PriorityQueue's stacked layout, where the
   * metadata columns become inline chips in the row instead).
   *
   * It carries a consequence, not just a style: a clipped cell cannot hold a pointer target. A
   * sort button inside one measures 1px wide and sits off-screen, so it is not rendered at all,
   * the cell does not sort on Enter either, and `aria-sort="none"` is withheld — the ARIA surface
   * must not advertise a control no pointer user has. `aria-sort` is still emitted when the
   * column IS the active sort, because that is a statement about the DATA rather than about a
   * control. Sorting such a column stays available to everyone through the caller's own ordering
   * control, which names the field in words.
   */
  headerHidden?: boolean;
  align?: "start" | "end";
  sortable?: boolean;
  resizable?: boolean;
  /** Resize bounds in px. Only consulted when `resizable`. */
  minPx?: number;
  maxPx?: number;
  /** The row's identity column, rendered role="rowheader". At most one per grid. */
  rowHeader?: boolean;
  /** The cell holds its own focusable control, so Enter / F2 step INTO it instead of activating. */
  interactive?: boolean;
  /** What a null renderer result means, for the NotObserved sentence. */
  unobservedWhat?: string;
  render: (item: T) => ReactNode;
}

export type GridNode<T> =
  | {
      kind: "group";
      id: string;
      label: string;
      count: number;
      /** false = these rows carry no observed value for the grouping key. */
      observed: boolean;
      collapsed: boolean;
      /** Extra content on the group header row, e.g. a severity breakdown. */
      detail?: ReactNode;
    }
  | { kind: "row"; id: string; item: T };

export interface GridSort {
  columnId: string;
  direction: "asc" | "desc";
}

export interface GridWindowing {
  /** Uniform row height in px. Windowing is impossible without one, so it is required here. */
  rowHeightPx: number;
  /** Rows below this count are all rendered. 146 rows do not need a window; 1,460 do. */
  threshold?: number;
  /** Viewport height override. Used by tests, where jsdom reports clientHeight 0. */
  viewportPx?: number;
  overscan?: number;
}

export interface DataGridProps<T> {
  /** Accessible name for the grid. */
  label: string;
  columns: readonly GridColumn<T>[];
  /** Flat, in display order. Rows inside a collapsed group are omitted by the caller. */
  nodes: readonly GridNode<T>[];
  /** grid-template-columns for both the header and every row. */
  template: string;
  /** The row currently selected in the shared investigation context. */
  activeId?: string | null;
  /**
   * The row to scroll into view when this value CHANGES. Defaults to `activeId`.
   *
   * Separate from `activeId` because the two answer different questions: `activeId` is what is
   * selected, `revealId` is what the reader needs to be looking at. A caller whose corpus holds no
   * row for the current selection — a device chosen on another surface, say — can still point the
   * reader at the nearest row the corpus does hold.
   */
  revealId?: string | null;
  /**
   * Rows related to a selection this corpus cannot hold as a row of its own — the findings that
   * name the selected device or the endpoints of the selected cable.
   *
   * Marked, never filtered. Hiding the rest would make the queue answer "what is wrong with this
   * box" while still calling itself the fleet punchlist, and the reader would have no way to see
   * that the corpus had narrowed under them.
   */
  relatedIds?: ReadonlySet<string>;
  /** Rows in the multi-select batch. Separate from `activeId` — focus, selection and the batch
   *  are three different states and conflating them is how bulk operations become accidental. */
  batchIds?: ReadonlySet<string>;
  sort?: GridSort | null;
  onSort?: (columnId: string) => void;
  onActivate?: (item: T, id: string) => void;
  onToggleBatch?: (item: T, id: string) => void;
  /** Replace the batch with a contiguous range, in display order. This is what Shift+Arrow and
   *  Shift+Home/End drive: a grid that declares `aria-multiselectable` has told assistive
   *  technology that range selection exists, so the range keys have to exist too. */
  onSelectRange?: (items: readonly T[], ids: readonly string[]) => void;
  onSelectAll?: () => void;
  onToggleGroup?: (groupId: string) => void;
  /** Return true when the component handled Escape itself (e.g. cleared a selection) and focus
   *  should stay in the grid. Anything else leaves the grid. */
  onEscape?: () => boolean;
  /** Where focus lands when the user leaves the grid with Escape. */
  exitFocusRef?: { current: HTMLElement | null };
  columnWidths?: Readonly<Record<string, number>>;
  onResizeColumn?: (columnId: string, px: number) => void;
  /** Row layout: "line" puts every cell on one line, "stacked" honours each column's `place`. */
  layout?: "line" | "stacked";
  window?: GridWindowing;
  /** Rendered in place of the body when there are no rows. Must explain WHY it is empty. */
  empty?: ReactNode;
  describedBy?: string;
  /** True while the row set is being recomputed, so partial rows are not announced one by one. */
  busy?: boolean;
  className?: string;
  /** Row height class hook, e.g. "compact" | "comfortable". Styling only. */
  density?: string;
}

/* ── navigation model ───────────────────────────────────────────────────────── */

type NavRow<T> = { kind: "header" } | { kind: "group"; node: Extract<GridNode<T>, { kind: "group" }> } | { kind: "data"; node: Extract<GridNode<T>, { kind: "row" }> };

/**
 * The page step when the viewport cannot be measured — jsdom, a `display: none` ancestor, the
 * first paint before layout. It stays at the brief's five rows so the contract is unchanged
 * wherever there is nothing to measure.
 */
const PAGE_ROWS_FALLBACK = 5;

/**
 * How far PageUp / PageDown travel.
 *
 * A11Y AUDIT FIX, 2026-09-21 (D2). This was a fixed 5 on the grounds that a measurement "reads 0
 * in a test environment", which is true and is why the fallback above still exists — but it made
 * the keys nearly useless on the surface they exist for. Measured in the browser: grid client
 * height 661 px over 51 px data rows = 12.96 visible rows, so a "page" moved under half a screen
 * and crossing 146 findings took ~29 presses. APG leaves the page size to the author precisely so
 * it can be the visible row count; its own data-grid examples derive it the same way.
 *
 * `visible - 1` keeps one row of context across the jump, which is what lets a reader join the
 * new screen to the old one instead of landing cold. The measurement is taken at KEYPRESS time,
 * never cached, so
 * a resize needs no invalidation. Anything unmeasurable falls back rather than paging by 0.
 */
const pageRows = (scroller: HTMLElement | null, head: HTMLElement | null): number => {
  if (!scroller) return PAGE_ROWS_FALLBACK;
  const row = scroller.querySelector<HTMLElement>('[role="row"].ag__row--data');
  const rowH = row?.getBoundingClientRect().height ?? 0;
  /* The sticky header sits inside the scroll port and covers the top of it, so the rows a reader
     can actually see start below it — the same correction the reveal effect makes. */
  const portH = scroller.clientHeight - (head?.getBoundingClientRect().height ?? 0);
  if (rowH < 1 || portH < 1) return PAGE_ROWS_FALLBACK;
  return Math.max(1, Math.floor(portH / rowH) - 1);
};

const RESIZE_STEP_PX = 8;

const clamp = (n: number, lo: number, hi: number): number => (n < lo ? lo : n > hi ? hi : n);

/** A renderer that produced nothing is an absence, not an empty cell. */
const cellContent = <T,>(col: GridColumn<T>, item: T): ReactNode => {
  const out = col.render(item);
  if (out === null || out === undefined || out === false || out === "") {
    return <NotObserved compact {...(col.unobservedWhat ? { what: col.unobservedWhat } : {})} />;
  }
  return out;
};

/**
 * Which slice of the rows to put in the DOM.
 *
 * Fails OPEN: with no usable viewport measurement (jsdom, a display:none ancestor, first paint)
 * it returns every row. Rendering too many rows is slow; rendering too few silently hides
 * evidence, and in this product that is the worse failure by a wide margin.
 */
function useRowWindow(
  count: number,
  scrollRef: { current: HTMLElement | null },
  spec: GridWindowing | undefined,
): { start: number; end: number; padTop: number; padBottom: number } {
  const [scrollTop, setScrollTop] = useState(0);
  const [measured, setMeasured] = useState(0);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !spec) return;
    const onScroll = (): void => setScrollTop(el.scrollTop);
    el.addEventListener("scroll", onScroll, { passive: true });
    setMeasured(el.clientHeight);
    const RO = typeof ResizeObserver === "undefined" ? null : ResizeObserver;
    const ro = RO ? new RO(() => setMeasured(el.clientHeight)) : null;
    ro?.observe(el);
    return () => {
      el.removeEventListener("scroll", onScroll);
      ro?.disconnect();
    };
  }, [scrollRef, spec]);

  return useMemo(() => {
    const all = { start: 0, end: count, padTop: 0, padBottom: 0 };
    if (!spec) return all;
    const threshold = spec.threshold ?? 200;
    if (count <= threshold) return all;
    const viewport = spec.viewportPx ?? measured;
    if (viewport <= 0) return all;
    const overscan = spec.overscan ?? 8;
    const h = spec.rowHeightPx;
    const start = clamp(Math.floor(scrollTop / h) - overscan, 0, count);
    const end = clamp(Math.ceil((scrollTop + viewport) / h) + overscan, start, count);
    return { start, end, padTop: start * h, padBottom: (count - end) * h };
  }, [count, spec, measured, scrollTop]);
}

/**
 * Does this column offer a SORT CONTROL — a thing a reader can operate, by pointer or by key?
 *
 * One predicate, three consumers: the header button, the `aria-sort` attribute and Enter on the
 * header cell. They used to test `col.sortable` separately, and a column whose header cell is
 * clipped to 1x1 (`headerHidden`) therefore got a 1px-wide button parked off-screen, an
 * `aria-sort="none"` announcing a sortable column, and a working Enter key — a control that only
 * a keyboard user could reach, on a column a pointer user could not sort at all. Being sortable
 * DATA and offering a sort CONTROL are two different properties; this is the second one.
 */
function hasSortControl<T>(col: GridColumn<T> | undefined, onSort: unknown): boolean {
  return col?.sortable === true && col.headerHidden !== true && typeof onSort === "function";
}

/* ── component ──────────────────────────────────────────────────────────────── */

export function DataGrid<T>({
  label,
  columns,
  nodes,
  template,
  activeId = null,
  revealId,
  relatedIds,
  batchIds,
  sort = null,
  onSort,
  onActivate,
  onToggleBatch,
  onSelectRange,
  onSelectAll,
  onToggleGroup,
  onEscape,
  exitFocusRef,
  columnWidths,
  onResizeColumn,
  layout = "line",
  window: windowing,
  empty,
  describedBy,
  busy = false,
  className,
  density = "comfortable",
}: DataGridProps<T>): ReactNode {
  const gridId = useId();
  /** The grid element is also the scroll container, so the sticky header sticks to it and the
   *  windowing hook measures the box the rows actually scroll inside. */
  const gridRef = useRef<HTMLDivElement | null>(null);
  /** The sticky header occupies the top of the scroll port, so "visible" starts below it. */
  const headRef = useRef<HTMLDivElement | null>(null);
  const cellRefs = useRef(new Map<string, HTMLElement>());
  const rowRefs = useRef(new Map<string, HTMLElement>());
  const hasFocus = useRef(false);
  /** Set once the user has driven the grid, so the initial-position effect stops adjusting under
   *  them when a filter changes the first row. */
  const userMoved = useRef(false);
  /** The column the user was travelling in, so passing through a single-cell group row and out
   *  the other side returns to the column they were reading, not to column 1. */
  const desiredCol = useRef(0);
  /** Where a Shift range started. Any unshifted move re-anchors, exactly like a file list. */
  const anchorRow = useRef<number | null>(null);

  const rows = useMemo<NavRow<T>[]>(
    () => [
      { kind: "header" as const },
      ...nodes.map((n) => (n.kind === "group" ? { kind: "group" as const, node: n } : { kind: "data" as const, node: n })),
    ],
    [nodes],
  );

  const colCount = columns.length;
  const cellsIn = useCallback(
    (r: number): number => (rows[r]?.kind === "group" ? 1 : colCount),
    [rows, colCount],
  );

  const firstDataRow = useMemo(() => {
    const i = rows.findIndex((r) => r.kind === "data");
    return i === -1 ? 0 : i;
  }, [rows]);

  const [focusCell, setFocusCell] = useState<{ row: number; col: number }>({ row: firstDataRow, col: 0 });
  const [cellMode, setCellMode] = useState(false);
  const [selectedCol, setSelectedCol] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState("");

  /* The row set changes under the user whenever a filter changes. Clamping here — rather than
     resetting to the top — is what keeps a filter edit from throwing away the user's place.
     Before the user has driven the grid at all, the roving cell parks on the first DATA row:
     entering a grid on its header is correct only if the header is what you came for. */
  useEffect(() => {
    setFocusCell((prev) => {
      const wanted = userMoved.current ? prev : { row: firstDataRow, col: 0 };
      const row = clamp(wanted.row, 0, Math.max(0, rows.length - 1));
      const col = clamp(wanted.col, 0, Math.max(0, cellsIn(row) - 1));
      return row === prev.row && col === prev.col ? prev : { row, col };
    });
  }, [rows, cellsIn, firstDataRow]);

  const cellKey = (r: number, c: number): string => `${r}:${c}`;

  /* Focus follows the roving cell only when the grid ALREADY owns focus. Moving focus because a
     filter changed would yank the caret out of the query bar mid-keystroke. */
  useLayoutEffect(() => {
    if (!hasFocus.current) return;
    const el = cellRefs.current.get(cellKey(focusCell.row, focusCell.col));
    if (el && document.activeElement !== el) el.focus();
  }, [focusCell]);

  /* ── reveal: a selection that arrives from another surface has to become visible ──
   *
   * A4 asks every surface to re-aim on a selection change, and marking a row `data-active` is not
   * re-aiming when the row is below the fold. Measured on the release build before this existed: a
   * URL-restored `?f=F120` left the grid at scrollTop 0 with the active row 6,171 px down a 561 px
   * viewport, and picking a sibling finding in the Inspector while the queue sat at scrollTop 3000
   * left it at 3000 with the newly active row 2,892 px ABOVE the fold. Both states showed the
   * reader an unchanged list and no indication of what had been selected.
   *
   * NEAREST semantics, arithmetic rather than `scrollIntoView`, for three reasons:
   *   1. An already-visible row must not move. That is the scroll-preservation half of A4, and it
   *      is what keeps a click INSIDE the grid from yanking the list under the pointer.
   *   2. `scrollIntoView({ block: "nearest" })` also scrolls every ancestor scroll port, so a
   *      queue selection would drag the whole rail.
   *   3. The sticky header overlaps the top of the scroll port: a row scrolled flush to
   *      `scrollTop` sits UNDER it. The visible top is the header's lower edge.
   *
   * A row the window has not mounted has no element to measure. That case pages to the row's
   * arithmetic position first; mounting it re-runs this effect, which then refines to nearest.
   */
  const revealTarget = revealId === undefined ? activeId : revealId;
  const revealedRef = useRef<string | null>(null);
  const pagedRef = useRef<string | null>(null);

  useLayoutEffect(() => {
    const scroller = gridRef.current;
    if (!scroller) return;
    if (revealTarget === null || revealTarget === undefined) {
      revealedRef.current = null;
      pagedRef.current = null;
      return;
    }
    if (revealedRef.current === revealTarget) return;

    const el = rowRefs.current.get(revealTarget);
    if (!el) {
      // Not in the DOM. Either the window dropped it, or this corpus holds no such row — and a
      // row that does not exist is not a row we can fail to reveal, so both exit quietly.
      if (pagedRef.current === revealTarget || !windowing) return;
      const index = nodes.findIndex((n) => n.kind === "row" && n.id === revealTarget);
      if (index === -1) return;
      pagedRef.current = revealTarget;
      scroller.scrollTop = Math.max(0, index * windowing.rowHeightPx);
      return;
    }

    revealedRef.current = revealTarget;
    pagedRef.current = null;
    const box = scroller.getBoundingClientRect();
    const top = box.top + (headRef.current?.offsetHeight ?? 0);
    const bottom = box.bottom;
    const row = el.getBoundingClientRect();
    if (row.top >= top && row.bottom <= bottom) return;
    scroller.scrollTop += row.top < top ? row.top - top : row.bottom - bottom;
  }, [revealTarget, nodes, windowing]);

  const move = useCallback(
    (row: number, col: number, keepDesired = false): void => {
      const r = clamp(row, 0, Math.max(0, rows.length - 1));
      const c = clamp(col, 0, Math.max(0, cellsIn(r) - 1));
      if (!keepDesired) desiredCol.current = c;
      userMoved.current = true;
      // An unshifted move re-anchors: the next Shift+Arrow range starts where the user is now.
      anchorRow.current = null;
      setFocusCell({ row: r, col: c });
    },
    [rows.length, cellsIn],
  );

  /**
   * Move the roving cell AND replace the batch with every data row between the anchor and the
   * destination. Shrinking the range back toward the anchor deselects, because a range is the
   * span between two points, not an accumulation of visits.
   */
  const extendTo = useCallback(
    (row: number, col: number): void => {
      const r = clamp(row, 0, Math.max(0, rows.length - 1));
      const c = clamp(col, 0, Math.max(0, cellsIn(r) - 1));
      userMoved.current = true;
      setFocusCell({ row: r, col: c });
      if (!onSelectRange) return;
      if (anchorRow.current === null) anchorRow.current = focusCell.row;
      const a = clamp(anchorRow.current, 0, Math.max(0, rows.length - 1));
      const lo = Math.min(a, r);
      const hi = Math.max(a, r);
      const items: T[] = [];
      const ids: string[] = [];
      for (let i = lo; i <= hi; i += 1) {
        const nav = rows[i];
        if (nav?.kind !== "data") continue;
        items.push(nav.node.item);
        ids.push(nav.node.id);
      }
      onSelectRange(items, ids);
      setAnnouncement(ids.length === 1 ? "1 row selected" : `${ids.length} rows selected`);
    },
    [rows, cellsIn, onSelectRange, focusCell.row],
  );

  const leaveGrid = useCallback((): void => {
    const target = exitFocusRef?.current ?? null;
    if (target) {
      target.focus();
      return;
    }
    const active = document.activeElement;
    if (active instanceof HTMLElement && gridRef.current?.contains(active)) active.blur();
  }, [exitFocusRef]);

  const enterCellMode = useCallback((r: number, c: number): boolean => {
    const el = cellRefs.current.get(cellKey(r, c));
    const inner = el?.querySelector<HTMLElement>("button,a[href],input,select,textarea,[tabindex]");
    if (!inner) return false;
    /* STRUCTURAL GUARD, not a special case for the sort button.
     *
     * This selector takes whatever control a cell happens to hold, and F2 then makes it
     * focusable. Anything hidden from assistive technology must never reach that state: focus
     * would sit on an element with no name, no role and no state (axe `aria-hidden-focus`).
     * Refusing here means a future cell control that is legitimately decorative-and-hidden
     * cannot reintroduce the defect the sort button had — the grid simply does not enter cell
     * mode, and the cell's own Enter behaviour still applies. */
    if (inner.closest('[aria-hidden="true"]') !== null) return false;
    setCellMode(true);
    inner.tabIndex = 0;
    inner.focus();
    return true;
  }, []);

  const exitCellMode = useCallback((r: number, c: number): void => {
    setCellMode(false);
    const el = cellRefs.current.get(cellKey(r, c));
    el?.querySelectorAll<HTMLElement>("[tabindex='0']").forEach((n) => {
      n.tabIndex = -1;
    });
    el?.focus();
  }, []);

  const resizeBy = useCallback(
    (col: GridColumn<T>, delta: number | "reset"): void => {
      if (!onResizeColumn || !col.resizable) return;
      const current = columnWidths?.[col.id];
      const el = cellRefs.current.get(cellKey(0, columns.indexOf(col)));
      const base = current ?? (el ? Math.round(el.getBoundingClientRect().width) : 0);
      if (delta === "reset") {
        onResizeColumn(col.id, 0);
        setAnnouncement(`${col.headerLabel ?? col.header} width reset`);
        return;
      }
      const next = Math.round(clamp(base + delta, col.minPx ?? 32, col.maxPx ?? 640));
      onResizeColumn(col.id, next);
      setAnnouncement(`${col.headerLabel ?? col.header} ${next} pixels`);
    },
    [onResizeColumn, columnWidths, columns],
  );

  const activateRow = useCallback(
    (r: number): void => {
      const row = rows[r];
      if (!row) return;
      if (row.kind === "group") {
        onToggleGroup?.(row.node.id);
        return;
      }
      if (row.kind === "header") {
        const col = columns[focusCell.col];
        /* Only where the control exists for everyone. A clipped header is not a keyboard-only
           back door into sorting a column no pointer user can sort. */
        if (col && hasSortControl(col, onSort)) onSort?.(col.id);
        return;
      }
      onActivate?.(row.node.item, row.node.id);
    },
    [rows, columns, focusCell.col, onActivate, onSort, onToggleGroup],
  );

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    const { row, col } = focusCell;
    const current = rows[row];
    if (!current) return;

    if (cellMode) {
      if (e.key === "Escape" || e.key === "F2") {
        e.preventDefault();
        e.stopPropagation();
        exitCellMode(row, col);
      }
      return;
    }

    const colDef = columns[col];

    switch (e.key) {
      case "ArrowRight":
        e.preventDefault();
        if (e.shiftKey && current.kind === "header" && colDef?.resizable) resizeBy(colDef, RESIZE_STEP_PX);
        else move(row, col + 1);
        return;
      case "ArrowLeft":
        e.preventDefault();
        if (e.shiftKey && current.kind === "header" && colDef?.resizable) resizeBy(colDef, -RESIZE_STEP_PX);
        else move(row, col - 1);
        return;
      case "ArrowDown":
        e.preventDefault();
        if (e.shiftKey && onSelectRange) extendTo(row + 1, desiredCol.current);
        else move(row + 1, desiredCol.current, true);
        return;
      case "ArrowUp":
        e.preventDefault();
        if (e.shiftKey && onSelectRange) extendTo(row - 1, desiredCol.current);
        else move(row - 1, desiredCol.current, true);
        return;
      case "Home":
        e.preventDefault();
        if (e.ctrlKey || e.metaKey) move(0, 0);
        else if (e.shiftKey && current.kind === "header" && colDef?.resizable) resizeBy(colDef, "reset");
        else move(row, 0);
        return;
      case "End":
        e.preventDefault();
        if (e.ctrlKey || e.metaKey) move(rows.length - 1, cellsIn(rows.length - 1) - 1);
        else move(row, cellsIn(row) - 1);
        return;
      case "PageDown": {
        e.preventDefault();
        const step = pageRows(gridRef.current, headRef.current);
        if (e.shiftKey && onSelectRange) extendTo(row + step, desiredCol.current);
        else move(row + step, desiredCol.current, true);
        return;
      }
      case "PageUp": {
        e.preventDefault();
        const step = pageRows(gridRef.current, headRef.current);
        if (e.shiftKey && onSelectRange) extendTo(row - step, desiredCol.current);
        else move(row - step, desiredCol.current, true);
        return;
      }
      case "Enter":
        e.preventDefault();
        if (colDef?.interactive && current.kind === "data" && enterCellMode(row, col)) return;
        activateRow(row);
        return;
      case "F2":
        e.preventDefault();
        enterCellMode(row, col);
        return;
      case " ":
      case "Spacebar":
        e.preventDefault();
        if (e.ctrlKey || e.metaKey) {
          setSelectedCol(col);
          setAnnouncement(`Column ${columns[col]?.headerLabel ?? columns[col]?.header ?? col + 1} selected`);
          return;
        }
        if (e.shiftKey) {
          if (current.kind === "data") {
            // A row toggled by hand becomes the anchor the next Shift+Arrow range grows from.
            anchorRow.current = row;
            onToggleBatch?.(current.node.item, current.node.id);
          }
          return;
        }
        activateRow(row);
        return;
      case "x":
      case "X":
        // Selection without movement: "look at the next one" and "add the next one to my batch"
        // must not be the same gesture.
        if (current.kind === "data" && onToggleBatch) {
          e.preventDefault();
          anchorRow.current = row;
          onToggleBatch(current.node.item, current.node.id);
        }
        return;
      case "a":
      case "A":
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault();
          onSelectAll?.();
        }
        return;
      case "t":
      case "T":
        if (current.kind === "group") {
          e.preventDefault();
          onToggleGroup?.(current.node.id);
        }
        return;
      case "Escape":
        e.preventDefault();
        if (onEscape?.() === true) return;
        leaveGrid();
        return;
      default:
    }
  };

  const win = useRowWindow(nodes.length, gridRef, windowing);

  const setCellRef = (r: number, c: number) => (el: HTMLElement | null) => {
    if (el) cellRefs.current.set(cellKey(r, c), el);
    else cellRefs.current.delete(cellKey(r, c));
  };

  const isFocused = (r: number, c: number): boolean => focusCell.row === r && focusCell.col === c;

  /* Track sizes travel as custom properties so the header row and every data row resolve the same
     template from one place — a second copy of the column widths is a second thing to get wrong. */
  const vars: Record<string, string> = { "--ag-cols": template };
  for (const [id, px] of Object.entries(columnWidths ?? {})) {
    if (px > 0) vars[`--ag-w-${id}`] = `${px}px`;
  }
  const style = vars as CSSProperties;

  const headerCells = columns.map((col, c) => {
    const sorted = sort?.columnId === col.id ? sort.direction : null;
    const SortGlyph = sorted === "asc" ? IconSortAsc : sorted === "desc" ? IconSortDesc : IconSortNone;
    const place = col.headerPlace ?? (layout === "stacked" ? col.place : undefined);
    /* A clipped header holds no control, so it renders none and claims none — but it still STATES
       the sort when this column is the one the grid is ordered by. */
    const sortControl = hasSortControl(col, onSort);
    return (
      <div
        key={col.id}
        ref={setCellRef(0, c)}
        role="columnheader"
        aria-colindex={c + 1}
        /* The name is DECLARED, not computed from the contents.
         *
         * It used to be computed: a `.visually-hidden` span supplied the full label and the sort
         * button was `aria-hidden` so its abbreviated visible text could not join the name. That
         * made the control's AT-invisibility load-bearing for the header's name, and hiding a
         * FOCUSABLE control is a conformance failure in its own right (see the button below).
         * Declaring the name here decouples the two: the button can be properly exposed and
         * named without the header ever becoming "Sort by ID ID". */
        aria-label={col.headerLabel ?? col.header}
        {...(sortControl || sorted
          ? { "aria-sort": sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none" }
          : {})}
        {...(selectedCol === c ? { "aria-selected": true } : {})}
        tabIndex={isFocused(0, c) ? 0 : -1}
        className="ag__cell ag__cell--head"
        data-col={col.id}
        {...(col.headerHidden ? { "data-headhidden": "yes" } : {})}
        data-align={col.align ?? "start"}
        style={place ? { gridArea: place } : undefined}
      >
        {sortControl && onSort ? (
          /* A11Y AUDIT FIX, 2026-09-21 (D2). This button used to carry `aria-hidden="true"`
             permanently while `enterCellMode` raised its tabindex to 0 on F2 — the APG-documented
             way into a widget inside a grid cell. Focus therefore landed on an element with no
             name, no role and no state at the focus location (axe `aria-hidden-focus`, serious;
             the ARIA spec forbids aria-hidden on focusable content outright). Measured by
             `review/_audit_a11y_d3_hidden.mjs`: F2 on the id columnheader gave
             {tag:'BUTTON', cls:'ag__sortbtn', ariaHidden:'true', tabindex:'0'}.

             `aria-hidden` was there to stop the ABBREVIATED visible text joining the header's
             accessible name. That job now belongs to the header's own `aria-label` above, so the
             control can be exposed and named for what it does. `aria-label` on the button
             overrides its contents for the same reason, which is why the visible text no longer
             needs hiding either. The sort STATE is not repeated here: `aria-sort` on the header
             already carries it, and a second copy on the button would be two answers to one
             question. */
          <button
            type="button"
            tabIndex={-1}
            className="ag__sortbtn"
            onClick={() => onSort(col.id)}
            aria-label={`Sort by ${col.headerLabel ?? col.header}`}
          >
            <span className="ag__headtext">{col.header}</span>
            <SortGlyph className="ag__sortglyph" />
          </button>
        ) : (
          <span className="ag__headtext">{col.header}</span>
        )}
        {col.resizable && onResizeColumn ? (
          <ColumnResizer
            column={col}
            widthPx={columnWidths?.[col.id]}
            headerRef={{ current: cellRefs.current.get(cellKey(0, c)) ?? null }}
            onResize={onResizeColumn}
          />
        ) : null}
      </div>
    );
  });

  const visible = nodes.slice(win.start, win.end);

  return (
    <div className={["ag", className].filter(Boolean).join(" ")} data-density={density}>
      <div
        ref={gridRef}
        role="grid"
        aria-label={label}
        aria-rowcount={rows.length}
        aria-colcount={colCount}
        aria-busy={busy || undefined}
        {...(onToggleBatch ? { "aria-multiselectable": true } : {})}
        {...(describedBy ? { "aria-describedby": describedBy } : {})}
        id={gridId}
        className="ag__grid scroll-y"
        style={style}
        onKeyDown={onKeyDown}
        onFocus={(e) => {
          hasFocus.current = true;
          /* Focus can arrive at a cell that is not the roving one — a screen reader moving by
             cell, an assistive script, or any programmatic focus(). If the roving tabindex did
             not follow, the next arrow key would jump the user back to wherever the grid still
             thought they were. The guard against re-entry matters: this handler also fires for
             the focus WE issue after an arrow key, and re-running `move` there would overwrite
             the travelled column that clamping through a group row is meant to restore. */
          const cell = (e.target as HTMLElement).closest<HTMLElement>(
            '[role="gridcell"],[role="rowheader"],[role="columnheader"]',
          );
          if (!cell) return;
          const r = Number(cell.closest('[role="row"]')?.getAttribute("aria-rowindex") ?? Number.NaN) - 1;
          const c = Number(cell.getAttribute("aria-colindex") ?? Number.NaN) - 1;
          if (!Number.isInteger(r) || !Number.isInteger(c)) return;
          if (r === focusCell.row && c === focusCell.col) return;
          move(r, c);
        }}
        onBlur={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) hasFocus.current = false;
        }}
      >
        <div role="rowgroup" className="ag__head" ref={headRef}>
          <div role="row" aria-rowindex={1} className="ag__row ag__row--head">
            {headerCells}
          </div>
        </div>

        <div role="rowgroup" className="ag__body">
          {win.padTop > 0 ? <div role="presentation" style={{ height: `${win.padTop}px` }} /> : null}
          {visible.map((node, i) => {
            const r = win.start + i + 1;
            if (node.kind === "group") {
              return (
                <div
                  key={`g:${node.id}`}
                  role="row"
                  aria-rowindex={r + 1}
                  aria-expanded={!node.collapsed}
                  className="ag__row ag__row--group"
                >
                  <div
                    ref={setCellRef(r, 0)}
                    role="gridcell"
                    aria-colindex={1}
                    aria-colspan={colCount}
                    tabIndex={isFocused(r, 0) ? 0 : -1}
                    className="ag__cell ag__groupcell"
                    onClick={() => {
                      move(r, 0);
                      onToggleGroup?.(node.id);
                    }}
                  >
                    {node.collapsed ? (
                      <IconChevronRight className="ag__groupchevron" />
                    ) : (
                      <IconChevronDown className="ag__groupchevron" />
                    )}
                    <span className="ag__grouplabel" data-observed={node.observed ? "yes" : "no"}>
                      {node.label}
                    </span>
                    <span className="ag__groupcount">{node.count}</span>
                    {node.detail ? <span className="ag__groupdetail">{node.detail}</span> : null}
                  </div>
                </div>
              );
            }
            const selected = batchIds?.has(node.id) ?? false;
            return (
              <div
                key={node.id}
                role="row"
                ref={(el) => {
                  if (el) rowRefs.current.set(node.id, el);
                  else rowRefs.current.delete(node.id);
                }}
                aria-rowindex={r + 1}
                {...(onToggleBatch ? { "aria-selected": selected } : {})}
                /* A11Y AUDIT FIX, 2026-09-21 (D2). `aria-selected` on these rows is spoken for by
                   the BATCH (`x` / Shift+Space), so the row the app itself calls "the selection"
                   had no programmatic state at all: the active row read
                   {data-active:'yes', aria-selected:'false'} and a screen reader was told nothing
                   was selected. The live region announced "Selected finding F002." once and then
                   the fact was gone — an announcement is not a determinable state.

                   `aria-current` is exactly the "current item within a set" semantic, and it is a
                   different attribute from `aria-selected`, so the two states coexist instead of
                   competing: a row can be the current one, batched, both, or neither, and each is
                   readable on its own. */
                {...(activeId === node.id ? { "aria-current": true } : {})}
                className="ag__row ag__row--data"
                data-active={activeId === node.id ? "yes" : undefined}
                data-related={relatedIds?.has(node.id) ? "yes" : undefined}
                data-batched={selected ? "yes" : undefined}
                /* The ROW owns activation, not the cell.
                 *
                 * It used to be the cell, and that left the row's centre strip dead to the mouse:
                 * `.ag__row` is a grid with `column-gap: var(--sp-2)` and `padding-inline`, so the
                 * gaps between cells and the two end margins are inside the row's hover highlight
                 * but outside every cell. Measured 2026-09-21 on the release build: clicking each
                 * of the six cells of a data row set `?f=F004` and re-aimed the evidence pane;
                 * clicking the same row's geometric centre left the URL unchanged and
                 * `aria-selected` at "false" — the row lit up under the pointer and then did
                 * nothing. A reader dragging down a dense list hits those gaps constantly.
                 *
                 * Hanging the handler here makes the hit area the same shape as the hover
                 * affordance, which is the honest arrangement: what looks clickable is clickable.
                 * Cells that own a control stop the click below this. */
                onClick={(e) => {
                  const inCell =
                    e.target instanceof Element &&
                    e.target.closest('[role="gridcell"],[role="rowheader"]') !== null;
                  // A gap click moved no cell: put the roving focus on the row the reader aimed
                  // at, keeping the column they were already navigating in.
                  if (!inCell) move(r, desiredCol.current, true);
                  onActivate?.(node.item, node.id);
                }}
              >
                {columns.map((col, c) => {
                  const place = layout === "stacked" ? col.place : undefined;
                  return (
                    <div
                      key={col.id}
                      ref={setCellRef(r, c)}
                      role={col.rowHeader ? "rowheader" : "gridcell"}
                      aria-colindex={c + 1}
                      {...(selectedCol === c ? { "aria-selected": true } : {})}
                      tabIndex={isFocused(r, c) ? 0 : -1}
                      className="ag__cell"
                      data-col={col.id}
                      data-align={col.align ?? "start"}
                      style={place ? { gridArea: place } : undefined}
                      onClick={(e) => {
                        move(r, c);
                        // A cell holding its own control must not double-fire: the control's own
                        // click handler already ran and stopped here. Stop the click before the
                        // row sees it, since the row is what activates now.
                        if (col.interactive) e.stopPropagation();
                      }}
                    >
                      {cellContent(col, node.item)}
                    </div>
                  );
                })}
              </div>
            );
          })}
          {win.padBottom > 0 ? <div role="presentation" style={{ height: `${win.padBottom}px` }} /> : null}
        </div>
      </div>
      {/* The empty state sits OUTSIDE the grid. A fabricated row would put a count in
          aria-rowcount that no data backs, which is the same lie as a blank cell. */}
      {nodes.length === 0 && empty ? <div className="ag__empty">{empty}</div> : null}
      <LiveRegion message={announcement} />
    </div>
  );
}

/* ── column resizer ─────────────────────────────────────────────────────────── */

/**
 * WCAG 2.5.7: the drag has a pointer-free twin. The handle is not a tab stop — the header cell
 * owns Shift+Arrow / Shift+Home for the same operation, so resizing costs no extra Tab presses in
 * a grid where the whole point is that there is exactly one.
 */
function ColumnResizer<T>({
  column,
  widthPx,
  headerRef,
  onResize,
}: {
  column: GridColumn<T>;
  widthPx: number | undefined;
  headerRef: { current: HTMLElement | null };
  onResize: (columnId: string, px: number) => void;
}): ReactNode {
  const drag = useRef<{ startX: number; startW: number } | null>(null);

  const onPointerDown = (e: ReactPointerEvent<HTMLSpanElement>): void => {
    const start = widthPx ?? Math.round(headerRef.current?.getBoundingClientRect().width ?? 0);
    drag.current = { startX: e.clientX, startW: start };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLSpanElement>): void => {
    const d = drag.current;
    if (!d) return;
    onResize(column.id, Math.round(clamp(d.startW + (e.clientX - d.startX), column.minPx ?? 32, column.maxPx ?? 640)));
  };
  const onPointerUp = (e: ReactPointerEvent<HTMLSpanElement>): void => {
    drag.current = null;
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  return (
    <span
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${column.headerLabel ?? column.header}`}
      className="ag__resizer"
      tabIndex={-1}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onDoubleClick={() => onResize(column.id, 0)}
    />
  );
}
