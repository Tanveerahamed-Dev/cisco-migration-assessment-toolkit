import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  IMPACT_FIELDS,
  IMPACT_NOT_ASSESSED,
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
});

describe("<ImpactValue>", () => {
  it("renders a lower bound as ≥ N with an accessible minimum-not-measurement explanation, never as the bare number", () => {
    const view = shown({ kind: "lower_bound", value: 42, why: WHY });
    expect(screen.queryByText("42")).toBeNull();
    const bound = view.querySelector('[data-impact="lower_bound"]')!;
    expect(bound).toHaveClass("impact-bound");
    expect(bound).toHaveTextContent("≥ 42");
    expect(bound.getAttribute("title")).toMatch(/^At least 42: a lower bound, not an exact measurement/);
    expect(bound.querySelector(".sr-only")).toHaveTextContent(/At least 42: a lower bound, not an exact measurement/);
    expect(bound.querySelector(".sr-only")).toHaveTextContent(WHY);
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
