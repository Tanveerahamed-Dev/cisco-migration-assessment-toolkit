import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import CutoverPlanner from "./CutoverPlanner";
import { api } from "../api";

// CutoverPlanner reaches three api methods on a populated render (cutover + meta + listExecutions),
// and its ExecutionRuns child uses useNavigate/Link — so it must be wrapped in a router.
const cutover = {
  summary: {
    verdict: "CONDITIONAL GO",
    statement: "Pilot-first cutover: one zero-outage wave proves the method before hard cuts.",
    n_waves: 1, n_devices: 3, n_make_before_break: 1, n_hard_cutover: 0,
    hard_cutover_endpoints: 0, est_window_minutes: 0, est_window_label: "0 min",
    gates: { "CONDITIONAL GO": 1 },
  },
  waves: [{
    group: "Access-Pilot", order: 1, gate: "GO", strategy: "make-before-break",
    readiness: "READY", n_switches: 3, endpoints: 120,
    est_window_minutes: 0, est_window_label: "0 min",
    make_before_break: [], hard_cutover: [], blast_radius: null, keystones: [],
    blockers: [], critical_crosslayer: [], run_of_show: [], validation: [], remediation: [],
  }],
};

function renderPlanner() {
  return render(
    <MemoryRouter>
      <CutoverPlanner snapId={1} />
    </MemoryRouter>,
  );
}

describe("CutoverPlanner (render)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the loading state while the plan builds", () => {
    vi.spyOn(api, "cutover").mockReturnValue(new Promise(() => {}) as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();
    expect(screen.getByText(/Building cutover plan/i)).toBeInTheDocument();
  });

  it("surfaces a load error from the primary cutover fetch", async () => {
    vi.spyOn(api, "cutover").mockRejectedValue(new Error("cutover 1 failed"));
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();
    expect(await screen.findByText("cutover 1 failed")).toBeInTheDocument();
  });

  it("renders the run-of-show once the plan loads", async () => {
    vi.spyOn(api, "cutover").mockResolvedValue(cutover as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();
    expect(await screen.findByText("Cutover plan · run-of-show")).toBeInTheDocument();
    // the populated wave rendered its stat labels
    expect(screen.getByText("est. total window")).toBeInTheDocument();
  });

  it("keeps every current-baseline blocker visible outside the ordinary ten-check cap", async () => {
    const ordinary = Array.from({ length: 31 }, (_, i) => ({
      category: "Reachability", severity: "Medium", check: `ordinary-check-${i + 1}`,
      command: `show ordinary ${i + 1}`, expect: "run after cutover",
    }));
    const blocker = {
      device: "DIST-1", wave: "Access-Pilot", category: "Routing", severity: "High",
      check: "OSPF observed adjacency baseline is degraded",
      command: "show ip ospf neighbor",
      expect: "PRE-CUTOVER DEGRADED — BLOCKER: 10.0.0.2 EXSTART/DR. Matching it is NOT ACCEPTANCE.",
      evidence_state: "degraded", projection_custody: "source_bound_embedded_unverified",
      source_key: "routing_neighbors.DIST-1.ospf",
    };
    const blockedPlan = {
      ...cutover,
      waves: [{
        ...cutover.waves[0],
        current_baseline: {
          schema: "current_baseline_gate/1", verdict: "BLOCKED", assessed: true,
          note: "One current degraded baseline blocks acceptance.",
          summary: { n_items: 32, n_blockers: 1, n_blockers_returned: 1, blockers_capped: false, by_state: { degraded: 1, review: 0, not_verified: 0 } },
          blockers: [blocker], integrity: { valid: true, failures: [] },
        },
        baseline_blockers: [blocker],
        validation: [...ordinary, blocker],
      }],
    };
    vi.spyOn(api, "cutover").mockResolvedValue(blockedPlan as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();

    const gate = await screen.findByTestId("current-baseline-verdict");
    expect(gate).toHaveTextContent("BLOCKED");
    expect(gate.style.color).toBe("var(--crit)");
    expect(screen.getAllByTestId("baseline-blocker")).toHaveLength(1);
    expect(screen.getByText("OSPF observed adjacency baseline is degraded")).toBeInTheDocument();
    expect(screen.getByText(/source_bound_embedded_unverified/)).toBeInTheDocument();
    expect(screen.getByText(/routing_neighbors\.DIST-1\.ospf/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Run-of-show/ }));
    expect(screen.getByText(/Post-cutover validation \(31\)/)).toBeInTheDocument();
    expect(screen.getByText(/\+21 more/)).toHaveTextContent("Current-baseline blockers remain visible above");
    expect(screen.queryByText("ordinary-check-31")).toBeNull();
    expect(screen.getByText("OSPF observed adjacency baseline is degraded")).toBeInTheDocument();
  });

  it("shows both sequential exact-candidate FHRP reviews outside the ordinary cap", async () => {
    const ordinary = Array.from({ length: 31 }, (_, i) => ({
      category: "Reachability", severity: "Medium", check: `ordinary-fhrp-check-${i + 1}`,
      command: `show ordinary fhrp ${i + 1}`, expect: "run after cutover",
    }));
    const acceptance = (
      "PRE-CUTOVER REVIEW — BLOCKER: Exact sequential candidate scope default/ipv4, HSRP "
      + "interface Vlan10 group 10, configured/runtime VIP 10.0.10.1, observed role composition "
      + "ACTIVE=2 across 2 distinct hosts: multiple ACTIVE leaders were observed in sequential "
      + "captures. Capture timing is not simultaneous evidence, and candidate scope may be incomplete; "
      + "verify the intended candidates simultaneously and explicitly disposition the election before acceptance. Matching the "
      + "conflicting or unresolved sequential roles is NOT ACCEPTANCE."
    );
    const reviews = ["edge-a", "edge-b"].map((device) => ({
      device, wave: "Access-Pilot", category: "FHRP", severity: "High",
      check: "HSRP configured group 10 evidence review", command: "show standby brief",
      expect: acceptance, why: "Sequential exact-candidate consistency review.",
      evidence_state: "review", baseline_state: "review",
      projection_custody: "current_run_source_bound",
      source_key: "show running-config#line:3 + show standby brief",
    }));
    const reviewPlan = {
      ...cutover,
      waves: [{
        ...cutover.waves[0],
        gate: "NO-GO",
        current_baseline: {
          schema: "current_baseline_gate/1", verdict: "INDETERMINATE", assessed: true,
          note: "Two sequential exact-candidate review rows withhold acceptance.",
          summary: { n_items: 33, n_blockers: 2, n_blockers_returned: 2, blockers_capped: false, by_state: { degraded: 0, review: 2, not_verified: 0 } },
          blockers: reviews, integrity: { valid: true, failures: [] },
        },
        baseline_blockers: reviews,
        validation: [...ordinary, ...reviews],
      }],
    };
    vi.spyOn(api, "cutover").mockResolvedValue(reviewPlan as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();

    const gate = await screen.findByTestId("current-baseline-verdict");
    expect(gate).toHaveTextContent("INDETERMINATE");
    expect(gate.style.color).toBe("var(--watch)");
    expect(screen.getAllByTestId("baseline-blocker")).toHaveLength(2);
    expect(screen.getByText("edge-a")).toBeInTheDocument();
    expect(screen.getByText("edge-b")).toBeInTheDocument();
    expect(screen.getAllByText(/Capture timing is not simultaneous evidence/)).toHaveLength(2);
    expect(screen.getAllByText(/Matching the conflicting or unresolved sequential roles is NOT ACCEPTANCE/)).toHaveLength(2);
    expect(screen.getAllByText(/current_run_source_bound/)).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: /Run-of-show/ }));
    expect(screen.getByText(/Post-cutover validation \(31\)/)).toBeInTheDocument();
    expect(screen.getByText(/\+21 more/)).toHaveTextContent("Current-baseline blockers remain visible above");
    expect(screen.queryByText("ordinary-fhrp-check-31")).toBeNull();
    expect(screen.getAllByTestId("baseline-blocker")).toHaveLength(2);
  });

  it("bounds CLEAR to observed validation evidence instead of presenting authorization", async () => {
    const clearPlan = {
      ...cutover,
      waves: [{
        ...cutover.waves[0],
        current_baseline: {
          schema: "current_baseline_gate/1", verdict: "CLEAR", assessed: true,
          note: "No producer-declared baseline blocker was found.",
          summary: { n_items: 2, n_blockers: 0, n_blockers_returned: 0, blockers_capped: false, by_state: { degraded: 0, review: 0, not_verified: 0 } },
          blockers: [], integrity: { valid: true, failures: [] },
        },
        baseline_blockers: [],
      }],
    };
    vi.spyOn(api, "cutover").mockResolvedValue(clearPlan as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();

    expect(await screen.findByTestId("current-baseline-verdict")).toHaveTextContent("CLEAR");
    expect(screen.getByTestId("current-baseline-clear-boundary")).toHaveTextContent(/not cutover authorization/i);
  });

  it("uses producer-owned blocker flags and keeps legacy marker fallback neutral", async () => {
    const declaredBlocker = {
      device: "DIST-TYPED", wave: "Access-Pilot", category: "Routing", severity: "High",
      check: "Typed baseline blocker", command: "show ip ospf neighbor",
      expect: "Typed producer classification.", evidence_state: "degraded", baseline_state: "degraded",
      baseline_blocker: true, projection_custody: "current_run_source_bound",
      source_key: "typed/blocker",
    };
    const producerNonBlocker = {
      category: "Routing", severity: "Medium", check: "Producer-declared ordinary validation",
      command: "show ip route", expect: "PRE-CUTOVER DEGRADED — BLOCKER: stale display text",
      evidence_state: "degraded", baseline_state: "degraded", baseline_blocker: false,
    };
    const legacyCandidate = {
      category: "Routing", severity: "Medium", check: "Legacy untyped baseline marker",
      command: "show ip ospf neighbor", expect: "PRE-CUTOVER REVIEW — BLOCKER: legacy marker",
      evidence_state: "review", baseline_state: "review",
    };
    const mixedVersionPlan = {
      ...cutover,
      waves: [{
        ...cutover.waves[0],
        validation: [declaredBlocker, producerNonBlocker, legacyCandidate],
      }],
    };
    vi.spyOn(api, "cutover").mockResolvedValue(mixedVersionPlan as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();

    expect(await screen.findByTestId("current-baseline-verdict")).toHaveTextContent("NOT ASSESSED");
    expect(screen.getAllByTestId("baseline-blocker")).toHaveLength(1);
    expect(screen.getByTestId("baseline-blocker")).toHaveTextContent("Typed baseline blocker");
    expect(screen.getAllByTestId("legacy-baseline-candidate")).toHaveLength(1);
    expect(screen.getByTestId("legacy-baseline-candidate")).toHaveTextContent("DISPLAY ONLY");
    expect(screen.getByTestId("legacy-baseline-disclosure")).toHaveTextContent(
      /do not alter the server-owned gate, counts, or cutover decision/i,
    );

    fireEvent.click(screen.getByRole("button", { name: /Run-of-show/ }));
    expect(screen.getByText(/Post-cutover validation \(1\)/)).toBeInTheDocument();
    expect(screen.getByText("Producer-declared ordinary validation")).toBeInTheDocument();
  });

  it("renders every fleet-level unbound review before the no-waves return", async () => {
    const reviews = Array.from({ length: 12 }, (_, i) => ({
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
    const noWavePlan = {
      ...cutover,
      summary: {
        ...cutover.summary,
        verdict: "NOT ASSESSED",
        n_waves: 0,
        n_devices: 0,
        n_unbound_baseline_blockers: reviews.length,
        n_baseline_blockers: reviews.length,
        current_baseline: {
          schema: "current_baseline_gate/1",
          verdict: "INDETERMINATE",
          assessed: true,
          note: "Unscheduled exact-domain reviews withhold fleet acceptance.",
          summary: {
            n_items: reviews.length,
            n_blockers: reviews.length,
            n_blockers_returned: 3,
            blockers_capped: true,
            by_state: { degraded: 0, review: reviews.length, not_verified: 0 },
          },
          blockers: reviews.slice(0, 3),
          integrity: { valid: true, failures: [] },
        },
      },
      waves: [],
      baseline_blockers: reviews,
    };
    vi.spyOn(api, "cutover").mockResolvedValue(noWavePlan as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();

    expect(await screen.findByText(/No migration waves were derived/)).toBeInTheDocument();
    expect(screen.getByTestId("current-baseline-verdict-fleet")).toHaveTextContent("INDETERMINATE");
    expect(screen.getAllByTestId("unbound-baseline-blocker")).toHaveLength(12);
    expect(screen.getByText("edge-unbound-12")).toBeInTheDocument();
    expect(screen.getAllByText(/explicit gateway\/member intent is not evidenced/)).toHaveLength(12);
    expect(screen.getByTestId("unbound-baseline-disclosure")).toHaveTextContent("12 unbound blocker(s)");
    expect(screen.getByText(/plan-level receipt retains all 12 operational blocker row/i)).toBeInTheDocument();
  });

  it("multiset-subtracts only the bound occurrence when identical blocker rows repeat", async () => {
    const repeated = {
      device: "edge-repeat",
      wave: "Access-Pilot",
      category: "FHRP",
      severity: "High",
      check: "Repeated exact-domain intent review",
      command: "show standby brief",
      expect: "REVIEW — intended redundancy membership is unresolved.",
      evidence_state: "review",
      projection_custody: "current_run_source_bound",
      source_key: "fhrp_redundancy_domain/repeated-occurrence",
    };
    const repeatedPlan = {
      ...cutover,
      summary: {
        ...cutover.summary,
        n_baseline_blockers: 2,
        n_unbound_baseline_blockers: 1,
        current_baseline: {
          schema: "current_baseline_gate/1",
          verdict: "INDETERMINATE",
          note: "One repeated occurrence is not assigned to the scheduled wave.",
          summary: { n_items: 2, n_blockers: 2, n_blockers_returned: 2, blockers_capped: false, by_state: { review: 2 } },
          blockers: [repeated, { ...repeated }],
        },
      },
      baseline_blockers: [repeated, { ...repeated }],
      waves: [{
        ...cutover.waves[0],
        baseline_blockers: [repeated],
        validation: [repeated],
      }],
    };
    vi.spyOn(api, "cutover").mockResolvedValue(repeatedPlan as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();

    await screen.findByText("Cutover plan · run-of-show");
    expect(screen.getAllByTestId("unbound-baseline-blocker")).toHaveLength(1);
    expect(screen.getAllByTestId("baseline-blocker")).toHaveLength(1);
    expect(screen.getByTestId("unbound-baseline-disclosure")).toHaveTextContent("1 unbound blocker(s)");
  });

  // FE-14: ExecutionRuns destructured useAsync for `data` + `reload` only, so a failed
  // GET /api/snapshots/{id}/executions (403 from the cross-site guard, 404 "Snapshot not found",
  // a dropped connection) left `runs === null` and the chip list simply did not render. The
  // engineer sees a bare "Start execution run" button and concludes no run exists for this
  // snapshot — then opens a SECOND war room over a cutover another operator already has live.
  it("FE-14: a failed run list says so instead of looking like 'no runs exist'", async () => {
    vi.spyOn(api, "cutover").mockResolvedValue(cutover as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockRejectedValue(new Error("403 cross-site refused"));
    renderPlanner();
    await screen.findByText("Cutover plan · run-of-show");

    expect(await screen.findByText(/403 cross-site refused/)).toBeInTheDocument();
    expect(screen.getByText(/not evidence that no run is open/i)).toBeInTheDocument();
  });

  it("FE-14: a successful empty run list stays quiet — the fix must not cry wolf", async () => {
    vi.spyOn(api, "cutover").mockResolvedValue(cutover as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();
    await screen.findByText("Cutover plan · run-of-show");

    expect(screen.queryByText(/not evidence that no run is open/i)).toBeNull();
  });

  it("surfaces the latest post-change gate and honest bind state from existing execution receipts", async () => {
    vi.spyOn(api, "cutover").mockResolvedValue(cutover as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([
      {
        id: 41, snapshot_id: 1, label: "Cutover run 1", status: "in_progress",
        started_at: "2026-08-20T00:00:00Z", ended_at: null, comparison_required: true,
      },
      {
        id: 42, snapshot_id: 1, label: "Cutover run 2", status: "completed",
        started_at: "2026-08-20T01:00:00Z", ended_at: "2026-08-20T02:00:00Z",
        comparison_required: true,
        latest_comparison: {
          schema: "execution_latest_comparison/1", receipt_id: 7,
          receipt_sha256: `sha256:${"a".repeat(64)}`,
          before_snapshot_id: 1, after_snapshot_id: 9,
          cutover_gate: { schema: "cutover_gate/1", verdict: "PASS" },
        },
      },
      {
        id: 43, snapshot_id: 1, label: "Legacy run", status: "completed",
        started_at: "2026-08-19T01:00:00Z", ended_at: "2026-08-19T02:00:00Z",
      },
    ] as never);
    renderPlanner();

    expect(await screen.findByTestId("cutover-execution-41")).toHaveTextContent(
      /post-change NOT VERIFIED/,
    );
    expect(screen.getByTestId("cutover-execution-42")).toHaveTextContent(
      /post-change PASS · after snapshot 9/,
    );
    expect(screen.getByTestId("cutover-execution-43")).toHaveTextContent(
      /legacy · no canonical receipt/,
    );
  });

  it("binds a same-campaign snapshot to a live execution and renders the returned canonical receipt", async () => {
    const sourceBinding = {
      source: "persisted snapshots.snapshot_json blob",
      sha256: `sha256:${"1".repeat(64)}`,
      bytes: 1234,
      snapshot_id: 1,
      campaign_id: 73,
      engagement_id: "eng-east",
      label: "Baseline",
      script_version: "3.30.0",
    };
    const initialExecution = {
      id: 41, snapshot_id: 1, label: "Cutover run 1", operator: "", status: "in_progress",
      outcome: null, started_at: "2026-08-20T00:00:00Z", ended_at: null,
      execution_schema: "cutover_execution/2",
      comparison_policy: {
        schema: "execution_comparison_policy/1",
        canonical_gate_required: true,
        before_snapshot: sourceBinding,
      },
      comparison_receipts: [],
    };
    const comparison = {
      comparison_schema: "source_bound_cutover_comparison/1",
      verdict: "CLEAN",
      cutover_gate: {
        schema: "cutover_gate/1", verdict: "PASS",
        note: "Comparison admission: ADMITTED. All canonical inputs pass.",
        operator_note: "Overall before/after cutover decision: PASS.",
        delta_verdict: "CLEAN", delta_display: "CLEAN", delta_note: "No new regression.",
        certificate_verdict: "PASS", certificate_note: "Service paths passed.",
        protocol_gate: "PASS", protocol_baseline_peers: 2,
        protocol_regressions: 0, protocol_coverage_gaps: 0,
        comparison_admission_status: "admitted",
        comparison_admission_note: "Frozen sources admitted.",
      },
    };
    const updatedExecution = {
      ...initialExecution,
      latest_comparison: {
        schema: "execution_latest_comparison/1", receipt_id: 91,
        receipt_sha256: `sha256:${"a".repeat(64)}`,
        before_snapshot_id: 1, after_snapshot_id: 2,
        cutover_gate: comparison.cutover_gate,
      },
      comparison_receipts: [{
        id: 91, execution_id: 41, before_snapshot_id: 1, after_snapshot_id: 2,
        receipt_sha256: `sha256:${"a".repeat(64)}`, cutover_verdict: "PASS",
        created_at: "2026-08-20T01:00:00Z",
        receipt: {
          schema: "execution_comparison_receipt/1",
          before_snapshot_id: 1, after_snapshot_id: 2,
          comparison, receipt_sha256: `sha256:${"a".repeat(64)}`,
        },
      }],
    };
    vi.spyOn(api, "cutover").mockResolvedValue(cutover as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([{
      id: 41, snapshot_id: 1, label: "Cutover run 1", status: "in_progress",
      started_at: "2026-08-20T00:00:00Z", ended_at: null, comparison_required: true,
    }] as never);
    vi.spyOn(api, "getExecution").mockResolvedValue(initialExecution as never);
    const getCampaign = vi.spyOn(api, "getCampaign").mockResolvedValue({
      id: 73, name: "DC East", description: "", created_at: "2026-08-19T00:00:00Z",
      snapshots: [
        { id: 1, campaign_id: 73, label: "Baseline" },
        { id: 2, campaign_id: 73, label: "Post-change" },
      ],
    } as never);
    const compare = vi.spyOn(api, "compareExecution").mockResolvedValue(updatedExecution as never);
    renderPlanner();

    fireEvent.click(await screen.findByRole("button", { name: "Open post-change evidence for Cutover run 1" }));
    expect(await screen.findByTestId("cutover-execution-gate-missing-41")).toHaveTextContent("NOT VERIFIED");
    expect(getCampaign).toHaveBeenCalledWith(73);
    const after = screen.getByLabelText("After snapshot for Cutover run 1");
    expect(within(after).queryByRole("option", { name: /Baseline/ })).toBeNull();
    expect(within(after).getByRole("option", { name: /Post-change · snapshot 2/ })).toBeInTheDocument();
    fireEvent.change(after, { target: { value: "2" } });
    const intent = {
      expected_changes: [{
        family: "fhrp_redundancy_domain", transitions: ["intent_changed"],
        subjects: [], reason: "planned active role move",
      }],
      note: "CAB-1234",
    };
    fireEvent.change(screen.getByLabelText("Expected family changes for Cutover run 1"), {
      target: { value: JSON.stringify(intent) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Bind and compare Cutover run 1" }));

    await waitFor(() => expect(compare).toHaveBeenCalledWith(41, 2, intent));
    expect(await screen.findByTestId("canonical-cutover-verdict")).toHaveTextContent("PASS");
    expect(screen.getByTestId("canonical-cutover-operator-note")).toHaveTextContent(
      "Overall before/after cutover decision: PASS.",
    );
    expect(screen.getByText(/appended as an immutable canonical comparison receipt/i)).toBeInTheDocument();
    expect(screen.getByTestId("cutover-execution-evidence-41")).toHaveTextContent(
      /1 immutable comparison receipt.*latest receipt 91/i,
    );
  });

  it("keeps a legacy planner execution read-only with no comparison backfill control", async () => {
    vi.spyOn(api, "cutover").mockResolvedValue(cutover as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([{
      id: 43, snapshot_id: 1, label: "Legacy run", status: "completed",
      started_at: "2026-08-19T01:00:00Z", ended_at: "2026-08-19T02:00:00Z",
    }] as never);
    vi.spyOn(api, "getExecution").mockResolvedValue({
      id: 43, snapshot_id: 1, label: "Legacy run", status: "completed",
      comparison_receipts: [],
    } as never);
    const getCampaign = vi.spyOn(api, "getCampaign");
    const compare = vi.spyOn(api, "compareExecution");
    renderPlanner();

    fireEvent.click(await screen.findByRole("button", { name: "Open post-change evidence for Legacy run" }));
    expect(await screen.findByTestId("cutover-execution-legacy-43")).toHaveTextContent(
      /cannot be reinterpreted or backfilled/i,
    );
    expect(screen.queryByLabelText("After snapshot for Legacy run")).toBeNull();
    expect(getCampaign).not.toHaveBeenCalled();
    expect(compare).not.toHaveBeenCalled();
  });

  it("flips aria-expanded on the wave's run-of-show toggle as it opens/closes", async () => {
    vi.spyOn(api, "cutover").mockResolvedValue(cutover as never);
    vi.spyOn(api, "meta").mockResolvedValue({ deliverables: [] } as never);
    vi.spyOn(api, "listExecutions").mockResolvedValue([] as never);
    renderPlanner();
    await screen.findByText("Cutover plan · run-of-show");
    const toggle = screen.getByRole("button", { name: /Run-of-show/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
