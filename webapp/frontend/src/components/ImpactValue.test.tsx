import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import {
  IMPACT_FIELDS,
  IMPACT_NOT_ASSESSED,
  IMPACT_ROOT_WITNESS,
  ImpactLowerBoundTag,
  ImpactValue,
  impactEntryValue,
  impactReasonText,
  impactStateText,
  impactTableCell,
  isImpactNotAssessed,
  parseImpactBound,
  projectionImpactBound,
  type ImpactValueState,
} from "./ImpactValue";

// W47 / F8: the four states webapp/backend/summary.py publishes for a failure-impact value (W27) must stay distinct.
// Shapes below are copied from webapp/tests/test_impact_surfaces.py's assertions on the real backend output.
const WHY = "the stored cable map cables this switch to a neighbour it does not show as collected (1 cable row(s)), "
  + "and the simulation counts only endpoints on scanned switches";
const BOUND_CELL = (v: string | number) => `≥ ${v} — a lower bound, not an exact measurement: ${WHY}`;
const HELD = "not collected: analyze.compute_failure_impact could not simulate this switch's blast radius (its detail "
  + "says why), so its severity and counts are not measurements";
const core2 = {
  host: "core2", severity: "High", stranded: 42, vlans_impacted: 3,
  detail: `LOWER BOUND, at least 42 endpoint(s) stranded: ${WHY}. VLAN 10: Hard partition`,
  lower_bound: true, lower_bound_reasons: [WHY], lower_bound_pointers: ["/cable_map/cables/35"],
};
const disclosure = {
  host: "", severity: "NOT ASSESSED", stranded: null, vlans_impacted: null, n_not_ranked: 2,
  detail: "2 failure-impact row(s) were not ranked because the engine withholds their host, severity or stranded count.",
};

const shown = (state: ImpactValueState) => render(<ImpactValue state={state} />).container;
/** The element a value's aria-describedby names: its reason, reachable by focus and by assistive tech. */
const reasonOf = (value: Element) => {
  const id = value.getAttribute("aria-describedby");
  expect(id).toBeTruthy();
  return document.getElementById(id!);
};

describe("impact value classification (one rule for every surface)", () => {
  it("reads a keystone or worst-case count in its engine state, never coercing it", () => {
    expect(impactEntryValue(core2, "stranded")).toEqual({ kind: "lower_bound", value: 42, why: WHY });
    expect(impactEntryValue(core2, "vlans_impacted")).toMatchObject({ kind: "lower_bound", value: 3 });
    expect(impactEntryValue(disclosure, "stranded")).toEqual({ kind: "not_assessed", why: disclosure.detail });
    expect(impactEntryValue(disclosure, "vlans_impacted").kind).toBe("not_assessed");
    expect(isImpactNotAssessed(disclosure)).toBe(true);
    expect(isImpactNotAssessed(core2)).toBe(false);
    // a ranked entry whose VLAN count the engine withholds (summary.impact_entry's None)
    expect(impactEntryValue({ ...core2, lower_bound: false, vlans_impacted: null }, "vlans_impacted").kind).toBe("unavailable");
    // a measured zero stays a zero; a count that is not a number is never read as one
    expect(impactEntryValue({ ...core2, lower_bound: false, stranded: 0 }, "stranded")).toEqual({ kind: "measured", value: 0 });
    for (const bad of ["3", Number.NaN, Number.POSITIVE_INFINITY, undefined, {}]) {
      expect(impactEntryValue({ ...core2, lower_bound: false, stranded: bad as never }, "stranded").kind).toBe("unavailable");
    }
    expect(impactEntryValue(null, "stranded").kind).toBe("unavailable");
  });

  it("reads each failure-impact tab cell as the backend owner wrote it", () => {
    expect(parseImpactBound(BOUND_CELL(42))).toEqual({ kind: "lower_bound", value: 42, why: WHY });
    expect(impactTableCell("stranded", BOUND_CELL(42))).toEqual({ kind: "lower_bound", value: 42, why: WHY });
    expect(impactTableCell("severity", BOUND_CELL("High"))).toEqual({ kind: "lower_bound", value: "High", why: WHY });
    expect(impactTableCell("stranded", HELD)).toEqual({ kind: "not_assessed", why: HELD });
    expect(impactTableCell("severity", HELD)).toEqual({ kind: "not_assessed", why: HELD });
    expect(impactTableCell("backup", 0)).toEqual({ kind: "measured", value: 0 });
    expect(impactTableCell("severity", "Info")).toEqual({ kind: "measured", value: "Info" });
    expect(impactTableCell("stranded", null).kind).toBe("unavailable");
    expect(impactTableCell("severity", 3).kind).toBe("unavailable");
    expect(impactTableCell("host", "core2")).toBeNull();
    expect(impactTableCell("detail", HELD)).toBeNull();
    expect(IMPACT_FIELDS).toEqual(["host", "severity", "vlans_impacted", "stranded", "hard", "backup", "fhrp",
      "off_scan_gw_vlans", "detail"]);
  });

  it("reads the projection's own lower-bound mark only on a published failure-impact measure", () => {
    const witness = { pointer: "/cable_map/cables/35", role: "witness" };
    const published = (value: unknown, refs: unknown[] = [witness]) => ({ state: "published", value, refs, basis: "x", subject: "/x" });
    expect(projectionImpactBound("stranded", published(42))).toMatch("/cable_map/cables/35");
    expect(projectionImpactBound("severity", published("High"))).toMatch("/cable_map/cables/35");
    expect(projectionImpactBound("stranded", published(42, []))).toBeUndefined();
    expect(projectionImpactBound("stranded", published(42, [{ pointer: "/x", role: "source" }]))).toBeUndefined();
    // a witness on a cell that is not a measure, or on a withheld cell, is not a published lower bound
    for (const field of ["host", "detail", "off_scan_gw_vlans"]) {
      expect(projectionImpactBound(field, published(1))).toBeUndefined();
    }
    expect(projectionImpactBound("stranded", { state: "not_collected", value: null, refs: [witness], reason: HELD })).toBeUndefined();
  });

  it("names each cited witness relative to the row it bounds, including a bound whose witness is the row itself", () => {
    const row = "/failure_impact/3";
    const citing = (...pointers: string[]) => ({ state: "published", value: 42, basis: "x", subject: `${row}/stranded`,
      refs: [{ pointer: `${row}/stranded`, role: "subject" }, ...pointers.map((pointer) => ({ pointer, role: "witness" }))] });
    // a row-level bound (its witness is the row's own pointer) never reads as a bound cited by some other record
    const own = projectionImpactBound("stranded", citing(row), row)!;
    expect(own).toContain(`this row's own record (${row})`);
    expect(own).toMatch(/only as a minimum/);
    expect(own).not.toMatch(/the record at/);
    expect(projectionImpactBound("stranded", citing(`${row}/off_scan_gw_vlans`), row))
      .toContain(`this row's off_scan_gw_vlans cell (${row}/off_scan_gw_vlans)`);
    expect(projectionImpactBound("stranded", citing("/cable_map/cables/35"), row)).toContain("the record at /cable_map/cables/35");
    // each witness once, in the order cited; the subject ref is not a witness
    const both = projectionImpactBound("stranded", citing(`${row}/off_scan_gw_vlans`, "/cable_map/cables/35", "/cable_map/cables/35"), row)!;
    expect(both.indexOf("off_scan_gw_vlans")).toBeLessThan(both.indexOf("/cable_map/cables/35"));
    expect(both.split("/cable_map/cables/35")).toHaveLength(2);
    expect(both).not.toContain(`${row}/stranded`);
    // a similar-looking pointer of another row is not this row's cell
    expect(projectionImpactBound("stranded", citing("/failure_impact/30"), row)).toContain("the record at /failure_impact/30");
  });

  it("words the snapshot root pointer \"\" as the snapshot as a whole, never as an empty pointer", () => {
    // The pending W35 engine change (PR #626) cites the root pointer "" as a bound's witness when no nearer record was
    // collected. RFC 6901's whole-document pointer is the empty string, so the old wording read "the record at " with
    // nothing after it.
    const row = "/failure_impact/3";
    const root = { state: "published", value: 42, basis: "x", subject: `${row}/stranded`,
      refs: [{ pointer: `${row}/stranded`, role: "subject" }, { pointer: "", role: "witness" }] };
    const said = projectionImpactBound("stranded", root, row)!;
    expect(IMPACT_ROOT_WITNESS).toBe("the snapshot as a whole (no nearer record was collected)");
    expect(said).toBe("the engine publishes this value only as a minimum, citing the snapshot as a whole (no nearer "
      + "record was collected) as what bounds it");
    expect(said).not.toMatch(/the record at\s*(;|as\b|$)/);
    expect(said).not.toContain("()");
    // the same without a row pointer, and beside a nearer witness, each named once, in the order cited
    expect(projectionImpactBound("stranded", root)).toContain(`citing ${IMPACT_ROOT_WITNESS} as`);
    const both = projectionImpactBound("stranded", { ...root, refs: [...root.refs, { pointer: "/cable_map/cables/35", role: "witness" },
      { pointer: "", role: "witness" }] }, row)!;
    expect(both).toContain(`citing ${IMPACT_ROOT_WITNESS}; the record at /cable_map/cables/35 as`);
    expect(both.split(IMPACT_ROOT_WITNESS)).toHaveLength(2);
    // the root is the root even when a row pointer is "" too: never "this row's own record ()"
    expect(projectionImpactBound("stranded", root, "")).toContain(IMPACT_ROOT_WITNESS);
    // and the visible and described reason built from it carries the same words
    expect(impactReasonText({ kind: "lower_bound", value: 42, why: said })).toContain(IMPACT_ROOT_WITNESS);
  });

  it("names each qualified state by its state text and its reason, as a row's disclosure lists it", () => {
    expect(impactStateText({ kind: "lower_bound", value: 42, why: WHY })).toBe("≥ 42");
    expect(impactStateText({ kind: "not_assessed", why: HELD })).toBe(IMPACT_NOT_ASSESSED);
    expect(impactStateText({ kind: "unavailable", why: "x" })).toBe("unavailable");
    expect(impactStateText({ kind: "measured", value: 0 })).toBe("0");
    expect(impactReasonText({ kind: "lower_bound", value: 42, why: WHY }))
      .toBe(`At least 42: a lower bound, not an exact measurement. Why: ${WHY}.`);
    expect(impactReasonText({ kind: "not_assessed", why: HELD })).toBe(HELD);
    expect(impactReasonText({ kind: "measured", value: 7 })).toBe("");
  });
});

describe("<ImpactValue>", () => {
  it("renders a lower bound as ≥ N with an accessible minimum-not-measurement explanation, never as the bare number", () => {
    shown({ kind: "lower_bound", value: 42, why: WHY });
    expect(screen.queryByText("42")).toBeNull();
    // a toggletip: a non-submitting button named by its state text and described by its reason
    const bound = screen.getByRole("button", { name: "At least 42" });
    expect(bound).toHaveAttribute("type", "button");
    expect(bound).toHaveAttribute("data-impact", "lower_bound");
    expect(bound).toHaveClass("impact-toggletip", "impact-bound");
    expect(bound).toHaveTextContent("≥ 42");
    expect(bound.querySelector(".sr-only")).toHaveTextContent("At least 42");
    expect(bound).toHaveAccessibleDescription(`At least 42: a lower bound, not an exact measurement. Why: ${WHY}.`);
    // no title beside the description: it would read the reason twice, or stand in for the state text as the name
    expect(bound).not.toHaveAttribute("title");
    expect(bound).not.toHaveAttribute("tabindex");          // a native tab stop, not a generic span forced into one
    const reason = reasonOf(bound);
    expect(reason).toHaveTextContent(WHY);
    expect(reason).toHaveClass("impact-why");
    expect(reason?.closest("button")).toBeNull();            // the description sits beside the button, not in its name
    // activation reveals the reason (a click or tap also focuses it); Escape and leaving it hide it again
    expect(bound).not.toHaveAttribute("data-open");
    fireEvent.click(bound);
    expect(bound).toHaveFocus();
    expect(bound).toHaveAttribute("data-open", "true");
    fireEvent.keyDown(bound, { key: "Escape" });
    expect(bound).not.toHaveAttribute("data-open");
    fireEvent.click(bound);
    expect(bound).toHaveAttribute("data-open", "true");
    fireEvent.click(bound);
    expect(bound).not.toHaveAttribute("data-open");
    fireEvent.click(bound);
    fireEvent.blur(bound);
    expect(bound).not.toHaveAttribute("data-open");
  });

  it("never submits a form it sits in", () => {
    const submit = vi.fn((event: Event) => event.preventDefault());
    render(<form onSubmit={(event) => submit(event.nativeEvent)}><ImpactValue state={{ kind: "not_assessed", why: HELD }} /></form>);
    fireEvent.click(screen.getByRole("button", { name: IMPACT_NOT_ASSESSED }));
    expect(submit).not.toHaveBeenCalled();
  });

  it("gives every qualified state a reachable reason, and keeps text, not colour, as the signal", () => {
    for (const [state, face] of [
      [{ kind: "not_assessed", why: HELD }, IMPACT_NOT_ASSESSED],
      [{ kind: "unavailable", why: "Withheld by the engine" }, "unavailable"],
    ] as const) {
      const { unmount } = render(<ImpactValue state={state} />);
      const value = screen.getByRole("button", { name: face });
      expect(value).toHaveAttribute("data-impact", state.kind);
      expect(value.firstChild?.textContent).toBe(face);
      expect(value).toHaveAccessibleDescription(state.why);
      expect(value).not.toHaveAttribute("title");
      expect(reasonOf(value)).toHaveTextContent(state.why);
      unmount();
    }
    render(<ImpactLowerBoundTag why="the wave's worst case may be larger" />);
    const tag = screen.getByRole("button", { name: "lower bound" });
    expect(tag).toHaveAttribute("data-impact", "lower_bound_tag");
    expect(tag).toHaveAccessibleDescription("the wave's worst case may be larger");
    expect(tag).not.toHaveAttribute("title");
  });

  it("with reasonShown, leaves the reason to the caller: a plain span, not a tab stop, not described twice", () => {
    const view = render(<ImpactValue state={{ kind: "lower_bound", value: 42, why: WHY }} reasonShown />).container;
    const bound = view.querySelector('[data-impact="lower_bound"]')!;
    expect(bound.tagName).toBe("SPAN");
    expect(screen.queryByRole("button")).toBeNull();
    expect(bound).toHaveTextContent("≥ 42");
    expect(bound).not.toHaveAttribute("tabindex");
    expect(bound).not.toHaveAttribute("aria-describedby");
    expect(view.querySelector(".impact-why")).toBeNull();
    // with no description present, the title stays for a pointer user's hover
    expect(bound.getAttribute("title")).toMatch(/^At least 42: a lower bound, not an exact measurement/);
  });

  it("renders NOT ASSESSED as the neutral tag, never as 0 or a blank", () => {
    const view = shown({ kind: "not_assessed", why: HELD });
    const tag = screen.getByRole("button", { name: IMPACT_NOT_ASSESSED });
    expect(tag).toHaveAttribute("data-impact", "not_assessed");
    expect(tag).toHaveClass("impact-na");
    expect(tag.firstChild?.textContent).toBe(IMPACT_NOT_ASSESSED);
    expect(tag).toHaveAccessibleDescription(HELD);
    expect(screen.queryByText("0")).toBeNull();
    expect(view.textContent?.trim()).not.toBe("");
  });

  it("renders a withheld value as unavailable, distinct from 0", () => {
    shown(impactEntryValue({ ...core2, lower_bound: false, vlans_impacted: null }, "vlans_impacted"));
    const cell = screen.getByRole("button", { name: "unavailable" });
    expect(cell).toHaveAttribute("data-impact", "unavailable");
    expect(cell).toHaveClass("impact-unavailable");
    expect(cell.firstChild?.textContent).toBe("unavailable");
    expect(cell).toHaveAccessibleDescription(/not a measured 0/);
    expect(screen.queryByText("0")).toBeNull();
  });

  it("renders a measured value as itself: a published 0 stays 0", () => {
    const view = shown({ kind: "measured", value: 0 });
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(view.querySelector('[data-impact="measured"]')).not.toHaveClass("impact-bound");
  });
});
