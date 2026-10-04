/**
 * PriorityQueue.sort-truth.test.tsx — every sort the queue announces is the order on screen (D2).
 *
 * THE DEFECT, measured by the D2 refuter in the release build (1920x1080, default queue): Enter on
 * the Severity header, or a click on its sort button, flipped `aria-sort` between "ascending" and
 * "descending" while the rows did not move at all — the row-order hash was identical in every state
 * and Critical came first every time. The groups came out in the fixed severity order and the sort
 * only reordered rows WITHIN a group, where every row shares one severity. A screen reader was told
 * the column was sorted in two opposite directions over the same rows.
 *
 * That is one instance of a class: a sort on the field a grouping is made of is a no-op inside each
 * group. So this guard is not about Severity. For BOTH corpora, BOTH densities and EVERY grouping the
 * Group control offers (read from the control, not listed here), it activates every sort the grid
 * offers — each header's sort control, twice, and every Order option for a field that has no header
 * in that density — and checks the rows against what is announced:
 *   - inside every group, the rows are in the announced direction of that field (unknowns last);
 *   - where the field holds one value per group (the grouping IS that field), the groups themselves
 *     are in the announced direction, so the whole list is;
 *   - ascending and descending are different orders whenever the field has two values to order.
 * Over the REAL compiled snapshot, because the defect lived in its shape: it was this snapshot's data
 * that made `rank` hold one value per severity, a no-op sort no list of groupings would have named.
 * Each field under each grouping is its own test, one unit of work per test (vitest.config.ts).
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import { findingSortCell, type FindingSortField } from "../core/query";
import { useInvestigation } from "../core/store";
import type { CrossLayerFinding, Finding } from "../core/types";
import { crossSortCell, PriorityQueue, QUEUE_GROUPINGS, QUEUE_SORT_COLUMNS } from "./PriorityQueue";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const PREF = "atlas-scope.queue.";
/** Mounted by one test and removed after it; a grouping's shared mount is removed by its own afterAll. */
const mounted: { root: Root; container: HTMLElement }[] = [];

beforeEach(() => {
  localStorage.clear();
  act(() => {
    useInvestigation.getState().reset();
  });
});
afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  localStorage.clear();
});

type Cell = string | number | null;
type Corpus = "findings" | "cross-layer";

/** The record a row shows, by its evidence control's name — the one label both corpora carry, and the
 *  only one that is unique for a cross-layer record (its id repeats across citations). */
const records = (corpus: Corpus): Map<string, Finding | CrossLayerFinding> => {
  const out = new Map<string, Finding | CrossLayerFinding>();
  for (const r of corpus === "findings" ? fabric.findings : fabric.crossLayer) out.set(`${r.id} at ${r.cite}`, r);
  return out;
};

const cellOf = (corpus: Corpus, item: Finding | CrossLayerFinding, field: string): Cell =>
  corpus === "findings" ? findingSortCell(item as Finding, field as FindingSortField) : crossSortCell(item as CrossLayerFinding, field);

/** Unknown sinks in both directions; otherwise numbers by value and text by code unit. Restated here
 *  rather than imported, so the guard does not share the comparator it is checking. */
const inOrder = (a: Cell, b: Cell, dir: "asc" | "desc"): boolean => {
  if (b === null) return true;
  if (a === null) return false;
  const base = typeof a === "number" && typeof b === "number" ? a - b : a < b ? -1 : a > b ? 1 : 0;
  return (dir === "asc" ? base : -base) <= 0;
};

interface Shown {
  groups: { label: string; cells: Cell[] }[];
  ids: string[];
}

function shown(c: HTMLElement, corpus: Corpus, field: string): Shown {
  const byLabel = records(corpus);
  const groups: Shown["groups"] = [];
  const ids: string[] = [];
  for (const row of c.querySelectorAll<HTMLElement>('[role="grid"] .ag__row--group, [role="grid"] .ag__row--data')) {
    if (row.classList.contains("ag__row--group")) {
      groups.push({ label: (row.textContent ?? "").trim(), cells: [] });
      continue;
    }
    const name = row.querySelector('[data-col="drill"] button')?.getAttribute("aria-label") ?? "";
    const key = name.replace(/^Open the source record for /, "");
    const item = byLabel.get(key);
    if (!item) throw new Error(`a row whose record is not in the snapshot: ${JSON.stringify(name)}`);
    if (groups.length === 0) groups.push({ label: "(ungrouped)", cells: [] });
    groups[groups.length - 1]!.cells.push(cellOf(corpus, item, field));
    ids.push(key);
  }
  return { groups, ids };
}

/** Every way the order on screen can contradict an announced `field`/`dir`; empty when it does not. */
function contradictions(s: Shown, dir: "asc" | "desc"): string[] {
  const out: string[] = [];
  for (const g of s.groups) {
    for (let i = 1; i < g.cells.length; i += 1) {
      if (!inOrder(g.cells[i - 1]!, g.cells[i]!, dir)) out.push(`in "${g.label}": ${String(g.cells[i - 1])} before ${String(g.cells[i])}`);
    }
  }
  const nonEmpty = s.groups.filter((g) => g.cells.length > 0);
  const onePerGroup = nonEmpty.every((g) => g.cells.every((v) => v === g.cells[0]));
  if (onePerGroup) {
    for (let i = 1; i < nonEmpty.length; i += 1) {
      const a = nonEmpty[i - 1]!;
      const b = nonEmpty[i]!;
      if (!inOrder(a.cells[0]!, b.cells[0]!, dir)) out.push(`group "${a.label}" (${String(a.cells[0])}) before group "${b.label}" (${String(b.cells[0])})`);
    }
  }
  return out;
}

/** Two values to order: then ascending and descending cannot be the same row order. */
const orderable = (s: Shown): boolean => {
  const nonEmpty = s.groups.filter((g) => g.cells.length > 0);
  const within = nonEmpty.some((g) => new Set(g.cells.filter((v) => v !== null)).size > 1);
  const across = new Set(nonEmpty.map((g) => g.cells[0]).filter((v) => v !== null)).size > 1 &&
    nonEmpty.every((g) => g.cells.every((v) => v === g.cells[0]));
  return within || across;
};

const selects = (c: HTMLElement): HTMLSelectElement[] => [...c.querySelectorAll<HTMLSelectElement>(".pq-controls select")];
const groupSelect = (c: HTMLElement): HTMLSelectElement => selects(c)[0]!;
const orderSelect = (c: HTMLElement): HTMLSelectElement => selects(c)[1]!;
const setSelect = (s: HTMLSelectElement, value: string): void => {
  act(() => {
    s.value = value;
    s.dispatchEvent(new Event("change", { bubbles: true }));
  });
};

/** The field a header sorts by, read back from the Order control the header click just moved. */
const orderedBy = (c: HTMLElement): { field: string; dir: "asc" | "desc" } | null => {
  const v = orderSelect(c).value;
  if (v === "ranked") return null;
  const [field, dir] = v.split(":");
  return { field: field!, dir: dir === "desc" ? "desc" : "asc" };
};

const ARIA: Record<"asc" | "desc", string> = { asc: "ascending", desc: "descending" };

type Density = "comfortable" | "compact";

function mountQueue(corpus: Corpus, density: Density, groupKey: string): { root: Root; container: HTMLElement } {
  localStorage.setItem(`${PREF}corpus`, corpus);
  localStorage.setItem(`${PREF}density`, density);
  // Every column on: in the compact density each sortable field then has a header of its own.
  localStorage.setItem(`${PREF}hiddenColumns`, "");
  localStorage.setItem(`${PREF}groupKey`, groupKey);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(<PriorityQueue debounceMs={0} />));
  return { root, container };
}

/** The column whose header sort control sorts by `field` in this grid, or null when no header offers it. */
const headerFor = (c: HTMLElement, corpus: Corpus, field: string): string | null =>
  [...c.querySelectorAll<HTMLElement>('[role="columnheader"]')]
    .filter((h) => h.querySelector(".ag__sortbtn") !== null)
    .map((h) => h.dataset.col!)
    .find((col) => QUEUE_SORT_COLUMNS[corpus][col] === field) ?? null;

/**
 * One sortable field, both directions, through the control the grid offers for it: its header's sort
 * control (pressed twice; `aria-sort` is the claim), or — a field with no header here, folded into the
 * title line in the comfortable density — the Order control (the order description is the claim).
 */
function sortTruth(c: HTMLElement, corpus: Corpus, field: string, where: string): string[] {
  const failures: string[] = [];
  const col = headerFor(c, corpus, field);
  const states: { dir: "asc" | "desc"; ids: string[]; can: boolean }[] = [];
  for (const want of ["asc", "desc"] as const) {
    let dir: "asc" | "desc" = want;
    let claim = `Order "${field}:${want}"`;
    if (col !== null) {
      act(() => c.querySelector<HTMLButtonElement>(`[role="columnheader"][data-col="${col}"] .ag__sortbtn`)!.click());
      const now = orderedBy(c);
      const aria = c.querySelector(`[role="columnheader"][data-col="${col}"]`)?.getAttribute("aria-sort");
      claim = `${col} aria-sort=${aria}`;
      if (now === null || now.field !== field) {
        failures.push(`${where}: the ${col} header sort ordered by ${now === null ? "nothing" : now.field}, not ${field}`);
        continue;
      }
      dir = now.dir;
      if (aria !== ARIA[dir]) failures.push(`${where}: ${claim} while the order is ${field} ${dir}`);
    } else {
      setSelect(orderSelect(c), `${field}:${want}`);
      if (orderSelect(c).value !== `${field}:${want}`) failures.push(`${where}: the Order control has no "${field}:${want}"`);
    }
    const s = shown(c, corpus, field);
    for (const x of contradictions(s, dir)) failures.push(`${where}: ${claim}: ${x}`);
    states.push({ dir, ids: s.ids, can: orderable(s) });
  }
  const [a, b] = states;
  if (a && b && a.dir !== b.dir && a.can && a.ids.join() === b.ids.join()) {
    failures.push(`${where}: ${field} announced ${ARIA[a.dir]} then ${ARIA[b.dir]} over the SAME row order`);
  }
  return failures;
}

/* What this guard enumerates is the queue's own: the Group control offers exactly the exported
   groupings, every header with a sort control maps to an exported sort field, and the Order control
   offers both directions of every one of those fields — so a grouping, column or field added to the
   queue is covered without being named here. */
describe("the guard enumerates the queue's own groupings and sort fields", () => {
  for (const corpus of ["findings", "cross-layer"] as const) {
    for (const density of ["comfortable", "compact"] as const) {
      it(`${corpus}, ${density}`, () => {
        const m = mountQueue(corpus, density, "severity");
        mounted.push(m);
        const c = m.container;
        expect([...groupSelect(c).options].map((o) => o.value)).toEqual(QUEUE_GROUPINGS[corpus].map((g) => g.value));
        const fields = Object.values(QUEUE_SORT_COLUMNS[corpus]);
        for (const h of c.querySelectorAll<HTMLElement>('[role="columnheader"]')) {
          if (h.querySelector(".ag__sortbtn") === null) continue;
          expect(fields, `the ${h.dataset.col} header sorts by an enumerated field`).toContain(QUEUE_SORT_COLUMNS[corpus][h.dataset.col!]);
        }
        const offered = [...orderSelect(c).options].map((o) => o.value).filter((v) => v !== "ranked").sort();
        expect(offered).toEqual(fields.flatMap((f) => [`${f}:asc`, `${f}:desc`]).sort());
      });
    }
  }
});

/* One grouping is mounted once and every field is its own test: the unit of work stays one sort, the
   mount is not repeated per field (vitest.config.ts — split, never a bigger limit). */
for (const corpus of ["findings", "cross-layer"] as const) {
  for (const density of ["comfortable", "compact"] as const) {
    for (const { value: groupKey } of QUEUE_GROUPINGS[corpus]) {
      describe(`${corpus}, ${density}, grouped by ${groupKey}: every announced sort is the order on screen`, () => {
        let shared: { root: Root; container: HTMLElement } | null = null;
        beforeAll(() => {
          shared = mountQueue(corpus, density, groupKey);
        });
        afterAll(() => {
          if (shared) {
            const s = shared;
            act(() => s.root.unmount());
            s.container.remove();
          }
          shared = null;
        });
        for (const field of new Set(Object.values(QUEUE_SORT_COLUMNS[corpus]))) {
          it(field, () => {
            const c = shared!.container;
            expect(groupSelect(c).value, "the grouping under test is the one shown").toBe(groupKey);
            expect(sortTruth(c, corpus, field, `${density}, grouped by ${groupKey}`)).toEqual([]);
          });
        }
      });
    }
  }
}
