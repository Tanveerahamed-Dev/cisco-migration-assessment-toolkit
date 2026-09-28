/**
 * PriorityQueue.filtered-reveal.test.tsx — acceptance A4 with a FILTER in force.
 *
 * THE DEFECT (refuter at 78bdba5, docs/acceptance-report.md, A4): `?q=severity:Critical`, then
 * Ctrl+K "F120" Enter. The URL, the status bar, the scope bar, the Inspector and the fabric label all
 * said F120 was selected; the queue showed `[Critical 3, F001, F002, F003, High 0, …]`, no grid
 * element carried aria-current or data-active, and the rail did not contain "F120" anywhere. The
 * reveal pointed at a row the filter had removed, so nothing was revealed and nothing was said.
 *
 * WHAT THE QUEUE DOES NOW, and what these tests hold it to:
 *   1. The selected row is PINNED above the filtered rows, under its own "Outside your filter"
 *      group, marked current and scrolled into view — with no interaction.
 *   2. The rail states it in words, naming every part of the filter that hides the row (the text
 *      the reader typed, or the scope chip it came from) and saying the filter is unchanged.
 *   3. One control widens the filter by exactly those parts, says what it removed, and the row is
 *      then shown IN PLACE, current and in view.
 * The reader's filter is never discarded silently: nothing changes until they press the control.
 *
 * "Every filter kind" is not a list typed here. The clause keys come from the grammar's own
 * registry (`FILTER_KEYS`), each in its positive and negated form; free text and excluded free text
 * are the other two token kinds the parser has; the scope chips are the three the store carries.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { actAsync } from "../test-support/act-turns";
import { fabric } from "../core/data";
import { applyToCrossLayer, applyToFindings, FILTER_KEYS, parseQuery, valueDomain } from "../core/query";
import { useInvestigation } from "../core/store";
import type { CrossLayerFinding, Finding } from "../core/types";
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

/* jsdom has no layout; see the same rig in PriorityQueue.test.tsx. A 561 px port, 40 px of sticky
   header, uniform 47 px data rows positioned from their index and the grid's live scrollTop. */
const VIEWPORT_PX = 561;
const HEAD_PX = 40;
const ROW_PX = 47;
let restoreLayout: (() => void) | null = null;
const rect = (top: number, bottom: number): DOMRect =>
  ({ top, bottom, left: 0, right: 900, width: 900, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;

function installLayout(container: HTMLElement): HTMLElement {
  const grid = container.querySelector<HTMLElement>(".ag__grid")!;
  let scrollTop = 0;
  Object.defineProperty(grid, "scrollTop", {
    configurable: true,
    get: () => scrollTop,
    set: (v: number) => {
      scrollTop = Math.max(0, v);
    },
  });
  const head = container.querySelector<HTMLElement>(".ag__head")!;
  Object.defineProperty(head, "offsetHeight", { configurable: true, get: () => HEAD_PX });
  const original = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function (this: HTMLElement): DOMRect {
    if (this.classList.contains("ag__grid")) return rect(0, VIEWPORT_PX);
    if (this.classList.contains("ag__row--data")) {
      const owner = this.closest<HTMLElement>(".ag__grid");
      const rows = owner ? [...owner.querySelectorAll<HTMLElement>(".ag__row--data")] : [];
      const i = rows.indexOf(this);
      const top = HEAD_PX + i * ROW_PX - (owner?.scrollTop ?? 0);
      return rect(top, top + ROW_PX);
    }
    return original.call(this) as DOMRect;
  };
  restoreLayout = () => {
    HTMLElement.prototype.getBoundingClientRect = original;
  };
  return grid;
}

const inView = (row: HTMLElement): boolean => {
  const r = row.getBoundingClientRect();
  return r.top >= HEAD_PX - 1 && r.bottom <= VIEWPORT_PX + 1;
};

beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    /* preferences are not evidence */
  }
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.setState({ evidenceTab: "summary" });
  });
});

afterEach(() => {
  restoreLayout?.();
  restoreLayout = null;
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
});

const textOf = (el: Element | null): string => el?.textContent ?? "";
const rowId = (row: Element): string => textOf(row.querySelector('[role="rowheader"]')).trim();

/** Let the queue's debounced echo (debounceMs 0 → one task) reach the store. */
async function flush(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await actAsync(async () => {
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
  }
}

const currentRows = (c: HTMLElement): HTMLElement[] => [...c.querySelectorAll<HTMLElement>('[role="grid"] [aria-current]')];
const outsideGroup = (c: HTMLElement): HTMLElement | undefined =>
  [...c.querySelectorAll<HTMLElement>(".ag__row--group")].find((g) => /outside your filter/i.test(textOf(g)));
const widenButton = (c: HTMLElement): HTMLButtonElement | undefined =>
  [...c.querySelectorAll<HTMLButtonElement>(".pq-pinned button")].find((b) => /in place/i.test(textOf(b)));

/**
 * The whole contract, for one filter and one hidden finding.
 * `hiding` is the text the statement must name — the clause or term as the reader typed it, or the
 * scope chip's clause.
 */
async function expectRevealedThenWidened(opts: {
  c: HTMLElement;
  grid: HTMLElement;
  selectId: string;
  rowLabel: string;
  hiding: string;
  stillFiltered: () => boolean;
}): Promise<void> {
  const { c, grid, selectId, rowLabel, hiding } = opts;
  act(() => { useInvestigation.getState().selectFinding(selectId); });
  await flush();

  /* 1. Discoverable in words, with the hiding filter named. */
  const note = c.querySelector<HTMLElement>(".pq-pinned");
  expect(note, `the rail must say that ${rowLabel} is selected but hidden (filter ${hiding})`).not.toBeNull();
  expect(textOf(note)).toContain(rowLabel);
  expect(textOf(note)).toContain(hiding);
  expect(textOf(note)).toMatch(/filter is unchanged/i);
  expect(opts.stillFiltered(), "the reader's filter must not be discarded by a selection").toBe(true);

  /* 2. Revealed: exactly one current row, it is the selection, it is in view, and it sits under the
        stated "outside your filter" group rather than masquerading as a filter match. */
  const current = currentRows(c);
  expect(current.map(rowId), "exactly one row is current, and it is the selection").toEqual([rowLabel]);
  expect(current[0]!.getAttribute("data-active")).toBe("yes");
  expect(inView(current[0]!), "the pinned row must be inside the scroll port").toBe(true);
  expect(outsideGroup(c), "the pinned row sits under a group that says it is outside the filter").toBeDefined();

  /* 3. The control: operable, named, and it widens by exactly the hiding part, saying so. */
  const button = widenButton(c);
  expect(button, "an operable control must offer to show the row in place").toBeDefined();
  expect(button!.getAttribute("aria-label") ?? "", "its name states what it will remove").toContain(hiding);
  /* Operated from the keyboard's position: the control holds focus when it removes itself. */
  act(() => button!.focus());
  expect(document.activeElement).toBe(button);
  act(() => {
    button!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await flush();
  await actAsync(async () => {
    await new Promise<void>((resolve) => setTimeout(resolve, 60));
  });
  const landedRow = currentRows(c)[0]!;
  expect(
    landedRow.contains(document.activeElement),
    "the control removed itself: focus lands on the row it put in place, never on <body>",
  ).toBe(true);
  /* The grid's single tab stop moved with the row. It used to stay at the pinned slot's index, so
     Tab into the grid after widening entered on whichever row now stood there (F001, measured). */
  const tabStops = [...c.querySelectorAll<HTMLElement>('[role="grid"] [tabindex="0"]')];
  expect(tabStops.length, "the grid keeps exactly one tab stop").toBe(1);
  expect(landedRow.contains(tabStops[0]!), "and it is on the landed row").toBe(true);

  expect(opts.stillFiltered(), `the control must remove ${hiding}`).toBe(false);
  expect(c.querySelector(".pq-pinned"), "once the row is in place nothing is pinned").toBeNull();
  expect(outsideGroup(c)).toBeUndefined();
  expect(textOf(c.querySelector(".pq-widened"))).toContain(`Removed ${hiding}`);
  const after = currentRows(c);
  expect(after.map(rowId), "exactly one row is current after widening").toEqual([rowLabel]);
  expect(inView(after[0]!), "the row shown in place must be scrolled into view").toBe(true);
  void grid;
}

/** A finding the given query hides from the punchlist, preferring one far down the ranked list so
 *  the in-place reveal after widening has to scroll. Null when the query hides nothing. */
function hiddenBy(query: string): Finding | null {
  const kept = new Set(applyToFindings(fabric.findings, parseQuery(query)).items.map((f) => f.id));
  const hidden = fabric.findings.filter((f) => !kept.has(f.id));
  return hidden.at(-1) ?? null;
}

const quote = (v: string): string => (/[\s,"]/.test(v) ? `"${v.replace(/"/g, "")}"` : v);

/** A value of `key` that hides at least one finding: from the snapshot's own domain when it has one. */
function hidingClause(key: string, negated: boolean): { clause: string; finding: Finding } | null {
  const domain = (valueDomain(key) ?? []).map((d) => d.value);
  for (const v of [...domain, "no-such-value"]) {
    const clause = `${negated ? "-" : ""}${key}:${quote(v)}`;
    const f = hiddenBy(clause);
    if (f) return { clause, finding: f };
  }
  return null;
}

describe("A4 under a filter: the refuter's case", () => {
  it("severity:Critical, then F120 from another surface: named, pinned, current, in view; then shown in place", async () => {
    const f120 = fabric.findings.find((f) => f.id === "F120");
    expect(f120, "the refuter's finding must exist in this snapshot").toBeDefined();
    expect(String(f120!.severity)).not.toBe("Critical");
    act(() => { useInvestigation.getState().setQuery("severity:Critical"); });
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    await expectRevealedThenWidened({
      c,
      grid,
      selectId: "F120",
      rowLabel: "F120",
      hiding: "severity:Critical",
      stillFiltered: () => useInvestigation.getState().query.includes("severity:Critical"),
    });
    expect(grid.scrollTop, "F120 is far below the fold of the full list, so showing it in place must scroll").toBeGreaterThan(0);
  });

  it("a finding the filter keeps is never pinned and nothing is said about it", async () => {
    act(() => { useInvestigation.getState().setQuery("severity:Critical"); });
    const c = mount(<PriorityQueue debounceMs={0} />);
    installLayout(c);
    const kept = fabric.findings.find((f) => String(f.severity) === "Critical")!;
    act(() => { useInvestigation.getState().selectFinding(kept.id); });
    await flush();
    expect(c.querySelector(".pq-pinned")).toBeNull();
    expect(outsideGroup(c)).toBeUndefined();
    expect(currentRows(c).map(rowId)).toEqual([kept.id]);
  });

  it("a device selection under a filter pins nothing and never narrows the corpus", async () => {
    act(() => { useInvestigation.getState().setQuery("severity:Critical"); });
    const c = mount(<PriorityQueue debounceMs={0} />);
    installLayout(c);
    const before = c.querySelectorAll(".ag__row--data").length;
    const host = fabric.findings.find((f) => String(f.severity) !== "Critical" && f.devices.length > 0)!.devices[0]!;
    act(() => { useInvestigation.getState().selectDevice(host); });
    await flush();
    expect(c.querySelector(".pq-pinned")).toBeNull();
    expect(outsideGroup(c)).toBeUndefined();
    expect(c.querySelectorAll(".ag__row--data").length).toBe(before);
    expect(useInvestigation.getState().query).toBe("severity:Critical");
  });
});

describe("A4 under a filter: the pinned group is a group like any other", () => {
  it("the reader may fold it; a NEW hidden selection opens it again; the filter never moves", async () => {
    act(() => { useInvestigation.getState().setQuery("severity:Critical"); });
    const c = mount(<PriorityQueue debounceMs={0} />);
    installLayout(c);
    act(() => { useInvestigation.getState().selectFinding("F120"); });
    await flush();
    const header = outsideGroup(c)!;
    expect(header).toBeDefined();
    act(() => {
      header.querySelector<HTMLElement>('[role="gridcell"]')!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flush();
    expect(outsideGroup(c)!.querySelector('[role="gridcell"]')?.getAttribute("aria-expanded")).toBe("false");
    expect(currentRows(c), "folded by the reader: the row is not forced back open").toHaveLength(0);
    expect(textOf(c.querySelector(".pq-pinned")), "the statement stays while the row is folded").toContain("F120");

    const other = fabric.findings.find((f) => String(f.severity) !== "Critical" && f.id !== "F120")!;
    act(() => { useInvestigation.getState().selectFinding(other.id); });
    await flush();
    expect(currentRows(c).map(rowId), "a new selection is revealed again").toEqual([other.id]);
    expect(useInvestigation.getState().query).toBe("severity:Critical");
  });
});

describe("A4 under a filter: every clause key the grammar registers, positive and negated", () => {
  const cases = FILTER_KEYS.flatMap((key) => [
    { key, negated: false },
    { key, negated: true },
  ]);
  it("the grammar registry is not empty (a vacuous loop proves nothing)", () => {
    expect(FILTER_KEYS.length).toBeGreaterThan(5);
  });
  for (const { key, negated } of cases) {
    it(`${negated ? "-" : ""}${key}: the hidden selection is named, pinned, revealed, then shown in place`, async () => {
      const hit = hidingClause(key, negated);
      expect(hit, `no value of ${key} hides any finding — the case must be constructible`).not.toBeNull();
      const { clause, finding } = hit!;
      act(() => { useInvestigation.getState().setQuery(clause); });
      const c = mount(<PriorityQueue debounceMs={0} />);
      const grid = installLayout(c);
      await expectRevealedThenWidened({
        c,
        grid,
        selectId: finding.id,
        rowLabel: finding.id,
        hiding: clause,
        stillFiltered: () => useInvestigation.getState().query.includes(clause),
      });
    });
  }
});

describe("A4 under a filter: free text, excluded text, and a clause beside text the row passes", () => {
  it("free text: the term the row lacks is named", async () => {
    /* A word some finding carries and the chosen one does not. */
    const withCore = fabric.findings.find((f) => f.devices.includes("core1"))!;
    expect(withCore).toBeDefined();
    const term = "core1";
    const hidden = hiddenBy(term)!;
    expect(hidden, "free text core1 must hide something").not.toBeNull();
    act(() => { useInvestigation.getState().setQuery(term); });
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    await expectRevealedThenWidened({
      c,
      grid,
      selectId: hidden.id,
      rowLabel: hidden.id,
      hiding: term,
      stillFiltered: () => useInvestigation.getState().query.includes(term),
    });
  });

  it("excluded free text (-term): the exclusion is named", async () => {
    const hidden = fabric.findings.find((f) => f.devices.includes("core1"))!;
    const term = "-core1";
    expect(hiddenBy(term), "-core1 must hide something").not.toBeNull();
    act(() => { useInvestigation.getState().setQuery(term); });
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    await expectRevealedThenWidened({
      c,
      grid,
      selectId: hidden.id,
      rowLabel: hidden.id,
      hiding: term,
      stillFiltered: () => useInvestigation.getState().query.includes(term),
    });
  });

  it("only the part that hides the row is removed; a part the row passes is kept", async () => {
    const f120 = fabric.findings.find((f) => f.id === "F120")!;
    const keep = `severity:${String(f120.severity)}`;
    const hide = "-F120";
    expect(applyToFindings([f120], parseQuery(keep)).items).toHaveLength(1);
    act(() => { useInvestigation.getState().setQuery(`${keep} ${hide}`); });
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    await expectRevealedThenWidened({
      c,
      grid,
      selectId: "F120",
      rowLabel: "F120",
      hiding: hide,
      stillFiltered: () => useInvestigation.getState().query.includes(hide),
    });
    expect(useInvestigation.getState().query.trim()).toBe(keep);
    expect(textOf(c.querySelector(".pq-widened"))).not.toContain(keep);
  });
});

describe("A4 under a filter: the scope chips the store carries", () => {
  const f120 = (): Finding => fabric.findings.find((f) => f.id === "F120")!;

  it("a severity chip: named, pinned, and the control removes the chip", async () => {
    const other = (["Critical", "High", "Medium", "Low", "Info"] as const).find((s) => s !== String(f120().severity))!;
    act(() => { useInvestigation.getState().toggleSeverity(other as Finding["severity"]); });
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    await expectRevealedThenWidened({
      c,
      grid,
      selectId: "F120",
      rowLabel: "F120",
      hiding: `severity:${other}`,
      stillFiltered: () => useInvestigation.getState().severities.size > 0,
    });
  });

  it("a role chip: named, pinned, and the control removes the chip", async () => {
    const roles = (valueDomain("role") ?? []).map((d) => d.value);
    let pick: { role: string; finding: Finding } | null = null;
    for (const role of roles) {
      const f = hiddenBy(`role:${quote(role)}`);
      if (f) {
        pick = { role, finding: f };
        break;
      }
    }
    expect(pick, "some role must hide some finding").not.toBeNull();
    act(() => { useInvestigation.getState().toggleRole(pick!.role); });
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    await expectRevealedThenWidened({
      c,
      grid,
      selectId: pick!.finding.id,
      rowLabel: pick!.finding.id,
      hiding: `role:${quote(pick!.role)}`,
      stillFiltered: () => useInvestigation.getState().roles.size > 0,
    });
  });

  it("the never-collected chip: named, pinned, and the control removes the chip", async () => {
    const hidden = hiddenBy("is:uncollected");
    expect(hidden, "is:uncollected must hide some finding").not.toBeNull();
    act(() => { useInvestigation.getState().setOnlyUncollected(true); });
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    await expectRevealedThenWidened({
      c,
      grid,
      selectId: hidden!.id,
      rowLabel: hidden!.id,
      hiding: "is:uncollected",
      stillFiltered: () => useInvestigation.getState().onlyUncollected,
    });
  });
});

describe("A4 under a filter: the cross-layer table", () => {
  /** Cross-layer records that join to exactly one punchlist row — the only ones a finding selection
   *  can land on (the queue's bridge). Recomputed from the data, not listed. */
  const bridged = (): { cross: CrossLayerFinding; finding: Finding }[] => {
    const out: { cross: CrossLayerFinding; finding: Finding }[] = [];
    for (const c of fabric.crossLayer) {
      const hits = fabric.findings.filter((f) => f.severity === c.severity && f.title === c.title && (f.detail ?? "") === (c.detail ?? ""));
      if (hits.length === 1) out.push({ cross: c, finding: hits[0]! });
    }
    return out;
  };

  for (const kind of ["severity", "layer"] as const) {
    it(`a ${kind} clause hiding the bridged cross-layer row: the cross-layer row is pinned, current and in view, then shown in place`, async () => {
      let pick: { clause: string; cross: CrossLayerFinding; finding: Finding } | null = null;
      for (const { cross, finding } of bridged()) {
        const values = (valueDomain(kind) ?? []).map((d) => d.value);
        for (const v of values) {
          const clause = `${kind}:${quote(v)}`;
          const kept = applyToCrossLayer(fabric.crossLayer, parseQuery(clause)).items;
          if (kept.length > 0 && !kept.includes(cross)) {
            pick = { clause, cross, finding };
            break;
          }
        }
        if (pick) break;
      }
      expect(pick, `some ${kind} clause must hide a bridged cross-layer row`).not.toBeNull();
      try {
        localStorage.setItem("atlas-scope.queue.corpus", "cross-layer");
      } catch {
        /* see beforeEach */
      }
      act(() => { useInvestigation.getState().setQuery(pick!.clause); });
      const c = mount(<PriorityQueue debounceMs={0} />);
      const grid = installLayout(c);
      await expectRevealedThenWidened({
        c,
        grid,
        selectId: pick!.finding.id,
        rowLabel: pick!.cross.id,
        hiding: pick!.clause,
        stillFiltered: () => useInvestigation.getState().query.includes(pick!.clause),
      });
      /* The queue stayed on the cross-layer table: the reader's table choice is context too. */
      expect(c.querySelector('[role="radio"][aria-checked="true"]')?.textContent).toContain("Cross-layer");
    });
  }
});
