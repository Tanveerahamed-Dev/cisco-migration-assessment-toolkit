import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CompareResponse } from "../api";
import ComparisonDecision from "./ComparisonDecision";

// W50: rehearsal.impacts is a versioned receipt contract. /2 rows bind only the engine owner's decisions (a verdict
// token, reason codes and, per cell, the stored value or {withheld: true}); this view resolves the words. /1 receipts
// were stored before bounds were tracked and must never read as exact.

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

// The engine's real /2 rows (protocol_assurance._rehearsal_impacts_v2), copied verbatim from its output on the
// committed snapshots; nothing here is invented or computed by the view.
const WITHHELD = { withheld: true };
// Sample core1: one inter-switch link with no trunk/STP evidence, so a lower bound; its zeros are withheld.
const BOUNDED_CORE1 = {
  index: 0,
  host: "core1",
  assessable: "lower_bound",
  reason_codes: [{ code: "blind_links", n: 1 }],
  severity: "High",
  vlans_impacted: 3,
  stranded: 45,
  hard: 3,
  backup: WITHHELD,
  fhrp: WITHHELD,
  detail: "VLAN 10: Hard partition (34 ep); VLAN 30: Hard partition (11 ep); VLAN 20: Hard partition",
};
// Sample core1 with its off_scan_gw_vlans marker removed (a row older than the marker): held, every cell withheld.
const HELD_CORE1 = {
  index: 0,
  host: "core1",
  assessable: "not_assessed",
  reason_codes: [{ code: "legacy_row", n: 0 }],
  severity: WITHHELD,
  vlans_impacted: WITHHELD,
  stranded: WITHHELD,
  hard: WITHHELD,
  backup: WITHHELD,
  fhrp: WITHHELD,
  detail: WITHHELD,
};
// Sample access1: a published measurement.
const MEASURED_ACCESS1 = {
  index: 1,
  host: "access1",
  assessable: "published",
  reason_codes: [],
  severity: "High",
  vlans_impacted: 3,
  stranded: 42,
  hard: 3,
  backup: 0,
  fhrp: 0,
  detail: "VLAN 10: Hard partition (32 ep); VLAN 30: Hard partition (10 ep); VLAN 20: Hard partition",
};
// Golden core2: an uncollected neighbour bounds it; its Low band (below the worst) and its zeros are withheld.
const BOUNDED_GOLDEN_CORE2 = {
  index: 1,
  host: "core2",
  assessable: "lower_bound",
  reason_codes: [{ code: "uncollected_neighbours", n: 1 }],
  severity: WITHHELD,
  vlans_impacted: 1,
  stranded: WITHHELD,
  hard: WITHHELD,
  backup: WITHHELD,
  fhrp: 1,
  detail: "VLAN 10: FHRP-covered",
};
// Sample core1 exactly as the producer stored it: what a /1 receipt copied raw.
const RAW_SAMPLE_CORE1 = {
  host: "core1", severity: "High", vlans_impacted: 3, stranded: 45, hard: 3, backup: 0, fhrp: 0,
  off_scan_gw_vlans: 0,
  detail: "VLAN 10: Hard partition (34 ep); VLAN 30: Hard partition (11 ep); VLAN 20: Hard partition",
  blind_links: 1,
};
// The sample's census (impacts_owner and n_impacts_by_assessable as the engine wrote them).
const SAMPLE_REHEARSAL = {
  impacts_owner: "failure_impact_assessability/1",
  n_impacts_by_assessable: { published: 20, lower_bound: 3, not_assessed: 0, ambiguous: 0 },
};

function rowFor(host: string) {
  const rows = screen.getAllByTestId("comparison-rehearsal-row").filter((row) => row.textContent?.includes(host));
  expect(rows).toHaveLength(1);
  return rows[0];
}

function impactCap() {
  const caps = within(screen.getByTestId("comparison-rehearsal")).getAllByTestId("comparison-cap-disclosure");
  expect(caps).toHaveLength(1);
  return caps[0];
}

describe("ComparisonDecision failure-impact rows by receipt contract", () => {
  it("renders a /2 lower bound as a floor with its reason code, never as the exact stored count", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/2",
      [BOUNDED_CORE1, MEASURED_ACCESS1], SAMPLE_REHEARSAL)} />);
    const core1 = rowFor("core1");
    expect(core1).toHaveAttribute("data-assessable", "lower_bound");
    expect(within(core1).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent("LOWER BOUND");
    expect(within(core1).getByTestId("comparison-rehearsal-row-reasons")).toHaveTextContent("blind links ×1");
    const values = within(core1).getByTestId("comparison-rehearsal-row-values");
    expect(values).toHaveTextContent("stranded endpoints: ≥ 45");
    expect(values).toHaveTextContent("severity: High (lower bound)");
    expect(values).toHaveTextContent("backup-covered: not assessed");
    expect(values).toHaveTextContent("FHRP-covered: not assessed");
    expect(values.textContent).not.toMatch(/stranded endpoints: 45\b/);
    expect(values.textContent).not.toMatch(/: 0\b/);
    expect(within(core1).getByTestId("comparison-rehearsal-row-detail")).toHaveTextContent(
      "Producer detail: VLAN 10: Hard partition (34 ep)");
    const measured = rowFor("access1");
    expect(within(measured).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent("PUBLISHED");
    expect(within(measured).queryByTestId("comparison-rehearsal-row-reasons")).not.toBeInTheDocument();
    expect(within(measured).getByTestId("comparison-rehearsal-row-values")).toHaveTextContent("stranded endpoints: 42");
    expect(within(measured).getByTestId("comparison-rehearsal-row-values")).toHaveTextContent("backup-covered: 0");
    expect(screen.getByTestId("comparison-rehearsal-impact-census")).toHaveTextContent(
      "20 published · 3 lower bound · 0 not assessed · 0 ambiguous",
    );
    expect(screen.getByTestId("comparison-rehearsal-impact-order")).toHaveTextContent(/stranded-endpoint floor/);
    expect(screen.queryByTestId("comparison-rehearsal-legacy-note")).not.toBeInTheDocument();
  });

  it("withholds a /2 lower bound's band below the worst and its zeros", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/2", [BOUNDED_GOLDEN_CORE2])} />);
    const core2 = rowFor("core2");
    expect(within(core2).getByTestId("comparison-rehearsal-row-reasons")).toHaveTextContent("uncollected neighbours ×1");
    const values = within(core2).getByTestId("comparison-rehearsal-row-values");
    expect(values).toHaveTextContent("severity: not assessed");
    expect(values).toHaveTextContent("VLANs impacted: ≥ 1");
    expect(values).toHaveTextContent("FHRP-covered: ≥ 1");
    expect(values).toHaveTextContent("stranded endpoints: not assessed");
    expect(values.textContent).not.toMatch(/Low/);
  });

  it("renders a /2 held row as NOT ASSESSED with no stored value", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/2", [HELD_CORE1])} />);
    const core1 = rowFor("core1");
    expect(core1).toHaveAttribute("data-assessable", "not_assessed");
    expect(within(core1).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent("NOT ASSESSED");
    expect(within(core1).getByTestId("comparison-rehearsal-row-reasons")).toHaveTextContent("legacy row");
    const values = within(core1).getByTestId("comparison-rehearsal-row-values");
    for (const label of ["severity", "stranded endpoints", "VLANs impacted", "hard partitions", "backup-covered", "FHRP-covered"]) {
      expect(values).toHaveTextContent(`${label}: not assessed`);
    }
    expect(values.textContent).not.toMatch(/\d/);
    expect(within(core1).getByTestId("comparison-rehearsal-row-detail")).toHaveTextContent(/withheld/);
  });

  it("renders a /2 row whose verdict or values are missing, mistyped or a prototype key as unavailable, never as 0", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/2", [
      { host: "edge9", severity: "Info", stranded: 0 },
      { host: "edge7", assessable: "published", severity: "Info", stranded: null, detail: "x" },
      { host: "edge5", assessable: "constructor", severity: "Info", stranded: 0 },
      { host: "edge3", assessable: "toString", severity: "Info", stranded: 0 },
    ])} />);
    for (const host of ["edge9", "edge5", "edge3"]) {
      const row = rowFor(host);
      expect(row).toHaveAttribute("data-assessable", "unavailable");
      expect(within(row).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent("VERDICT UNAVAILABLE");
      expect(within(row).getByTestId("comparison-rehearsal-row-values")).toHaveTextContent("stranded endpoints: unavailable");
      expect(within(row).getByTestId("comparison-rehearsal-row-values").textContent).not.toMatch(/Info|: 0/);
    }
    const missing = rowFor("edge7");
    expect(within(missing).getByTestId("comparison-rehearsal-row-values")).toHaveTextContent("stranded endpoints: unavailable");
  });

  it("marks a /1 receipt's rows as recorded before bounds were tracked", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/1", [
      RAW_SAMPLE_CORE1,
    ])} />);
    const note = screen.getByTestId("comparison-rehearsal-legacy-note");
    expect(note).toHaveTextContent(/recorded before bounds were tracked/i);
    expect(note).toHaveTextContent(/none of these values is an exact measurement/i);
    const core1 = rowFor("core1");
    expect(core1).toHaveAttribute("data-assessable", "recorded_before_bounds");
    expect(core1).toHaveTextContent("NOT BOUND-CHECKED");
    expect(core1).toHaveTextContent("as recorded: High");
    expect(impactCap()).toHaveTextContent("Rendered: 1 · Total: 1 · Omitted: 0.");
  });

  it("shows no legacy note for a /1 receipt that recorded no failure-impact rows", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/1", [])} />);
    expect(screen.queryByTestId("comparison-rehearsal-legacy-note")).not.toBeInTheDocument();
    expect(screen.queryAllByTestId("comparison-rehearsal-row")).toHaveLength(0);
  });

  it("withholds the values of rows published under an unrecognised contract and renders none of them", () => {
    render(<ComparisonDecision value={compareWith("cutover_operator_evidence/9", [
      RAW_SAMPLE_CORE1,
    ])} />);
    expect(screen.getByTestId("comparison-rehearsal-contract-unknown")).toHaveTextContent(/unrecognised/);
    expect(screen.queryAllByTestId("comparison-rehearsal-row")).toHaveLength(0);
    expect(screen.getByTestId("comparison-rehearsal")).not.toHaveTextContent("Hard partition (34 ep)");
    expect(impactCap()).toHaveTextContent("Rendered: 0 · Total: 1 · Omitted: 1.");
  });
});
