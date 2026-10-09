import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import {
  IMPACT_FIELDS,
  IMPACT_NOT_ASSESSED,
  ImpactLowerBoundTag,
  ImpactValue,
  impactEntryValue,
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
});

describe("<ImpactValue>", () => {
  it("renders a lower bound as ≥ N with an accessible minimum-not-measurement explanation, never as the bare number", () => {
    const view = shown({ kind: "lower_bound", value: 42, why: WHY });
    expect(screen.queryByText("42")).toBeNull();
    const bound = view.querySelector('[data-impact="lower_bound"]')!;
    expect(bound).toHaveClass("impact-bound");
    expect(bound).toHaveTextContent("≥ 42");
    expect(bound.getAttribute("title")).toMatch(/^At least 42: a lower bound, not an exact measurement/);
    expect(bound.querySelector(".sr-only")).toHaveTextContent("At least 42");
    // the reason is not hover-only: the value takes focus (a tap focuses it) and is described by the reason
    expect(bound).toHaveAttribute("tabindex", "0");
    const reason = reasonOf(bound);
    expect(reason).toHaveTextContent(/At least 42: a lower bound, not an exact measurement/);
    expect(reason).toHaveTextContent(WHY);
    expect(reason).toHaveClass("impact-why");
    fireEvent.click(bound);
    expect(bound).toHaveFocus();
  });

  it("gives every qualified state a reachable reason, and keeps text, not colour, as the signal", () => {
    for (const [state, face] of [
      [{ kind: "not_assessed", why: HELD }, IMPACT_NOT_ASSESSED],
      [{ kind: "unavailable", why: "Withheld by the engine" }, "unavailable"],
    ] as const) {
      const view = shown(state);
      const value = view.querySelector(`[data-impact="${state.kind}"]`)!;
      expect(value.firstChild?.textContent).toBe(face);
      expect(value).toHaveAttribute("tabindex", "0");
      expect(reasonOf(value)).toHaveTextContent(state.why);
      view.remove();
    }
    const tag = render(<ImpactLowerBoundTag why="the wave's worst case may be larger" />).container
      .querySelector('[data-impact="lower_bound_tag"]')!;
    expect(tag).toHaveTextContent("lower bound");
    expect(tag).toHaveAttribute("tabindex", "0");
    expect(reasonOf(tag)).toHaveTextContent("the wave's worst case may be larger");
  });

  it("with reasonShown, leaves the reason to the caller's visible text: not focusable, not described twice", () => {
    const view = render(<ImpactValue state={{ kind: "lower_bound", value: 42, why: WHY }} reasonShown />).container;
    const bound = view.querySelector('[data-impact="lower_bound"]')!;
    expect(bound).toHaveTextContent("≥ 42");
    expect(bound).not.toHaveAttribute("tabindex");
    expect(bound).not.toHaveAttribute("aria-describedby");
    expect(view.querySelector(".impact-why")).toBeNull();
  });

  it("renders NOT ASSESSED as the neutral tag, never as 0 or a blank", () => {
    const view = shown({ kind: "not_assessed", why: HELD });
    const tag = view.querySelector('[data-impact="not_assessed"]')!;
    expect(tag).toHaveClass("impact-na");
    expect(tag.firstChild?.textContent).toBe(IMPACT_NOT_ASSESSED);
    expect(tag).toHaveAttribute("title", HELD);
    expect(screen.queryByText("0")).toBeNull();
    expect(view.textContent?.trim()).not.toBe("");
  });

  it("renders a withheld value as unavailable, distinct from 0", () => {
    const view = shown(impactEntryValue({ ...core2, lower_bound: false, vlans_impacted: null }, "vlans_impacted"));
    const cell = view.querySelector('[data-impact="unavailable"]')!;
    expect(cell).toHaveClass("impact-unavailable");
    expect(cell.firstChild?.textContent).toBe("unavailable");
    expect(cell.getAttribute("title")).toMatch(/not a measured 0/);
    expect(screen.queryByText("0")).toBeNull();
  });

  it("renders a measured value as itself: a published 0 stays 0", () => {
    const view = shown({ kind: "measured", value: 0 });
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(view.querySelector('[data-impact="measured"]')).not.toHaveClass("impact-bound");
  });
});
