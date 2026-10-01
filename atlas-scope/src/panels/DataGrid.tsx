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
  Component,
  memo,
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
import { returnFocus } from "../app/focus-return";
import "./DataGrid.css";
import { own } from "../core/own";

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
  /** The cell holds its own focusable control, so Enter / F2 step INTO it instead of activating.
   *  A cell whose ONLY control is a button is operated directly: Enter presses it, no widget mode. */
  interactive?: boolean;
  /** The cell holds exactly ONE control and nothing else of its own (a lone icon button). APG:
   *  "when a cell contains a single widget, focus the widget" — so the roving tabindex lands on the
   *  control itself, and the cell carries neither a tabindex nor a duplicate of the control's
   *  name. The renderer receives the tabindex to put on the control (`render`'s second argument).
   *  Measured before (A11Y critic, D2): End on a row focused the gridcell DIV, whose inner button
   *  sat at tabindex=-1 with the same aria-label — two elements, one name, focus on the wrong one. */
  soleControl?: boolean;
  /** Accessible name for a cell that has no text of its own (a lone icon button). Without it the
   *  focused cell announces nothing until the reader steps into its widget (A11Y critic, D2). */
  cellLabel?: (item: T) => string;
  /** What a null renderer result means, for the NotObserved sentence. */
  unobservedWhat?: string;
  /** `cell.tabIndex` is the roving tabindex for a `soleControl` column's control (0 when this cell
   *  is the grid's tab stop, else -1). Other columns can ignore it. */
  render: (item: T, cell: { tabIndex: 0 | -1 }) => ReactNode;
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
  | {
      kind: "row";
      id: string;
      item: T;
      /**
       * The row's React identity when `id` is not unique in `nodes`: grouping by a multi-valued key
       * (a finding on several hosts) puts the same item under several groups, and keying each copy
       * by `id` alone collides. Absent means `id` is already unique.
       */
      key?: string;
    };

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
   * Identity of the whole shared selection (finding, device, link, hop). A change re-runs the
   * reveal even when `revealId` itself is unchanged: A4 counts selecting a device, a link or a hop
   * as a selection change, and re-aiming the queue on one means the selected row is in view.
   * Compared by value; omit it and only a `revealId` change re-aims.
   */
  revealKey?: string;
  /**
   * Rows ANY ONE of which already answers the reveal. When one of them is fully inside the visible
   * band of the scroll port (below the sticky header, inside every clip) the reveal does nothing:
   * the reader is already looking at an answer, and moving the list would throw their place away.
   *
   * For a reveal whose target is a representative of a set rather than the selection itself — the
   * queue with no finding selected reveals the FIRST row naming the picked device, but every row
   * naming it answers "what names this box". Measured without it (A4, 1920x1080, `?s=queue`): the
   * reader at scrollTop 3200 with F060 and F069 (both naming access13) on screen picked access13
   * and was thrown to 0, where F002 is. Omit it for a reveal of the selection itself.
   */
  revealUnlessVisible?: ReadonlySet<string>;
  /**
   * Identity of the reader's ACT — the selection as it stands the moment they make it, before any
   * deferred render catches up. When it changes, the grid records which rows the reader could see
   * BEFORE that commit touches the DOM (`getSnapshotBeforeUpdate`), and every "is it already on
   * screen?" decision the resulting reveal takes (`revealUnlessVisible`, a multi-copy target) also
   * accepts a row that was fully visible then, and brings it back by the least movement if the
   * layout has since moved it.
   *
   * Why: those decisions are taken against the layout, and the act itself moves the layout before
   * they run. MEASURED (A4, 1920x1080, no finding): F099 — the only visible row naming access13 —
   * sat at 999-1041 in a port of 352-1054 at scrollTop 4777. The canvas pick's URGENT render put
   * "19 of 146 shown findings name access13 — marking the rows." above the grid, moving the port's
   * top to 389.7; the DEFERRED reveal then found F099 38 px under the bottom edge and threw the list
   * to 0. Any content the act adds above the grid (a re-worded, re-wrapped sentence on a
   * device-to-device switch, a note on Back) does the same, so the decision is taken against what
   * the reader saw when they acted, not against whatever the act has since done to the layout.
   * The record is dropped as soon as the reader touches the grid or scrolls it: their newer view
   * is then the one that counts. Omit it and only the live layout is consulted.
   */
  actKey?: string;
  /**
   * Rows related to a selection this corpus cannot hold as a row of its own — the findings that
   * name the selected device or the endpoints of the selected cable.
   *
   * Marked, never filtered. Hiding the rest would make the queue answer "what is wrong with this
   * box" while still calling itself the fleet punchlist, and the reader would have no way to see
   * that the corpus had narrowed under them.
   */
  relatedIds?: ReadonlySet<string>;
  /**
   * What a row in `relatedIds` IS related to, in words — e.g. "names the selected device core1".
   *
   * The trailing-edge mark is visual only; without this the relation reached assistive technology
   * solely as a count sentence, and a reader on a row had to infer it from the host text inside the
   * row (A11Y critic, D8). Exposed per related row as `aria-description`, and folded into the row
   * header's accessible text so screen readers that ignore `aria-description` still hear it when
   * they announce the row header on a row change.
   */
  relatedDescription?: string;
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
  /**
   * How the rows are ordered, in words, whatever put them in that order.
   *
   * `aria-sort` can only state an order that IS a single column. A caller whose default order is a
   * composite ranking (severity, then priority, then rank) leaves every header at
   * `aria-sort="none"`, which tells a screen-reader user nothing about the order in front of them
   * (A11Y critic, D2). The grid renders this sentence as its own visually-hidden description and
   * appends it to `aria-describedby`, so the order is always determinable from the grid itself.
   */
  orderDescription?: string;
  /**
   * True while the row set the grid is showing is KNOWN TO BE OUT OF DATE — the query has moved on
   * and the filter has not caught up yet. Rendered as `aria-busy` on the grid.
   *
   * E5 AUDIT FIX, 2026-09-21. This prop existed and nothing outside the tests ever passed it true,
   * so `aria-busy` was dead code: the query recompute that the E5 sweep measures at 233-396 ms was
   * silent to assistive technology as well as invisible. A guard exercised only where it is inert
   * is not a guard. `PriorityQueue` now passes it for its debounce window — the one interval in
   * which the rows on screen answer a question the user has already changed.
   */
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
  /* A "page" is what the reader can SEE, not the grid's own box. MEASURED (critic, 2026-09-22): at
     577x630 and 400x800 the grid is not its own scroll port — it lays out at its full 5,008 px and
     an ancestor (or the window) scrolls it — so clientHeight counted every row and one PageDown
     jumped from row 3 to row 152, off-screen. The band is the same predicate the reveal uses: the
     grid's box below the sticky header, intersected with every clip and the viewport. */
  const band = visibleBand(scroller, head);
  const portH = band.bottom - band.top;
  if (rowH < 1 || portH < 1) return PAGE_ROWS_FALLBACK;
  return Math.max(1, Math.floor(portH / rowH) - 1);
};

const RESIZE_STEP_PX = 8;

const clamp = (n: number, lo: number, hi: number): number => (n < lo ? lo : n > hi ? hi : n);

/** What counts as a cell's control — the same set `enterCellMode` steps into. */
const SOLE_CONTROL_SELECTOR = "button,a[href],input,select,textarea";

/** A renderer that produced nothing is an absence, not an empty cell. */
const cellContent = <T,>(col: GridColumn<T>, item: T, tabIndex: 0 | -1 = -1): ReactNode => {
  const out = col.render(item, { tabIndex });
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

/**
 * Scroll `scroller` the least distance that puts `el` fully inside the part of the scroll port
 * the sticky header does not cover. NEAREST semantics, arithmetic rather than `scrollIntoView`
 * (which also scrolls every ancestor and ignores the header). An element inside the header itself
 * is always visible, so it never scrolls.
 */
export function revealBelowHeader(
  scroller: HTMLElement,
  head: HTMLElement | null,
  el: HTMLElement,
  align: "nearest" | "centre" = "nearest",
  /** False: the remainder may scroll the grid's scrolling ANCESTORS but never the document (see
   *  `revealThroughAncestors`). */
  page = true,
): void {
  let off = offsetFromView(scroller, head, el);
  if (off === 0) return;
  /* NESTED PORTS: when the grid's OWN port already shows the row and only an outer clip hides it,
     the outer scroller is the one to move — scrolling the grid instead aims the row at a band that
     may be shorter than the row. MEASURED (A4, repair wave 8, 1920x1080): the path panel grew above
     the queue inside rail A and left the grid's visible band at 1042-1054 (12 px) with F026 at
     1141-1197 inside the grid's own box; a grid-first reveal cannot fit a 56 px row in 12 px, while
     scrolling the rail by 143 px shows it whole. Element ancestors only here; whatever is left falls
     through to the grid-first reveal below, exactly as before.
     FITS FIRST (C2, 2026-09-26): that reason is the predicate. The outer scroller carries everything
     else in it — at 1440x900 Rail A carries the path panel — so it moves first ONLY when the grid's
     own visible band cannot hold the row. MEASURED (acceptance report C2, 1440x900, state 06): F001
     (40.4 px) slid 19 px below a 51.3 px band; moving the rail instead of the grid cut the path
     panel's tab strip to 13 of its 32 px ("Trace a flow" visibleFrac 0.406), where scrolling the
     grid 20 px showed F001 whole with the rail left at 0. */
  if (isOwnPort(scroller) && ownPortShows(scroller, head, el) && !bandHoldsRow(scroller, head, el)) {
    revealThroughAncestors(scroller, head, el, false);
    off = offsetFromView(scroller, head, el);
    if (off === 0) return;
  }
  if (align === "nearest") {
    /* Rounded AWAY from the row, never to nearest: rows sit on fractional pixels (F099 at
       999.25-1040.63) while the browser snaps scrollTop to device pixels, so `+= 37.7` landed
       0.3 px short — a row that still failed this very predicate, which the hold then answered by
       CENTRING it. MEASURED (A4, 1920x1080, dev build): a 38 px restore became a 322 px throw. */
    const target = scroller.scrollTop + off;
    scroller.scrollTop = off > 0 ? Math.ceil(target) : Math.floor(target);
    revealThroughAncestors(scroller, head, el, page);
    return;
  }
  /* "centre" — for a SELECTION reveal (not keyboard focus, which stays nearest so an arrow key moves
     the list by one row). Measured (A1, 2026-09-21 critic): a nearest reveal left the selected F099
     row flush on the grid's bottom edge (row 1021-1054, grid 787-1054), where any resize of the
     panel above pushed it back out. A row that must be scrolled to is brought to the middle of the
     visible part of the port instead; a row already fully visible still does not move (off === 0). */
  const { top, bottom } = visibleBand(scroller, head && !head.contains(el) ? head : null);
  const row = (el.closest<HTMLElement>('[role="row"]') ?? el).getBoundingClientRect();
  const delta = row.top + row.height / 2 - (top + bottom) / 2;
  scroller.scrollTop = Math.max(0, scroller.scrollTop + delta);
  revealThroughAncestors(scroller, head, el, page);
}

/** The grid scrolls its own rows (every desktop layout); narrow layouts lay it out at full height. */
function isOwnPort(scroller: HTMLElement): boolean {
  return scroller.scrollHeight > scroller.clientHeight + 1;
}

/** Is `el`'s row wholly inside the grid's own box below its sticky header — ignoring every clip and
 *  overlay outside the grid? */
function ownPortShows(scroller: HTMLElement, head: HTMLElement | null, el: HTMLElement): boolean {
  if (head?.contains(el)) return false;
  const box = scroller.getBoundingClientRect();
  const top = head ? Math.max(box.top, head.getBoundingClientRect().bottom) : box.top;
  const row = (el.closest<HTMLElement>('[role="row"]') ?? el).getBoundingClientRect();
  return row.height > 0 && row.top >= top - 0.5 && row.bottom <= box.bottom + 0.5;
}

/**
 * Can the grid show `el`'s row WHOLE by scrolling only itself? True when the part of the grid the
 * reader can see (below the sticky header, inside every clip, past every overlay — `visibleBand`
 * without its layout-box fallback) is at least as tall as the row, with a pixel to spare for the
 * device-pixel snap of scrollTop (see the "rounded AWAY" note in `revealBelowHeader`).
 *
 * An EMPTY band does not reach this test. When an ancestor has scrolled the grid wholly out of view,
 * `offsetFromView` measures against `visibleBand`'s layout-box fallback, so a row the grid's own port
 * shows reads as 0 and `revealBelowHeader` returns first; one it does not show is scrolled into the
 * grid's own port, and the ancestor walk again reads 0. Either way the carrier is left where it is —
 * the A4 design (probe-a4-surface-switch.mjs: "QUEUE OFF SCREEN" is reported, not revealed, because a
 * surface switch put another panel in the rail) — and the row waits in the grid's own port for the
 * carrier to bring the grid back. Only a sub-pixel disagreement between `ownPortShows`' half-pixel
 * slack and the fallback band's exact edge could arrive here with an empty band; it returns false, and
 * the ancestor walk then moves the carrier by that sub-pixel remainder at most. Pinned by
 * DataGrid.c2-chrome-slice.test.tsx ("a grid its carrier scrolled wholly out of view ...").
 */
function bandHoldsRow(scroller: HTMLElement, head: HTMLElement | null, el: HTMLElement): boolean {
  const band = clippedBand(scroller, head && !head.contains(el) ? head : null);
  const row = (el.closest<HTMLElement>('[role="row"]') ?? el).getBoundingClientRect();
  return row.height > 0 && band.bottom - band.top >= row.height + 1;
}

/**
 * NAVIGATION IS WHOLE OR ABSENT (C2). The composite widgets a reader steers a region by: a strip of
 * tabs, a toolbar, a menu bar. Named by ARIA role — the platform's own definition of the class — not
 * by panel, so a strip any future panel adds is covered without being listed here.
 */
const NAV_STRIP_SELECTOR = '[role="tablist"],[role="toolbar"],[role="menubar"]';

interface NavStrip {
  el: HTMLElement;
  height: number;
  /** Wholly on screen before the scroll: the only strips a scroll can newly cut. */
  whole: boolean;
}

/** Every navigation strip in `root` that a scroll of `root` could carry, outside the grid. */
function navStripsIn(root: ParentNode, scroller: HTMLElement): NavStrip[] {
  const out: NavStrip[] = [];
  for (const strip of root.querySelectorAll<HTMLElement>(NAV_STRIP_SELECTOR)) {
    if (scroller.contains(strip) || strip.contains(scroller)) continue;
    const height = strip.getBoundingClientRect().height;
    if (height <= 0) continue;
    out.push({ el: strip, height, whole: onScreenExtent(strip) >= height - 0.5 });
  }
  return out;
}

/** The first strip that was whole before the scroll and is now only PARTLY on screen, with how much
 *  of it the reader still sees. A strip scrolled wholly away is absent, not cut. */
function cutStrip(strips: readonly NavStrip[]): { strip: NavStrip; seen: number } | null {
  for (const strip of strips) {
    if (!strip.whole) continue;
    const seen = onScreenExtent(strip.el);
    if (seen > 0.5 && seen < strip.height - 0.5) return { strip, seen };
  }
  return null;
}

/**
 * The ancestor (or document) half of a reveal has just moved a scroller by `moved` px; make sure it
 * did not leave a navigation strip that was whole PARTLY visible. MEASURED (acceptance report C2,
 * 1440x900): the queue's act-view restore scrolled Rail A 19 px and left the path panel's tab strip
 * 13 of 32 px on screen — "a primary control sliced in half". A sticky strip does not move with its
 * scroller and is never newly cut, so it never engages this.
 *
 * Two ways out, tried in order:
 *   1. TAKE IT OUT: move on, in the same direction, by what is still visible of the strip — the
 *      strip leaves whole — provided the row being revealed ends at least as visible as the scroll
 *      left it (everything in this scroller moves together, so it normally does).
 *   2. KEEP IT WHOLE: otherwise (the scroller cannot move that far, or the row would be lost) move
 *      back by what is hidden of the strip, never past where the scroll started. The row is then
 *      revealed as far as the strip allows, and whatever is left is handed to the next ancestor.
 * `move(dy)` scrolls and returns the distance actually moved (scroll ranges clamp).
 */
function keepNavWhole(
  strips: readonly NavStrip[],
  moved: number,
  move: (dy: number) => number,
  rowOff: () => number,
): void {
  if (moved === 0 || strips.length === 0) return;
  const dir = Math.sign(moved);
  let cut = cutStrip(strips);
  if (cut === null) return;
  const offBefore = Math.abs(rowOff());
  let pushed = 0;
  for (let i = 0; i < 4 && cut !== null; i += 1) {
    const step = move(dir * Math.ceil(cut.seen));
    pushed += step;
    if (step === 0) break;
    cut = cutStrip(strips);
  }
  if (cut === null && Math.abs(rowOff()) <= offBefore + 0.5) return;
  move(-pushed);
  let total = moved;
  cut = cutStrip(strips);
  for (let i = 0; i < 4 && cut !== null && total !== 0; i += 1) {
    const back = -dir * Math.min(Math.abs(total), Math.ceil(cut.strip.height - cut.seen));
    const step = move(back);
    total += step;
    if (step === 0) break;
    cut = cutStrip(strips);
  }
}

/**
 * The remainder of a reveal the grid could not absorb itself. When the grid is its own scroll port
 * (every desktop layout) the adjustment above already made the row visible and this is a no-op.
 * When it is NOT — narrow layouts where the grid lays out at full height inside a scrolling rail or
 * the page (measured 577x630, 400x800) — `scroller.scrollTop +=` moves nothing, and the focused
 * row stayed thousands of px off-screen. The leftover distance is handed to the nearest scrolling
 * ancestors, innermost first, then the document: the least movement that puts the row in view.
 *
 * Those ancestors also carry whatever ELSE the reader is looking at, so this half of a reveal yields
 * to the reader's focus: a scroll that leaves less of the focused element (outside the grid) on
 * screen than before is undone, and the walk stops there. MEASURED (390x844, 2026-09-25): Enter on
 * the Evidence pane's "F002 …" button moved focus to the pane's new title, on screen at scrollY
 * 14 080; the queue's selection reveal then scrolled the document by -5 017 px to show the F002
 * row and left the focused title at top 5 383 — off screen (`audit-d3-focus.mjs --self-removing`,
 * 24 phone FAILs). Measured rather than predicted, so a focused element the scroll does not move
 * (a fixed or sticky bar) does not block the reveal. Focus inside the grid is the row being
 * revealed or its neighbour, and focus on <body> has nothing to lose, so neither restrains it.
 */
function revealThroughAncestors(scroller: HTMLElement, head: HTMLElement | null, el: HTMLElement, page = true): void {
  let rest = offsetFromView(scroller, head, el);
  if (rest === 0) return;
  const doc = scroller.ownerDocument;
  const view = doc.defaultView;
  if (!view) return;
  const active = doc.activeElement;
  const guarded =
    active instanceof view.HTMLElement && active !== doc.body && active !== doc.documentElement && !scroller.contains(active) ? active : null;
  const seen = guarded === null ? 0 : onScreenExtent(guarded);
  /** False when the scroll just made cost the reader some of their focused element. */
  const keepsFocus = (): boolean => guarded === null || seen <= 0 || onScreenExtent(guarded) >= seen - 0.5;
  const rowOff = (): number => offsetFromView(scroller, head, el);
  for (let a = scroller.parentElement; a !== null && rest !== 0; a = a.parentElement) {
    const oy = view.getComputedStyle(a).overflowY;
    if ((oy !== "auto" && oy !== "scroll") || a.scrollHeight <= a.clientHeight) continue;
    const port = a;
    const strips = navStripsIn(port, scroller);
    const before = port.scrollTop;
    port.scrollTop = before + rest;
    keepNavWhole(
      strips,
      port.scrollTop - before,
      (dy) => {
        const b = port.scrollTop;
        port.scrollTop = b + dy;
        return port.scrollTop - b;
      },
      rowOff,
    );
    if (!keepsFocus()) {
      port.scrollTop = before;
      return;
    }
    /* What this scroller did not absorb goes outward — never MORE than was asked, in either
       direction. keepNavWhole's take-out may move past the remainder (the row is then revealed with
       the strip wholly out of view); subtracting that overshoot left a remainder of the opposite
       sign, and the next scroller out (the document, at the full-height shape) scrolled BACK by it.
       MEASURED (C2 verifier V2, model): rail 16 px -> 32 px, then scrollY 500 -> 484. */
    const left = rest - (port.scrollTop - before);
    rest = Math.sign(left) === Math.sign(rest) ? left : 0;
  }
  if (rest === 0 || !page) return;
  const strips = navStripsIn(doc, scroller);
  const y0 = view.scrollY;
  view.scrollBy(0, rest);
  keepNavWhole(
    strips,
    view.scrollY - y0,
    (dy) => {
      const b = view.scrollY;
      view.scrollBy(0, dy);
      return view.scrollY - b;
    },
    rowOff,
  );
  if (!keepsFocus()) view.scrollBy(0, y0 - view.scrollY);
}

/**
 * How many px of `el`'s height the reader can see: what it can paint (`paintedBox`: its box inside the
 * viewport and every clipping ancestor on its containing-block chain), then past everything PAINTED
 * OVER it (`uncovered`). 0 in jsdom, which lays nothing out.
 *
 * Overlays count as a cut exactly as a clip does (C2 verifier m3): below 48rem the status bar is
 * `position: sticky; bottom: 0` (85 px at 390x844, measured D3 wave 8), and a strip a reveal slid
 * partly under it read as whole here while the reader saw it sliced — so `keepNavWhole` left it cut.
 * This measure is also run in the real page by `review/capture.mjs` (text and app modes) against a
 * per-pixel paint census of every navigation strip, so a misread in the product fails a capture.
 */
function onScreenExtent(el: HTMLElement): number {
  const doc = el.ownerDocument;
  const view = doc.defaultView;
  const r = el.getBoundingClientRect();
  if (!view || r.height <= 0 || view.innerHeight <= 0) return 0;
  let { top, bottom } = paintedBox(el);
  if (bottom <= top) return 0;
  ({ top, bottom } = uncovered(el, doc, r, top, bottom));
  return Math.max(0, bottom - top);
}

/**
 * The vertical part of `el`'s box the browser can PAINT: its border box intersected with the viewport
 * and with every ancestor whose overflow clips it (the root element's clip is the viewport, and a
 * <body> whose overflow the root does not claim propagates to the viewport too, as in `clippedBand`).
 * Only ancestors on its CONTAINING-BLOCK chain clip it: an absolutely positioned box escapes the clip
 * of a static ancestor between it and its positioned container, and a fixed one every ancestor up to
 * one that contains fixed descendants (a transform, filter, perspective or paint/layout containment).
 * So a fixed bar inside a scrolling rail is not trimmed by the rail it floats over. May be empty
 * (bottom <= top): the element paints nothing on screen. jsdom lays out nothing (0-height boxes are
 * not clips there).
 */
function paintedBox(el: Element): { top: number; bottom: number } {
  const doc = el.ownerDocument;
  const view = doc.defaultView;
  const r = el.getBoundingClientRect();
  let top = r.top;
  let bottom = r.bottom;
  if (!view) return { top, bottom };
  if (view.innerHeight > 0) {
    top = Math.max(top, 0);
    bottom = Math.min(bottom, view.innerHeight);
  }
  const holdsFixed = (cs: CSSStyleDeclaration): boolean =>
    (cs.transform !== "" && cs.transform !== "none") ||
    (cs.filter !== "" && cs.filter !== "none") ||
    (cs.perspective !== "" && cs.perspective !== "none") ||
    /\b(?:paint|layout|strict|content)\b/.test(cs.contain) ||
    /\b(?:transform|perspective|filter)\b/.test(cs.willChange);
  const escapeOf = (cs: CSSStyleDeclaration): "fixed" | "absolute" | "flow" =>
    cs.position === "fixed" ? "fixed" : cs.position === "absolute" ? "absolute" : "flow";
  const rootOy = view.getComputedStyle(doc.documentElement).overflowY;
  let escape = escapeOf(view.getComputedStyle(el));
  for (let a = el.parentElement; a !== null && bottom > top; a = a.parentElement) {
    if (a === doc.documentElement) break;
    const cs = view.getComputedStyle(a);
    const contains =
      escape === "flow" || holdsFixed(cs) || (escape === "absolute" && cs.position !== "" && cs.position !== "static");
    if (!contains) continue;
    escape = escapeOf(cs);
    if (a === doc.body && (rootOy === "visible" || rootOy === "")) continue;
    if (cs.overflowY === "visible" || cs.overflowY === "") continue;
    const c = a.getBoundingClientRect();
    if (c.height <= 0) continue;
    top = Math.max(top, c.top);
    bottom = Math.min(bottom, c.bottom);
  }
  return { top, bottom };
}

/**
 * The part of `[top, bottom]` (already inside every clip) that nothing paints over at `el`'s
 * horizontal centre: the browser's hit-test stack at each edge, down to `el` (or an element that
 * holds it), is what covers it there. Unlike `trimOverlays` — whose band is a whole grid, which one
 * box rarely covers — an element's extent is often SMALLER than the bar over it, so a cover that
 * reaches past the far edge leaves nothing: the element is absent, not whole. Repeated a few times
 * because the first hit can be a child of the overlay whose box starts inside the overlay's padding.
 * Where hit testing is not available (jsdom), the extent is unchanged.
 *
 * A hit is a cover only where it PAINTS: its box inside its own clip chain (`paintedBox`), and only
 * if that box holds the probe point. The stack alone is not evidence. MEASURED (R9 verifier V1,
 * release build, state 06, 1440x900): half a pixel inside the bottom edge of the path panel's mode
 * strip (84-117), Chrome's stack began with the content of the scrolled `.pt-panel` below it —
 * `div.hop__fact 116.81-243.69`, then `div.hop__fact -159.19-116.81`, a box that panel scrolled away and
 * clips. Taken by its layout box, the second "covered" the whole strip: a strip the reader saw whole
 * read as 0 px, so `navStripsIn` marked it not whole and `keepNavWhole` stopped protecting it — at
 * every width from 768. Probes sit a pixel inside the edge as well (as `trimOverlays`' do): on the
 * measured shapes the misanswer covers less than the strip's last pixel row (up to 0.95 px inside on a
 * capture.mjs selftest fixture of that shape), so the inset clears it today — but how deep it reaches
 * is the hit test's business, so the inset is not what is relied on.
 */
function uncovered(el: HTMLElement, doc: Document, box: DOMRect, top: number, bottom: number): { top: number; bottom: number } {
  const stack = typeof doc.elementsFromPoint === "function";
  if (!stack && typeof doc.elementFromPoint !== "function") return { top, bottom };
  const view = doc.defaultView;
  const maxX = view && view.innerWidth > 0 ? view.innerWidth - 1 : box.right;
  const x = Math.min(Math.max((Math.max(box.left, 0) + Math.min(box.right, maxX)) / 2, 0), maxX);
  const coversAt = (y: number): { top: number; bottom: number }[] => {
    const hits = stack ? doc.elementsFromPoint(x, y) : [doc.elementFromPoint(x, y)];
    const out: { top: number; bottom: number }[] = [];
    for (const hit of hits) {
      if (hit === null || el.contains(hit) || hit.contains(el)) break;
      const layout = hit.getBoundingClientRect();
      if (y < layout.top || y > layout.bottom) continue; // a clip only shrinks it: it paints nothing here
      const painted = paintedBox(hit);
      if (painted.bottom > painted.top && y >= painted.top && y <= painted.bottom) out.push(painted);
    }
    return out;
  };
  /* A probe a pixel inside the edge (never past the middle of a sliver). */
  const inset = (): number => Math.min(1, (bottom - top) / 2);
  /* A COVER THE HIT TEST CANNOT SEE IS STILL A COVER (R9 verifier m3; owner requirement: pointer-events:none overlays
     are counted by this guard). A positioned box with `pointer-events: none` — a translucent fixed bar, App.css's
     opaque `.stage-warmup` — is skipped by elementsFromPoint, so a strip half under one read as whole here while the
     reader saw it sliced (review/capture.mjs selftest: "Mode" read 32 px, painted 12). For the duration of the probes
     every element takes part in hit testing — one sheet, removed in `finally`, synchronously, so nothing is painted,
     laid out or dispatched in between — and the stack IS the paint order: the census's own technique
     (capture.mjs `readScrollEdge`), now in the product. */
  const hitAll = doc.createElement("style");
  hitAll.textContent = "*, *::before, *::after { pointer-events: auto !important; }";
  (doc.head ?? doc.documentElement).appendChild(hitAll);
  try {
    for (let i = 0; i < 4 && bottom > top; i += 1) {
      let next = bottom;
      for (const c of coversAt(bottom - inset())) if (c.top < next) next = Math.max(top, c.top);
      if (next >= bottom) break;
      bottom = next;
    }
    for (let i = 0; i < 4 && bottom > top; i += 1) {
      let next = top;
      for (const c of coversAt(top + inset())) if (c.bottom > next) next = Math.min(bottom, c.bottom);
      if (next <= top) break;
      top = next;
    }
  } finally {
    hitAll.remove();
  }
  return { top, bottom: Math.max(top, bottom) };
}

/**
 * The vertical band of `scroller` a reader can actually SEE: its own box, below the sticky header,
 * intersected with every clipping ancestor and the viewport.
 *
 * Why not the scroller's box alone: that box is where the grid is laid out, not what is on screen.
 * Measured (2026-09-22 capability audit, A4): with the Path panel open at 1920x1080 the grid's box
 * ran to y=1091 while the frame clipped at 1080 and the status bar covered 1054-1080, so a row
 * "revealed" at 1060 passed this predicate while sitting under the chrome. The layout no longer
 * overflows (shell.css), but when a rail is too short for both floors it scrolls and clips the grid
 * instead — and the predicate must answer for THAT box, whatever clips it, not for one layout.
 */
function visibleBand(scroller: HTMLElement, head: HTMLElement | null): { top: number; bottom: number } {
  const { top, bottom } = clippedBand(scroller, head);
  /* Nothing visible at all (a rail scrolled away from the grid): fall back to the layout box, so a
     reveal still moves the row to where the grid WILL show it rather than thrashing. */
  if (bottom > top) return { top, bottom };
  const box = scroller.getBoundingClientRect();
  return { top: head ? Math.max(box.top, head.getBoundingClientRect().bottom) : box.top, bottom: box.bottom };
}

/** `visibleBand` without its fallback: what the reader sees, which may be empty (bottom <= top). */
function clippedBand(scroller: HTMLElement, head: HTMLElement | null): { top: number; bottom: number } {
  const box = scroller.getBoundingClientRect();
  let top = head ? Math.max(box.top, head.getBoundingClientRect().bottom) : box.top;
  let bottom = box.bottom;
  const view = scroller.ownerDocument.defaultView;
  if (view) {
    const doc = scroller.ownerDocument;
    const rootOy = view.getComputedStyle(doc.documentElement).overflowY;
    for (let a = scroller.parentElement; a !== null; a = a.parentElement) {
      /* The root element's clip IS the viewport (handled below), and a <body> whose overflow the
         root does not claim propagates it to the viewport too — its box scrolls WITH the page, so
         treating it as a clip read a band 1,500 px above the screen once the page had scrolled
         (measured 577x630, 2026-09-22: PageUp then scrolled the page DOWN, away from the row). */
      if (a === doc.documentElement) continue;
      if (a === doc.body && (rootOy === "visible" || rootOy === "")) continue;
      const oy = view.getComputedStyle(a).overflowY;
      if (oy === "visible" || oy === "") continue;
      const r = a.getBoundingClientRect();
      /* jsdom lays nothing out: every rect is 0x0. A zero-height ancestor there is not a clip. */
      if (r.height <= 0) continue;
      top = Math.max(top, r.top);
      bottom = Math.min(bottom, r.bottom);
    }
    if (view.innerHeight > 0) {
      top = Math.max(top, 0);
      bottom = Math.min(bottom, view.innerHeight);
    }
    ({ top, bottom } = trimOverlays(scroller, doc, box, top, bottom));
  }
  return { top, bottom };
}

/**
 * Shrink the band past anything that PAINTS OVER its edges — a sticky or fixed bar that is not part
 * of the grid. Clips say where the grid can be drawn; they say nothing about a sibling layered on
 * top of it. MEASURED (D3, 390x844, 2026-09-23): the page scrolls the grid there, and the status
 * bar (`position: sticky; bottom: 0`, wrapped to 85 px) covered the viewport's bottom edge, so
 * ArrowDown left every focused row from the 17th on fully UNDER it — rows 788-844 against a bar
 * from 759 — while this band called them visible (WCAG 2.4.11).
 *
 * The browser's own hit test is the only generic answer to "what covers this point", so each edge
 * is probed just inside the band: a hit outside the grid that is not one of its ancestors is an
 * overlay, and the band moves past its box. Repeated a few times because the first hit can be a
 * child of the overlay whose box starts inside the overlay's padding. Where hit testing is not
 * available (jsdom), the band is unchanged.
 */
function trimOverlays(
  scroller: HTMLElement,
  doc: Document,
  box: DOMRect,
  top: number,
  bottom: number,
): { top: number; bottom: number } {
  const stack = typeof doc.elementsFromPoint === "function";
  if ((!stack && typeof doc.elementFromPoint !== "function") || bottom <= top) return { top, bottom };
  const view = doc.defaultView;
  const maxX = view && view.innerWidth > 0 ? view.innerWidth - 1 : box.right;
  const x = Math.min(Math.max((Math.max(box.left, 0) + Math.min(box.right, maxX)) / 2, 0), maxX);
  /**
   * Every box painted OVER the grid at (x, y): the hit-test stack down to the grid (or an element
   * that holds it). The WHOLE stack, not only the topmost hit. MEASURED (D3, 390x844, repair wave 8,
   * `audit-d3-focus.mjs` phone/inspector (citation), traced): focus arrived on a grid cell while the
   * queue's "What the collection gap means" popover (635-833) was still open over the band, and the
   * edge probes hit the popover's pieces rather than the status bar (759-844) under them. With the
   * topmost hit only, a box that covers the whole remaining band (the popover's own frame) ends the
   * walk, and whatever it hides — the bar — is never trimmed; the stack lets it be passed over. (That
   * trace's cell went under the bar by a second route as well — the arrival reveal measured against
   * the still-open popover; see `settleFocus`.) Where only `elementFromPoint` exists, the topmost hit
   * is the stack.
   */
  const coversAt = (y: number): DOMRect[] => {
    const hits = stack ? doc.elementsFromPoint(x, y) : [doc.elementFromPoint(x, y)];
    const out: DOMRect[] = [];
    for (const hit of hits) {
      if (hit === null || scroller.contains(hit) || hit.contains(scroller)) break;
      out.push(hit.getBoundingClientRect());
    }
    return out;
  };
  for (let i = 0; i < 4 && bottom > top; i += 1) {
    let next = bottom;
    for (const r of coversAt(bottom - 1)) if (r.top < next && r.top > top) next = r.top;
    if (next >= bottom) break;
    bottom = next;
  }
  for (let i = 0; i < 4 && bottom > top; i += 1) {
    let next = top;
    for (const r of coversAt(top + 1)) if (r.bottom > next && r.bottom < bottom) next = r.bottom;
    if (next <= top) break;
    top = next;
  }
  return { top, bottom };
}

/**
 * How far `el`'s row sits outside the part of the scroll port the reader can see (below the sticky
 * header, inside every clip): 0 when it is fully visible, negative when it is above, positive when
 * it is below. The single visibility predicate shared by the reveal and by the hold that keeps a
 * revealed row in view.
 */
function offsetFromView(
  scroller: HTMLElement,
  head: HTMLElement | null,
  el: HTMLElement,
  /** The band for `head`, when the caller already measured it for several rows. */
  rowBand?: { top: number; bottom: number },
): number {
  if (head?.contains(el)) {
    /* The header is sticky inside the grid's OWN scroll port, so there it is always visible. When
       the grid is not its own port (narrow layouts — the page scrolls it) the header scrolls away
       with the rows: measured 577x630, PageUp onto the header row left it 126 px above the screen.
       So the header answers to the same clip test, against a band it does not itself cover. */
    const band = visibleBand(scroller, null);
    const r = el.getBoundingClientRect();
    if (r.top >= band.top && r.bottom <= band.bottom) return 0;
    return r.top < band.top ? r.top - band.top : r.bottom - band.bottom;
  }
  const { top, bottom } = rowBand ?? visibleBand(scroller, head);
  const target = el.closest<HTMLElement>('[role="row"]') ?? el;
  const row = target.getBoundingClientRect();
  if (row.top >= top && row.bottom <= bottom) return 0;
  return row.top < top ? row.top - top : row.bottom - bottom;
}

/**
 * The TOPMOST mounted row whose id is in `ids` and which is fully inside the visible band, or null.
 * The same predicate as the reveal and the hold (`offsetFromView`), so "already visible" cannot mean
 * something different here from what a reveal would have produced.
 *
 * Fails toward revealing: a row with no laid-out height (jsdom, a display:none ancestor, a frame
 * before layout) proves nothing about what the reader sees, so it never counts as visible — skipping
 * a reveal on no evidence is exactly the silent failure this product refuses.
 */
function firstVisibleRow(
  scroller: HTMLElement,
  head: HTMLElement | null,
  rowEls: ReadonlyMap<string, HTMLElement>,
  ids: ReadonlySet<string>,
): string | null {
  if (ids.size === 0) return null;
  let band: { top: number; bottom: number } | undefined;
  let best: { id: string; top: number } | null = null;
  for (const [id, el] of rowEls) {
    if (!ids.has(id) || head?.contains(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.height <= 0) continue;
    band ??= visibleBand(scroller, head); // measured once, and only when a candidate exists
    if (seenInBand(scroller, head, el, band) && (best === null || r.top < best.top)) best = { id, top: r.top };
  }
  return best?.id ?? null;
}

/**
 * How much of a row may sit outside the band and still count as SEEN for an "already on screen?"
 * decision: less than one CSS pixel. Rows are laid out on fractional pixels while scrollTop snaps to
 * device pixels, so a row the reader scrolled flush to the header's edge can sit 0.25 px under it.
 * MEASURED (A4 band sweep, 1920x1080): F012 flush at the band's top edge, 0.25 px under the header,
 * read as not visible, and the pick threw the list 645 px to F002. The same slack the hold uses to
 * decide that a row is still where a reveal put it; a REVEAL still aims for the whole row.
 */
const SEEN_SLACK_PX = 1;

function seenInBand(scroller: HTMLElement, head: HTMLElement | null, el: HTMLElement, band: { top: number; bottom: number }): boolean {
  return Math.abs(offsetFromView(scroller, head, el, band)) < SEEN_SLACK_PX;
}

/**
 * Every mounted data row (by `rowKeyOf`) the reader can see right now — the same predicate as
 * `firstVisibleRow`, applied to all rows — with how far it sat outside the band then (0 when fully
 * inside, under a pixel otherwise). Used only for the act-time record (see `actKey`), which is taken
 * before the act's commit mutates anything, so the layout it reads is the one already on screen and
 * forces no reflow (measured on the release build, 146 rows: 0.6 ms median, 1 ms max).
 */
function visibleRowKeys(scroller: HTMLElement, head: HTMLElement | null, rowEls: ReadonlyMap<string, HTMLElement>): Map<string, number> {
  const out = new Map<string, number>();
  let band: { top: number; bottom: number } | undefined;
  for (const [key, el] of rowEls) {
    if (head?.contains(el)) continue;
    if (el.getBoundingClientRect().height <= 0) continue;
    band ??= visibleBand(scroller, head);
    if (seenInBand(scroller, head, el, band)) out.set(key, offsetFromView(scroller, head, el, band));
  }
  return out;
}

/**
 * Calls `capture` in the commit's BEFORE-MUTATION phase whenever `watch` changes — the one moment
 * React guarantees the DOM, and so the layout, is still exactly what the reader was looking at.
 * A layout effect is too late: by then the same commit has already inserted whatever moves the grid.
 */
class BeforeCommit extends Component<{ watch: string | undefined; capture: () => void }> {
  override getSnapshotBeforeUpdate(prev: Readonly<{ watch: string | undefined }>): null {
    if (prev.watch !== this.props.watch) this.props.capture();
    return null;
  }
  /* Required alongside getSnapshotBeforeUpdate; the snapshot is kept by `capture` itself. */
  override componentDidUpdate(): void {}
  override render(): null {
    return null;
  }
}

/** Keys that scroll the page when the element they are pressed on does not take them. */
const PAGE_SCROLL_KEYS: ReadonlySet<string> = new Set([" ", "PageUp", "PageDown", "Home", "End", "ArrowUp", "ArrowDown"]);

/** The element focus is on inside `scroller` (not the scroller itself), or null when the grid does
 *  not hold focus. */
function focusedCellIn(scroller: HTMLElement | null, hasFocus: boolean): HTMLElement | null {
  const view = scroller?.ownerDocument.defaultView;
  const active = scroller?.ownerDocument.activeElement;
  if (!scroller || !view || !hasFocus || !(active instanceof view.HTMLElement) || active === scroller || !scroller.contains(active)) return null;
  return active;
}

/** `aimedAt` before the first render has looked at the reveal target. */
const UNAIMED: unique symbol = Symbol("unaimed");

/**
 * A data row's identity IN THIS GRID: its caller-qualified `key` when it has one, else its `id`.
 *
 * A4, MEASURED (1920x1080, Group = Device health band): F144 is listed as row 92 (Poor) and row 167
 * (Critical). The grid knew a row only by its item id, so the roving cell, the reveal and the focus
 * they hand on all resolved "F144" to the FIRST copy: clicking the visible row 167 at scrollTop 7879
 * threw the list to 4655 and focus to row 92. Every place the grid addresses ONE rendered row — its
 * element, the roving aim, the reveal, the hold, the current mark — uses this key; the caller's
 * selection (`activeId`, `revealId`) stays an item id, and which copy answers it is decided here.
 */
const rowKeyOf = <T,>(n: Extract<GridNode<T>, { kind: "row" }>): string => n.key ?? n.id;

export function DataGrid<T>({
  label,
  columns,
  nodes,
  template,
  activeId = null,
  revealId,
  revealKey,
  revealUnlessVisible,
  actKey,
  relatedIds,
  relatedDescription,
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
  orderDescription,
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

  /**
   * Can the roving cell stand on (r, c)?
   *
   * A11Y AUDIT FIX, 2026-09-21 (D2). A `headerHidden` column's header cell is clipped to 1x1 at
   * the viewport origin — it exists so the grid's column model stays whole for assistive
   * technology, not so it can be visited. It used to be an ordinary stop in the arrow-key model:
   * ArrowRight along the header row put focus on an invisible box at (0,0), and because the grid
   * roves its tabindex that box then became the grid's remembered Tab stop (WCAG 2.4.7 / 2.4.11).
   *
   * This is the ONE predicate every movement path consults — arrows, Home/End, Ctrl+Home/End,
   * Page keys, Shift ranges, the clamp after a filter change and focus that arrives from outside —
   * so a clipped cell is unreachable by construction rather than by each key remembering to skip
   * it. It is stated over the flag that clips the cell, not over any column's name.
   */
  const navigable = useCallback(
    (r: number, c: number): boolean => !(rows[r]?.kind === "header" && columns[c]?.headerHidden === true),
    [rows, columns],
  );

  /** The nearest cell the roving cell may stand on in row `r`, searching `dir` first. */
  const landOn = useCallback(
    (r: number, c: number, dir: 1 | -1): number => {
      const n = cellsIn(r);
      const start = clamp(c, 0, Math.max(0, n - 1));
      for (let i = start; i >= 0 && i < n; i += dir) if (navigable(r, i)) return i;
      for (let i = start - dir; i >= 0 && i < n; i -= dir) if (navigable(r, i)) return i;
      return start;
    },
    [cellsIn, navigable],
  );

  const firstDataRow = useMemo(() => {
    const i = rows.findIndex((r) => r.kind === "data");
    return i === -1 ? 0 : i;
  }, [rows]);

  const [focusCell, setFocusCell] = useState<{ row: number; col: number }>({ row: firstDataRow, col: 0 });
  /** Mirror of `focusCell` for effects and handlers that must read the CURRENT roving cell
   *  without re-subscribing to it. */
  const focusCellRef = useRef(focusCell);
  focusCellRef.current = focusCell;
  /**
   * Set when a selection from OUTSIDE the grid (the command palette, the Inspector, a URL, the
   * path surface) moved the roving cell onto the newly revealed row, and focus has not yet
   * followed it. While set, focus that re-enters the grid from outside — above all a dialog
   * restoring focus to the cell that opened it — is redirected to the roving cell, and a reveal
   * that mounts the row hands it focus. Cleared by any pointer or key input in the grid, so it
   * never overrides something the user did in the grid themselves.
   */
  const aimFocus = useRef(false);
  /** Set while a re-entry redirect is paging the window to the roving row (see onFocus). */
  const aimEntry = useRef(false);
  /** A representative reveal's roving aim, left for the reveal effect to place (see `aimedAt`):
   *  "initial" places only a tab stop (mount), "change" also redirects focus that re-enters. */
  const repAim = useRef<"none" | "initial" | "change">("none");
  /** Set by a pointerdown on the grid and consumed by the focus it causes (see onFocus). */
  const pointerFocus = useRef(false);

  /* The roving cell follows the reveal target (D3). Revealing a row while the keyboard's position
     stays on the row that WAS selected leaves two defects at once: focus restored to that old cell
     (a dialog returning focus to its invoker) sits thousands of pixels outside the scroll port with
     no visible indicator, and the next arrow key scrolls the grid back to it, throwing the reveal
     away. MEASURED (critic, 1920x1080): palette pick of F099 from the F001 cell left focus at
     y=-4007 and the next ArrowDown landed on row 4 at scrollTop 80.

     Adjusted DURING render (React's derived-state pattern) rather than in the reveal effect, so
     the row that gains the tab stop renders once, together with its selection change, instead of
     twice (DataGrid.memo.test.tsx). A selection made IN the grid already has the roving cell on
     that row, so this is a no-op there. Focus itself is moved by the effects below — now if the
     grid owns focus, or when focus next re-enters it from outside (`aimFocus`). */
  const aimTarget = revealId === undefined ? activeId : revealId;
  /** Every rendered copy of each item id, in display order (see `rowKeyOf`). */
  const copies = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const n of nodes) {
      if (n.kind !== "row") continue;
      const list = m.get(n.id);
      if (list) list.push(rowKeyOf(n));
      else m.set(n.id, [rowKeyOf(n)]);
    }
    return m;
  }, [nodes]);
  /** The copy of the selected item the reader acted on or was shown last. Only consulted while it
   *  is still a copy of `activeId`; otherwise the first copy is the current one. */
  const [chosenCopy, setChosenCopy] = useState<string | null>(null);
  const activeKey = useMemo((): string | null => {
    if (activeId === null) return null;
    const list = copies.get(activeId);
    if (list === undefined) return null;
    return chosenCopy !== null && list.includes(chosenCopy) ? chosenCopy : (list[0] ?? null);
  }, [activeId, copies, chosenCopy]);
  // Starts unaimed, so a selection restored from the URL also carries the tab stop to its row.
  const [aimedAt, setAimedAt] = useState<string | null | undefined | typeof UNAIMED>(UNAIMED);
  /** The row set the last plain aim saw and the row index it left the roving cell on (null: it
   *  placed nothing, or the reader has since moved the roving cell). See the re-order branch. */
  const aimedRow = useRef<{ rows: typeof rows; row: number | null } | null>(null);
  if (aimedAt !== aimTarget) {
    setAimedAt(aimTarget);
    /* A target listed more than once is answered by whichever copy the reader is already on or
       looking at, and "looking at" needs a measurement only the reveal effect can take. So, like a
       representative reveal, its aim is left to that effect — which keeps the copy under the roving
       cell (a click or Enter on it), else a copy in view, else the first. */
    const multi = aimTarget != null && (copies.get(aimTarget)?.length ?? 0) > 1;
    const rovingNow = rows[focusCell.row];
    const onCopy = multi && rovingNow?.kind === "data" && rovingNow.node.id === aimTarget;
    if (multi) repAim.current = onCopy ? "none" : aimedAt === UNAIMED ? "initial" : "change";
    /* A REPRESENTATIVE reveal (`revealUnlessVisible`) may decide not to scroll at all, and only the
       reveal effect can measure that. Aiming the roving cell here would move FOCUS to the
       representative row — and scroll the list to it — before that decision: MEASURED (A4,
       1920x1080) with focus on F060 at scrollTop 3200, palette -> access13 -> Enter ended at 70 with
       focus on F002. So a representative aim is only recorded here; the reveal effect places the
       roving cell on the row it actually shows (the answer on screen, or the one it scrolled to). */
    else if (revealUnlessVisible !== undefined) repAim.current = aimTarget == null ? "none" : aimedAt === UNAIMED ? "initial" : "change";
    const at =
      aimTarget == null || revealUnlessVisible !== undefined || multi ? -1 : rows.findIndex((r) => r.kind === "data" && r.node.id === aimTarget);
    if (at !== -1 && at !== focusCell.row) {
      userMoved.current = true;
      anchorRow.current = null;
      // At mount there is no stale focus to redirect, only a tab stop to place.
      if (aimedAt !== UNAIMED) aimFocus.current = true;
      setFocusCell({ row: at, col: landOn(at, focusCell.col, 1) });
    }
    aimedRow.current = { rows, row: at === -1 ? null : at };
  } else if (aimedRow.current !== null && aimedRow.current.rows !== rows) {
    /* The same target, a different row set. A filter edit or a re-sort that keeps the selection but
       moves it to another index used to leave the tab stop on whatever row now stood at the old
       index, so Tab entered the grid on a stranger (W6-a4 — PriorityQueue withdrew `revealId` for one
       commit to force this for its own widen control). The aim follows the row as long as the roving
       cell is still where the aim put it: once the reader has moved it, their place is theirs, and
       the clamp effect below keeps its index as before. Only the plain aim above is followed; a
       representative or multi-copy aim is placed by the reveal effect, which measures. */
    const was = aimedRow.current.row;
    const at = was === null || focusCell.row !== was ? -1 : rows.findIndex((r) => r.kind === "data" && r.node.id === aimTarget);
    aimedRow.current = { rows, row: was === null || focusCell.row !== was ? null : at === -1 ? was : at };
    if (at !== -1 && at !== focusCell.row) setFocusCell({ row: at, col: landOn(at, focusCell.col, 1) });
  }
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
      const col = landOn(row, wanted.col, 1);
      return row === prev.row && col === prev.col ? prev : { row, col };
    });
  }, [rows, landOn, firstDataRow]);

  const cellKey = (r: number, c: number): string => `${r}:${c}`;

  /* EVERY focus the grid moves goes through here. A bare `el.focus()` lets the browser scroll the
     cell to the scroll port's top edge — which is UNDER the sticky column header. Measured: an
     ArrowUp onto a group row left 21 of its 28 px behind the header, and a hit-test at the focused
     cell's centre landed on the header's sort button (D3). So focus never scrolls on its own; the
     same header-aware nearest-reveal the selection reveal uses brings the cell's row into view. */
  const focusInView = useCallback((el: HTMLElement): void => {
    focusKeptRef.current = true;
    el.focus({ preventScroll: true });
    const scroller = gridRef.current;
    if (scroller) revealBelowHeader(scroller, headRef.current, el);
  }, []);

  /* Focus follows the roving cell only when the grid ALREADY owns focus. Moving focus because a
     filter changed would yank the caret out of the query bar mid-keystroke. */
  useLayoutEffect(() => {
    if (!hasFocus.current) return;
    const el = cellRefs.current.get(cellKey(focusCell.row, focusCell.col));
    if (!el) return;
    aimFocus.current = false;
    if (document.activeElement !== el) focusInView(el);
  }, [focusCell, focusInView]);

  /* Completes a pending aim once the window has mounted the roving row (see `aimFocus`). Runs
     after every commit because the commit that mounts the row is a windowing re-render, which no
     dependency of this component names; the body is one Map lookup when nothing is pending. */
  useLayoutEffect(() => {
    if (!aimFocus.current) return;
    /* Paging can unmount the stale cell focus was restored to, which drops focus to <body> and
       clears `hasFocus`; a re-entry this grid is completing still owns that focus. */
    const active = document.activeElement;
    const entering = aimEntry.current && (active === null || active === document.body || gridRef.current?.contains(active) === true);
    if (!hasFocus.current && !entering) return;
    const { row, col } = focusCellRef.current;
    const el = cellRefs.current.get(cellKey(row, col));
    if (!el) return;
    aimFocus.current = false;
    aimEntry.current = false;
    if (document.activeElement !== el) focusInView(el);
  });

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
  /** Move the roving cell to the data row whose `rowKeyOf` is `key` from an effect; `redirect`
   *  makes focus that re-enters the grid (or already owns it) follow. */
  const placeRoving = (key: string, redirect: boolean): void => {
    const at = rows.findIndex((r) => r.kind === "data" && rowKeyOf(r.node) === key);
    if (at === -1 || at === focusCellRef.current.row) return;
    userMoved.current = true;
    anchorRow.current = null;
    if (redirect) aimFocus.current = true;
    setFocusCell({ row: at, col: landOn(at, focusCellRef.current.col, 1) });
  };
  const revealTarget = revealId === undefined ? activeId : revealId;
  const revealedRef = useRef<string | null>(null);
  /** WHICH copy of `revealedRef` was revealed (its `rowKeyOf`): the row the hold keeps in view. */
  const revealedKeyRef = useRef<string | null>(null);
  const pagedRef = useRef<string | null>(null);
  /**
   * The data row the reader just activated IN this grid (click, Enter, Space). That row is under
   * the pointer or the focused cell, so it is already where the reader is looking, and the
   * selection it produces needs no reveal. Without this, the click's own commit measured the whole
   * document (getBoundingClientRect after every surface's DOM writes) to learn nothing: a forced
   * layout of ~20-40 ms inside `DIV#root.onclick` on every finding selection (acceptance E3,
   * journey 1, CPU profile on the release build). Consumed by the next reveal, whatever it is.
   */
  const activatedRef = useRef<{ id: string; key: string } | null>(null);
  const revealKeyRef = useRef(revealKey);
  /**
   * HOLD. True while the revealed row is inside the scroll port and the reader has not scrolled it
   * out. A reveal is not a one-shot: MEASURED (1920x1080, `?s=path&f=F099`), tracing a flow
   * selected core1, which added the "N of 146 shown findings name core1" line above the grid; the
   * port's top moved 795 -> 829 px with scrollTop unchanged, and the active F099 row that had sat
   * flush on the bottom edge ended 34 px below it — marked, not revealed. Anything that resizes the
   * port (a sibling panel growing, the header wrapping, a window resize) or reflows the rows above
   * the target moves the row without a scroll event, so while this is set those changes re-run the
   * same nearest-reveal. A reader who scrolls the row away clears it: holding is never a fight
   * with the reader's own scrolling.
   */
  const heldRef = useRef(false);
  /**
   * How the hold re-reveals. "centre" for a row a reveal SCROLLED to (its own alignment); "nearest"
   * for a selection the reader made with the row already under their eyes — a click, Enter or Space
   * in this grid — which no reveal moved, so a later change of the port brings it back by the least
   * movement and never throws the list to centre it.
   *
   * WHY THE SECOND MODE EXISTS (A4, repair wave 8; acceptance-report.md at `34bd435`, reproduced
   * twice at 1920x1080): the reader scrolled to 1000, CLICKED F026 (visible at 844-900 in a port of
   * 389-1054), picked access5, core1, L33 and access5 on the canvas, then pressed the Path surface
   * button. The path panel shrank the port to 786-1054, scrollTop moved only 1000 -> 1015, and the
   * `data-active` F026 sat at 1241-1297, off screen; the flow submit and a double-click on dist1
   * left it there. The hold was armed only by a reveal that scrolled, and a click skips the reveal
   * (the activation path below), so the port-size observer had nothing to keep; the device, link and
   * hop picks do not re-key the reveal (a device pick keeps the reader's place, A4). After a URL load
   * the same switch re-anchored the row, because that selection HAD scrolled. The latch now depends
   * on whether the reader can see the selection, not on how it was reached.
   */
  const holdAlignRef = useRef<"centre" | "nearest">("centre");
  /**
   * Whether the FOCUSED cell is to be kept on screen (see `keepFocusInView`): raised whenever focus
   * arrives in the grid or the keyboard moves it (the grid itself has just put it in view), and
   * re-read from the screen when the READER scrolls — the grid, an ancestor or the page — so a reader
   * who scrolls away from their focus to read something else is never pulled back by a later layout
   * change. The same rule as the hold, for the keyboard's position.
   */
  const focusKeptRef = useRef(true);
  /** Reader input that scrolls the PAGE or a scrolling ancestor of the grid (the grid's own port has
   *  `readerInputRef`): see `onPageInput`. Lowered when focus arrives in the grid or the keyboard
   *  acts in it. No clock, as for the grid. */
  const pageInputRef = useRef(false);
  const revealTargetRef = useRef(revealTarget);
  revealTargetRef.current = revealTarget;
  /** True once the reader has touched the grid (wheel, touch, pointer, key) since the last reveal;
   *  only then may a scroll release the hold. See the hold effect below. */
  const readerInputRef = useRef(false);
  /**
   * What the reader could see when they last acted (see `actKey`): the fully visible row keys and
   * the scroll offset they were read at. Consumed by the next reveal decision; dropped by reader
   * input on the grid, and ignored if the grid has scrolled since (the reader's newer view counts).
   */
  const actViewRef = useRef<{ keys: ReadonlyMap<string, number>; scrollTop: number } | null>(null);
  const captureActView = useCallback((): void => {
    const scroller = gridRef.current;
    actViewRef.current = scroller ? { keys: visibleRowKeys(scroller, headRef.current, rowRefs.current), scrollTop: scroller.scrollTop } : null;
  }, []);

  useLayoutEffect(() => {
    const scroller = gridRef.current;
    if (!scroller) return;
    if (revealTarget === null || revealTarget === undefined) {
      revealedRef.current = null;
      pagedRef.current = null;
      heldRef.current = false;
      return;
    }
    /* A new selection elsewhere (a device, a link, a hop) re-aims even when the row to reveal is
       the same one: the reader may have scrolled it away since, and A4 counts that selection as a
       change every surface answers. */
    if (revealKeyRef.current !== revealKey) {
      revealKeyRef.current = revealKey;
      revealedRef.current = null;
      pagedRef.current = null;
    }
    if (revealedRef.current === revealTarget) return;
    const activated = activatedRef.current;
    activatedRef.current = null;
    if (activated !== null && activated.id === revealTarget && rowRefs.current.has(activated.key)) {
      revealedRef.current = revealTarget;
      revealedKeyRef.current = activated.key;
      pagedRef.current = null;
      repAim.current = "none";
      /* The row is under the reader's pointer or focused cell: nothing to reveal NOW, but it is the
         selection on screen, so it is held — by the least movement (see `holdAlignRef`). Armed
         without measuring anything: this is the click's own commit (E3, journey 1); the hold's
         triggers (the port's ResizeObserver, a scroll the reader did not make, a later commit
         that reflows the rows) do the measuring. */
      heldRef.current = true;
      holdAlignRef.current = "nearest";
      pageInputRef.current = false;
      return;
    }

    /* Already answered (see `revealUnlessVisible`): a row the reader can see right now is one the
       reveal would only have scrolled AWAY from. Checked before paging, so a target the window has
       not even mounted cannot move the list either. No hold: nothing was revealed, so a later resize
       has nothing to keep in view, and the reader's own scrolling stays theirs. */
    const keysFor = (ids: Iterable<string>): Set<string> => {
      const out = new Set<string>();
      for (const id of ids) for (const k of copies.get(id) ?? []) out.add(k);
      return out;
    };
    /* What the reader saw when they acted (see `actKey`), taken once per act: this decision is the
       one it was recorded for. Void once the grid has scrolled since — the reader's own newer view
       (or a clamp) is then what is on screen. */
    const actView = actViewRef.current;
    actViewRef.current = null;
    const sawAtAct = actView !== null && Math.abs(actView.scrollTop - scroller.scrollTop) < 0.5 ? actView.keys : null;
    /** Of `keys`, the row the reader could see when they acted that the layout has since moved out
     *  of the band — the one nearest to it, so bringing it back is the least movement. */
    const seenAtAct = (keys: ReadonlySet<string>): string | null => {
      if (sawAtAct === null) return null;
      let best: { key: string; off: number } | null = null;
      for (const k of keys) {
        const el = sawAtAct.has(k) ? rowRefs.current.get(k) : undefined;
        if (el === undefined || el.getBoundingClientRect().height <= 0) continue;
        const off = Math.abs(offsetFromView(scroller, headRef.current, el));
        if (best === null || off < best.off) best = { key: k, off };
      }
      return best?.key ?? null;
    };
    let answered: string | null = null;
    if (revealUnlessVisible !== undefined) {
      const keys = keysFor(revealUnlessVisible);
      answered = firstVisibleRow(scroller, headRef.current, rowRefs.current, keys) ?? seenAtAct(keys);
      /* The reader was looking at this answer when they acted. If the act has since pushed it
         further out of the band than it was then (the sentence above the grid moving the port — by
         38 px, or by the 0.8 px that leaves it just under the edge), put it back by the least
         movement; never throw the reader to the first naming row, and never nudge a row the act
         did not move (a sliver the reader's own scroll left under the header stays theirs). */
      const el = answered === null ? undefined : rowRefs.current.get(answered);
      const then = answered === null ? undefined : sawAtAct?.get(answered);
      if (el !== undefined && then !== undefined && Math.abs(offsetFromView(scroller, headRef.current, el)) > Math.abs(then) + 0.01) {
        revealBelowHeader(scroller, headRef.current, el, "nearest");
      }
    }
    if (answered !== null) {
      revealedRef.current = revealTarget;
      revealedKeyRef.current = answered;
      pagedRef.current = null;
      heldRef.current = false;
      /* The roving cell follows the answer on screen, not the representative this skip declined to
         scroll to: focus re-entering the grid lands on the roving cell, so a dialog returning focus
         would otherwise page the list away (see `repAim`). No focus redirect: the reader's focus,
         if it is in the grid, is already on screen. */
      repAim.current = "none";
      placeRoving(answered, false);
      return;
    }

    /* WHICH copy answers the target (see `rowKeyOf`). With one copy, that one. With several: the
       copy under the roving cell when it is in view, else the topmost copy in view — the reader is
       already looking at the selection, and moving the list would throw their place away (A4,
       R39's rule extended to a finding listed under several groups) — else the copy under the
       roving cell, where the keyboard is, else the first. */
    const targetCopies = copies.get(revealTarget) ?? [];
    let key = targetCopies[0] ?? revealTarget;
    /** True when the copy chosen was on screen when the reader acted and has since been moved. */
    let restoring = false;
    if (targetCopies.length > 1) {
      const onRoving = rows[focusCellRef.current.row];
      const rovingKey = onRoving?.kind === "data" && onRoving.node.id === revealTarget ? rowKeyOf(onRoving.node) : null;
      const rovingEl = rovingKey === null ? undefined : rowRefs.current.get(rovingKey);
      const rovingInView =
        rovingEl !== undefined && rovingEl.getBoundingClientRect().height > 0 && Math.abs(offsetFromView(scroller, headRef.current, rovingEl)) < SEEN_SLACK_PX;
      const liveCopy = rovingInView ? rovingKey : firstVisibleRow(scroller, headRef.current, rowRefs.current, new Set(targetCopies));
      const actCopy = liveCopy === null ? seenAtAct(new Set(targetCopies)) : null;
      restoring = actCopy !== null;
      key = liveCopy ?? actCopy ?? rovingKey ?? key;
    } else if (sawAtAct !== null && sawAtAct.has(key)) {
      /* The selection itself was on screen when the reader acted: if the act has since moved it, the
         least movement brings it back — centring would move a row the reader was already reading. */
      restoring = true;
    }
    const el = rowRefs.current.get(key);
    if (!el) {
      // Not in the DOM. Either the window dropped it, or this corpus holds no such row — and a
      // row that does not exist is not a row we can fail to reveal, so both exit quietly.
      if (pagedRef.current === revealTarget || !windowing) return;
      const index = nodes.findIndex((n) => n.kind === "row" && rowKeyOf(n) === key);
      if (index === -1) return;
      pagedRef.current = revealTarget;
      scroller.scrollTop = Math.max(0, index * windowing.rowHeightPx);
      return;
    }

    revealedRef.current = revealTarget;
    revealedKeyRef.current = key;
    pagedRef.current = null;
    revealBelowHeader(scroller, headRef.current, el, restoring ? "nearest" : "centre");
    heldRef.current = true;
    /* The hold keeps the row the way it was placed: a row the reader was already looking at is
       restored by the least movement, and so is every later re-reveal of it (see `holdAlignRef`). */
    holdAlignRef.current = restoring ? "nearest" : "centre";
    if (targetCopies.length > 1 && revealTarget === activeId) setChosenCopy(key);
    /* A representative reveal that DID scroll places the roving cell on the row it brought into
       view — what the render-time aim does for every other reveal (see `repAim`). A target with
       several copies is placed the same way, on the copy chosen above. */
    if (repAim.current !== "none") {
      placeRoving(key, repAim.current === "change");
      repAim.current = "none";
    }
    // A fresh reveal starts a fresh hold: input that preceded it is not a scroll away from it.
    readerInputRef.current = false;
    pageInputRef.current = false;
    /* A row that had to be paged in has only just mounted, so the focus-follows-roving effect
       below found no cell to focus when the roving cell moved. Hand it focus now. */
    if (aimFocus.current && hasFocus.current) {
      const { row, col } = focusCellRef.current;
      const cell = cellRefs.current.get(cellKey(row, col));
      if (cell) {
        aimFocus.current = false;
        if (document.activeElement !== cell) focusInView(cell);
      }
    }
  }, [revealTarget, revealKey, revealUnlessVisible, nodes, windowing, rows, landOn, focusInView, copies, activeId]);

  /* The hold itself (see `heldRef`). One re-reveal routine, three triggers: the port or its sticky
     header changing size (ResizeObserver), the rows changing (a commit that reflows what is above
     the target), and the reader's own scrolling, which decides whether the hold still applies. */
  const holdReveal = useCallback((page = true): void => {
    const scroller = gridRef.current;
    const id = revealTargetRef.current;
    const key = revealedKeyRef.current;
    if (!scroller || !heldRef.current || id === null || id === undefined || revealedRef.current !== id || key === null) return;
    const el = rowRefs.current.get(key);
    if (el) revealBelowHeader(scroller, headRef.current, el, holdAlignRef.current, page);
  }, []);

  /**
   * The FOCUSED cell answers to the same rule as the held selection: a change the reader did not
   * make to the grid — the port shrinking under a surface switch, the viewport resizing, a panel
   * closing over it — must not leave the cell the keyboard is on out of view (WCAG 2.4.11). Nearest
   * semantics, so a cell in view never moves; run after the hold, so when the two disagree the
   * keyboard's position wins. Only while focus is IN the grid: a reader focused elsewhere has
   * nothing here to lose.
   */
  const keepFocusInView = useCallback((): void => {
    const scroller = gridRef.current;
    const active = focusedCellIn(scroller, hasFocus.current);
    if (!scroller || active === null || !focusKeptRef.current) return;
    revealBelowHeader(scroller, headRef.current, active);
  }, []);
  /**
   * Re-check the focused cell once the layout has SETTLED after focus arrived from outside the grid.
   * The arrival's own reveal (onFocus) measures a layout the same act is still changing: MEASURED
   * (D3, 390x844, repair wave 8, `audit-d3-focus.mjs` phone/inspector (citation)), Tab off the
   * queue's "What the collection gap means" popover focused the roving cell at 714-755 — above the
   * status bar (759) — while the popover was still open. The arrival reveal, measuring THAT layout,
   * read one of the popover's boxes as an overlay over the band's top and called
   * `window.scrollBy(0, -37.3)` (traced from `onFocus` through `revealThroughAncestors`); the popover
   * then closed and left the cell at 754-788, under the bar (0 of 9 hit points on it). The same shape for
   * the Escape that follows: the selection it clears re-words the rail above the grid in a deferred
   * commit and pushed the cell 24 px down, under the bar. So the reveal is re-run after the next
   * frame, and again after the task the deferred commits run in (`deferPastPaint`), twice over.
   * Nothing here runs inside the event: each check reads layout AFTER the act, never in its commit.
   */
  const settleTimers = useRef<{ raf: Set<number>; timeout: Set<number> }>({ raf: new Set(), timeout: new Set() });
  const settleFocus = useCallback((): void => {
    const view = gridRef.current?.ownerDocument.defaultView;
    if (!view || typeof view.requestAnimationFrame !== "function") return;
    const t = settleTimers.current;
    const pass = (left: number): void => {
      const raf = view.requestAnimationFrame(() => {
        t.raf.delete(raf);
        keepFocusInView();
        const timeout = view.setTimeout(() => {
          t.timeout.delete(timeout);
          keepFocusInView();
          if (left > 1) pass(left - 1);
        }, 0);
        t.timeout.add(timeout);
      });
      t.raf.add(raf);
    };
    pass(2);
  }, [keepFocusInView]);
  useEffect(
    () => () => {
      const view = gridRef.current?.ownerDocument.defaultView ?? window;
      for (const id of settleTimers.current.raf) view.cancelAnimationFrame(id);
      for (const id of settleTimers.current.timeout) view.clearTimeout(id);
    },
    [],
  );
  /** One routine for every layout change the reader did not make: keep the selection, then focus. */
  const keepInView = useCallback((): void => {
    holdReveal();
    keepFocusInView();
  }, [holdReveal, keepFocusInView]);

  useLayoutEffect(() => holdReveal(), [nodes, relatedIds, holdReveal]);

  /**
   * The held row and the focused cell, WATCHED on screen (IntersectionObserver, which accounts for
   * every clipping ancestor). Resizes are not the only way a layout change takes them out of view:
   * content growing ABOVE the grid moves it inside a scrolling rail without resizing anything the
   * grid observes. MEASURED (A4, repair wave 8, 1920x1080, the report's sequence then "Trace this
   * flow" with the form's errors): the path panel above the queue grew, the grid kept its 19rem box
   * and slid down inside rail A, and the visible band became 1042-1054 — F026 at 1141-1197, marked,
   * not on screen, with no resize and no scroll event anywhere. The observer answers "it left the
   * screen" whatever moved it; the reader's own scrolling has already released the hold or the focus
   * by then (scroll events run before intersection callbacks in a frame). A hold re-reveal from here
   * never scrolls the DOCUMENT: when the page is what scrolls the grid, a page that moved is the
   * reader's or another surface's (a JSON search revealing its match), and pulling it back would take
   * their place away; only the grid and its scrolling ancestors move.
   */
  const watchRef = useRef<{ io: IntersectionObserver | null; targets: Element[] }>({ io: null, targets: [] });
  useLayoutEffect(() => {
    const w = watchRef.current;
    if (w.io === null) return;
    const key = revealedKeyRef.current;
    const held = heldRef.current && key !== null ? rowRefs.current.get(key) : undefined;
    const focused = focusedCellIn(gridRef.current, hasFocus.current);
    const next = [held, focused].filter((e): e is HTMLElement => e !== undefined && e !== null);
    if (next.length === w.targets.length && next.every((e, i) => e === w.targets[i])) return;
    for (const e of w.targets) w.io.unobserve(e);
    for (const e of next) w.io.observe(e);
    w.targets = next;
  });

  useEffect(() => {
    const scroller = gridRef.current;
    if (!scroller) return;
    /* Only the READER's scrolling may release the hold. A scroll event is also fired by the browser
       itself — scrollTop clamped when the port or the content shrinks, scroll anchoring when rows
       above reflow — and treating that as "the reader scrolled it away" dropped the hold at exactly
       the moment it was needed: MEASURED by the critic (A4) after a second path trace, the active
       F099 row sat 272 px below the port, marked, not revealed. So a scroll with no reader input
       on the grid re-runs the reveal instead of abandoning it.
       No clock: reader input raises a flag (`readerInputRef`) that a new reveal and the pointer
       leaving the grid lower again, so the classification is a function of the event sequence. */
    const onUserInput = (e: Event): void => {
      readerInputRef.current = true;
      /* The keyboard acting in the grid puts the reader back on their focus (the grid reveals every
         cell it moves to), and ends a page scroll of theirs. */
      if (e.type === "keydown") {
        focusKeptRef.current = true;
        pageInputRef.current = false;
      }
      // The reader's own hand on the grid supersedes what they could see when they last acted.
      actViewRef.current = null;
    };
    const onLeave = (): void => {
      readerInputRef.current = false;
    };
    const onScroll = (): void => {
      const id = revealTargetRef.current;
      const key = revealedKeyRef.current;
      const el = id === null || id === undefined || revealedRef.current !== id || key === null ? undefined : rowRefs.current.get(key);
      if (heldRef.current && !readerInputRef.current) {
        holdReveal();
        keepFocusInView();
        return;
      }
      /* 1 px of slack: a reveal lands on fractional device pixels, and a row the reveal itself just
         placed must not read as scrolled away. */
      heldRef.current = el !== undefined && Math.abs(offsetFromView(scroller, headRef.current, el)) <= 1;
      /* The focused cell by the same rule: a scroll the reader did not make keeps it; one they made
         decides, from what it left on screen, whether it is still theirs to keep. */
      if (!readerInputRef.current) keepFocusInView();
      else {
        const focused = focusedCellIn(scroller, hasFocus.current);
        if (focused !== null) focusKeptRef.current = Math.abs(offsetFromView(scroller, headRef.current, focused)) <= 1;
      }
    };
    const inputs = ["wheel", "touchmove", "pointerdown", "keydown"] as const;
    for (const t of inputs) scroller.addEventListener(t, onUserInput, { passive: true });
    scroller.addEventListener("pointerleave", onLeave, { passive: true });
    scroller.addEventListener("scroll", onScroll, { passive: true });
    const RO = typeof ResizeObserver === "undefined" ? null : ResizeObserver;
    const ro = RO ? new RO(keepInView) : null;
    ro?.observe(scroller);
    if (headRef.current) ro?.observe(headRef.current);
    /* The viewport is the band's last clip (`visibleBand`): a window resize can take the row or the
       focused cell off screen without resizing the grid's own box (narrow layouts, where the page
       scrolls the grid). The hold answers it without scrolling the DOCUMENT: a phone resizes the
       window whenever its address bar slides away under the reader's own page scroll. */
    const view = scroller.ownerDocument.defaultView;
    const onViewResize = (): void => {
      holdReveal(false);
      keepFocusInView();
    };
    view?.addEventListener("resize", onViewResize);
    /* The FOCUSED cell also answers to changes outside the grid's box. Narrow layouts scroll the grid
       with the page, so content above it growing or shrinking MOVES the grid without resizing it
       (no observer above fires), and a scroll of the page or of a scrolling ancestor that the reader
       did not make — a panel's close, scroll anchoring, a clamp — carries the cell off screen with no
       event on the grid at all. A scroll of those that the reader did not make re-reveals the focused
       cell only; the held row is answered by the watcher below, which never scrolls the document (a
       page scroll may be another surface revealing ITS content). A scroll the reader DID make decides,
       for both, whether they are still to be kept. */
    const doc = scroller.ownerDocument;
    const IO = typeof IntersectionObserver === "undefined" ? null : IntersectionObserver;
    const io = IO
      ? new IO(
          () => {
            holdReveal(false);
            keepFocusInView();
          },
          { threshold: [0, 0.5, 1] },
        )
      : null;
    watchRef.current = { io, targets: [] };
    const ro2 = RO ? new RO(keepFocusInView) : null;
    ro2?.observe(doc.body);
    const onDocScroll = (e: Event): void => {
      if (!hasFocus.current && !heldRef.current) return;
      const t = e.target;
      // The grid's own port has its own handler; a scroller that does not hold the grid is unrelated.
      if (t instanceof Node && t !== doc && (t === scroller || scroller.contains(t) || !t.contains(scroller))) return;
      if (!pageInputRef.current) {
        keepFocusInView();
        return;
      }
      const focused = focusedCellIn(scroller, hasFocus.current);
      if (focused !== null) focusKeptRef.current = Math.abs(offsetFromView(scroller, headRef.current, focused)) <= 1;
      /* The reader scrolled the page or a rail that carries the grid: the held row, by the grid's own
         rule, stays held only while it is still on screen. */
      const key = revealedKeyRef.current;
      const row = heldRef.current && key !== null ? rowRefs.current.get(key) : undefined;
      if (row !== undefined) heldRef.current = Math.abs(offsetFromView(scroller, headRef.current, row)) <= 1;
    };
    /* Reader input counts only when it scrolls a scroller that CARRIES the grid — the page or a rail
       holding it. MEASURED (A4, repair wave 8, 1440x900): counting any press or wheel anywhere let the
       press on "Trace this flow" and the wheel that zooms the canvas classify the rail's own
       re-layout scroll that followed as the reader's, which released the hold and left F026 at
       970-1026 below a port of 751-874. So: a wheel, touch or scroll key counts when the innermost
       scroller under it is the page or one of the grid's scrolling ancestors; a press counts only on
       such a scroller itself (its scrollbar). */
    const scrollsY = (a: Element): boolean => {
      const oy = view?.getComputedStyle(a).overflowY ?? "";
      return (oy === "auto" || oy === "scroll") && a.scrollHeight > a.clientHeight;
    };
    const carries = (a: Element): boolean => a === doc.documentElement || a === doc.body || (a !== scroller && a.contains(scroller));
    const onPageInput = (e: Event): void => {
      if (!hasFocus.current && !heldRef.current) return;
      const t = e.target;
      if (!(t instanceof Element)) return;
      // The grid's own keys and presses are the grid's (`readerInputRef`).
      if (scroller.contains(t) && e.type !== "wheel" && e.type !== "touchmove") return;
      if (e.type === "keydown" && !PAGE_SCROLL_KEYS.has((e as KeyboardEvent).key)) return;
      if (e.type === "pointerdown") {
        if (carries(t)) pageInputRef.current = true;
        return;
      }
      let a: Element | null = t;
      while (a !== null && a !== doc.documentElement && !scrollsY(a)) a = a.parentElement;
      if (a === null || a === doc.documentElement || a === scroller || carries(a)) pageInputRef.current = true;
    };
    const pageInputs = ["wheel", "touchmove", "pointerdown", "keydown"] as const;
    doc.addEventListener("scroll", onDocScroll, { capture: true, passive: true });
    for (const t of pageInputs) doc.addEventListener(t, onPageInput, { capture: true, passive: true });
    return () => {
      for (const t of inputs) scroller.removeEventListener(t, onUserInput);
      scroller.removeEventListener("pointerleave", onLeave);
      scroller.removeEventListener("scroll", onScroll);
      view?.removeEventListener("resize", onViewResize);
      doc.removeEventListener("scroll", onDocScroll, { capture: true });
      for (const t of pageInputs) doc.removeEventListener(t, onPageInput, { capture: true });
      ro?.disconnect();
      ro2?.disconnect();
      io?.disconnect();
      watchRef.current = { io: null, targets: [] };
    };
  }, [holdReveal, keepInView, keepFocusInView]);

  const move = useCallback(
    (row: number, col: number, keepDesired = false): void => {
      const r = clamp(row, 0, Math.max(0, rows.length - 1));
      // Travelling left searches left for a standable cell; every other move searches right.
      const c = landOn(r, col, r === focusCell.row && col < focusCell.col ? -1 : 1);
      if (!keepDesired) desiredCol.current = c;
      userMoved.current = true;
      // An unshifted move re-anchors: the next Shift+Arrow range starts where the user is now.
      anchorRow.current = null;
      setFocusCell({ row: r, col: c });
    },
    [rows.length, landOn, focusCell.row, focusCell.col],
  );

  /**
   * Move the roving cell AND replace the batch with every data row between the anchor and the
   * destination. Shrinking the range back toward the anchor deselects, because a range is the
   * span between two points, not an accumulation of visits.
   */
  const extendTo = useCallback(
    (row: number, col: number): void => {
      const r = clamp(row, 0, Math.max(0, rows.length - 1));
      const c = landOn(r, col, 1);
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
    [rows, landOn, onSelectRange, focusCell.row],
  );

  const leaveGrid = useCallback((): void => {
    /* Leaving goes SOMEWHERE: the declared exit target if it is still mounted, else the region
       landmark around the grid (the queue's labelled section), else focus stays on the cell.
       This used to `blur()` the cell whenever no exit target was declared, which parks focus on
       <body> (acceptance D3), and to focus a declared target without checking it was still
       mounted, which silently did nothing. The queue — the one production host today — no longer
       declares an exit target and handles every Escape itself (`onEscape` returns true), so this
       path is reached by a host that lets Escape through; it must still never drop focus. One
       owner decides: src/app/focus-return.ts. */
    returnFocus(exitFocusRef?.current ?? null, gridRef.current);
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
    focusInView(inner);
    return true;
  }, [focusInView]);

  const exitCellMode = useCallback((r: number, c: number): void => {
    setCellMode(false);
    const el = cellRefs.current.get(cellKey(r, c));
    el?.querySelectorAll<HTMLElement>("[tabindex='0']").forEach((n) => {
      n.tabIndex = -1;
    });
    if (el) focusInView(el);
  }, [focusInView]);

  const resizeBy = useCallback(
    (col: GridColumn<T>, delta: number | "reset"): void => {
      if (!onResizeColumn || !col.resizable) return;
      const current = own(columnWidths, col.id);
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
      activatedRef.current = { id: row.node.id, key: rowKeyOf(row.node) };
      setChosenCopy(rowKeyOf(row.node));
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
        // Ending on a clipped cell would search right and find nothing; land searching leftward.
        if (e.ctrlKey || e.metaKey) move(rows.length - 1, landOn(rows.length - 1, cellsIn(rows.length - 1) - 1, -1));
        else move(row, landOn(row, cellsIn(row) - 1, -1));
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
        if (colDef?.interactive && current.kind === "data") {
          /* A lone button needs no arrow keys of its own, so there is nothing to protect by
             holding it behind widget mode: the APG data grid operates it from the cell. MEASURED
             (A11Y critic, D2): the drill cell took Enter to reach the button, and Enter again to
             press it. Anything richer (several controls, a text field) still steps in. */
          const cellEl = cellRefs.current.get(cellKey(row, col));
          /* A sole-control cell registers the control itself as its roving element. */
          const controls = !cellEl
            ? []
            : cellEl.matches(SOLE_CONTROL_SELECTOR)
              ? [cellEl]
              : [...cellEl.querySelectorAll<HTMLElement>("button,a[href],input,select,textarea,[tabindex]")];
          const only = controls.length === 1 ? controls[0] : undefined;
          if (only instanceof HTMLButtonElement && !only.disabled && only.closest('[aria-hidden="true"]') === null) {
            only.click();
            return;
          }
          if (enterCellMode(row, col)) return;
        }
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

  /* The data rows are memoised (see DataRow), so what they call must not change identity from one
     grid render to the next. The latest closures ride in a ref, refreshed after every commit and
     therefore before any event a row can dispatch; the handler object itself lives for the grid's
     lifetime. */
  const latestRow = useRef({ move, onActivate });
  useLayoutEffect(() => {
    latestRow.current = { move, onActivate };
  });
  const rowHandlers = useMemo<RowHandlers<T>>(
    () => ({
      rowRef: (key, el) => {
        if (el) rowRefs.current.set(key, el);
        else rowRefs.current.delete(key);
      },
      cellRef: (r, c) => (el) => {
        if (el) cellRefs.current.set(`${r}:${c}`, el);
        else cellRefs.current.delete(`${r}:${c}`);
      },
      move: (r, c) => latestRow.current.move(r, c),
      moveKeepingColumn: (r) => latestRow.current.move(r, desiredCol.current, true),
      activate: (item, id, key) => {
        activatedRef.current = { id, key };
        setChosenCopy(key);
        latestRow.current.onActivate?.(item, id);
      },
    }),
    [],
  );

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
        {/* A clipped header cannot hold a pointer target either: its resizer measured 8x1 px, was
            still exposed as role=separator, and was reachable by neither pointer nor key
            (A11Y critic 2026-09-21, D5). Same predicate family as `hasSortControl`. */}
        {col.resizable && col.headerHidden !== true && onResizeColumn ? (
          <ColumnResizer
            column={col}
            widthPx={own(columnWidths, col.id)}
            headerRef={{ current: cellRefs.current.get(cellKey(0, c)) ?? null }}
            onResize={onResizeColumn}
          />
        ) : null}
      </div>
    );
  });

  const visible = nodes.slice(win.start, win.end);
  const orderId = `${gridId}-order`;
  const describedByAll = [describedBy, orderDescription ? orderId : undefined].filter(Boolean).join(" ");

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
        {...(describedByAll ? { "aria-describedby": describedByAll } : {})}
        id={gridId}
        className="ag__grid scroll-y"
        style={style}
        onKeyDown={(e) => {
          aimFocus.current = false;
          aimEntry.current = false;
          onKeyDown(e);
        }}
        onPointerDown={() => {
          aimFocus.current = false;
          aimEntry.current = false;
          pointerFocus.current = true;
          /* The focus a press causes is dispatched in the same task; a press on an already focused
             cell causes none, and must not mark a LATER keyboard arrival as the pointer's. */
          setTimeout(() => {
            pointerFocus.current = false;
          }, 0);
        }}
        onFocus={(e) => {
          hasFocus.current = true;
          focusKeptRef.current = true;
          pageInputRef.current = false;
          /* Focus ARRIVING from outside the grid by keyboard or script — Tab, a dialog restoring focus
             to its invoker — gets the same band-aware reveal as focus the grid moves itself. The
             browser's own focus scroll knows nothing of a bar painted over the grid: MEASURED (D3,
             1000x800, audit-d3-focus compact/idle) the roving cell restored by the palette's Escape
             sat at 763-780 under the status bar (774-800), its ring 38 px of indicator against a
             41 px floor. Nearest semantics, so a cell already in view does not move; a pointer's own
             focus is left alone, so a click never nudges the list under the pointer. */
          const fromPointer = pointerFocus.current;
          pointerFocus.current = false;
          if (!fromPointer && !e.currentTarget.contains(e.relatedTarget as Node | null)) {
            const scroller = gridRef.current;
            const target = e.target as HTMLElement;
            if (scroller && target !== scroller) revealBelowHeader(scroller, headRef.current, target);
            // …and again once whatever moved focus here has finished changing the layout.
            settleFocus();
          }
          /* Focus coming back from OUTSIDE the grid after an external selection moved the roving
             cell — a dialog restoring focus to the cell that opened it is the common case — lands
             on the roving cell, which is on the revealed row and therefore in view. Adopting the
             stale target instead would put focus far outside the scroll port (D3). */
          if (aimFocus.current && !e.currentTarget.contains(e.relatedTarget as Node | null)) {
            const { row, col } = focusCellRef.current;
            const roving = cellRefs.current.get(cellKey(row, col));
            if (roving === e.target || (roving !== undefined && roving.contains(e.target as Node))) {
              aimFocus.current = false;
            } else if (roving !== undefined) {
              aimFocus.current = false;
              focusInView(roving);
              return;
            } else if (windowing) {
              /* The roving row is outside the window — the restore's own scroll-into-view just
                 carried the port back to the stale cell. Page to the roving row; the effect
                 below focuses it the moment the window mounts it. Never adopt the stale cell. */
              const scroller = gridRef.current;
              aimEntry.current = true;
              if (scroller) scroller.scrollTop = Math.max(0, (row - 1) * windowing.rowHeightPx);
              return;
            } else {
              aimFocus.current = false;
            }
          }
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
          /* Focus arriving on a clipped header from outside the arrow model (a script, an AT
             "move to cell") is redirected to the nearest standable cell rather than adopted as the
             roving stop — adopting it is exactly how the invisible cell became the Tab stop. */
          move(r, landOn(r, c, 1));
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
                  className="ag__row ag__row--group"
                >
                  {/* aria-expanded lives on the CELL, not the row (A11Y critic, D2): an expandable
                      ROW is treegrid semantics, and on a plain grid's row the state is not reliably
                      announced. ARIA 1.2 supports aria-expanded on gridcell, and the cell is what
                      takes focus, so the state is read at the focus location. */}
                  <div
                    ref={setCellRef(r, 0)}
                    role="gridcell"
                    aria-expanded={!node.collapsed}
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
            return (
              <DataRow<T>
                key={node.key ?? node.id}
                node={node}
                r={r}
                columns={columns}
                layout={layout}
                batchable={onToggleBatch !== undefined}
                active={activeKey !== null && activeKey === rowKeyOf(node)}
                related={relatedIds?.has(node.id) ? (relatedDescription ?? "") : null}
                selected={batchIds?.has(node.id) ?? false}
                selectedCol={selectedCol}
                focusedCol={focusCell.row === r ? focusCell.col : -1}
                handlers={rowHandlers}
              />
            );
          })}
          {win.padBottom > 0 ? <div role="presentation" style={{ height: `${win.padBottom}px` }} /> : null}
        </div>
      </div>
      {/* The empty state sits OUTSIDE the grid. A fabricated row would put a count in
          aria-rowcount that no data backs, which is the same lie as a blank cell. */}
      {nodes.length === 0 && empty ? <div className="ag__empty">{empty}</div> : null}
      {orderDescription ? (
        <p className="visually-hidden" id={orderId}>
          {orderDescription}
        </p>
      ) : null}
      <LiveRegion message={announcement} />
      <BeforeCommit watch={actKey} capture={captureActView} />
    </div>
  );
}

/* ── data row ───────────────────────────────────────────────────────────────── */

/**
 * The stable callbacks every data row calls. One object for the grid's lifetime, reading the
 * grid's CURRENT closures through a ref, so passing it never breaks a row's memoisation.
 */
interface RowHandlers<T> {
  /** Keyed by `rowKeyOf`, so every rendered copy of an item keeps its own element. */
  rowRef: (key: string, el: HTMLElement | null) => void;
  cellRef: (r: number, c: number) => (el: HTMLElement | null) => void;
  move: (r: number, c: number) => void;
  moveKeepingColumn: (r: number) => void;
  /** `key` is the activated copy's `rowKeyOf`. */
  activate: (item: T, id: string, key: string) => void;
}

interface DataRowProps<T> {
  node: Extract<GridNode<T>, { kind: "row" }>;
  r: number;
  columns: readonly GridColumn<T>[];
  layout: "line" | "stacked";
  batchable: boolean;
  active: boolean;
  /** null = not related; a string (possibly empty) = related, with the relation in words. A string
   *  rather than a boolean + a second prop so the row's memo still compares primitives only. */
  related: string | null;
  selected: boolean;
  selectedCol: number | null;
  /** The roving cell's column when it stands in THIS row, else -1. */
  focusedCol: number;
  handlers: RowHandlers<T>;
}

/**
 * One data row, memoised on props that are all primitives or grid-lifetime references.
 *
 * RESPONSIVENESS FIX, 2026-09-21 (acceptance E2/E3, journey 1). Selecting a finding used to
 * re-render EVERY row and every cell of the grid: the rows were inline JSX in the grid's own render,
 * so a change to `activeId` re-ran all 146 rows' column renderers (severity badges, cite icons,
 * not-observed sentences). CPU profile on the dev build, 12 clicks: DataGrid 1656 ms inclusive of
 * which the row map was 1619 ms, against 20 ms for the evidence pane the click actually re-aims.
 * That commit is synchronous inside the click (a store write is an urgent update, design-brief
 * §8.3 rule 1), so it landed on the interaction path as the long `DIV#root.onclick` task.
 *
 * A selection change now re-renders the two rows whose `active` flag flipped (and, for a click,
 * the rows the roving cell left and entered), not the table.
 */
function DataRowImpl<T>({
  node,
  r,
  columns,
  layout,
  batchable,
  active,
  related,
  selected,
  selectedCol,
  focusedCol,
  handlers,
}: DataRowProps<T>): ReactNode {
  const relatedNote = related !== null && related !== "" ? related : null;
  return (
    <div
      role="row"
      ref={(el) => handlers.rowRef(rowKeyOf(node), el)}
      aria-rowindex={r + 1}
      {...(batchable ? { "aria-selected": selected } : {})}
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
      {...(active ? { "aria-current": true } : {})}
      /* A11Y CRITIC FIX (D8): the related mark is a trailing-edge line, which assistive technology
         cannot see. The relation is stated on the row itself as well as in the grid's count
         sentence, so a reader landing on a row learns it there. */
      {...(relatedNote ? { "aria-description": relatedNote } : {})}
      className="ag__row ag__row--data"
      data-active={active ? "yes" : undefined}
      data-related={related !== null ? "yes" : undefined}
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
        if (!inCell) handlers.moveKeepingColumn(r);
        handlers.activate(node.item, node.id, rowKeyOf(node));
      }}
    >
      {columns.map((col, c) => {
        const place = layout === "stacked" ? col.place : undefined;
        /* The row header is what screen readers repeat on a row change, so the relation rides in
           its accessible text too: `aria-description` on a row is not announced by every reader. */
        const noteHere = col.rowHeader === true && relatedNote !== null;
        const label = col.cellLabel
          ? noteHere
            ? `${col.cellLabel(node.item)}, ${relatedNote}`
            : col.cellLabel(node.item)
          : null;
        /* A sole-control cell hands its focus stop and its name to the control (see
           `GridColumn.soleControl`): the registered roving element is the control, so every
           focus the grid moves — arrows, Home/End, re-entry — lands on the widget itself. */
        const sole = col.soleControl === true && !noteHere;
        const cellRef = handlers.cellRef(r, c);
        return (
          <div
            key={col.id}
            ref={
              sole
                ? (el) => cellRef(el?.querySelector<HTMLElement>(SOLE_CONTROL_SELECTOR) ?? el)
                : cellRef
            }
            role={col.rowHeader ? "rowheader" : "gridcell"}
            aria-colindex={c + 1}
            {...(label !== null && !sole ? { "aria-label": label } : {})}
            {...(selectedCol === c ? { "aria-selected": true } : {})}
            {...(sole ? {} : { tabIndex: focusedCol === c ? 0 : -1 })}
            className="ag__cell"
            data-col={col.id}
            data-align={col.align ?? "start"}
            style={place ? { gridArea: place } : undefined}
            onClick={(e) => {
              handlers.move(r, c);
              // A cell holding its own control must not double-fire: the control's own
              // click handler already ran and stopped here. Stop the click before the
              // row sees it, since the row is what activates now.
              if (col.interactive) e.stopPropagation();
            }}
          >
            {cellContent(col, node.item, focusedCol === c ? 0 : -1)}
            {noteHere && label === null ? <span className="visually-hidden">{`, ${relatedNote}`}</span> : null}
          </div>
        );
      })}
    </div>
  );
}

/* `node` is compared by what it carries, not by identity: a caller that rebuilds its node list on
   a filter or group change hands every surviving row a fresh wrapper around the same item, and an
   identity test would re-render all of them for nothing. Every other prop is compared shallowly. */
function sameRowProps<T>(a: DataRowProps<T>, b: DataRowProps<T>): boolean {
  for (const k of Object.keys(b) as (keyof DataRowProps<T>)[]) {
    if (k === "node") {
      if (a.node.id !== b.node.id || a.node.item !== b.node.item || a.node.key !== b.node.key) return false;
    } else if (!Object.is(a[k], b[k])) {
      return false;
    }
  }
  return Object.keys(a).length === Object.keys(b).length;
}

const DataRow = memo(DataRowImpl, sameRowProps) as <T>(
  props: DataRowProps<T> & { key?: string },
) => ReactNode;

/* ── column resizer ─────────────────────────────────────────────────────────── */

/**
 * WCAG 2.5.7: the drag has a pointer-free twin. The handle is not a tab stop — the header cell
 * owns Shift+Arrow / Shift+Home for the same operation, so resizing costs no extra Tab presses in
 * a grid where the whole point is that there is exactly one.
 *
 * It is also NOT focusable at all (no `tabIndex`). ARIA 1.2 makes a focusable separator a widget
 * that must carry aria-valuenow/min/max; this one is a static, labelled structure whose keyboard
 * operation lives on the header cell, so a focusable-but-valueless separator inside an APG grid
 * was an incorrect aria surface (a11y audit D2, 2026-09-21).
 *
 * WCAG 2.5.8: the pointer hit area is 24 CSS px wide (DataGrid.css), centred on the column rule.
 *
 * WCAG 2.5.7 (dragging): the header-cell keys are a KEYBOARD twin, not a single-pointer one, and
 * they are invisible (A11Y critic, D1). The caller must also offer non-drag controls; the
 * priority queue's Display dialog carries Narrower / Wider / Auto per resizable column.
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
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onDoubleClick={() => onResize(column.id, 0)}
    />
  );
}
