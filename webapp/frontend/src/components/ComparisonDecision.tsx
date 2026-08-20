import type { ReactNode } from "react";
import type {
  CompareResponse,
  CutoverGateVerdict,
  PrecertReceipt,
  ProtocolComparisonStatus,
  ProtocolFamilyChange,
  ProtocolFamilyChangeSet,
  ProtocolFamilyChangeSummary,
} from "../api";

const ROW_CAP = 8;

const GATE_COLOR: Record<CutoverGateVerdict, string> = {
  PASS: "var(--ok)",
  CONDITIONAL: "var(--watch)",
  REVIEW: "var(--watch)",
  INDETERMINATE: "var(--text-faint)",
  FAIL: "var(--crit)",
  REGRESSED: "var(--crit)",
};

const ADMISSION_COLOR: Record<ProtocolComparisonStatus, string> = {
  admitted: "var(--ok)",
  coverage_lost: "var(--watch)",
  not_comparable: "var(--crit)",
};

const DECISION_EFFECT_COLOR: Record<ProtocolFamilyChange["decision_effect"], string> = {
  block: "var(--crit)",
  review: "var(--watch)",
  none: "var(--accent)",
  not_verified: "var(--text-faint)",
};

const L2_REHEARSAL_COLOR: Record<string, string> = {
  simulation_only: "var(--accent)",
  projected_risk: "var(--watch)",
  current_fault: "var(--crit)",
  not_verified: "var(--text-faint)",
};

export interface ProtocolFamilyPresentationBuckets {
  expected: ProtocolFamilyChange[];
  unexpected: ProtocolFamilyChange[];
  coverage: ProtocolFamilyChange[];
  drilldownOnly: ProtocolFamilyChange[];
}

/**
 * Partition rows only from producer-owned classifications.
 *
 * Transition vocabulary remains useful evidence in each row, but it is not a second UI-owned
 * classifier. Rows whose producer effect is `none` and which are not declared expected remain in
 * the per-family drilldown and complete export instead of being relabelled by presentation code.
 */
export function bucketProtocolFamilyRows(
  rows: ProtocolFamilyChange[],
): ProtocolFamilyPresentationBuckets {
  const buckets: ProtocolFamilyPresentationBuckets = {
    expected: [], unexpected: [], coverage: [], drilldownOnly: [],
  };
  for (const row of rows) {
    if (row.decision_effect === "not_verified") buckets.coverage.push(row);
    else if (row.expected) buckets.expected.push(row);
    else if (row.decision_effect === "block" || row.decision_effect === "review") {
      buckets.unexpected.push(row);
    } else buckets.drilldownOnly.push(row);
  }
  return buckets;
}

type ReconciledSummary = Pick<
  ProtocolFamilyChangeSummary,
  "n_subject_changes" | "n_expected" | "n_blocking" | "n_review" | "n_not_verified" | "by_decision_effect"
>;

function summaryCountMismatches(
  label: string,
  summary: ReconciledSummary,
  rows: ProtocolFamilyChange[],
): string[] {
  const effects: Record<ProtocolFamilyChange["decision_effect"], number> = {
    block: 0, review: 0, none: 0, not_verified: 0,
  };
  let expected = 0;
  for (const row of rows) {
    expected += row.expected ? 1 : 0;
    effects[row.decision_effect] += 1;
  }
  const checks: Array<[string, number | undefined, number]> = [
    ["n_subject_changes", summary.n_subject_changes, rows.length],
    ["n_expected", summary.n_expected, expected],
    ["n_blocking", summary.n_blocking, effects.block],
    ["n_review", summary.n_review, effects.review],
    ["n_not_verified", summary.n_not_verified, effects.not_verified],
  ];
  const failures = checks.flatMap(([field, declared, observed]) => (
    typeof declared === "number" && declared !== observed
      ? [`${label}.${field}=${declared}, rows=${observed}`]
      : []
  ));
  if (summary.by_decision_effect) {
    for (const effect of Object.keys(effects) as Array<ProtocolFamilyChange["decision_effect"]>) {
      const declared = summary.by_decision_effect[effect];
      if (typeof declared === "number" && declared !== effects[effect]) {
        failures.push(`${label}.by_decision_effect.${effect}=${declared}, rows=${effects[effect]}`);
      }
    }
  }
  return failures;
}

/** Structural reconciliation only: exact producer fields and counters, never transition semantics. */
export function protocolFamilySummaryMismatches(value: ProtocolFamilyChangeSet): string[] {
  const rows = value.families.flatMap((family) => family.changes);
  const failures = summaryCountMismatches("summary", value.summary, rows);
  for (const family of value.families) {
    failures.push(...summaryCountMismatches(`family[${family.family}]`, family.summary, family.changes));
  }
  return failures;
}

function safeFilename(value: string) {
  const stem = value.trim().replace(/[^a-z0-9._-]+/gi, "-").replace(/^-+|-+$/g, "");
  return stem || "atlas-comparison-receipt.json";
}

function downloadCompleteJson(value: CompareResponse, filename: string) {
  // Export the complete API response, never the capped arrays rendered below. The detached receipt
  // and its digest stay beside every decision input for portable/offline reconciliation.
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json;charset=utf-8" });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = safeFilename(filename);
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(href);
}

function CapDisclosure({ rendered, total }: { rendered: number; total: number }) {
  const omitted = Math.max(0, total - rendered);
  return (
    <div className="faint" data-testid="comparison-cap-disclosure" style={{ fontSize: 10.5, marginTop: 7 }}>
      Rendered: {rendered} · Total: {total} · Omitted: {omitted}. Complete JSON export includes all received rows.
    </div>
  );
}

function stateText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return "[unrenderable state]";
  }
}

function ChangeRows({ rows, testId, total = rows.length }: {
  rows: ProtocolFamilyChange[];
  testId: string;
  total?: number;
}) {
  const rendered = rows.slice(0, ROW_CAP);
  return (
    <>
      {rendered.length === 0 ? (
        <div className="faint" style={{ fontSize: 11.5 }}>No rows published in this category.</div>
      ) : rendered.map((row, index) => {
        const before = stateText(row.before_state);
        const after = stateText(row.after_state);
        return (
        <div key={`${row.family}|${row.subject}|${row.transition}|${index}`} data-testid={testId}
          style={{ borderTop: index ? "1px solid var(--border-faint)" : undefined, padding: "6px 0" }}>
          <div className="row-flex" style={{ gap: 6, flexWrap: "wrap", alignItems: "baseline" }}>
            <span className="chip mono">{row.family}</span>
            {row.subject_kind && (
              <span className="chip" data-testid={`${testId}-subject-kind`}>
                {row.subject_kind.replaceAll("_", " ").toUpperCase()}
              </span>
            )}
            <span className="chip">{row.transition.replaceAll("_", " ").toUpperCase()}</span>
            <span className="chip" data-testid={`${testId}-effect`}
              style={{ color: DECISION_EFFECT_COLOR[row.decision_effect], borderColor: DECISION_EFFECT_COLOR[row.decision_effect] }}>
              {row.decision_effect.replaceAll("_", " ").toUpperCase()}
            </span>
            <span className="chip" data-testid={`${testId}-expectation`}>
              {row.expected ? "EXPECTED" : "UNEXPECTED"}
            </span>
            <b className="mono" style={{ fontSize: 11.5, overflowWrap: "anywhere" }}>{row.subject || "unnamed subject"}</b>
          </div>
          {(before !== "—" || after !== "—") && (
            <div className="faint mono" style={{ fontSize: 10.5, marginTop: 3 }}>
              {before} → {after}
            </div>
          )}
          {row.note && <div className="dim" style={{ fontSize: 11, marginTop: 3 }}>{row.note}</div>}
        </div>
      );})}
      <CapDisclosure rendered={rendered.length} total={Math.max(total, rows.length)} />
    </>
  );
}

function FamilyChangeSection({
  title,
  rows,
  tone,
  testId,
  total,
}: {
  title: string;
  rows: ProtocolFamilyChange[];
  tone: string;
  testId: string;
  total?: number;
}) {
  return (
    <section aria-label={`${title} protocol family changes`} data-testid={`${testId}-section`}
      style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
      <div className="spread" style={{ gap: 8, marginBottom: 6 }}>
        <b style={{ color: tone, fontSize: 12 }}>{title}</b>
        <span className="chip" style={{ color: tone, borderColor: tone }}>{total ?? rows.length}</span>
      </div>
      <ChangeRows rows={rows} testId={`${testId}-row`} total={total} />
    </section>
  );
}

function PrecertEvidence({ value }: { value?: PrecertReceipt }) {
  if (!value) {
    return (
      <section aria-label="Service and path evidence" data-testid="comparison-precert"
        style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
        <b style={{ fontSize: 12 }}>Service and path evidence</b>
        <div className="faint" style={{ fontSize: 11.5, marginTop: 5 }}>
          No precert/1 receipt was published. Service and path preservation is not verified by this response.
        </div>
      </section>
    );
  }

  const evidence = [
    ...value.regressions.map((text) => ({ kind: "Regression", text, color: "var(--crit)" })),
    ...value.gate_failures.map((text) => ({ kind: "Gate failure", text, color: "var(--crit)" })),
    ...value.blind_spots.map((text) => ({ kind: "Blind spot", text, color: "var(--watch)" })),
  ];
  const rendered = evidence.slice(0, ROW_CAP);
  const verdictColor = value.verdict === "PASS"
    ? "var(--ok)"
    : value.verdict === "FAIL"
      ? "var(--crit)"
      : value.verdict === "CONDITIONAL"
        ? "var(--watch)"
        : "var(--text-faint)";
  const changed = Array.isArray(value.flows.changed) ? value.flows.changed.length : 0;

  return (
    <section aria-label="Service and path evidence" data-testid="comparison-precert"
      style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
      <div className="spread" style={{ gap: 8 }}>
        <b style={{ fontSize: 12 }}>Service and path evidence</b>
        <span className="chip" style={{ color: verdictColor, borderColor: verdictColor }}>{value.verdict}</span>
      </div>
      <div className="dim" data-testid="comparison-precert-note" style={{ fontSize: 11.5, marginTop: 6 }}>
        {value.verdict_note}
      </div>
      <div className="faint" style={{ fontSize: 10.5, marginTop: 5 }}>
        Reachability: {value.flows.assessed ? "assessed" : "not assessed"}
        {typeof value.flows.subnets_tested === "number" && typeof value.flows.subnets_total === "number"
          ? ` · ${value.flows.subnets_tested} of ${value.flows.subnets_total} subnet(s) tested`
          : ""}
        {value.flows.capped ? " · bounded sample" : ""} · {changed} changed flow(s) · {value.segmentation.length} segmentation invariant(s) · {value.intents.length} path intent(s)
      </div>
      {rendered.map((row, index) => (
        <div key={`${row.kind}|${row.text}|${index}`} data-testid="comparison-precert-evidence-row"
          style={{ borderTop: "1px solid var(--border-faint)", marginTop: 6, paddingTop: 6, fontSize: 11 }}>
          <b style={{ color: row.color }}>{row.kind}:</b> <span className="dim">{row.text}</span>
        </div>
      ))}
      <CapDisclosure rendered={rendered.length} total={evidence.length} />
    </section>
  );
}

function OperatorEvidence({ value }: { value: CompareResponse["operator_evidence"] }) {
  const rehearsal = value?.rehearsal;
  const rollback = value?.rollback;
  const impactRows = (rehearsal?.impacts || []).slice(0, ROW_CAP);
  const l2 = rehearsal?.l2_failure_rehearsal;
  const l2Rows = (l2?.scenarios || []).slice(0, ROW_CAP);
  const rollbackRows = (rollback?.plans || []).slice(0, ROW_CAP);
  return (
    <>
      <section aria-label="Failure rehearsal evidence" data-testid="comparison-rehearsal"
        style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
        <div className="spread" style={{ gap: 8 }}>
          <b style={{ fontSize: 12 }}>Failure rehearsal</b>
          <span className="chip" data-testid="comparison-rehearsal-status"
            style={{
              color: L2_REHEARSAL_COLOR[rehearsal?.status || "not_verified"] || "var(--text-faint)",
              borderColor: L2_REHEARSAL_COLOR[rehearsal?.status || "not_verified"] || "var(--text-faint)",
            }}>
            {(rehearsal?.status || "not_verified").replaceAll("_", " ").toUpperCase()}
          </span>
        </div>
        <div className="dim" style={{ fontSize: 11.5, marginTop: 6 }}>
          {rehearsal?.note || "No cutover_operator_evidence/1 rehearsal projection was published; rehearsal is not verified."}
        </div>
        {impactRows.map((row, index) => (
          <div key={`${String(row.host || "impact")}|${index}`} data-testid="comparison-rehearsal-row"
            style={{ borderTop: "1px solid var(--border-faint)", marginTop: 6, paddingTop: 6, fontSize: 11 }}>
            <b className="mono">{String(row.host || "unnamed subject")}</b>
            <span className="dim"> · {String(row.severity || "unrated")} · {String(row.detail || "No detail published.")}</span>
          </div>
        ))}
        <CapDisclosure rendered={impactRows.length} total={rehearsal?.n_impacts_total || 0} />
        {l2 && (
          <div data-testid="comparison-l2-rehearsal"
            style={{ borderTop: "1px solid var(--border-faint)", marginTop: 8, paddingTop: 8 }}>
            <div className="spread" style={{ gap: 8 }}>
              <b style={{ fontSize: 11.5 }}>L2 failure projections</b>
              <span className="chip" data-testid="comparison-l2-rehearsal-status"
                style={{
                  color: L2_REHEARSAL_COLOR[l2.status] || "var(--text-faint)",
                  borderColor: L2_REHEARSAL_COLOR[l2.status] || "var(--text-faint)",
                }}>
                {l2.status.replaceAll("_", " ").toUpperCase()}
              </span>
            </div>
            <div className="faint" style={{ fontSize: 10.5, marginTop: 4 }}>
              Exact-source bound: {l2.source_bound ? "yes" : "no"} · {l2.summary.n_current_faults} current fault(s) · {l2.summary.n_projected_risks} projected risk(s) · {l2.summary.n_not_verified} not verified
            </div>
            {l2Rows.map((row, index) => (
              <div key={`${row.family}|${row.subject}|${index}`} data-testid="comparison-l2-rehearsal-row"
                style={{ borderTop: "1px solid var(--border-faint)", marginTop: 6, paddingTop: 6, fontSize: 11 }}>
                <div className="row-flex" style={{ gap: 6, flexWrap: "wrap", alignItems: "baseline" }}>
                  <span className="chip mono">{row.family}</span>
                  <b className="mono">{row.subject}</b>
                  <span className="chip" data-testid="comparison-l2-rehearsal-disposition"
                    style={{
                      color: L2_REHEARSAL_COLOR[row.disposition] || "var(--text-faint)",
                      borderColor: L2_REHEARSAL_COLOR[row.disposition] || "var(--text-faint)",
                    }}>
                    {row.disposition.replaceAll("_", " ").toUpperCase()}
                  </span>
                </div>
                <div className="faint" style={{ marginTop: 2 }}>
                  {row.failure_scenario.replaceAll("_", " ")} · {row.source_owner}
                </div>
                <div className="dim" style={{ marginTop: 2 }}>{row.note}</div>
              </div>
            ))}
            <CapDisclosure rendered={l2Rows.length} total={l2.summary.n_scenarios} />
          </div>
        )}
      </section>

      <section aria-label="Rollback evidence" data-testid="comparison-rollback"
        style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
        <div className="spread" style={{ gap: 8 }}>
          <b style={{ fontSize: 12 }}>Rollback</b>
          <span className="chip" data-testid="comparison-rollback-status"
            style={{ color: rollback?.status === "planned" ? "var(--watch)" : "var(--text-faint)", borderColor: rollback?.status === "planned" ? "var(--watch)" : "var(--text-faint)" }}>
            {(rollback?.status || "not_verified").replaceAll("_", " ").toUpperCase()}
          </span>
        </div>
        <div className="dim" style={{ fontSize: 11.5, marginTop: 6 }}>
          {rollback?.note || "No cutover_operator_evidence/1 rollback projection was published; rollback coverage is not verified."}
        </div>
        {rollbackRows.map((row, index) => (
          <div key={`${row.group}|${index}`} data-testid="comparison-rollback-row"
            style={{ borderTop: "1px solid var(--border-faint)", marginTop: 6, paddingTop: 6, fontSize: 11 }}>
            <b className="mono">{row.group || "unnamed group"}</b>
            {row.recommended_scenario && <span className="faint"> · {row.recommended_scenario}</span>}
            <div className="dim" style={{ marginTop: 2 }}>{row.rollback}</div>
          </div>
        ))}
        <CapDisclosure rendered={rollbackRows.length} total={rollback?.n_plans_total || 0} />
      </section>
    </>
  );
}

function ReceiptCustody({ value }: { value: CompareResponse }) {
  const admission = value.comparison_admission;
  const receipt = value.comparison_receipt;
  const issues = admission
    ? [
      ...admission.failures.map((text) => ({ kind: "Failure", text, color: "var(--crit)" })),
      ...admission.coverage_gaps.map((text) => ({ kind: "Coverage gap", text, color: "var(--watch)" })),
    ]
    : [];
  const rendered = issues.slice(0, ROW_CAP);
  const status = admission?.status;
  const statusColor = status ? ADMISSION_COLOR[status] : "var(--text-faint)";

  return (
    <section aria-label="Comparison admission and receipt custody" data-testid="comparison-admission"
      style={{ border: "1px solid var(--border-faint)", borderRadius: 8, padding: 9 }}>
      <div className="spread" style={{ gap: 8 }}>
        <b style={{ fontSize: 12 }}>Comparison admission and receipt custody</b>
        <span className="chip" data-testid="comparison-admission-status"
          style={{ color: statusColor, borderColor: statusColor }}>
          {(status || "not verified").replaceAll("_", " ").toUpperCase()}
        </span>
      </div>
      {!admission ? (
        <div className="faint" style={{ fontSize: 11.5, marginTop: 5 }}>
          No source/campaign/engagement admission receipt was published by this legacy response.
        </div>
      ) : (
        <>
          <div className="faint" style={{ fontSize: 10.5, marginTop: 6 }}>
            Engagement: <span className="mono">{admission.engagement_id}</span> · campaign {admission.campaign_id} · assurance {admission.assurance_level.replaceAll("_", " ")}
          </div>
          <div className="faint mono" style={{ fontSize: 10, marginTop: 4, overflowWrap: "anywhere" }}>
            Before snapshot {admission.source_binding.before.snapshot_id}: {admission.source_binding.before.sha256}<br />
            After snapshot {admission.source_binding.after.snapshot_id}: {admission.source_binding.after.sha256}
          </div>
          {rendered.map((row, index) => (
            <div key={`${row.kind}|${row.text}|${index}`} data-testid="comparison-admission-issue"
              style={{ borderTop: "1px solid var(--border-faint)", marginTop: 6, paddingTop: 6, fontSize: 11 }}>
              <b style={{ color: row.color }}>{row.kind}:</b> <span className="dim">{row.text}</span>
            </div>
          ))}
          <CapDisclosure rendered={rendered.length} total={issues.length} />
        </>
      )}
      {receipt && (
        <div className="faint mono" data-testid="comparison-receipt-digests"
          style={{ fontSize: 10, marginTop: 7, overflowWrap: "anywhere" }}>
          Payload: {receipt.payload_sha256}<br />Receipt: {receipt.receipt_sha256}
        </div>
      )}
    </section>
  );
}

export default function ComparisonDecision({
  value,
  currentBaseline,
  exportFilename = "atlas-comparison-receipt.json",
}: {
  value: CompareResponse;
  /** Optional producer-owned current-state panel, placed directly after the canonical decision. */
  currentBaseline?: ReactNode;
  exportFilename?: string;
}) {
  const gate = value.cutover_gate?.schema === "cutover_gate/1" ? value.cutover_gate : undefined;
  const gateColor = gate ? (GATE_COLOR[gate.verdict] || "var(--text-faint)") : "var(--text-faint)";
  const families = value.protocol_families?.schema === "protocol_family_change_set/1"
    ? value.protocol_families
    : undefined;
  const rows = families?.families.flatMap((family) => family.changes) || [];
  // Presentation consumes the producer's two classifications directly. It does not duplicate the
  // Python transition vocabulary or derive the overall verdict; cutover_gate/1 remains the sole
  // decision owner. Neutral producer rows remain available in the family drilldown/export.
  const buckets = bucketProtocolFamilyRows(rows);
  const reconciliationFailures = families ? protocolFamilySummaryMismatches(families) : [];
  const expectedTotal = families?.summary.n_expected === buckets.expected.length
    ? families.summary.n_expected
    : buckets.expected.length;
  const unexpectedTotal = families?.summary.n_unexpected === buckets.unexpected.length
    ? families.summary.n_unexpected
    : buckets.unexpected.length;
  const declaredCoverage = families?.summary.n_not_verified;
  const coverageTotal = declaredCoverage === buckets.coverage.length
    ? declaredCoverage
    : buckets.coverage.length;
  const gateBackground = gate?.verdict === "PASS"
    ? "var(--ok-soft)"
    : gate?.verdict === "FAIL" || gate?.verdict === "REGRESSED"
      ? "var(--crit-soft)"
      : gate?.verdict === "CONDITIONAL" || gate?.verdict === "REVIEW"
        ? "var(--watch-soft)"
        : undefined;

  return (
    <div data-testid="comparison-decision" style={{ marginBottom: 12 }}>
      <section aria-label="Canonical cutover decision" data-testid="canonical-cutover-decision"
        style={{ border: `1px solid ${gateColor}`, borderRadius: 9, marginBottom: 12, overflow: "hidden" }}>
        <div className="spread" style={{ padding: "10px 11px", gap: 9, background: gateBackground }}>
          <div>
            <b>Canonical cutover decision</b>
            <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>Server-owned cutover_gate/1 · sole overall decision</div>
          </div>
          <div className="row-flex" style={{ gap: 7, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <span className="chip" data-testid="canonical-cutover-verdict" style={{ color: gateColor, borderColor: gateColor }}>
              <span className="dot" /> {gate?.verdict || "NOT VERIFIED"}
            </span>
            <button type="button" className="btn ghost" data-testid="comparison-json-export"
              onClick={() => downloadCompleteJson(value, exportFilename)} style={{ fontSize: 10.5, padding: "4px 8px" }}>
              Export complete JSON
            </button>
          </div>
        </div>
        <div style={{ padding: "9px 11px" }}>
          {gate ? (
            <>
              <div className="dim" data-testid="canonical-cutover-operator-note" style={{ fontSize: 12.5, overflowWrap: "anywhere" }}>
                {gate.operator_note}
              </div>
              <div className="faint" data-testid="canonical-cutover-basis" style={{ fontSize: 10.5, marginTop: 7, overflowWrap: "anywhere" }}>
                {gate.note}
              </div>
            </>
          ) : (
            <div className="faint" data-testid="canonical-cutover-legacy-absence" style={{ fontSize: 12 }}>
              This response did not publish a canonical source-bound cutover gate. The legacy delta below remains supporting evidence, not cutover authorization.
            </div>
          )}
        </div>
      </section>

      {currentBaseline}

      <section aria-label="Protocol family changes" data-testid="protocol-family-changes"
        style={{ border: "1px solid var(--border-faint)", borderRadius: 9, padding: 10, marginBottom: 12 }}>
        <div className="spread" style={{ gap: 8, marginBottom: 8 }}>
          <div>
            <b>Protocol family changes</b>
            <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>Reference-only composition; owns no score or verdict</div>
          </div>
          {families && (
            <span className="faint" data-testid="protocol-family-server-summary" style={{ fontSize: 10.5 }}>
              Server summary: {families.summary.n_expected} expected · {families.summary.n_unexpected} unexpected · {families.summary.n_coverage_lost} coverage lost
            </span>
          )}
        </div>
        {!families && (
          <div className="faint" style={{ fontSize: 11.5, marginBottom: 8 }}>
            No protocol_family_change_set/1 receipt was published. Family change coverage is not verified.
          </div>
        )}
        {families && (
          <div data-testid="protocol-family-summary-reconciliation"
            style={{
              color: reconciliationFailures.length ? "var(--crit)" : "var(--text-faint)",
              fontSize: 10.5,
              marginBottom: 8,
              overflowWrap: "anywhere",
            }}>
            {reconciliationFailures.length
              ? `NOT VERIFIED — producer summary/row mismatch: ${reconciliationFailures.join("; ")}`
              : "RECONCILED — producer subject, expected, and decision-effect counters match every received row."}
          </div>
        )}
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
          <FamilyChangeSection title="Expected changes" rows={buckets.expected} tone="var(--accent)" testId="family-change-expected"
            total={expectedTotal} />
          <FamilyChangeSection title="Unexpected changes" rows={buckets.unexpected} tone="var(--watch)" testId="family-change-unexpected"
            total={unexpectedTotal} />
          <FamilyChangeSection title="Coverage loss / not verified" rows={buckets.coverage} tone="var(--text-faint)" testId="family-change-coverage"
            total={coverageTotal} />
        </div>
        {buckets.drilldownOnly.length > 0 && (
          <div className="faint" data-testid="protocol-family-drilldown-only" style={{ fontSize: 10.5, marginTop: 8 }}>
            {buckets.drilldownOnly.length} non-expected producer row(s) have decision effect NONE;
            they remain in the family drilldown and complete JSON without being relabelled by this UI.
          </div>
        )}
        {families && families.families.length > 0 && (
          <div data-testid="protocol-assurance-portfolio" style={{ marginTop: 9 }}>
            <div className="faint" style={{ fontSize: 10.5, marginBottom: 5 }}>
              Protocol Assurance portfolio · open a family to inspect its bound subjects
            </div>
            {families.families.map((family) => (
              <details key={`${family.family}|${family.owner_schema}`} data-testid="protocol-assurance-family"
                style={{ borderTop: "1px solid var(--border-faint)", padding: "6px 0" }}>
                <summary style={{ cursor: "pointer", fontSize: 11.5 }}>
                  <b>{family.family}</b>{" · "}
                  <span className="faint">{family.assurance_level.replaceAll("_", " ")} · {family.summary.n_subject_changes} subject change(s)</span>
                </summary>
                <div style={{ padding: "6px 8px 2px" }}>
                  <ChangeRows rows={family.changes} testId="protocol-assurance-subject"
                    total={family.summary.n_subject_changes} />
                </div>
              </details>
            ))}
          </div>
        )}
      </section>

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 8 }}>
        <PrecertEvidence value={value.precert} />
        <OperatorEvidence value={value.operator_evidence} />
        <ReceiptCustody value={value} />
      </div>
    </div>
  );
}
