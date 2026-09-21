/**
 * PriorityQueue.test.tsx — the honesty behaviour of the left rail, over the REAL compiled data.
 *
 * Every assertion here is derived from `fabric` at test time rather than from a number typed into
 * this file. A test that hardcodes "146" passes against a stale snapshot and tells you nothing;
 * a test that reads the denominator from the same place the UI does fails the moment the two
 * disagree, which is the only failure worth catching.
 *
 * The four things a critic will try to break, and which each have a test below:
 *   - an unrecognised filter key that silently matches everything;
 *   - a short list with no statement of what removed the rows;
 *   - an empty severity bucket quietly dropped, turning "zero at this severity" into silence;
 *   - a null rendered as a blank cell.
 */
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fabric, severityCounts } from "../core/data";
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
  try {
    localStorage.clear();
  } catch {
    /* preferences are not evidence; a locked-down storage is not a test failure */
  }
  act(() => {
    useInvestigation.getState().reset();
    useInvestigation.setState({ evidenceTab: "summary" });
  });
});

afterEach(() => {
  for (const m of mounted.splice(0)) {
    act(() => m.root.unmount());
    m.container.remove();
  }
  document.body.innerHTML = "";
});

const click = (el: Element): void => {
  act(() => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
};

const setQuery = (q: string): void => {
  act(() => useInvestigation.getState().setQuery(q));
};

const dataRows = (c: HTMLElement): HTMLElement[] => [...c.querySelectorAll<HTMLElement>(".ag__row--data")];
const groupRows = (c: HTMLElement): HTMLElement[] => [...c.querySelectorAll<HTMLElement>(".ag__row--group")];
const textOf = (c: HTMLElement): string => c.textContent ?? "";
const buttonNamed = (c: HTMLElement, text: string): HTMLElement => {
  const hit = [...c.querySelectorAll<HTMLElement>("button")].find((b) => textOf(b).includes(text));
  if (!hit) throw new Error(`no button containing ${JSON.stringify(text)}`);
  return hit;
};

/* ══ ranking and row anatomy ═══════════════════════════════════════════════ */

describe("the ranked queue", () => {
  it("ranks by severity, then priority, then rank", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    const ids = dataRows(c).map((r) => r.querySelector('[role="rowheader"]')?.textContent ?? "");
    const expected = [...fabric.findings]
      .sort(
        (a, b) =>
          ["Critical", "High", "Medium", "Low", "Info"].indexOf(a.severity) -
            ["Critical", "High", "Medium", "Low", "Info"].indexOf(b.severity) ||
          (a.priority ?? 1e9) - (b.priority ?? 1e9) ||
          (a.rank ?? 1e9) - (b.rank ?? 1e9) ||
          a.id.localeCompare(b.id),
      )
      .map((f) => f.id);
    expect(ids).toEqual(expected);
  });

  it("a row carries severity, id, title, category and devices — no useless truncation", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    const first = dataRows(c)[0]!;
    const finding = fabric.findings.find((f) => f.id === "F001")!;
    const t = textOf(first);
    expect(t).toContain(finding.id);
    // The FULL title is in the DOM, so the accessible name is never the visually truncated one.
    expect(t).toContain(finding.title);
    expect(t).toContain(finding.category ?? "");
    expect(t).toContain(finding.devices[0] ?? "");
    // Severity carries a non-colour channel as well as the colour (WCAG 1.4.1). In the 24px grid
    // track that channel is the INITIAL, not a 7px glyph: see SeverityBadge.
    expect(t).toContain(finding.severity);
    expect(first.querySelector('[data-severity="Critical"] .ui-sev__text')?.textContent).toBe("C");
  });

  it("a finding naming no device renders the unobserved treatment, never a blank cell", () => {
    const orphan = fabric.findings.find((f) => f.devices.length === 0);
    expect(orphan, "this snapshot must still contain a finding that names no device").toBeDefined();
    setQuery(orphan!.id);
    const c = mount(<PriorityQueue debounceMs={0} />);
    const row = dataRows(c).find((r) => textOf(r).includes(orphan!.id));
    expect(row).toBeDefined();
    /* Addressed by column id, not by ordinal: which ordinal a column occupies depends on which
       columns are on by default, and pinning the ordinal made this test fail for a reason that had
       nothing to do with the claim it is making. The device now LEADS the title cell, so that is
       where the absence has to be stated. */
    const titleCell = row!.querySelector<HTMLElement>('[data-col="title"]')!;
    expect(titleCell.querySelector("[data-unobserved='true']")).not.toBeNull();
    expect(textOf(titleCell)).toContain("not observed");
  });
});

/* ══ the windowing decision, measured rather than assumed ══════════════════ */

describe("bounded DOM", () => {
  it("renders every row unwindowed, and records the DOM size that decision rests on", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    // Every finding is in the DOM: at this corpus size the windowing hook is below its threshold,
    // so Ctrl+F finds every row and nothing is hidden behind a scroll position.
    expect(dataRows(c)).toHaveLength(fabric.findings.length);
    const cells = c.querySelectorAll('[role="gridcell"],[role="rowheader"],[role="columnheader"]').length;
    const elements = c.querySelectorAll("*").length;
    /* Measured 2026-09-21 on this snapshot: 887 cells, 3,546 elements for 146 rows plus five
       group headers — roughly 24 elements per row. That is well inside what a browser renders
       and scrolls without help, which is the whole basis of the decision not to window here.
       The bounds, not the exact numbers, so this fails if the grid starts emitting several times
       the DOM per row or if the corpus grows past the point where windowing has to turn on. */
    expect(cells).toBeLessThan(1400);
    expect(elements).toBeLessThan(4000);
    // The mechanism ships regardless and is exercised at 1,000 rows in DataGrid.test.tsx; it is
    // simply inactive here, which is a property of this snapshot and not of the component.
  });
});

/* ══ grouping ══════════════════════════════════════════════════════════════ */

describe("grouping states the denominator", () => {
  it("renders every severity group with its count, INCLUDING the empty ones", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    const counts = severityCounts(fabric.findings);
    const headers = groupRows(c).map(textOf);
    for (const [sev, n] of Object.entries(counts)) {
      const hit = headers.find((h) => h.startsWith(sev));
      expect(hit, `${sev} group must render`).toBeDefined();
      expect(hit).toContain(String(n));
    }
    // The point of the rule: at least one bucket really is zero in this snapshot, and it renders.
    const empties = Object.entries(counts).filter(([, n]) => n === 0);
    expect(empties.length).toBeGreaterThan(0);
    for (const [sev] of empties) {
      expect(headers.some((h) => h.startsWith(sev) && h.includes("0"))).toBe(true);
    }
  });

  it("a grouping key nothing was observed for lands in an explicit Not-observed bucket", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    const select = [...c.querySelectorAll<HTMLSelectElement>("select")][0]!;
    act(() => {
      select.value = "wave";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const unobservedCount = fabric.findings.filter((f) => f.wave === null).length;
    expect(unobservedCount).toBeGreaterThan(0);
    const header = groupRows(c).find((r) => textOf(r).includes("Not observed"));
    expect(header, "rows with no observed wave must get their own named bucket").toBeDefined();
    expect(textOf(header!)).toContain(String(unobservedCount));
    // And it says WHY, rather than presenting itself as just another value.
    expect(textOf(header!)).toContain("no wave value was collected");
  });

  it("a group collapses and its rows leave the row model rather than being hidden by CSS", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    const before = dataRows(c).length;
    const critical = groupRows(c).find((r) => textOf(r).startsWith("Critical"))!;
    click(critical.querySelector('[role="gridcell"]')!);
    expect(dataRows(c).length).toBe(before - severityCounts(fabric.findings)["Critical"]!);
    expect(critical.getAttribute("aria-expanded")).toBe("false");
  });
});

/* ══ the filter says what it did ═══════════════════════════════════════════ */

describe("filter accounting", () => {
  it("reports an unrecognised filter key instead of silently matching everything", () => {
    setQuery("nosuchkey:whatever");
    const c = mount(<PriorityQueue debounceMs={0} />);
    const alert = c.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(textOf(alert as HTMLElement)).toContain("nosuchkey");
    expect(textOf(alert as HTMLElement)).toContain("not a filter this data model answers");
    // Fails CLOSED: zero rows, not the whole unfiltered fleet dressed up as a result.
    expect(dataRows(c)).toHaveLength(0);
    expect(textOf(c)).toContain("No findings match this scope");
  });

  it("an empty result explains itself with the clause that emptied it", () => {
    // QoS carries exactly one finding in this snapshot and it is not Critical, so the pair is
    // genuinely empty rather than empty because the test guessed.
    setQuery("category:QoS severity:Critical");
    const c = mount(<PriorityQueue debounceMs={0} />);
    expect(dataRows(c)).toHaveLength(0);
    const t = textOf(c);
    expect(t).toContain("No findings match this scope");
    // The explanation names a clause and its numbers, not a generic "no results".
    expect(t).toMatch(/decided against \d+ of \d+ findings/);
    expect(t).toMatch(/without it \d+ would be shown/);
  });

  it("states how many rows a filter excluded, per clause, with an undetermined count kept apart", () => {
    setQuery("severity:Critical");
    const c = mount(<PriorityQueue debounceMs={0} />);
    const critical = severityCounts(fabric.findings)["Critical"]!;
    expect(dataRows(c)).toHaveLength(critical);
    expect(textOf(c)).toContain(`of ${fabric.findings.length} findings shown`);
    expect(textOf(c)).toContain(`${fabric.findings.length - critical} excluded`);

    click(buttonNamed(c, "Why?"));
    const clause = [...c.querySelectorAll<HTMLElement>(".pq-clause")].find((el) =>
      textOf(el).includes("severity:Critical"),
    );
    expect(clause).toBeDefined();
    expect(textOf(clause!)).toContain(`${critical} matched`);
    expect(textOf(clause!)).toContain(`${fabric.findings.length - critical} excluded`);
    expect(textOf(clause!)).toContain("undetermined");
  });

  it("a row nobody could decide is reported as undetermined, never as excluded", () => {
    /* `role:` is observed on only part of the fleet, so a finding naming a device whose role was
       never collected is UNDETERMINED. If that row were folded into "excluded", the panel would be
       republishing an unknown as a decided negative — the exact failure this product exists to
       prevent, one level up from the data. */
    const roles = [...new Set(fabric.devices.map((d) => d.role).filter((r): r is string => r !== null))];
    expect(roles.length).toBeGreaterThan(0);
    setQuery(`role:${roles[0]!}`);
    const c = mount(<PriorityQueue debounceMs={0} />);
    click(buttonNamed(c, "Why?"));
    const clause = [...c.querySelectorAll<HTMLElement>(".pq-clause")].find((el) => textOf(el).includes("role:"))!;
    const nums = textOf(clause);
    const matched = Number(/(\d+) matched/.exec(nums)?.[1]);
    const excluded = Number(/(\d+) excluded/.exec(nums)?.[1]);
    const undetermined = Number(/(\d+) undetermined/.exec(nums)?.[1]);
    expect(matched + excluded + undetermined).toBe(fabric.findings.length);
    expect(undetermined).toBeGreaterThan(0);
  });

  it("a value that matches nothing in this snapshot is marked in the query, not reported as an error", () => {
    setQuery("category:NotAThingHere");
    const c = mount(<PriorityQueue debounceMs={0} />);
    expect(c.querySelector('[data-unmatchable="yes"]')).not.toBeNull();
    // It is not an unrecognised KEY, so no alert fires: the grammar answered, the snapshot did not.
    expect(c.querySelector('[role="alert"]')).toBeNull();
  });

  it("carries the store's scope into the same accounting, as removable chips", () => {
    act(() => useInvestigation.getState().toggleSeverity("Critical"));
    const c = mount(<PriorityQueue debounceMs={0} />);
    expect(dataRows(c)).toHaveLength(severityCounts(fabric.findings)["Critical"]!);
    const chipRemove = c.querySelector<HTMLElement>('[aria-label="Remove the Critical severity filter"]');
    expect(chipRemove).not.toBeNull();
    click(chipRemove!);
    expect(useInvestigation.getState().severities.size).toBe(0);
    expect(dataRows(c)).toHaveLength(fabric.findings.length);
  });

  it("typing echoes immediately and the filter follows after the debounce", async () => {
    const c = mount(<PriorityQueue debounceMs={1} />);
    const input = c.querySelector<HTMLInputElement>(".pq-query__input")!;
    act(() => {
      /* React tracks the last value it wrote, so assigning `.value` directly makes it treat the
         following input event as a no-op. The native setter is how a React test types. */
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(
        input,
        "severity:Critical",
      );
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    // The character is on screen before any filtering has happened.
    expect(input.value).toBe("severity:Critical");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(useInvestigation.getState().query).toBe("severity:Critical");
    expect(dataRows(c)).toHaveLength(severityCounts(fabric.findings)["Critical"]!);
  });

  it("Tab out of the filter moves focus and does NOT accept a completion", async () => {
    /* THE REGRESSION. The completion menu opens on focus, and Tab used to accept the highlighted
       suggestion: a keyboard user tabbing through the page had the punchlist scoped from 146 rows
       to 3 by a navigation key, silently, without ever typing. A navigation key must not mutate
       the investigation — and `preventDefault` on Tab is what stopped focus moving at all. */
    const c = mount(<PriorityQueue debounceMs={1} />);
    const input = c.querySelector<HTMLInputElement>(".pq-query__input")!;
    act(() => input.focus());
    // Preconditions: the menu really is open with a live suggestion, so this is not a vacuous pass.
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(c.querySelector(".pq-suggest")).not.toBeNull();

    const ev = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    act(() => {
      input.dispatchEvent(ev);
    });
    // Not prevented: the browser's own focus move is what carries the user out of the field.
    expect(ev.defaultPrevented).toBe(false);
    expect(input.value).toBe("");
    // ...and the popup is gone before the next control can take focus (SC 2.4.11 / 2.4.12).
    expect(c.querySelector(".pq-suggest")).toBeNull();

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(useInvestigation.getState().query).toBe("");
    expect(dataRows(c)).toHaveLength(fabric.findings.length);
  });

  it("Enter still accepts the highlighted completion", () => {
    const c = mount(<PriorityQueue debounceMs={1} />);
    const input = c.querySelector<HTMLInputElement>(".pq-query__input")!;
    act(() => input.focus());
    const ev = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    act(() => {
      input.dispatchEvent(ev);
    });
    expect(ev.defaultPrevented).toBe(true);
    expect(input.value.length).toBeGreaterThan(0);
  });
});

/* ══ selection re-aims, it does not reset ══════════════════════════════════ */

describe("selection", () => {
  it("writes the shared selection and leaves the fabric and the flow untouched", () => {
    const device = fabric.devices[0]!;
    act(() =>
      useInvestigation.setState({
        deviceId: device.id,
        flow: { srcIp: "10.0.10.50", dstIp: "10.0.30.10", protocol: "tcp", dstPort: 3389, srcPort: null },
      }),
    );
    const c = mount(<PriorityQueue debounceMs={0} />);
    const target = fabric.findings.find((f) => f.id === "F003")!;
    const row = dataRows(c).find((r) => textOf(r).includes(target.id))!;
    click(row.querySelector('[aria-colindex="3"]')!);

    const s = useInvestigation.getState();
    expect(s.findingId).toBe(target.id);
    expect(s.deviceId, "selecting a finding must not clear the device the fabric is framed on").toBe(device.id);
    expect(s.flow, "selecting a finding must not discard the path question").not.toBeNull();
    // Rail B re-aims to the tab that can render this record — re-aiming, not blanking.
    expect(s.evidenceTab).toBe("findings");
    expect(row.getAttribute("data-active")).toBe("yes");
  });

  it("the drill affordance is a separate control from the row click", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    const row = dataRows(c)[0]!;
    const drill = row.querySelector<HTMLElement>('[data-col="drill"] button')!;
    expect(drill.getAttribute("aria-label")).toContain("Open the source record");
    click(drill);
    const s = useInvestigation.getState();
    expect(s.evidenceTab).toBe("raw");
    expect(s.findingId).toBe("F001");
  });
});

/* ══ the batch is a third state, and it does something ═════════════════════ */

describe("batch selection", () => {
  const keyOn = (el: EventTarget, k: string, init: KeyboardEventInit = {}): void => {
    act(() => {
      el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init }));
    });
  };

  it("X adds a row to the batch without moving the investigation selection", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    const cell = dataRows(c)[0]!.querySelector<HTMLElement>('[role="rowheader"]')!;
    act(() => cell.focus());
    keyOn(document.activeElement!, "x");
    expect(dataRows(c)[0]!.getAttribute("data-batched")).toBe("yes");
    expect(dataRows(c)[0]!.getAttribute("aria-selected")).toBe("true");
    // Focus and selection stay exactly where they were: three separate states.
    expect(useInvestigation.getState().findingId).toBeNull();
    expect(textOf(c)).toContain("1 selected");
  });

  it("Ctrl+A selects everything matching the FILTER, not the whole snapshot", () => {
    setQuery("severity:Critical");
    const c = mount(<PriorityQueue debounceMs={0} />);
    const cell = dataRows(c)[0]!.querySelector<HTMLElement>('[role="rowheader"]')!;
    act(() => cell.focus());
    keyOn(document.activeElement!, "a", { ctrlKey: true });
    const critical = severityCounts(fabric.findings)["Critical"]!;
    expect(textOf(c)).toContain(`${critical} selected`);
    expect(critical).toBeLessThan(fabric.findings.length);
  });

  it("Shift+ArrowDown extends the batch from the focused row, and Shift+ArrowUp shrinks it back", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    // Anchored well inside the High group, so the range never crosses a group header row (a group
    // row carries no finding, so extending onto one adds nothing — correct, but not what this
    // test is about).
    const cell = dataRows(c)[8]!.querySelector<HTMLElement>('[role="rowheader"]')!;
    act(() => cell.focus());
    // The grid declares aria-multiselectable; range extension is the key that claim implies.
    expect(c.querySelector('[role="grid"]')!.getAttribute("aria-multiselectable")).toBe("true");
    keyOn(document.activeElement!, "ArrowDown", { shiftKey: true });
    expect(textOf(c)).toContain("2 selected");
    keyOn(document.activeElement!, "ArrowDown", { shiftKey: true });
    expect(textOf(c)).toContain("3 selected");
    // A range is the span between anchor and focus, not an accumulation of visits.
    keyOn(document.activeElement!, "ArrowUp", { shiftKey: true });
    expect(textOf(c)).toContain("2 selected");
    // An UNSHIFTED move re-anchors: the next range starts where the user now is.
    keyOn(document.activeElement!, "ArrowDown");
    keyOn(document.activeElement!, "ArrowDown", { shiftKey: true });
    expect(textOf(c)).toContain("2 selected");
  });

  it("Escape clears the batch before it clears the selection", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    const cell = dataRows(c)[0]!.querySelector<HTMLElement>('[role="rowheader"]')!;
    act(() => cell.focus());
    click(dataRows(c)[0]!.querySelector('[aria-colindex="3"]')!);
    keyOn(document.activeElement!, "x");
    expect(textOf(c)).toContain("1 selected");
    keyOn(document.activeElement!, "Escape");
    expect(textOf(c)).not.toContain("1 selected");
    expect(useInvestigation.getState().findingId).not.toBeNull();
    keyOn(document.activeElement!, "Escape");
    expect(useInvestigation.getState().findingId).toBeNull();
  });
});

/* ══ the cross-layer corpus ════════════════════════════════════════════════ */

describe("the cross-layer corpus", () => {
  it("is switched to, counted separately, and never concatenated with the punchlist", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    const toggle = [...c.querySelectorAll<HTMLElement>('[role="radio"]')].find((b) =>
      textOf(b).includes("Cross-layer"),
    )!;
    expect(textOf(toggle)).toContain(String(fabric.crossLayer.length));
    click(toggle);
    expect(dataRows(c)).toHaveLength(fabric.crossLayer.length);
    // The layers field exists here and nowhere in the punchlist view — that is why they are two
    // views rather than one concatenated list.
    expect(textOf(c)).toContain(fabric.crossLayer[0]!.layers ?? "");
  });

  it("selecting a cross-layer record re-aims the shared selection at the punchlist row it joins to", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    click([...c.querySelectorAll<HTMLElement>('[role="radio"]')].find((b) => textOf(b).includes("Cross-layer"))!);
    const row = dataRows(c)[0]!;
    click(row.querySelector('[aria-colindex="3"]')!);
    const id = useInvestigation.getState().findingId;
    expect(id).not.toBeNull();
    const finding = fabric.findings.find((f) => f.id === id);
    expect(finding, "the join must resolve to a real punchlist row").toBeDefined();
    // The join is on the record itself, so the two rows must describe the same thing.
    expect(fabric.crossLayer.some((x) => x.title === finding!.title && x.severity === finding!.severity)).toBe(true);
  });
});

/* ══ reveal: a selection that arrives from another surface ═════════════════ */

/**
 * jsdom has no layout. Every `getBoundingClientRect` is a zero rect, so the reveal effect's
 * question — "is this row inside the scroll port?" — answers "yes" for every row on earth, and the
 * defect these tests guard (an active row 6,171 px below the fold, never scrolled to) is
 * structurally unobservable. That is exactly why the existing `data-active` assertion above passed
 * while the behaviour was missing.
 *
 * So the layout is supplied: a 561 px scroll port with 40 px of sticky header over uniform 47 px
 * rows, positioned from the element's own index and the grid's live scrollTop. Nothing here
 * asserts a constant — the assertions are about what MOVED.
 */
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

describe("a selection from another surface is revealed, not merely marked", () => {
  afterEach(() => {
    restoreLayout?.();
    restoreLayout = null;
  });

  it("scrolls a finding set through the STORE — no row was clicked — into view", () => {
    /* The direction the existing `data-active` test never exercises: the finding arrives from the
       Inspector, the command palette or a restored URL, so nothing in the queue put it there. */
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    const deep = dataRows(c).at(-1)!;
    const id = deep.querySelector('[role="rowheader"]')?.textContent?.trim() ?? "";
    expect(id, "the last row must carry a finding id to select").toMatch(/^F\d+/);
    expect(inView(deep), "the row must start below the fold or this test proves nothing").toBe(false);

    act(() => useInvestigation.getState().selectFinding(id));

    const revealed = dataRows(c).find((r) => r.getAttribute("data-active") === "yes")!;
    expect(revealed.getAttribute("data-active")).toBe("yes");
    expect(grid.scrollTop, "the grid must have scrolled").toBeGreaterThan(0);
    expect(inView(revealed), "the active row must be inside the scroll port").toBe(true);
  });

  it("leaves the scroll position alone when the active row is already visible", () => {
    /* The other half of A4: re-aiming must not throw away the reader's place. A row inside the
       port is already the answer, so the correct amount of scrolling is none. */
    const c = mount(<PriorityQueue debounceMs={0} />);
    const grid = installLayout(c);
    const first = dataRows(c)[0]!;
    const id = first.querySelector('[role="rowheader"]')?.textContent?.trim() ?? "";
    expect(inView(first)).toBe(true);

    act(() => useInvestigation.getState().selectFinding(id));
    expect(grid.scrollTop).toBe(0);
  });

  it("marks the rows naming a device selected elsewhere, and says how many in words", () => {
    /* Before this, `?d=core2` produced a byte-identical grid: the queue was the one surface a
       device selection did not reach. */
    const c = mount(<PriorityQueue debounceMs={0} />);
    installLayout(c);
    expect(c.querySelectorAll('[data-related="yes"]')).toHaveLength(0);

    const host = "core2";
    const expected = fabric.findings.filter((f) => f.devices.includes(host)).length;
    expect(expected, "this test needs a host some finding names").toBeGreaterThan(0);

    act(() => useInvestigation.getState().selectDevice(host));

    const marked = [...c.querySelectorAll<HTMLElement>('[data-related="yes"]')];
    expect(marked).toHaveLength(expected);
    for (const row of marked) expect(textOf(row)).toContain(host);
    expect(textOf(c)).toContain(`${expected} of ${fabric.findings.length} shown findings name ${host}`);
  });

  it("says nothing is published rather than nothing is wrong when no row names the device", () => {
    const c = mount(<PriorityQueue debounceMs={0} />);
    installLayout(c);
    const quiet = fabric.devices.find((d) => !fabric.findings.some((f) => f.devices.includes(d.host)));
    if (!quiet) return; // every device carries a finding in this snapshot; nothing to assert
    act(() => useInvestigation.getState().selectDevice(quiet.id));
    expect(c.querySelectorAll('[data-related="yes"]')).toHaveLength(0);
    expect(textOf(c)).toContain("not an assessment that");
  });
});
