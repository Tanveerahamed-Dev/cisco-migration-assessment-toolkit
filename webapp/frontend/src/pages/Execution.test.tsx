import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router";
import ExecutionPage, { fmtClock, OUTCOME_COLOR } from "./Execution";
import { api } from "../api";
import type { CompareResponse, ExecCheck, ExecutionState, SnapshotMeta } from "../api";

// ── pure helpers ──────────────────────────────────────────────────────────
// The war-room elapsed clock: seconds → H:MM:SS, recomputed from started_at each tick.
describe("fmtClock", () => {
  it("formats sub-minute durations with zero hours and padded seconds", () => {
    expect(fmtClock(0)).toBe("0:00:00");
    expect(fmtClock(5)).toBe("0:00:05");
    expect(fmtClock(59)).toBe("0:00:59");
  });

  it("rolls seconds→minutes→hours, zero-padding minutes and seconds to two digits", () => {
    expect(fmtClock(60)).toBe("0:01:00");
    expect(fmtClock(65)).toBe("0:01:05");
    expect(fmtClock(3599)).toBe("0:59:59");
    expect(fmtClock(3600)).toBe("1:00:00");
    expect(fmtClock(3723)).toBe("1:02:03");
  });

  it("does NOT pad the hours field — a long cutover can run past 9:59:59", () => {
    expect(fmtClock(36000)).toBe("10:00:00");
    expect(fmtClock(3600 * 25 + 61)).toBe("25:01:01");
  });
});

// Outcome badge colour — a rolled-back / aborted run must never read as a green success.
describe("OUTCOME_COLOR", () => {
  it("greens a clean cutover", () => {
    expect(OUTCOME_COLOR("SUCCESSFUL")).toBe("var(--ok)");
  });

  it("reds the failure outcomes", () => {
    expect(OUTCOME_COLOR("ROLLED BACK")).toBe("var(--crit)");
    expect(OUTCOME_COLOR("ABORTED")).toBe("var(--crit)");
  });

  it("ambers partial / unknown outcomes — coverage-honest, never a false green", () => {
    expect(OUTCOME_COLOR("PARTIALLY IMPLEMENTED")).toBe("var(--watch)");
    expect(OUTCOME_COLOR("")).toBe("var(--watch)");
    expect(OUTCOME_COLOR("SOMETHING NEW")).toBe("var(--watch)");
  });
});

// ── page integration ──────────────────────────────────────────────────────
function execState(over: Partial<ExecutionState> = {}): ExecutionState {
  return {
    id: 1,
    snapshot_id: 7,
    label: "Cutover Run A",
    operator: "",
    status: "in_progress",
    outcome: null,
    started_at: "2026-01-01T10:00:00Z",
    ended_at: null,
    plan_summary: {} as ExecutionState["plan_summary"],
    waves: [
      {
        group: "Core-fabric",
        order: 1,
        gate: "GO",
        strategy: "phased",
        n_switches: 2,
        switches: [],
        endpoints: 0,
        hard_cutover_endpoints: 0,
        est_window_minutes: 30,
        est_window_label: "30m",
        blockers: [],
        steps: [],
        checks: [],
        closeout: { decision: null, at: null, by: "", note: "" },
      },
    ],
    events: [],
    progress: {
      n_steps: 4,
      n_steps_done: 1,
      n_steps_skipped: 0,
      pct: 25,
      checks: { pending: 0, pass: 2, fail: 0, na: 0 },
      n_deviations: 0,
      elapsed_seconds: 0,
      planned_window_minutes: 30,
      waves: [{ group: "Core-fabric", state: "active", n_steps: 4, n_actioned: 1 }],
    },
    ...over,
  };
}

const snapMeta: SnapshotMeta = {
  id: 7,
  campaign_id: 3,
  label: "Baseline",
  uploaded_at: "2026-01-01T00:00:00Z",
  script_version: "3.30.0",
  n_devices: 10,
  summary: {} as SnapshotMeta["summary"],
};

function renderExec() {
  return render(
    <MemoryRouter initialEntries={["/executions/1"]}>
      <Routes>
        <Route path="/executions/:id" element={<ExecutionPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function comparisonPolicy() {
  return {
    schema: "execution_comparison_policy/1" as const,
    canonical_gate_required: true as const,
    before_snapshot: {
      source: "persisted snapshots.snapshot_json blob",
      sha256: `sha256:${"1".repeat(64)}`,
      bytes: 1234,
      snapshot_id: 7,
      campaign_id: 3,
      engagement_id: "eng-east",
      label: "Baseline",
      script_version: "3.30.0",
    },
  };
}

function canonicalComparison(verdict: "PASS" | "FAIL" = "PASS"): CompareResponse {
  return {
    comparison_schema: "source_bound_cutover_comparison/1",
    verdict: verdict === "PASS" ? "CLEAN" : "REGRESSED",
    cutover_gate: {
      schema: "cutover_gate/1",
      verdict,
      note: `Bound decision basis for ${verdict}.`,
      operator_note: `Overall before/after cutover decision: ${verdict}. Server-owned execution evidence.`,
      delta_verdict: verdict === "PASS" ? "CLEAN" : "REGRESSED",
      delta_display: verdict === "PASS" ? "CLEAN" : "REGRESSED",
      delta_note: "Bound delta evidence.",
      certificate_verdict: verdict,
      certificate_note: "Bound path evidence.",
      protocol_gate: verdict,
      protocol_baseline_peers: 1,
      protocol_regressions: verdict === "PASS" ? 0 : 1,
      protocol_coverage_gaps: 0,
      comparison_admission_status: "admitted",
      comparison_admission_note: "Source and subject identities admitted.",
    },
  };
}

function executionProtocolFamilyChanges(): NonNullable<CompareResponse["protocol_families"]> {
  const supportProfile = {
    schema: "protocol_support_profile/1" as const,
    family: "ipv4_routing_adjacency",
    owner_schema: "protocol_adjacency_delta/1",
    implementation_state: "implemented" as const,
    assurance_level: "observed_state_preservation" as const,
    evidence_contracts: ["protocol_assessability/1"],
    runtime_support_claim: "receipt_required_per_device_family_cell",
    scope: { address_family: "IPv4" },
    limitations: ["Observed-state preservation only."],
  };
  const changes = [{
    family: "ipv4_routing_adjacency", subject: "DIST-EXPECTED|BGP|10.0.0.2",
    transition: "regressed" as const, expected: true,
    decision_effect: "block" as const, before_state: "Established", after_state: "Idle",
    note: "Expected intent cannot neutralize this producer-owned block.",
  }, {
    family: "ipv4_routing_adjacency", subject: "DIST-UNEXPECTED|OSPF|10.0.0.3",
    transition: "regressed" as const, expected: false,
    decision_effect: "block" as const, before_state: "FULL", after_state: "EXSTART",
    note: "Unexpected adjacency regression.",
  }, {
    family: "ipv4_routing_adjacency", subject: "DIST-COVERAGE|BGP|*",
    transition: "coverage_lost" as const, expected: false,
    decision_effect: "not_verified" as const, before_state: "observed", after_state: "",
    note: "Post-change capture was lost.",
  }];
  const summary = {
    n_subject_changes: 3, n_implicit_unchanged_healthy: 0,
    n_expected: 1, n_unexpected: 1, n_coverage_lost: 1,
    n_blocking: 2, n_review: 0, n_not_verified: 1,
    by_transition: {
      unchanged_healthy: 0, unchanged_degraded: 0, recovered: 0, regressed: 2,
      appeared: 0, disappeared: 0, intent_changed: 0, coverage_lost: 1, not_comparable: 0,
    },
    by_decision_effect: { block: 2, review: 0, none: 0, not_verified: 1 },
  };
  return {
    schema: "protocol_family_change_set/1", owner: "reference_only_composition",
    owns_score: false, owns_verdict: false,
    summary: { n_families: 1, ...summary },
    families: [{
      family: "ipv4_routing_adjacency", owner_schema: "protocol_adjacency_delta/1",
      assurance_level: "observed_state_preservation", support_profile: supportProfile,
      summary, changes, source_receipt: { schema: "protocol_adjacency_delta/1" },
    }],
  };
}

function executionWithComparison(verdict: "PASS" | "FAIL" = "PASS"): ExecutionState {
  const comparison = canonicalComparison(verdict);
  const cutoverGate = comparison.cutover_gate!;
  return execState({
    execution_schema: "cutover_execution/2",
    comparison_policy: comparisonPolicy(),
    latest_comparison: {
      schema: "execution_latest_comparison/1",
      receipt_id: 41,
      receipt_sha256: `sha256:${"a".repeat(64)}`,
      before_snapshot_id: 7,
      after_snapshot_id: 8,
      cutover_gate: cutoverGate,
    },
    comparison_receipts: [{
      id: 41,
      execution_id: 1,
      before_snapshot_id: 7,
      after_snapshot_id: 8,
      receipt_sha256: `sha256:${"a".repeat(64)}`,
      cutover_verdict: verdict,
      created_at: "2026-01-01T11:30:00Z",
      receipt: {
        schema: "execution_comparison_receipt/1",
        before_snapshot_id: 7,
        after_snapshot_id: 8,
        comparison,
        receipt_sha256: `sha256:${"a".repeat(64)}`,
      },
    }],
  });
}

describe("ExecutionPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the war-room loading state while the run loads", () => {
    vi.spyOn(api, "getExecution").mockReturnValue(new Promise<ExecutionState>(() => {}));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();
    expect(screen.getByText(/Opening the war room/i)).toBeInTheDocument();
  });

  it("surfaces a load error instead of a blank console", async () => {
    vi.spyOn(api, "getExecution").mockRejectedValue(new Error("run 1 not found"));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();
    expect(await screen.findByText("run 1 not found")).toBeInTheDocument();
  });

  it("renders a live run: LIVE badge, waves, progress, and the operator input", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(execState());
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    expect(await screen.findByText("Cutover Run A")).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText("Core-fabric")).toBeInTheDocument();
    // server-derived progress line (the pct itself is an animated CountUp, so assert the stable text)
    expect(screen.getByText(/1 of 4 steps done/)).toBeInTheDocument();
    // a live run is signable — the operator field and Finish control are present
    expect(screen.getByPlaceholderText(/Operator/i)).toBeInTheDocument();
    expect(screen.getByText(/Finish run/i)).toBeInTheDocument();
  });

  it("renders a finished run read-only: outcome badge, no operator field or Finish control", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(
      execState({ status: "completed", outcome: "ROLLED BACK", ended_at: "2026-01-01T12:00:00Z" }),
    );
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    expect(await screen.findByText("ROLLED BACK")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("LIVE")).not.toBeInTheDocument());
    expect(screen.queryByPlaceholderText(/Operator/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Finish run/i)).not.toBeInTheDocument();
  });

  // Validation-checks accordion: showChecks starts true, so the toggle's aria-expanded must start
  // true and flip with every click — a screen reader user relies on this, not just the glyph swap.
  it("flips the validation-checks accordion's aria-expanded with its open state", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(
      execState({
        waves: [
          {
            group: "Core-fabric", order: 1, gate: "GO", strategy: "phased",
            n_switches: 2, switches: [], endpoints: 0, hard_cutover_endpoints: 0,
            est_window_minutes: 30, est_window_label: "30m", blockers: [],
            steps: [],
            checks: [
              {
                category: "l2", severity: "High", check: "VLAN present", command: "show vlan brief",
                expect: "vlan 10 up", result: "pending", observed: "", at: null, by: "",
              },
            ],
            closeout: { decision: null, at: null, by: "", note: "" },
          },
        ],
      }),
    );
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    const toggle = await screen.findByRole("button", { name: /Validation checks/i });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("freezes a start-snapshot blocker in view and disables the impossible plain PASS", async () => {
    const blocker = {
      device: "DIST-1", wave: "Core-fabric", category: "Routing", severity: "High",
      check: "OSPF neighbor remains EXSTART", command: "show ip ospf neighbor",
      expect: "PRE-CUTOVER DEGRADED — BLOCKER: EXSTART remains present; matching it is NOT ACCEPTANCE.",
      why: "The adjacency is degraded before cutover.", evidence_state: "degraded",
      projection_custody: "source_bound_embedded_unverified",
      source_key: "routing_neighbors.DIST-1.ospf", baseline_state: "degraded", baseline_blocker: true,
    };
    const current = {
      schema: "current_baseline_gate/1", verdict: "BLOCKED", assessed: true,
      note: "The start snapshot has one definite degraded baseline row.", n_blockers: 1,
      summary: { n_items: 1, n_blockers: 1, n_blockers_returned: 1, blockers_capped: false, by_state: { degraded: 1 } },
      blockers: [blocker], integrity: { valid: true, failures: [] },
    };
    const st = execState();
    st.plan_summary = { current_baseline: current, n_baseline_blockers: 1 } as ExecutionState["plan_summary"];
    st.waves[0].gate = "NO-GO";
    st.waves[0].current_baseline = current;
    st.waves[0].baseline_blockers = [blocker];
    st.waves[0].checks = [{ ...blocker, result: "pending", observed: "", at: null, by: "" }];
    st.progress.checks = { pending: 1, pass: 0, fail: 0, na: 0 };
    const checkCall = vi.spyOn(api, "execCheck");
    vi.spyOn(api, "getExecution").mockResolvedValue(st);
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    const runGate = await screen.findByTestId("execution-baseline-verdict-run");
    expect(runGate).toHaveTextContent("BLOCKED");
    expect(runGate.style.color).toBe("var(--crit)");
    expect(screen.getByTestId("execution-baseline-blocker")).toBeInTheDocument();
    expect(screen.getByText(/source_bound_embedded_unverified/)).toBeInTheDocument();
    expect(screen.getByText(/routing_neighbors\.DIST-1\.ospf/)).toBeInTheDocument();
    const pass = screen.getByRole("button", { name: "PASS BLOCKED" });
    expect(pass).toBeDisabled();
    expect(pass).toHaveAttribute("title", expect.stringContaining("start-snapshot blocker"));
    fireEvent.click(pass);
    expect(checkCall).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Finish run · partial/i })).toHaveAttribute(
      "title", expect.stringContaining("PARTIALLY IMPLEMENTED"),
    );
  });

  it("shows every frozen unbound review as a run-level receipt outside wave checks", async () => {
    const unbound = Array.from({ length: 12 }, (_, i) => ({
      device: `edge-unbound-${i + 1}`,
      wave: "",
      category: "FHRP",
      severity: "High",
      check: `Exact FHRP domain member-intent review ${i + 1}`,
      command: "show standby brief",
      expect: "REVIEW — this SVI is an evidenced gateway in the same exact observed domain while another host has positive FHRP participation; explicit gateway/member intent is not evidenced.",
      why: "Verify intended redundancy membership simultaneously or explicitly disposition the independent gateway.",
      evidence_state: "review",
      baseline_state: "review",
      baseline_blocker: true,
      projection_custody: "current_run_source_bound",
      source_key: `fhrp_redundancy_domain/default/10/10.0.10.0-24/${i + 1}`,
    }));
    const bound = {
      ...unbound[0],
      device: "edge-bound",
      wave: "Core-fabric",
      check: "Bound exact-domain review",
      source_key: "fhrp_redundancy_domain/default/10/10.0.10.0-24/bound",
    };
    const st = execState();
    st.plan_summary = {
      current_baseline: {
        schema: "current_baseline_gate/1",
        verdict: "INDETERMINATE",
        note: "Unresolved exact-domain member intent remains frozen at run start.",
        summary: {
          n_items: 13,
          n_blockers: 13,
          n_blockers_returned: 2,
          blockers_capped: true,
          by_state: { degraded: 0, review: 13, not_verified: 0 },
        },
        blockers: [bound, unbound[0]],
      },
      n_baseline_blockers: 13,
      n_unbound_baseline_blockers: unbound.length,
      baseline_blockers_capped: true,
    } as ExecutionState["plan_summary"];
    st.baseline_blockers = [bound, ...unbound];
    st.unbound_baseline_blockers = unbound;
    st.waves[0].baseline_blockers = [bound];
    vi.spyOn(api, "getExecution").mockResolvedValue(st);
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    expect(await screen.findByTestId("execution-unbound-baseline-receipt")).toHaveTextContent("12 UNBOUND");
    expect(screen.getAllByTestId("execution-unbound-baseline-blocker")).toHaveLength(12);
    expect(screen.getByText("edge-unbound-12")).toBeInTheDocument();
    expect(screen.getAllByText(/explicit gateway\/member intent is not evidenced/)).toHaveLength(12);
    expect(screen.getByText(/without asserting a definite fault/i)).toBeInTheDocument();
    expect(screen.getByText(/fhrp_redundancy_domain\/default\/10\/10\.0\.10\.0-24\/12/)).toBeInTheDocument();
    expect(screen.getByText(/receipt retains all 12 unbound operational row/i)).toBeInTheDocument();
  });

  it("keeps ordinary checks passable when the frozen baseline is CLEAR", async () => {
    const st = execState();
    st.plan_summary = {
      current_baseline: { schema: "current_baseline_gate/1", verdict: "CLEAR", note: "Observed scope clear." },
      n_baseline_blockers: 0,
    } as ExecutionState["plan_summary"];
    st.waves[0].current_baseline = { schema: "current_baseline_gate/1", verdict: "CLEAR", note: "Observed scope clear." };
    st.waves[0].baseline_blockers = [];
    st.waves[0].checks = [{
      category: "Reachability", severity: "High", check: "Ping service", command: "ping 10.0.0.1",
      expect: "Replies received", evidence_state: "assessed", baseline_state: "clear", baseline_blocker: false,
      result: "pending", observed: "", at: null, by: "",
    }];
    vi.spyOn(api, "getExecution").mockResolvedValue(st);
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    const pass = await screen.findByRole("button", { name: "PASS" });
    expect(pass).toBeEnabled();
    expect(screen.getByTestId("execution-baseline-verdict-run")).toHaveTextContent("CLEAR");
    expect(screen.getAllByText(/not authorization by itself/i)).toHaveLength(2);
  });

  it("does not reinterpret evidence text or state when the producer blocker flag is false or absent", async () => {
    const st = execState();
    st.waves[0].checks = [{
      category: "Routing", severity: "High", check: "Typed non-blocker",
      command: "show ip route", expect: "PRE-CUTOVER DEGRADED — BLOCKER: stale display text",
      evidence_state: "degraded", baseline_state: "degraded", baseline_blocker: false,
      result: "pending", observed: "", at: null, by: "",
    }, {
      category: "Routing", severity: "High", check: "Legacy untyped marker",
      command: "show ip ospf neighbor", expect: "PRE-CUTOVER REVIEW — BLOCKER: legacy marker",
      evidence_state: "review", baseline_state: "review",
      result: "pending", observed: "", at: null, by: "",
    }];
    st.progress.checks = { pending: 2, pass: 0, fail: 0, na: 0 };
    vi.spyOn(api, "getExecution").mockResolvedValue(st);
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    await screen.findByText("Typed non-blocker");
    expect(screen.queryByTestId("execution-baseline-blocker")).not.toBeInTheDocument();
    const legacy = screen.getByTestId("execution-legacy-baseline-candidate");
    expect(legacy).toHaveTextContent("LEGACY BASELINE MARKER · DISPLAY ONLY");
    expect(legacy).toHaveTextContent(/does not alter the server-owned gate, outcome, or operator controls/i);
    expect(screen.queryByRole("button", { name: "PASS BLOCKED" })).not.toBeInTheDocument();
    screen.getAllByRole("button", { name: "PASS" }).forEach((button) => expect(button).toBeEnabled());
  });

  // Live log empty state: with zero events the log used to render nothing at all — an honest
  // placeholder replaces that silent blank (companion test below confirms it steps aside once
  // entries exist).
  it("shows an honest placeholder in the live log at zero events", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(execState({ events: [] }));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    expect(await screen.findByText(/No entries yet/i)).toBeInTheDocument();
  });

  it("renders logged entries instead of the empty placeholder once events exist", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(
      execState({
        events: [{ at: "2026-01-01T10:05:00Z", kind: "step", wave: "Core-fabric", text: "did a thing", by: "operator" }],
      }),
    );
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();

    expect(await screen.findByText("did a thing")).toBeInTheDocument();
    expect(screen.queryByText(/No entries yet/i)).not.toBeInTheDocument();
  });
});

describe("ExecutionPage · immutable post-change comparison", () => {
  afterEach(() => vi.restoreAllMocks());

  function campaignWithAfterSnapshot() {
    return {
      id: 3,
      name: "DC East Migration",
      description: "",
      created_at: "2026-01-01T00:00:00Z",
      snapshots: [
        snapMeta,
        { ...snapMeta, id: 6, label: "Older capture", uploaded_at: "2026-01-01T11:30:00Z" },
        { ...snapMeta, id: 9, label: "Pre-run upload", uploaded_at: "2026-01-01T09:59:59Z" },
        { ...snapMeta, id: 8, label: "Post-change", uploaded_at: "2026-01-01T11:00:00Z" },
      ],
    };
  }

  it("binds a same-campaign after snapshot and renders the returned canonical receipt", async () => {
    const initial = execState({
      execution_schema: "cutover_execution/2",
      comparison_policy: comparisonPolicy(),
      comparison_receipts: [],
    });
    const updated = executionWithComparison("PASS");
    vi.spyOn(api, "getExecution").mockResolvedValue(initial);
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    vi.spyOn(api, "getCampaign").mockResolvedValue(campaignWithAfterSnapshot());
    const compare = vi.spyOn(api, "compareExecution").mockResolvedValue(updated);
    renderExec();

    expect(await screen.findByTestId("execution-canonical-gate-missing")).toHaveTextContent("NOT VERIFIED");
    const after = await screen.findByLabelText("After snapshot");
    expect(await within(after).findByRole("option", { name: /Post-change · snapshot 8/ })).toBeInTheDocument();
    expect(within(after).queryByRole("option", { name: /Older capture/ })).not.toBeInTheDocument();
    expect(within(after).queryByRole("option", { name: /Pre-run upload/ })).not.toBeInTheDocument();
    fireEvent.change(after, { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: "Bind and compare" }));

    await waitFor(() => expect(compare).toHaveBeenCalledWith(1, 8));
    expect(await screen.findByTestId("canonical-cutover-verdict")).toHaveTextContent("PASS");
    expect(screen.getByTestId("canonical-cutover-operator-note")).toHaveTextContent("Server-owned execution evidence");
    expect(screen.queryByTestId("execution-canonical-gate-missing")).not.toBeInTheDocument();
    expect(screen.getByTestId("execution-compare-form")).toHaveTextContent("1 immutable comparison receipt");
  });

  it("renders expected, unexpected, and coverage evidence in order without weakening an expected block", async () => {
    const state = executionWithComparison("FAIL");
    state.comparison_receipts![0].receipt.comparison.protocol_families = executionProtocolFamilyChanges();
    vi.spyOn(api, "getExecution").mockResolvedValue(state);
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    vi.spyOn(api, "getCampaign").mockResolvedValue(campaignWithAfterSnapshot());
    renderExec();

    const canonical = await screen.findByTestId("canonical-cutover-decision");
    const expected = screen.getByTestId("family-change-expected-section");
    const unexpected = screen.getByTestId("family-change-unexpected-section");
    const coverage = screen.getByTestId("family-change-coverage-section");
    expect(canonical.compareDocumentPosition(expected) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(expected.compareDocumentPosition(unexpected) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(unexpected.compareDocumentPosition(coverage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(expected).getByTestId("family-change-expected-row-expectation")).toHaveTextContent("EXPECTED");
    const effect = within(expected).getByTestId("family-change-expected-row-effect");
    expect(effect).toHaveTextContent("BLOCK");
    expect(effect.style.color).toBe("var(--crit)");
    expect(screen.getByTestId("canonical-cutover-verdict")).toHaveTextContent("FAIL");
  });

  it("freezes optional expected-family intent into the execution comparison request", async () => {
    const initial = execState({
      execution_schema: "cutover_execution/2",
      comparison_policy: comparisonPolicy(),
      comparison_receipts: [],
    });
    vi.spyOn(api, "getExecution").mockResolvedValue(initial);
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    vi.spyOn(api, "getCampaign").mockResolvedValue(campaignWithAfterSnapshot());
    const compare = vi.spyOn(api, "compareExecution").mockResolvedValue(
      executionWithComparison("REVIEW"),
    );
    const intent = {
      expected_changes: [{
        family: "fhrp_redundancy_domain", transitions: ["intent_changed"],
        subjects: [], reason: "planned active role move",
      }],
      note: "CAB-1234",
    };
    renderExec();

    const after = await screen.findByLabelText("After snapshot");
    expect(await within(after).findByRole("option", { name: /Post-change · snapshot 8/ }))
      .toBeInTheDocument();
    fireEvent.change(after, { target: { value: "8" } });
    fireEvent.change(screen.getByLabelText("Execution expected family changes JSON"), {
      target: { value: JSON.stringify(intent) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Bind and compare" }));

    await waitFor(() => expect(compare).toHaveBeenCalledWith(1, 8, intent));
  });

  it("binds the typed observed L2 phase set and exact witness bytes to execution compare", async () => {
    const initial = execState({
      execution_schema: "cutover_execution/2",
      comparison_policy: comparisonPolicy(),
      comparison_receipts: [],
    });
    vi.spyOn(api, "getExecution").mockResolvedValue(initial);
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    vi.spyOn(api, "getCampaign").mockResolvedValue({
      id: 3,
      name: "DC East Migration",
      description: "",
      created_at: "2026-01-01T00:00:00Z",
      snapshots: [
        snapMeta,
        { ...snapMeta, id: 8, label: "Trial pre", uploaded_at: "2026-01-01T10:30:00Z" },
        { ...snapMeta, id: 9, label: "Trial post", uploaded_at: "2026-01-01T10:40:00Z" },
        { ...snapMeta, id: 10, label: "Recovery", uploaded_at: "2026-01-01T10:50:00Z" },
      ],
    });
    const compare = vi.spyOn(api, "compareExecution").mockResolvedValue(
      executionWithComparison("PASS"),
    );
    renderExec();

    const after = await screen.findByLabelText("After snapshot");
    expect(await within(after).findByRole("option", { name: /Recovery · snapshot 10/ }))
      .toBeInTheDocument();
    fireEvent.change(after, { target: { value: "10" } });
    fireEvent.click(screen.getByLabelText("execution-compare include observed local L2 trial"));
    fireEvent.change(screen.getByLabelText("execution-compare pre-failure snapshot"), {
      target: { value: "8" },
    });
    fireEvent.change(screen.getByLabelText("execution-compare post-failure snapshot"), {
      target: { value: "9" },
    });
    const witness = '{"schema":"l2_failure_witness/1","subject":"dist1|Po10"}';
    fireEvent.change(screen.getByLabelText("execution-compare failure witness JSON"), {
      target: { files: [new File([witness], "execution-trial.json", { type: "application/json" })] },
    });
    expect(await screen.findByText("Witness loaded: execution-trial.json")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bind and compare" }));

    await waitFor(() => expect(compare).toHaveBeenCalledWith(1, 10, undefined, {
      pre_failure_snapshot_id: 8,
      post_failure_snapshot_id: 9,
      witness_json_base64: btoa(witness),
    }));
  });

  it("renders an unresolved exact local re-trial requirement as a finish-blocking warning", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(execState({
      execution_schema: "cutover_execution/2",
      comparison_policy: comparisonPolicy(),
      comparison_receipts: [],
      l2_failure_trial_requirement: {
        schema: "execution_l2_failure_trial_requirement/1",
        family: "etherchannel",
        subject: "dist1|Po10",
        failure_scenario: "single_observed_forwarding_member_loss",
        status: "not_verified",
        phase_sources: {
          pre_failure: { snapshot_id: 8, collected_at: "2026-01-01T10:30:00Z", uploaded_at: "2026-01-01T10:31:00Z" },
          post_failure: { snapshot_id: 9, collected_at: "2026-01-01T10:40:00Z", uploaded_at: "2026-01-01T10:41:00Z" },
          recovery: { snapshot_id: 10, collected_at: "2026-01-01T10:50:00Z", uploaded_at: "2026-01-01T10:51:00Z" },
        },
      },
    }));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    vi.spyOn(api, "getCampaign").mockResolvedValue(campaignWithAfterSnapshot());
    renderExec();

    const warning = await screen.findByTestId("execution-l2-retrial-requirement");
    expect(warning).toHaveTextContent(/not verified trial remains binding/i);
    expect(warning).toHaveTextContent("etherchannel · dist1|Po10");
    expect(warning).toHaveTextContent(/only a strictly newer exact observed-survival/i);
    expect(screen.getByRole("button", { name: /Finish run · partial/i })).toBeInTheDocument();
  });

  it("keeps a legacy execution neutral and offers no backfill control", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(execState());
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    const getCampaign = vi.spyOn(api, "getCampaign");
    renderExec();

    expect(await screen.findByTestId("execution-comparison-legacy")).toHaveTextContent(/cannot be reinterpreted or backfilled/i);
    expect(screen.queryByTestId("execution-compare-form")).not.toBeInTheDocument();
    expect(getCampaign).not.toHaveBeenCalled();
  });
});

// ── FE-13: an UNVALIDATED wave must not wear the colour of a VALIDATED one ──────────────────
// The wave header's check counter is `{nPass}✓ {nFail}✗` coloured `nFail ? crit : ok`. A wave whose
// validation checks are all still `pending` has nFail === 0, so it rendered in exactly the green a
// wave that passed every check does — "not observed" reading as "healthy" on the surface an engineer
// scans immediately before pressing "✓ Complete wave".
describe("ExecutionPage · unrecorded validation is not a pass", () => {
  afterEach(() => vi.restoreAllMocks());

  const check = (result: ExecCheck["result"], name: string): ExecCheck => ({
    category: "l2", severity: "High", check: name, command: "show vlan brief",
    expect: "vlan 10 up", result, observed: "", at: null, by: "",
  });

  function withChecks(checks: ExecCheck[]) {
    const st = execState();
    st.waves[0].checks = checks;
    return st;
  }
  // the wave header's check tile: the .wmeta cell whose label starts with "checks"
  const counterIn = (container: HTMLElement) =>
    Array.from(container.querySelectorAll(".wmeta .lbl"))
      .find((e) => (e.textContent || "").startsWith("checks"))!.parentElement!;

  it("FE-13: all-pending checks render tone-neutral and say how many are unrecorded", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(withChecks([check("pending", "a"), check("pending", "b")]));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    const { container } = renderExec();
    await screen.findByText("Cutover Run A");

    const el = counterIn(container);
    expect(el.textContent).toMatch(/2 unrecorded/);
    expect(el.querySelector(".num")!.getAttribute("style")).not.toContain("var(--ok)");
  });

  it("FE-13: a fully-passed wave keeps the green — the fix must not flatten a real verdict", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(withChecks([check("pass", "a"), check("pass", "b")]));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    const { container } = renderExec();
    await screen.findByText("Cutover Run A");

    const el = counterIn(container);
    expect(el.textContent).not.toMatch(/unrecorded/);
    expect(el.querySelector(".num")!.getAttribute("style")).toContain("var(--ok)");
  });

  it("FE-13: a failing check still reds the counter regardless of what is left pending", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(withChecks([check("fail", "a"), check("pending", "b")]));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    const { container } = renderExec();
    await screen.findByText("Cutover Run A");

    expect(counterIn(container).querySelector(".num")!.getAttribute("style")).toContain("var(--crit)");
  });

  it("FE-13: the console strip discloses the run-wide pending validation count", async () => {
    const st = execState();
    st.progress.checks = { pending: 7, pass: 2, fail: 0, na: 0 };
    vi.spyOn(api, "getExecution").mockResolvedValue(st);
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    renderExec();
    await screen.findByText("Cutover Run A");

    expect(screen.getByText(/7 pending/)).toBeInTheDocument();
  });
});

// ── FE-10: the finish-confirm must not disagree with the backend's own outcome derivation ──
// webapp/backend/execution.py :: _derive_outcome is
//   `if not decisions or any(d != "COMPLETE" for d in decisions): return OUTCOME_PARTIAL`
// so a wave closed out DEFERRED forces PARTIALLY IMPLEMENTED — while the page's `open` counter
// (waves with NO decision) reads 0 and used to show the unconditional "the outcome is derived for
// the PIR" wording, i.e. no warning at all before an irreversible, signed sign-off.
describe("ExecutionPage · finish-confirm matches the backend outcome derivation", () => {
  afterEach(() => vi.restoreAllMocks());

  function closedAs(decision: string) {
    const st = execState();
    st.waves[0].closeout = { decision, at: "2026-01-01T11:00:00Z", by: "eng", note: "" };
    return st;
  }

  it("FE-10: a DEFERRED-closed wave warns that finishing derives PARTIALLY IMPLEMENTED", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(closedAs("DEFERRED"));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderExec();
    fireEvent.click(await screen.findByRole("button", { name: /Finish run/i }));
    expect(confirm).toHaveBeenCalledTimes(1);
    const msg = confirm.mock.calls[0][0] as string;
    expect(msg).toMatch(/other than COMPLETE/);
    expect(msg).toContain("PARTIALLY IMPLEMENTED");
  });

  it("FE-10: a ROLLED BACK wave predicts ROLLED BACK, matching _derive_outcome's precedence", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(closedAs("ROLLED BACK"));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderExec();
    fireEvent.click(await screen.findByRole("button", { name: /Finish run/i }));
    expect(confirm.mock.calls[0][0] as string).toContain("ROLLED BACK");
  });

  it("FE-10: an all-COMPLETE run keeps the plain confirm — the fix must not cry wolf", async () => {
    vi.spyOn(api, "getExecution").mockResolvedValue(closedAs("COMPLETE"));
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderExec();
    fireEvent.click(await screen.findByRole("button", { name: /Finish run/i }));
    const msg = confirm.mock.calls[0][0] as string;
    expect(msg).toMatch(/becomes read-only/);
    expect(msg).not.toMatch(/PARTIALLY IMPLEMENTED/);
  });

  it("warns that an all-COMPLETE run with a frozen BLOCKED baseline derives partial", async () => {
    const st = closedAs("COMPLETE");
    st.plan_summary = {
      current_baseline: {
        schema: "current_baseline_gate/1", verdict: "BLOCKED",
        note: "A degraded start-snapshot row remains.",
      },
      n_baseline_blockers: 1,
    } as ExecutionState["plan_summary"];
    vi.spyOn(api, "getExecution").mockResolvedValue(st);
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderExec();
    fireEvent.click(await screen.findByRole("button", { name: /Finish run · partial/i }));

    const msg = confirm.mock.calls[0][0] as string;
    expect(msg).toContain("start-snapshot current-baseline gate is BLOCKED");
    expect(msg).toContain("PARTIALLY IMPLEMENTED");
    expect(msg).toContain("re-collect a CLEAR snapshot");
  });

  it("warns that a new execution without a latest canonical PASS derives partial", async () => {
    const st = executionWithComparison("FAIL");
    st.waves[0].closeout = { decision: "COMPLETE", at: "2026-01-01T11:00:00Z", by: "eng", note: "" };
    st.plan_summary = {
      current_baseline: {
        schema: "current_baseline_gate/1", verdict: "CLEAR", assessed: true,
        note: "Observed start scope is clear.",
      },
    } as ExecutionState["plan_summary"];
    vi.spyOn(api, "getExecution").mockResolvedValue(st);
    vi.spyOn(api, "getSnapshot").mockResolvedValue(snapMeta);
    vi.spyOn(api, "getCampaign").mockResolvedValue({
      id: 3, name: "DC East Migration", description: "", created_at: "2026-01-01T00:00:00Z",
      snapshots: [snapMeta, { ...snapMeta, id: 8, label: "Post-change" }],
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderExec();
    fireEvent.click(await screen.findByRole("button", { name: /Finish run · partial/i }));

    const msg = confirm.mock.calls[0][0] as string;
    expect(msg).toContain("latest canonical post-change gate is FAIL");
    expect(msg).toContain("PARTIALLY IMPLEMENTED");
    expect(msg).toContain("server-owned cutover gate is PASS");
  });
});
