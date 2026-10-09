import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CompareResponse } from "../api";
import ComparisonDecision from "./ComparisonDecision";

// W50: rehearsal.impacts is a versioned receipt contract. /2 rows carry the engine owner's verdict and
// owner-valued cells; /1 receipts were stored before bounds were tracked and must never read as exact.

type Evidence = NonNullable<CompareResponse["operator_evidence"]>;

function compareWith(schema: string, impacts: Array<Record<string, unknown>>,
  extra: Partial<Evidence["rehearsal"]> = {}): CompareResponse {
  const evidence = {
    schema,
    owner: "reference_only_projection",
    owns_verdict: false,
    rehearsal: {
      status: impacts.length ? "simulation_only" : "not_verified",
      assurance_level: "not_verified",
      source_owner: "failure_impact projection",
      n_impacts_total: impacts.length,
      impacts,
      note: "Simulation exists, but no source-bound operator rehearsal receipt was supplied.",
      ...extra,
    },
    rollback: {
      status: "not_verified",
      assurance_level: "not_verified",
      source_owner: "migration_scenarios playbook.rollback",
      n_groups_total: 0,
      n_plans_total: 0,
      plans: [],
      note: "Rollback not verified.",
    },
  } as unknown as Evidence;
  return { verdict: "CLEAN", operator_evidence: evidence };
}

// The owner's values for the committed sample's core1 (one evidence-less inter-switch link: a lower bound) and
// for the same row held (older than the off-scan marker: not assessed). The strings are the owner's own
// table_value / table_detail output shapes; nothing here is computed by the view.
const BOUNDED_CORE1 = {
  host: "core1",
  assessable: "lower_bound",
  why: "it has 1 inter-switch link(s) with no trunk/STP evidence",
  severity: "High (lower bound)",
  vlans_impacted: "≥ 3",
  stranded: "≥ 45",
  hard: "≥ 3",
  backup: "not assessed",
  fhrp: "not assessed",
  detail: "Lower bound — it has 1 inter-switch link(s) with no trunk/STP evidence.",
};
const HELD_CORE1 = {
  host: "core1",
  assessable: "not_assessed",
  why: "this stored row predates the off-scan marker",
  severity: "not assessed",
  vlans_impacted: "not assessed",
  stranded: "not assessed",
  hard: "not assessed",
  backup: "not assessed",
  fhrp: "not assessed",
  detail: "Not assessed — this stored row predates the off-scan marker.",
};
const MEASURED_DIST = {
  host: "dist1",
  assessable: "published",
  why: "",
  severity: "Low",
  vlans_impacted: 1,
  stranded: 0,
  hard: 0,
  backup: 1,
  fhrp: 1,
  detail: "One VLAN keeps its FHRP peer.",
};

function rowFor(host: string) {
  const rows = screen.getAllByTestId("comparison-rehearsal-row").filter((row) => row.textContent?.includes(host));
  expect(rows).toHaveLength(1);
  return rows[0];
}

describe("ComparisonDecision failure-impact rows by receipt contract", () => {
  it("renders a /2 lower bound as a bound, never as the exact stored count", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/2", [BOUNDED_CORE1, MEASURED_DIST], {
      impacts_owner: "failure_impact_assessability/1",
      n_impacts_by_assessable: { published: 1, lower_bound: 1, not_assessed: 0, ambiguous: 0 },
    })} />);
    const core1 = rowFor("core1");
    expect(core1).toHaveAttribute("data-assessable", "lower_bound");
    expect(within(core1).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent("LOWER BOUND");
    const values = within(core1).getByTestId("comparison-rehearsal-row-values");
    expect(values).toHaveTextContent("stranded endpoints: ≥ 45");
    expect(values).toHaveTextContent("severity: High (lower bound)");
    expect(values).toHaveTextContent("backup-covered: not assessed");
    expect(values.textContent).not.toMatch(/stranded endpoints: 45\b/);
    expect(within(core1).getByTestId("comparison-rehearsal-row-detail")).toHaveTextContent(/^Lower bound/);
    const measured = rowFor("dist1");
    expect(within(measured).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent("PUBLISHED");
    expect(within(measured).getByTestId("comparison-rehearsal-row-values")).toHaveTextContent("stranded endpoints: 0");
    expect(screen.getByTestId("comparison-rehearsal-impact-census")).toHaveTextContent(
      "1 published · 1 lower bound · 0 not assessed · 0 ambiguous",
    );
    expect(screen.queryByTestId("comparison-rehearsal-legacy-note")).not.toBeInTheDocument();
  });

  it("renders a /2 held row as NOT ASSESSED with no stored value", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/2", [HELD_CORE1])} />);
    const core1 = rowFor("core1");
    expect(core1).toHaveAttribute("data-assessable", "not_assessed");
    expect(within(core1).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent("NOT ASSESSED");
    const values = within(core1).getByTestId("comparison-rehearsal-row-values");
    for (const label of ["severity", "stranded endpoints", "VLANs impacted", "hard partitions", "backup-covered", "FHRP-covered"]) {
      expect(values).toHaveTextContent(`${label}: not assessed`);
    }
    expect(values.textContent).not.toMatch(/\d/);
  });

  it("renders a /2 row whose verdict or values are missing as unavailable, never as 0", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/2", [
      { host: "edge9", severity: "Info", stranded: 0 },
      { host: "edge7", assessable: "published", severity: "Info", stranded: null, detail: "x" },
    ])} />);
    const unknown = rowFor("edge9");
    expect(unknown).toHaveAttribute("data-assessable", "unavailable");
    expect(within(unknown).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent("VERDICT UNAVAILABLE");
    expect(within(unknown).getByTestId("comparison-rehearsal-row-values")).toHaveTextContent("stranded endpoints: unavailable");
    expect(within(unknown).getByTestId("comparison-rehearsal-row-values").textContent).not.toMatch(/Info|: 0/);
    const missing = rowFor("edge7");
    expect(within(missing).getByTestId("comparison-rehearsal-row-values")).toHaveTextContent("stranded endpoints: unavailable");
  });

  it("marks a /1 receipt's rows as recorded before bounds were tracked", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/1", [
      { host: "core1", severity: "High", stranded: 45, detail: "45 endpoints strand" },
    ])} />);
    const note = screen.getByTestId("comparison-rehearsal-legacy-note");
    expect(note).toHaveTextContent(/recorded before bounds were tracked/i);
    expect(note).toHaveTextContent(/none of these values is an exact measurement/i);
    const core1 = rowFor("core1");
    expect(core1).toHaveAttribute("data-assessable", "recorded_before_bounds");
    expect(core1).toHaveTextContent("NOT BOUND-CHECKED");
    expect(core1).toHaveTextContent("as recorded: High");
  });

  it("shows no legacy note for a /1 receipt that recorded no failure-impact rows", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/1", [])} />);
    expect(screen.queryByTestId("comparison-rehearsal-legacy-note")).not.toBeInTheDocument();
    expect(screen.queryAllByTestId("comparison-rehearsal-row")).toHaveLength(0);
  });

  it("withholds the values of rows published under an unrecognised contract", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/9", [
      { host: "core1", severity: "High", stranded: 45, detail: "45 endpoints strand" },
    ])} />);
    expect(screen.getByTestId("comparison-rehearsal-contract-unknown")).toHaveTextContent(/unrecognised/);
    expect(screen.queryAllByTestId("comparison-rehearsal-row")).toHaveLength(0);
    expect(screen.getByTestId("comparison-rehearsal")).not.toHaveTextContent("45 endpoints strand");
  });
});
