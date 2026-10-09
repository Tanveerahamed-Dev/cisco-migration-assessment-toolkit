import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CompareResponse, ImpactsViewRow, RehearsalImpactsView } from "../api";
import ComparisonDecision from "./ComparisonDecision";

// W50: a comparison's operator_evidence.rehearsal.impacts binds the stored failure-impact rows as raw EVIDENCE. This
// view never renders those values; it renders only the engine owner's live, display-only impactsView (computed by
// AssessHub from the bound after snapshot and returned beside the comparison), and only when the view interpreted
// exactly the bytes the comparison binds.

const AFTER_SHA = `sha256:${"a".repeat(64)}`;
const binding = (snapshotId: number, sha256: string) => ({
  source: "persisted snapshots.snapshot_json blob", sha256, bytes: 1, snapshot_id: snapshotId, campaign_id: 1,
  engagement_id: "ENG-W50", label: `snapshot ${snapshotId}`,
});

// Sample core1 exactly as the producer stored it: what the receipt binds as raw evidence.
const RAW_SAMPLE_CORE1 = {
  host: "core1", severity: "High", vlans_impacted: 3, stranded: 45, hard: 3, backup: 0, fhrp: 0,
  off_scan_gw_vlans: 0,
  detail: "VLAN 10: Hard partition (34 ep); VLAN 30: Hard partition (11 ep); VLAN 20: Hard partition",
  blind_links: 1,
};

function compareWith(impacts: Array<Record<string, unknown>> = [RAW_SAMPLE_CORE1]): CompareResponse {
  const evidence = {
    schema: "cutover_operator_evidence/1",
    owner: "reference_only_projection",
    owns_verdict: false,
    rehearsal: {
      status: impacts.length ? "simulation_only" : "not_verified",
      assurance_level: "not_verified",
      source_owner: "failure_impact projection",
      n_impacts_total: impacts.length,
      impacts,
      note: "Simulation exists, but no source-bound operator rehearsal receipt was supplied.",
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
  };
  const admission = {
    schema: "protocol_comparison_admission/1",
    status: "admitted",
    decision_eligible: true,
    assurance_level: "source_bound",
    engagement_id: "ENG-W50",
    campaign_id: 1,
    source_binding: { before: binding(1, `sha256:${"b".repeat(64)}`), after: binding(2, AFTER_SHA) },
    subject_binding: {},
    owner_versions: {},
    support_profiles: [],
    failures: [],
    coverage_gaps: [],
  };
  return {
    verdict: "CLEAN", operator_evidence: evidence, comparison_admission: admission,
  } as unknown as CompareResponse;
}

// The engine's real impacts_view rows (webapp.backend.engine.rehearsal_impacts_view), copied verbatim from its
// output on the committed sample; nothing here is invented or computed by the view.
// Sample core1: one inter-switch link with no trunk/STP evidence, so a lower bound; its zeros are withheld.
const BOUNDED_CORE1: ImpactsViewRow = {
  index: 0, host: "core1", assessable: "lower_bound", state: "not_collected",
  reasons: [{ code: "blind_links", n: 1 }], ranked: true,
  cells: {
    severity: { kind: "floor", text: "High (lower bound)", state: null },
    vlans_impacted: { kind: "floor", text: "≥ 3", state: null },
    stranded: { kind: "floor", text: "≥ 45", state: null },
    hard: { kind: "floor", text: "≥ 3", state: null },
    backup: { kind: "withheld", text: null, state: "not_collected" },
    fhrp: { kind: "withheld", text: null, state: "not_collected" },
    detail: {
      kind: "published", state: null,
      text: "VLAN 10: Hard partition (34 ep); VLAN 30: Hard partition (11 ep); VLAN 20: Hard partition",
    },
  },
};
// Sample access1: a published measurement (its zeros are measured zeros).
const MEASURED_ACCESS1: ImpactsViewRow = {
  index: 1, host: "access1", assessable: "published", state: null, reasons: [], ranked: true,
  cells: {
    severity: { kind: "published", text: "High", state: null },
    vlans_impacted: { kind: "published", text: "3", state: null },
    stranded: { kind: "published", text: "42", state: null },
    hard: { kind: "published", text: "3", state: null },
    backup: { kind: "published", text: "0", state: null },
    fhrp: { kind: "published", text: "0", state: null },
    detail: {
      kind: "published", state: null,
      text: "VLAN 10: Hard partition (32 ep); VLAN 30: Hard partition (10 ep); VLAN 20: Hard partition",
    },
  },
};
const withheld = (state: string) => ({ kind: "withheld", text: null, state });
// Sample core1 with its off_scan_gw_vlans marker removed (a row older than the marker): held, every cell withheld.
const HELD_CORE1: ImpactsViewRow = {
  index: 0, host: "core1", assessable: "not_assessed", state: "not_collected",
  reasons: [{ code: "legacy_row", n: 0 }], ranked: false,
  cells: {
    severity: withheld("not_collected"), vlans_impacted: withheld("not_collected"), stranded: withheld("not_collected"),
    hard: withheld("not_collected"), backup: withheld("not_collected"), fhrp: withheld("not_collected"),
    detail: withheld("not_collected"),
  },
};
// A stored row that is not an object (the sample with "not an object" appended at index 23).
const UNREADABLE_ROW: ImpactsViewRow = {
  index: 23, host: null, assessable: "not_assessed", state: "unverified",
  reasons: [{ code: "row_unreadable", n: 0 }], ranked: false,
  cells: {
    severity: withheld("unverified"), vlans_impacted: withheld("unverified"), stranded: withheld("unverified"),
    hard: withheld("unverified"), backup: withheld("unverified"), fhrp: withheld("unverified"),
    detail: withheld("unverified"),
  },
};

// The owner's STATE_WORD, as every view carries it.
const STATE_WORDS = {
  analysis_unavailable: "analysis unavailable", unverified: "unverified", not_collected: "not collected",
};

// `unranked` follows the engine's rule (every row the owner does not rank, in stored order); `unreadable` (the stored
// positions of rows that are not objects) cannot be derived from the rows, so a test that needs it passes it.
function viewOf(rows: ImpactsViewRow[], extra: Partial<Record<string, unknown>> = {}): RehearsalImpactsView {
  const unranked = rows.filter((row) => row.ranked !== true)
    .sort((a, b) => a.index - b.index)
    .map(({ index, host, assessable, state, reasons }) => ({ index, host, assessable, state, reasons }));
  return {
    schema: "rehearsal_impacts_view/1", display_only: true, available: true,
    owner: "failure_impact_assessability/1", source_sha256: AFTER_SHA, state_words: STATE_WORDS, section_state: null,
    n_rows_total: rows.length, n_rows_unreadable: 0, unreadable: [],
    counts: { published: 0, lower_bound: 0, not_assessed: 0, ambiguous: 0 },
    rows,
    unranked,
    ...extra,
  } as RehearsalImpactsView;
}
// The sample's census as the engine wrote it.
const SAMPLE_VIEW = viewOf([BOUNDED_CORE1, MEASURED_ACCESS1], {
  n_rows_total: 23, counts: { published: 20, lower_bound: 3, not_assessed: 0, ambiguous: 0 },
});

function rehearsal() {
  return screen.getByTestId("comparison-rehearsal");
}

function rowFor(host: string) {
  const rows = within(rehearsal()).getAllByTestId("comparison-rehearsal-row")
    .filter((row) => row.textContent?.includes(host));
  expect(rows).toHaveLength(1);
  return rows[0];
}

function impactCap() {
  const caps = within(rehearsal()).getAllByTestId("comparison-cap-disclosure");
  expect(caps).toHaveLength(1);
  return caps[0];
}

describe("ComparisonDecision failure-impact rows through the engine owner's live view", () => {
  it("renders a lower bound as the owner's floor, with its reason and state, never the exact stored count", () => {
    render(<ComparisonDecision value={compareWith()} impactsView={SAMPLE_VIEW} />);
    const core1 = rowFor("core1");
    expect(core1).toHaveAttribute("data-assessable", "lower_bound");
    expect(within(core1).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent("LOWER BOUND");
    expect(within(core1).getByTestId("comparison-rehearsal-row-state")).toHaveTextContent("not collected");
    expect(within(core1).getByTestId("comparison-rehearsal-row-reasons")).toHaveTextContent(
      "1 inter-switch link(s) on it carry no VLAN evidence, so what it carries over them was not simulated");
    const values = within(core1).getByTestId("comparison-rehearsal-row-values");
    expect(values).toHaveTextContent("stranded endpoints: ≥ 45");
    expect(values).toHaveTextContent("severity: High (lower bound)");
    expect(values).toHaveTextContent("backup-covered: not assessed (not collected)");
    expect(values).toHaveTextContent("FHRP-covered: not assessed (not collected)");
    expect(values.textContent).not.toMatch(/stranded endpoints: 45\b/);
    expect(values.textContent).not.toMatch(/: 0\b/);
    expect(within(core1).getByTestId("comparison-rehearsal-row-detail")).toHaveTextContent(
      "Producer detail: VLAN 10: Hard partition (34 ep)");
    const measured = rowFor("access1");
    expect(within(measured).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent("PUBLISHED");
    expect(within(measured).queryByTestId("comparison-rehearsal-row-reasons")).not.toBeInTheDocument();
    expect(within(measured).queryByTestId("comparison-rehearsal-row-state")).not.toBeInTheDocument();
    expect(within(measured).getByTestId("comparison-rehearsal-row-values")).toHaveTextContent("stranded endpoints: 42");
    expect(within(measured).getByTestId("comparison-rehearsal-row-values")).toHaveTextContent("backup-covered: 0");
    expect(screen.getByTestId("comparison-rehearsal-impact-census")).toHaveTextContent(
      "Engine-owner verdicts over every one of the 23 stored rows: 20 published · 3 lower bound · 0 not assessed · 0 ambiguous",
    );
    expect(screen.getByTestId("comparison-rehearsal-impact-order")).toHaveTextContent(/stranded-endpoint floor/);
    expect(screen.getByTestId("comparison-rehearsal-impact-live")).toHaveTextContent(
      /computed live by the engine owner from the bound evidence; it is not part of this comparison or of any receipt/,
    );
    expect(impactCap()).toHaveTextContent("Rendered: 2 · Total: 23 · Omitted: 21.");
  });

  it("renders a held row as NOT ASSESSED with the owner's reason and state, and no stored value", () => {
    render(<ComparisonDecision value={compareWith()} impactsView={viewOf([HELD_CORE1])} />);
    const core1 = rowFor("core1");
    expect(core1).toHaveAttribute("data-assessable", "not_assessed");
    expect(within(core1).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent("NOT ASSESSED");
    expect(within(core1).getByTestId("comparison-rehearsal-row-reasons")).toHaveTextContent(
      "the row predates the engine's assessability marker");
    expect(within(core1).getByTestId("comparison-rehearsal-row-unranked")).toHaveTextContent("not ranked");
    const values = within(core1).getByTestId("comparison-rehearsal-row-values");
    for (const label of ["severity", "stranded endpoints", "VLANs impacted", "hard partitions", "backup-covered", "FHRP-covered"]) {
      expect(values).toHaveTextContent(`${label}: not assessed (not collected)`);
    }
    expect(values.textContent).not.toMatch(/\d/);
    expect(within(core1).getByTestId("comparison-rehearsal-row-detail")).toHaveTextContent(
      "Producer detail withheld: not assessed (not collected).");
    expect(rehearsal()).not.toHaveTextContent("Hard partition (34 ep)");
  });

  it("counts and shows an unreadable stored row instead of dropping it", () => {
    render(<ComparisonDecision value={compareWith()} impactsView={viewOf([BOUNDED_CORE1, UNREADABLE_ROW], {
      n_rows_total: 2, n_rows_unreadable: 1, unreadable: [23],
      counts: { published: 0, lower_bound: 1, not_assessed: 1, ambiguous: 0 },
    })} />);
    expect(screen.getByTestId("comparison-rehearsal-impact-census")).toHaveTextContent(
      "Engine-owner verdicts over all 2 stored rows (1 unreadable): 0 published · 1 lower bound · 1 not assessed · 0 ambiguous",
    );
    expect(screen.getByTestId("comparison-rehearsal-impact-census")).not.toHaveTextContent(/every one/);
    expect(screen.getByTestId("comparison-rehearsal-impact-unreadable")).toHaveTextContent("#23");
    const unreadable = rowFor("stored row 23");
    expect(unreadable).toHaveTextContent("switch not named by the engine owner");
    expect(within(unreadable).getByTestId("comparison-rehearsal-row-state")).toHaveTextContent("unverified");
    expect(within(unreadable).getByTestId("comparison-rehearsal-row-reasons")).toHaveTextContent(
      "the stored row cannot be read");
    expect(impactCap()).toHaveTextContent("Rendered: 2 · Total: 2 · Omitted: 0.");
  });

  it("names an unrecognised code, verdict or state instead of guessing, and an unreadable value is never 0", () => {
    const unknownCode: ImpactsViewRow = { ...BOUNDED_CORE1, host: "edge1", reasons: [{ code: "new_owner_code", n: 2 }] };
    const unknownVerdict: ImpactsViewRow = { ...MEASURED_ACCESS1, host: "edge2", assessable: "constructor" };
    const unknownState: ImpactsViewRow = { ...HELD_CORE1, host: "edge3", state: "half_collected" };
    const unreadableCell: ImpactsViewRow = {
      ...MEASURED_ACCESS1, host: "edge4",
      cells: { ...MEASURED_ACCESS1.cells, stranded: { kind: "unreadable", text: null, state: null } },
    };
    render(<ComparisonDecision value={compareWith()}
      impactsView={viewOf([unknownCode, unknownVerdict, unknownState, unreadableCell])} />);
    expect(within(rowFor("edge1")).getByTestId("comparison-rehearsal-row-reasons")).toHaveTextContent(
      "unrecognised reason code (new_owner_code)");
    const edge2 = rowFor("edge2");
    expect(edge2).toHaveAttribute("data-assessable", "unrecognised");
    expect(within(edge2).getByTestId("comparison-rehearsal-row-verdict")).toHaveTextContent(
      "UNRECOGNISED VERDICT (constructor)");
    expect(within(edge2).getByTestId("comparison-rehearsal-row-values")).toHaveTextContent("stranded endpoints: unavailable");
    expect(within(edge2).getByTestId("comparison-rehearsal-row-values").textContent).not.toMatch(/42|: 0\b/);
    expect(within(rowFor("edge3")).getByTestId("comparison-rehearsal-row-state")).toHaveTextContent(
      "unrecognised state (half_collected)");
    const edge4 = within(rowFor("edge4")).getByTestId("comparison-rehearsal-row-values");
    expect(edge4).toHaveTextContent("stranded endpoints: unavailable (the stored value cannot be read)");
    expect(edge4.textContent).not.toMatch(/stranded endpoints: 0/);
  });

  it("words each state with the owner's word the view carries, not a copy of its own", () => {
    render(<ComparisonDecision value={compareWith()} impactsView={viewOf([HELD_CORE1], {
      state_words: { not_collected: "never collected by this run" },
    })} />);
    const core1 = rowFor("core1");
    expect(within(core1).getByTestId("comparison-rehearsal-row-state")).toHaveTextContent("never collected by this run");
    expect(within(core1).getByTestId("comparison-rehearsal-row-values")).toHaveTextContent(
      "stranded endpoints: not assessed (never collected by this run)");
  });

  it("shows the rows as unavailable, never as raw values, when no view is supplied", () => {
    render(<ComparisonDecision value={compareWith()} />);
    expect(screen.getByTestId("comparison-rehearsal-impacts-unavailable")).toHaveTextContent(
      /Failure-impact interpretation unavailable: this surface does not supply the engine owner's interpretation/,
    );
    expect(within(rehearsal()).queryAllByTestId("comparison-rehearsal-row")).toHaveLength(0);
    expect(rehearsal()).not.toHaveTextContent("Hard partition (34 ep)");
    expect(rehearsal()).not.toHaveTextContent(/\b45\b/);
    expect(impactCap()).toHaveTextContent("Rendered: 0 · Total: 1 · Omitted: 1.");
  });

  it("shows the server's reason when the view is unavailable", () => {
    render(<ComparisonDecision value={compareWith()} impactsView={{
      schema: "rehearsal_impacts_view/1", display_only: true, available: false, code: "snapshot_missing",
      reason: "the bound after snapshot is no longer stored, so its failure-impact rows cannot be interpreted",
    }} />);
    expect(screen.getByTestId("comparison-rehearsal-impacts-unavailable")).toHaveTextContent(
      "the bound after snapshot is no longer stored");
    expect(within(rehearsal()).queryAllByTestId("comparison-rehearsal-row")).toHaveLength(0);
  });

  it("refuses a view computed from other bytes than the comparison binds", () => {
    render(<ComparisonDecision value={compareWith()}
      impactsView={viewOf([BOUNDED_CORE1], { source_sha256: `sha256:${"c".repeat(64)}` })} />);
    expect(screen.getByTestId("comparison-rehearsal-impacts-unavailable")).toHaveTextContent(
      "computed from different evidence bytes than this comparison binds");
    expect(within(rehearsal()).queryAllByTestId("comparison-rehearsal-row")).toHaveLength(0);
  });

  it("says an unreadable section is not a finding of no impact, and an empty one stores no rows", () => {
    const { unmount } = render(<ComparisonDecision value={compareWith([])}
      impactsView={viewOf([], { section_state: "not_collected" })} />);
    expect(screen.getByTestId("comparison-rehearsal-impact-section")).toHaveTextContent(
      "The bound evidence's failure-impact section is not collected");
    expect(screen.getByTestId("comparison-rehearsal-impact-section")).toHaveTextContent("not a finding of no impact");
    expect(screen.queryByTestId("comparison-rehearsal-impact-empty")).not.toBeInTheDocument();
    unmount();
    render(<ComparisonDecision value={compareWith([])} impactsView={viewOf([])} />);
    expect(screen.getByTestId("comparison-rehearsal-impact-empty")).toHaveTextContent(
      "The bound evidence stores no failure-impact rows.");
    expect(screen.queryByTestId("comparison-rehearsal-impact-census")).not.toBeInTheDocument();
  });

  it("caps rendering in the owner's ranking order and discloses the rest", () => {
    const rows = Array.from({ length: 10 }, (_unused, index): ImpactsViewRow => ({
      ...MEASURED_ACCESS1, index, host: `access${index}`,
    }));
    render(<ComparisonDecision value={compareWith()} impactsView={viewOf(rows, {
      counts: { published: 10, lower_bound: 0, not_assessed: 0, ambiguous: 0 },
    })} />);
    const rendered = within(rehearsal()).getAllByTestId("comparison-rehearsal-row");
    expect(rendered).toHaveLength(8);
    expect(rendered[0]).toHaveTextContent("access0");
    expect(rendered[7]).toHaveTextContent("access7");
    expect(impactCap()).toHaveTextContent("Rendered: 8 · Total: 10 · Omitted: 2.");
    expect(screen.queryByTestId("comparison-rehearsal-impact-unranked")).not.toBeInTheDocument();
  });

  it("names every row the owner does not rank even when more than the cap are ranked", () => {
    // 10 ranked rows fill the cap; three held rows sort after them and are never rendered as rows, so the owner's
    // unranked disclosure must name each one (W50 round 4, P2-B).
    const ranked = Array.from({ length: 10 }, (_unused, index): ImpactsViewRow => ({
      ...MEASURED_ACCESS1, index, host: `access${index}`,
    }));
    const held = ["held-a", "held-b", "held-c"].map((host, offset): ImpactsViewRow => ({
      ...HELD_CORE1, index: 10 + offset, host,
    }));
    render(<ComparisonDecision value={compareWith()} impactsView={viewOf([...ranked, ...held], {
      counts: { published: 10, lower_bound: 0, not_assessed: 3, ambiguous: 0 },
    })} />);
    const rendered = within(rehearsal()).getAllByTestId("comparison-rehearsal-row");
    expect(rendered).toHaveLength(8);
    for (const row of rendered) expect(row.textContent).not.toMatch(/held-/);
    const disclosure = screen.getByTestId("comparison-rehearsal-impact-unranked");
    expect(disclosure).toHaveTextContent("Not ranked by the engine owner (3;");
    const named = within(disclosure).getAllByTestId("comparison-rehearsal-impact-unranked-row");
    expect(named.map((item) => item.textContent)).toEqual(["held-a", "held-b", "held-c"].map((host) =>
      `${host} — not assessed (not collected): the row predates the engine's assessability marker`));
    for (const item of named) expect(item.textContent).not.toMatch(/\d+ ep|: 45\b/);
    expect(impactCap()).toHaveTextContent("Rendered: 8 · Total: 13 · Omitted: 5.");
  });

  it("lists unreadable rows from the view's own list, the census's rule, even under a failed section", () => {
    // Under a failed section a non-object row carries section_unavailable, not row_unreadable: the list must follow
    // the owner's census rule (the view's `unreadable`), never a reason code (P3-2).
    const failedRow = (index: number): ImpactsViewRow => ({
      ...UNREADABLE_ROW, index, state: "analysis_unavailable", reasons: [{ code: "section_unavailable", n: 0 }],
    });
    render(<ComparisonDecision value={compareWith()} impactsView={viewOf([failedRow(0), failedRow(3)], {
      section_state: "analysis_unavailable", n_rows_unreadable: 1, unreadable: [3],
      counts: { published: 0, lower_bound: 0, not_assessed: 2, ambiguous: 0 },
    })} />);
    expect(screen.getByTestId("comparison-rehearsal-impact-census")).toHaveTextContent("(1 unreadable)");
    expect(screen.getByTestId("comparison-rehearsal-impact-unreadable")).toHaveTextContent(
      "Unreadable stored rows (counted above, never dropped): #3");
    expect(screen.getByTestId("comparison-rehearsal-impact-unreadable")).not.toHaveTextContent("#0");
  });

  it("shows a view under an unknown schema as unrecognised, with no row value", () => {
    render(<ComparisonDecision value={compareWith()}
      impactsView={{ ...viewOf([BOUNDED_CORE1]), schema: "rehearsal_impacts_view/9" } as unknown as RehearsalImpactsView} />);
    expect(screen.getByTestId("comparison-rehearsal-impacts-unrecognised")).toHaveTextContent(
      'this page does not read view schema "rehearsal_impacts_view/9". No row value is shown.');
    expect(within(rehearsal()).queryAllByTestId("comparison-rehearsal-row")).toHaveLength(0);
    expect(rehearsal()).not.toHaveTextContent("≥ 45");
    expect(rehearsal()).not.toHaveTextContent("Hard partition (34 ep)");
    expect(impactCap()).toHaveTextContent("Rendered: 0 · Total: 1 · Omitted: 1.");
  });

  it("names an unknown cell kind instead of calling it unavailable", () => {
    const odd: ImpactsViewRow = {
      ...MEASURED_ACCESS1, host: "edge5",
      cells: {
        ...MEASURED_ACCESS1.cells,
        stranded: { kind: "estimate", text: "about 40", state: null },
        detail: { kind: "summary", text: "text", state: null },
      },
    };
    render(<ComparisonDecision value={compareWith()} impactsView={viewOf([odd])} />);
    const values = within(rowFor("edge5")).getByTestId("comparison-rehearsal-row-values");
    expect(values).toHaveTextContent("stranded endpoints: unrecognised value kind (estimate)");
    expect(values).not.toHaveTextContent("about 40");
    expect(within(rowFor("edge5")).getByTestId("comparison-rehearsal-row-detail")).toHaveTextContent(
      "Producer detail: unrecognised value kind (summary).");
  });

  it("says the export holds only the bound evidence rows, never the interpretation", () => {
    render(<ComparisonDecision value={compareWith()} impactsView={SAMPLE_VIEW} />);
    expect(impactCap()).toHaveTextContent(
      "The complete JSON export holds only the bound evidence (each stored row that is an object, raw and "
      + "uninterpreted): neither this interpretation nor any stored row that is not an object.");
    expect(impactCap()).not.toHaveTextContent("includes all received rows");
  });
});
