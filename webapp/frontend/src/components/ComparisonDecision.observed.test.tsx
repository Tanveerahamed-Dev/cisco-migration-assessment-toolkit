import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CompareResponse, ObservedL2FailureEvidence } from "../api";
import ComparisonDecision from "./ComparisonDecision";

function observedReceipt(): ObservedL2FailureEvidence {
  const phase = (id: number, collectedAt: string) => ({
    source: "persisted snapshots.snapshot_json blob",
    source_id: `snapshot:${id}`,
    campaign_id: 7,
    engagement_id: "ENG-L2",
    sha256: `sha256:${String(id).padStart(64, "0")}`,
    bytes: 4096 + id,
    collected_at: collectedAt,
    custody_at: collectedAt,
  });
  return {
    schema: "observed_l2_failure_evidence/1",
    owner: "observed_local_l2_failure_trial",
    owns_score: false,
    owns_verdict: false,
    status: "observed_survival",
    assurance_level: "local_safety_preservation",
    family: "etherchannel",
    subject: "dist1|Po10",
    failure_scenario: "single_observed_forwarding_member_loss",
    source_binding: {
      pre_failure: phase(11, "2026-08-20T01:00:00+00:00"),
      post_failure: phase(12, "2026-08-20T01:01:00+00:00"),
      recovery: phase(13, "2026-08-20T01:02:00+00:00"),
      failure_witness: {
        encoding: "base64",
        content_base64: "c2VjcmV0LW9wZXJhdG9yLWNvbnRleHQ=",
        sha256: `sha256:${"f".repeat(64)}`,
        bytes: 23,
        induced_at: "2026-08-20T01:00:30+00:00",
      },
    },
    precondition: { status: "passed", evidence: {} },
    failure_witness: {
      status: "witnessed", action: "shut_link",
      target: { host: "dist1", interface: "Gi1/0/2" },
      induced_at: "2026-08-20T01:00:30+00:00", evidence: {},
    },
    post_failure: { status: "survived", evidence: {} },
    recovery: { status: "recovered", evidence: {} },
    claims: {
      local_scenario: "observed_survival",
      service_path_survival: "not_verified",
      traffic_continuity: "not_verified",
      convergence: "not_verified",
    },
    failures: Array.from({ length: 9 }, (_unused, index) => `failure ${index + 1}`),
    limitations: ["Exact local scenario only."],
  };
}

describe("ComparisonDecision observed local L2 evidence", () => {
  it("renders the canonical context-bound local result without upgrading service claims", () => {
    const observed = observedReceipt();
    const value: CompareResponse = {
      verdict: "CLEAN",
      cutover_gate: {
        schema: "cutover_gate/1",
        verdict: "INDETERMINATE",
        note: "Other coverage gaps remain non-PASS.",
        operator_note: "Do not proceed until unrelated gaps are resolved.",
        delta_verdict: "CLEAN",
        delta_display: "CLEAN",
        delta_note: "No regression observed.",
        certificate_verdict: "PASS",
        certificate_note: "Bounded service evidence passed.",
        protocol_gate: "PASS",
        protocol_baseline_peers: 2,
        protocol_regressions: 0,
        protocol_coverage_gaps: 1,
        l2_observed_trial_status: "observed_survival",
        l2_observed_trial_assurance: "local_safety_preservation",
        l2_observed_trial_family: "etherchannel",
        l2_observed_trial_subject: "dist1|Po10",
        l2_observed_trial_scenario: "single_observed_forwarding_member_loss",
        l2_observed_trial_matched_projected_risks: 1,
        l2_observed_trial_note: "Exact recovery binding accepted; unrelated gaps remain.",
      },
      operator_evidence: {
        schema: "cutover_operator_evidence/1",
        owner: "reference_only_projection",
        owns_verdict: false,
        rehearsal: {
          status: "local_safety_preservation",
          assurance_level: "local_safety_preservation",
          source_owner: "observed_local_l2_failure_trial + failure_impact projection",
          n_impacts_total: 0,
          impacts: [],
          observed_l2_failure_evidence: observed,
          note: "Local safety preservation only.",
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
      },
    };

    render(<ComparisonDecision value={value} />);
    const block = screen.getByTestId("comparison-observed-l2-trial");
    expect(within(block).getByTestId("comparison-observed-l2-status")).toHaveTextContent(
      "OBSERVED SURVIVAL",
    );
    expect(within(block).getByTestId("comparison-observed-l2-note")).toHaveTextContent(
      "Exact recovery binding accepted",
    );
    expect(within(block).getAllByTestId("comparison-observed-l2-phase")).toHaveLength(3);
    expect(within(block).getByText(/snapshot:13/)).toBeInTheDocument();
    expect(within(block).getByTestId("comparison-observed-l2-claim-boundary")).toHaveTextContent(
      /service-path survival: not verified.*traffic continuity: not verified.*convergence: not verified/i,
    );
    expect(within(block).getAllByTestId("comparison-observed-l2-failure")).toHaveLength(8);
    expect(within(block).getByTestId("comparison-cap-disclosure")).toHaveTextContent(
      "Rendered: 8 · Total: 9 · Omitted: 1",
    );
    expect(block).not.toHaveTextContent(observed.source_binding.failure_witness.content_base64);
  });
});
