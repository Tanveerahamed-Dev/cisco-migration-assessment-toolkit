import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import {
  api,
  gateColor,
  type Campaign,
  type CutoverChangeIntentInput,
  type CurrentBaselineBlocker,
  type CurrentBaselineGate,
  type CutoverWave,
  type ExecutionMeta,
  type ExecutionState,
  type ValidationCheck,
} from "../api";
import {
  baselinePresentationKey,
  isLegacyBaselinePresentationCandidate,
  isProducerDeclaredBaselineBlocker,
  type BaselinePresentationRow,
} from "../baselinePresentation";
import ComparisonDecision from "./ComparisonDecision";
import ObservedL2TrialInput, {
  EMPTY_OBSERVED_L2_TRIAL,
  observedL2TrialIsReading,
  observedL2TrialRequest,
} from "./ObservedL2TrialInput";
import type { ObservedL2TrialDraft } from "./ObservedL2TrialInput";
import { CountUp, ErrorBox, SegBar, SevChip, SkelLines, useAsync } from "./ui";

/* The cutover-plan panel: a gated, pilot-first run-of-show synthesized server-side from the
   snapshot's migration model (waves, readiness checks, blast radius, validation, remediation). */

function GateBadge({ gate, big }: { gate: string; big?: boolean }) {
  if (big) {
    return (
      <span className="gatebadge" style={{ ["--gc" as any]: gateColor(gate) }}>
        <span className="dot" /> {gate}
      </span>
    );
  }
  return (
    <span className="chip gate" style={{ ["--gc" as any]: gateColor(gate) }}>
      <span className="dot" /> {gate}
    </span>
  );
}

function Stat({ value, label, color }: { value: ReactNode; label: string; color?: string }) {
  return (
    <div>
      <div style={{ font: "800 22px var(--sans)", color: color || "var(--text)", lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".5px", color: "var(--text-faint)", marginTop: 4 }}>{label}</div>
    </div>
  );
}

type PlannerBaselineRow = CurrentBaselineBlocker | ValidationCheck;

const BASELINE_GATE_COLOR: Record<string, string> = {
  BLOCKED: "var(--crit)",
  INDETERMINATE: "var(--watch)",
  NOT_ASSESSED: "var(--text-faint)",
  CLEAR: "var(--ok)",
};

function baselinePresentationForWave(w: CutoverWave): {
  blockers: PlannerBaselineRow[];
  legacyCandidates: ValidationCheck[];
} {
  const explicitRows = Array.isArray(w.baseline_blockers)
    ? w.baseline_blockers
    : Array.isArray(w.current_baseline?.blockers)
      ? w.current_baseline.blockers
      : null;
  const blockers = explicitRows ?? w.validation.filter(isProducerDeclaredBaselineBlocker);
  const legacyCandidates = explicitRows === null
    ? w.validation.filter(isLegacyBaselinePresentationCandidate)
    : [];
  return {
    blockers: Array.from(new Map(blockers.map((row) => [baselinePresentationKey(row), row])).values()),
    legacyCandidates: Array.from(new Map(
      legacyCandidates.map((row) => [baselinePresentationKey(row), row]),
    ).values()),
  };
}

/** Use explicit receipts first; mixed-version fallback consumes only the producer-owned boolean. */
function boundBaselineBlockersForWave(w: CutoverWave): PlannerBaselineRow[] {
  if (Array.isArray(w.baseline_blockers)) return w.baseline_blockers;
  if (Array.isArray(w.current_baseline?.blockers)) return w.current_baseline.blockers;
  return w.validation.filter(isProducerDeclaredBaselineBlocker);
}

/** Multiset subtraction preserves repeated top-level rows while removing only bound occurrences. */
function unboundBaselineBlockers(
  allRows: CurrentBaselineBlocker[], waves: CutoverWave[],
): CurrentBaselineBlocker[] {
  const boundCounts = new Map<string, number>();
  waves.forEach((wave) => boundBaselineBlockersForWave(wave).forEach((row) => {
    const key = baselinePresentationKey(row);
    boundCounts.set(key, (boundCounts.get(key) || 0) + 1);
  }));
  return allRows.filter((row) => {
    const key = baselinePresentationKey(row);
    const remaining = boundCounts.get(key) || 0;
    if (!remaining) return true;
    boundCounts.set(key, remaining - 1);
    return false;
  });
}

function BaselineBlockerRow({ row, index, testId = "baseline-blocker" }: {
  row: PlannerBaselineRow;
  index: number;
  testId?: string;
}) {
  const state = String(row.evidence_state || row.baseline_state || "review").trim().toLowerCase();
  const degraded = state === "degraded";
  const tone = degraded ? "var(--crit)" : "var(--watch)";
  return (
    <div data-testid={testId} key={`${baselinePresentationKey(row)}\u0000${index}`}
      style={{ borderLeft: `3px solid ${tone}`, borderTop: "1px solid var(--border-faint)", padding: "9px 10px", background: degraded ? "var(--crit-soft)" : "var(--watch-soft)" }}>
      <div className="row-flex" style={{ gap: 7, alignItems: "baseline", flexWrap: "wrap" }}>
        <span className="chip" style={{ color: tone, borderColor: tone }}>{state.replaceAll("_", " ").toUpperCase()}</span>
        {row.device && <span className="chip mono">{row.device}</span>}
        {row.category && <span className="faint" style={{ fontSize: 11 }}>{row.category}</span>}
        <b style={{ fontSize: 12.5 }}>{row.check || "Current baseline blocker"}</b>
      </div>
      {row.command && <div className="cmd" style={{ marginTop: 5 }}>{row.command}</div>}
      {row.expect && (
        <div className="dim" style={{ fontSize: 11.5, marginTop: 4 }}>
          <b style={{ color: "var(--text-dim)" }}>Observed baseline / acceptance:</b> {row.expect}
        </div>
      )}
      {row.why && <div className="dim" style={{ fontSize: 11.5, marginTop: 3 }}>{row.why}</div>}
      <div className="faint" style={{ fontSize: 10.5, marginTop: 5 }}>
        Evidence: <span className="mono">{state || "unspecified"}</span>
        {row.projection_custody && <> · custody: <span className="mono">{row.projection_custody}</span></>}
        {row.source_key && <> · source: <span className="mono">{row.source_key}</span></>}
      </div>
    </div>
  );
}

function LegacyBaselineCandidateRow({ row, index }: {
  row: BaselinePresentationRow;
  index: number;
}) {
  const state = String(row.baseline_state || row.evidence_state || "unspecified")
    .trim().toLowerCase();
  return (
    <div data-testid="legacy-baseline-candidate"
      key={`${baselinePresentationKey(row)}\u0000legacy\u0000${index}`}
      style={{ borderLeft: "3px solid var(--text-faint)", borderTop: "1px solid var(--border-faint)", padding: "9px 10px" }}>
      <div className="row-flex" style={{ gap: 7, alignItems: "baseline", flexWrap: "wrap" }}>
        <span className="chip" style={{ color: "var(--text-faint)", borderColor: "var(--text-faint)" }}>
          LEGACY MARKER · DISPLAY ONLY
        </span>
        {row.device && <span className="chip mono">{row.device}</span>}
        <b style={{ fontSize: 12.5 }}>{row.check || "Legacy current-baseline marker"}</b>
      </div>
      {row.expect && <div className="dim" style={{ fontSize: 11.5, marginTop: 4 }}>{row.expect}</div>}
      <div className="faint" style={{ fontSize: 10.5, marginTop: 5 }}>
        Legacy evidence marker: <span className="mono">{state || "unspecified"}</span>. No producer-owned
        <span className="mono"> baseline_blocker</span> flag is attached, so this row does not derive a gate or blocker count.
      </div>
    </div>
  );
}

function CurrentBaselinePanel({
  gate, blockers, legacyCandidates = [], scope, title = "Current baseline gate",
  subtitle = "Current observed state, separate from before→after change detection",
  rowTestId = "baseline-blocker", footer, fullOperationalCount,
}: {
  gate?: CurrentBaselineGate;
  blockers: PlannerBaselineRow[];
  legacyCandidates?: BaselinePresentationRow[];
  scope?: string;
  title?: string;
  subtitle?: string;
  rowTestId?: string;
  footer?: ReactNode;
  fullOperationalCount?: number;
}) {
  if (!gate && blockers.length === 0 && legacyCandidates.length === 0 && !footer) return null;
  const verdict = gate?.verdict || "NOT_ASSESSED";
  const color = BASELINE_GATE_COLOR[verdict] || "var(--text-dim)";
  const testSuffix = scope ? `-${scope}` : "";
  const suppliedCounts = Object.entries(gate?.summary?.by_state || {})
    .filter((entry): entry is [string, number] => (
      typeof entry[1] === "number" && Number.isFinite(entry[1]) && entry[1] >= 0
    ));
  return (
    <section aria-label={title} data-testid={`current-baseline-gate${testSuffix}`}
      style={{ marginTop: 12, border: `1px solid ${color}`, borderRadius: 9, overflow: "hidden" }}>
      <div className="spread" style={{ padding: "9px 10px", gap: 10, background: verdict === "BLOCKED" ? "var(--crit-soft)" : verdict === "INDETERMINATE" ? "var(--watch-soft)" : undefined }}>
        <div>
          <b>{title}</b>
          <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>
            {subtitle}
          </div>
        </div>
        <span className="chip" data-testid={`current-baseline-verdict${testSuffix}`} style={{ color, borderColor: color }}>
          <span className="dot" /> {verdict.replaceAll("_", " ")}
        </span>
      </div>
      <div style={{ padding: "8px 10px" }}>
        <div className="dim" style={{ fontSize: 11.5 }}>
          {gate?.note || "No server-owned current_baseline_gate/1 is attached. Compatibility rows are display-only; no verdict is inferred."}
        </div>
        {verdict === "CLEAR" && (
          <div className="faint" data-testid={`current-baseline-clear-boundary${testSuffix}`} style={{ fontSize: 10.5, marginTop: 4 }}>
            CLEAR is bounded to the validation evidence collected in this snapshot; it is not cutover authorization.
          </div>
        )}
        <div className="faint" style={{ fontSize: 10.5, marginTop: 4 }}>
          {suppliedCounts.length
            ? suppliedCounts.map(([state, count]) => `${count} ${state.replaceAll("_", " ")}`).join(" · ")
            : `${blockers.length} producer-declared blocker row(s) rendered · server state totals not supplied`}
          {gate?.integrity?.valid === false && " · validation-plan integrity failed"}
        </div>
      </div>
      {blockers.map((row, index) => (
        <BaselineBlockerRow row={row} index={index} testId={rowTestId}
          key={`${baselinePresentationKey(row)}\u0000${index}`} />
      ))}
      {legacyCandidates.length > 0 && (
        <div className="faint" data-testid="legacy-baseline-disclosure"
          style={{ fontSize: 10.5, padding: "7px 10px", borderTop: "1px solid var(--border-faint)" }}>
          {legacyCandidates.length} compatibility candidate(s) are shown so legacy evidence is not hidden.
          They are neutral presentation hints and do not alter the server-owned gate, counts, or cutover decision.
        </div>
      )}
      {legacyCandidates.map((row, index) => (
        <LegacyBaselineCandidateRow row={row} index={index}
          key={`${baselinePresentationKey(row)}\u0000legacy\u0000${index}`} />
      ))}
      {gate?.summary?.blockers_capped && (
        <div className="faint" style={{ fontSize: 10.5, padding: "7px 10px" }}>
          {typeof fullOperationalCount === "number"
            && fullOperationalCount >= (gate.summary.n_blockers ?? Number.POSITIVE_INFINITY)
            ? <>The diagnostic gate sample was capped, but the plan-level receipt retains all {fullOperationalCount} operational blocker row(s).</>
            : <>The gate reports {gate.summary.n_blockers ?? "additional"} blocker(s), but only {gate.summary.n_blockers_returned ?? blockers.length} were returned. Open the full Validation-plan deliverable before disposition.</>}
        </div>
      )}
      {footer}
    </section>
  );
}

function WaveCard({ w, i }: { w: CutoverWave; i: number }) {
  const [open, setOpen] = useState(false);
  const split: Record<string, number> = {};
  if (w.make_before_break.length) split["make-before-break"] = w.make_before_break.length;
  if (w.hard_cutover.length) split["hard-cutover"] = w.hard_cutover.length;
  const splitColor = (k: string) => (k === "make-before-break" ? "var(--ok)" : "var(--risk)");
  const br = w.blast_radius;
  // Explicit receipt rows and the typed producer boolean are authoritative. Untyped legacy markers
  // are separated as neutral display hints and never promoted into the current-baseline decision.
  const { blockers: baselineBlockers, legacyCandidates } = baselinePresentationForWave(w);
  const separatedKeys = new Set([...baselineBlockers, ...legacyCandidates].map(baselinePresentationKey));
  const ordinaryValidation = w.validation.filter((row) => !separatedKeys.has(baselinePresentationKey(row)));

  return (
    // .ros-reveal: reveal-up on mount, capped+staggered per card (DesignBlueprint's DecisionCard idiom)
    // so a long wave list never waits seconds. Inert under reduced motion.
    <div className="wave-card ros-reveal" style={{ ["--gc" as any]: gateColor(w.gate), animationDelay: `${Math.min(i, 8) * 50}ms` }}>
      <div className="wh">
        <span className="ordno">{w.order}</span>
        <span className="wname">{w.group}</span>
        <GateBadge gate={w.gate} />
        <span className="chip tag">{w.strategy}</span>
        {w.readiness && <span className="dim" style={{ fontSize: 12 }}>readiness: {w.readiness}</span>}
        <span className="wmeta">
          <span><span className="num">{w.n_switches}</span><span className="lbl">switches</span></span>
          <span><span className="num">{w.endpoints}</span><span className="lbl">endpoints</span></span>
          <span><span className="num" style={{ color: w.est_window_minutes ? "var(--risk)" : "var(--ok)" }}>{w.est_window_label}</span><span className="lbl">window</span></span>
        </span>
      </div>

      {Object.keys(split).length > 0 && (
        <div style={{ marginTop: 12 }}>
          <SegBar data={split} colorFor={splitColor} />
        </div>
      )}

      <div className="grid cols-2" style={{ marginTop: 12, gap: 12 }}>
        {br && (
          <div>
            <div className="lbl" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".5px", color: "var(--text-faint)", marginBottom: 4 }}>Worst-case blast radius</div>
            <div style={{ fontSize: 13 }}>
              <b className="mono">{br.host}</b> · <SevChip sev={br.severity} /> · <b>{br.stranded}</b> endpoints stranded across <b>{br.vlans_impacted}</b> VLAN(s)
            </div>
            <div className="dim" style={{ fontSize: 12, marginTop: 3 }}>{br.detail}</div>
          </div>
        )}
        {w.keystones.length > 0 && (
          <div>
            <div className="lbl" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".5px", color: "var(--text-faint)", marginBottom: 4 }}>Keystone devices in this wave</div>
            <div className="kchips">
              {w.keystones.map((k) => <span key={k} className="chip mono">{k}</span>)}
            </div>
          </div>
        )}
      </div>

      {(w.blockers.length > 0 || w.critical_crosslayer.length > 0) && (
        <div style={{ marginTop: 12, borderTop: "1px solid var(--border-faint)", paddingTop: 10 }}>
          <div className="lbl" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".5px", color: "var(--text-faint)", marginBottom: 6 }}>
            Gating checks · resolve before this wave passes
          </div>
          {w.blockers.map((b, i) => (
            <div className="blocker" key={i}>
              <span className={`pill ${b.status}`}>{b.status}</span>
              <span style={{ flex: 1 }}><b>{b.check}</b> <span className="dim">— {b.note}</span></span>
              {b.phase && <span className="ph">{b.phase}</span>}
            </div>
          ))}
          {w.critical_crosslayer.map((cl) => (
            <div className="blocker" key={cl.id}>
              <span className="pill fail">{cl.layers || "X-LAYER"}</span>
              <span style={{ flex: 1 }}><b>{cl.title}</b> <span className="dim">— {cl.recommendation}</span></span>
              <span className="ph">{cl.id}</span>
            </div>
          ))}
        </div>
      )}

      <CurrentBaselinePanel gate={w.current_baseline} blockers={baselineBlockers}
        legacyCandidates={legacyCandidates} />

      <div style={{ marginTop: 12 }}>
        <button className="btn" onClick={() => setOpen((v) => !v)} aria-expanded={open} style={{ padding: "6px 12px", fontSize: 12 }}>
          {open ? "▾" : "▸"} Run-of-show
          <span className="chip mono" style={{ fontSize: 9, padding: "1px 6px" }}>{w.run_of_show.length} steps · {w.validation.length} checks · {w.remediation.length} fixes</span>
        </button>
      </div>

      {open && (
        <div className="ros-reveal" style={{ marginTop: 12 }}>
          <div className="ros">
            {w.run_of_show.map((s, i) => (
              <div className="step" key={i}>
                <div className="ph">{s.phase}</div>
                <div className="ac">{s.action}</div>
              </div>
            ))}
          </div>

          {w.remediation.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div className="lbl" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".5px", color: "var(--text-faint)", marginBottom: 6 }}>
                Pre-cutover remediation ({w.remediation.length})
              </div>
              <div style={{ overflow: "auto" }}>
                <table className="tbl">
                  <thead><tr><th>Device</th><th>Sev</th><th>Category</th><th>Fix</th></tr></thead>
                  <tbody>
                    {w.remediation.slice(0, 12).map((r, i) => (
                      <tr key={i}>
                        <td className="mono">{r.device}</td>
                        <td><SevChip sev={r.severity} /></td>
                        <td className="dim">{r.category}</td>
                        <td><b>{r.title}</b><div className="dim" style={{ fontSize: 11 }}>{r.why}</div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {w.remediation.length > 12 && <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>+{w.remediation.length - 12} more in the Remediation deliverable.</div>}
              </div>
            </div>
          )}

          {ordinaryValidation.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div className="lbl" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".5px", color: "var(--text-faint)", marginBottom: 6 }}>
                Post-cutover validation ({ordinaryValidation.length}) · run after the cut, compare to baseline
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {ordinaryValidation.slice(0, 10).map((v, i) => (
                  <div key={i} style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 10, alignItems: "start" }}>
                    <SevChip sev={v.severity} />
                    <div>
                      <div style={{ fontSize: 12.5 }}><b>{v.check}</b></div>
                      <div className="cmd" style={{ marginTop: 4 }}>{v.command}</div>
                      <div className="dim" style={{ fontSize: 11, marginTop: 3 }}><b style={{ color: "var(--text-dim)" }}>expect:</b> {v.expect}</div>
                    </div>
                  </div>
                ))}
                {ordinaryValidation.length > 10 && <div className="faint" style={{ fontSize: 11 }}>+{ordinaryValidation.length - 10} more in the Validation-plan section. Current-baseline blockers remain visible above regardless of this limit.</div>}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function canonicalGateColor(verdict: string) {
  return verdict === "PASS"
    ? "var(--ok)"
    : verdict === "FAIL" || verdict === "REGRESSED"
      ? "var(--crit)"
      : verdict === "CONDITIONAL" || verdict === "REVIEW"
        ? "var(--watch)"
        : "var(--text-faint)";
}

type PlannerExecutionContext = {
  execution: ExecutionState;
  campaign: Campaign | null;
};

function PlannerExecutionComparison({ run, onReceiptBound }: {
  run: ExecutionMeta;
  onReceiptBound: () => void;
}) {
  const { data, error, loading } = useAsync<PlannerExecutionContext>(async () => {
    const execution = await api.getExecution(run.id);
    const campaign = execution.comparison_policy
      ? await api.getCampaign(execution.comparison_policy.before_snapshot.campaign_id)
      : null;
    return { execution, campaign };
  }, [run.id]);
  const [boundExecution, setBoundExecution] = useState<ExecutionState | null>(null);
  const [afterSnapshotId, setAfterSnapshotId] = useState<number | "">("");
  const [changeIntentText, setChangeIntentText] = useState("");
  const [observedL2Trial, setObservedL2Trial] = useState<ObservedL2TrialDraft>(
    EMPTY_OBSERVED_L2_TRIAL,
  );
  const [compareBusy, setCompareBusy] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [boundMessage, setBoundMessage] = useState<string | null>(null);

  if (loading && !boundExecution) {
    return <div className="faint" style={{ padding: 10, fontSize: 11.5 }}>Loading the immutable execution receipt…</div>;
  }
  if (error && !boundExecution) return <ErrorBox msg={error} />;
  const execution = boundExecution || data?.execution;
  if (!execution) return null;

  const policy = execution.comparison_policy;
  const receipts = Array.isArray(execution.comparison_receipts) ? execution.comparison_receipts : [];
  const latestStored = execution.latest_comparison
    ? receipts.find((row) => row.id === execution.latest_comparison!.receipt_id)
    : receipts[receipts.length - 1];
  const latestComparison = latestStored?.receipt.comparison;
  const frozenCampaignId = policy?.before_snapshot.campaign_id;
  const campaign = data?.campaign;
  const candidates = policy && campaign && campaign.id === frozenCampaignId
    ? (campaign.snapshots || []).filter((snapshot) => (
      snapshot.campaign_id === frozenCampaignId
      && snapshot.id !== execution.snapshot_id
      && snapshot.id !== policy?.before_snapshot.snapshot_id
    ))
    : [];
  const live = execution.status === "in_progress";

  const bind = () => {
    if (afterSnapshotId === "") {
      setCompareError("Choose the post-change snapshot first.");
      return;
    }
    let changeIntent: CutoverChangeIntentInput | undefined;
    if (changeIntentText.trim()) {
      try {
        const parsed = JSON.parse(changeIntentText);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("Expected-change intent must be a JSON object.");
        }
        changeIntent = parsed as CutoverChangeIntentInput;
      } catch (intentError: any) {
        setCompareError(`Expected-change intent is not valid JSON: ${intentError?.message || String(intentError)}`);
        return;
      }
    }
    const observed = observedL2TrialRequest(
      observedL2Trial,
      policy?.before_snapshot.snapshot_id ?? execution.snapshot_id,
      afterSnapshotId,
    );
    if (observed.error) {
      setCompareError(observed.error);
      return;
    }
    setCompareBusy(true);
    setCompareError(null);
    setBoundMessage(null);
    const request = observed.input
      ? api.compareExecution(
        execution.id, afterSnapshotId, changeIntent, observed.input,
      )
      : changeIntent
        ? api.compareExecution(execution.id, afterSnapshotId, changeIntent)
        : api.compareExecution(execution.id, afterSnapshotId);
    request
      .then((updated) => {
        setBoundExecution(updated);
        setAfterSnapshotId("");
        setChangeIntentText("");
        setObservedL2Trial({ ...EMPTY_OBSERVED_L2_TRIAL });
        setBoundMessage("Post-change evidence was appended as an immutable canonical comparison receipt.");
        onReceiptBound();
      })
      .catch((compareFailure) => setCompareError(compareFailure.message || String(compareFailure)))
      .finally(() => setCompareBusy(false));
  };

  return (
    <div data-testid={`cutover-execution-evidence-${run.id}`}
      style={{ border: "1px solid var(--border-faint)", borderRadius: 9, padding: 10, marginTop: 8 }}>
      {latestComparison ? (
        <ComparisonDecision
          value={latestComparison}
          exportFilename={`execution-${execution.id}-comparison-receipt-${latestStored?.id || "latest"}.json`}
        />
      ) : policy ? (
        <section aria-label="Canonical post-change cutover decision"
          data-testid={`cutover-execution-gate-missing-${run.id}`}
          style={{ border: "1px solid var(--text-faint)", borderRadius: 9, padding: "9px 10px", marginBottom: 10 }}>
          <div className="spread" style={{ gap: 8 }}>
            <div>
              <b>Canonical post-change cutover decision</b>
              <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>
                {execution.latest_comparison
                  ? `Latest receipt ${execution.latest_comparison.receipt_id} is identified, but its complete payload is unavailable.`
                  : "No immutable comparison receipt has been bound to this run."}
              </div>
            </div>
            <span className="chip" style={{ color: "var(--text-faint)", borderColor: "var(--text-faint)" }}>
              NOT VERIFIED
            </span>
          </div>
          <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
            Only the server-owned cutover_gate/1 in a complete stored receipt can authorize this execution.
          </div>
        </section>
      ) : (
        <section aria-label="Legacy execution comparison status"
          data-testid={`cutover-execution-legacy-${run.id}`}
          style={{ border: "1px solid var(--border-faint)", borderRadius: 9, padding: "9px 10px", marginBottom: 10 }}>
          <b>Post-change comparison · legacy execution</b>
          <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>
            This run predates immutable canonical comparison receipts. It remains unchanged and cannot be reinterpreted or backfilled.
          </div>
        </section>
      )}

      {policy && live && (
        <section aria-label={`Bind post-change evidence for ${run.label}`}
          data-testid={`cutover-execution-compare-form-${run.id}`}>
          <b>Bind post-change evidence</b>
          <div className="dim" style={{ fontSize: 11.5, margin: "4px 0 8px" }}>
            Candidates come only from frozen campaign {policy.before_snapshot.campaign_id}. The server rechecks campaign, engagement, source custody, subjects, and owner semantics before appending—not replacing—an immutable receipt.
          </div>
          <div className="row-flex" style={{ gap: 8, flexWrap: "wrap" }}>
            <label htmlFor={`cutover-execution-after-${run.id}`} className="faint" style={{ fontSize: 11 }}>
              After snapshot
            </label>
            <select id={`cutover-execution-after-${run.id}`}
              aria-label={`After snapshot for ${run.label}`}
              value={afterSnapshotId}
              onChange={(event) => setAfterSnapshotId(event.target.value === "" ? "" : Number(event.target.value))}
              disabled={compareBusy || candidates.length === 0}
              style={{ minWidth: 220 }}>
              <option value="">choose post-change evidence…</option>
              {candidates.map((snapshot) => (
                <option key={snapshot.id} value={snapshot.id}>{snapshot.label} · snapshot {snapshot.id}</option>
              ))}
            </select>
            <button type="button" className="btn primary" onClick={bind}
              aria-label={`Bind and compare ${run.label}`}
              disabled={compareBusy || afterSnapshotId === ""
                || observedL2TrialIsReading(observedL2Trial)}>
              {compareBusy ? "Comparing…" : "Bind and compare"}
            </button>
          </div>
          <details style={{ marginTop: 8 }}>
            <summary className="faint" style={{ cursor: "pointer", fontSize: 11.5 }}>
              Expected family changes (optional, frozen into this receipt)
            </summary>
            <textarea aria-label={`Expected family changes for ${run.label}`}
              value={changeIntentText}
              onChange={(event) => setChangeIntentText(event.target.value)} rows={4}
              placeholder={'{"expected_changes":[{"family":"fhrp_redundancy_domain","transitions":["intent_changed"],"subjects":[],"reason":"planned active role move"}],"note":"CAB-1234"}'}
              style={{ width: "100%", marginTop: 6, fontFamily: "var(--mono)", fontSize: 11 }} />
          </details>
          <ObservedL2TrialInput
            idPrefix={`cutover-planner-${run.id}`}
            draft={observedL2Trial}
            onChange={setObservedL2Trial}
            snapshots={candidates}
            beforeSnapshotId={policy.before_snapshot.snapshot_id}
            recoverySnapshotId={afterSnapshotId}
            disabled={compareBusy}
          />
          {execution.l2_failure_trial_requirement && (
            <div role="alert" data-testid={`cutover-execution-l2-retrial-${run.id}`}
              style={{ color: "var(--crit)", fontSize: 11.5, marginTop: 8 }}>
              A prior {execution.l2_failure_trial_requirement.status.replaceAll("_", " ")} trial
              remains binding for <span className="mono">{execution.l2_failure_trial_requirement.family} · {execution.l2_failure_trial_requirement.subject}</span>.
              Only a strictly newer exact observed-survival trial can clear it.
            </div>
          )}
          {candidates.length === 0 && (
            <div className="faint" style={{ fontSize: 11, marginTop: 7 }}>
              No second snapshot is available in this execution&apos;s campaign yet.
            </div>
          )}
          {compareError && <div role="alert" style={{ color: "var(--crit)", fontSize: 11.5, marginTop: 7 }}>{compareError}</div>}
          {boundMessage && <div role="status" style={{ color: "var(--ok)", fontSize: 11.5, marginTop: 7 }}>{boundMessage}</div>}
        </section>
      )}
      {policy && !live && (
        <div className="faint" style={{ fontSize: 11.5 }}>
          This execution is read-only; its {receipts.length} immutable comparison receipt(s) cannot be replaced or appended.
        </div>
      )}
      {policy && receipts.length > 0 && (
        <div className="faint" style={{ fontSize: 10.5, marginTop: 7 }}>
          {receipts.length} immutable comparison receipt(s) retained · latest receipt {execution.latest_comparison?.receipt_id ?? "not identified"}
        </div>
      )}
    </div>
  );
}

function ExecutionRunCard({ run, onReceiptBound }: {
  run: ExecutionMeta;
  onReceiptBound: () => void;
}) {
  const [open, setOpen] = useState(false);
  const STATUS_COLOR: Record<string, string> = {
    in_progress: "var(--accent)", completed: "var(--ok)", aborted: "var(--crit)",
  };
  return (
    <div data-testid={`cutover-execution-card-${run.id}`}>
      <div className="row-flex" style={{ gap: 7, flexWrap: "wrap" }}>
        <Link to={`/executions/${run.id}`} className="chip"
          data-testid={`cutover-execution-${run.id}`} style={{ textDecoration: "none" }}>
          <span className="dot" style={{ background: STATUS_COLOR[run.status] || "var(--text-faint)" }} />
          {run.label} · <span className="faint">{run.status.replace("_", " ")}</span>
          {run.latest_comparison ? (
            <>
              {" · "}<span style={{ color: canonicalGateColor(run.latest_comparison.cutover_gate.verdict) }}>
                post-change {run.latest_comparison.cutover_gate.verdict}
              </span>
              <span className="faint"> · after snapshot {run.latest_comparison.after_snapshot_id}</span>
            </>
          ) : run.comparison_required ? (
            <span style={{ color: "var(--text-faint)" }}> · post-change NOT VERIFIED</span>
          ) : (
            <span className="faint"> · legacy · no canonical receipt</span>
          )}
        </Link>
        <button type="button" className="btn ghost"
          aria-expanded={open}
          aria-label={`${open ? "Hide" : "Open"} post-change evidence for ${run.label}`}
          onClick={() => setOpen((value) => !value)}
          style={{ padding: "3px 8px", fontSize: 10.5 }}>
          {open ? "Hide evidence" : run.comparison_required ? "Bind / view evidence" : "View legacy status"}
        </button>
      </div>
      {open && <PlannerExecutionComparison run={run} onReceiptBound={onReceiptBound} />}
    </div>
  );
}

/* Existing war-room runs over this plan + the entry point to start a new one. */
function ExecutionRuns({ snapId }: { snapId: number }) {
  const navigate = useNavigate();
  // audit FE-14: this destructured `data` + `reload` only, so a failed GET
  // /api/snapshots/{id}/executions (a 403 from the cross-site guard, the endpoint's own 404
  // "Snapshot not found", a dropped connection) left `runs === null` and the chip list below simply
  // did not render — identical to the honest "no runs yet" state. The engineer sees a bare "Start
  // execution run" button, concludes nothing is open for this snapshot, and opens a SECOND war room
  // over a cutover another operator already has live. Same class as the Snapshot page's FE-2/FE-3:
  // an absence claimed out of a request that failed. `loading` is read for the same reason.
  const { data: runs, error: listError, loading: listLoading, reload } = useAsync(() => api.listExecutions(snapId), [snapId]);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const start = () => {
    setStarting(true);
    setError(null);
    api.startExecution(snapId)
      .then((ex) => navigate(`/executions/${ex.id}`))
      .catch((e) => { setError(e.message || String(e)); reload(); })
      .finally(() => setStarting(false));
  };
  return (
    <div style={{ marginTop: 16, borderTop: "1px solid var(--border-faint)", paddingTop: 14 }}>
      <div className="row-flex">
        <button className="btn primary" onClick={start} disabled={starting}>
          ▶ Start execution run
        </button>
        <span className="dim" style={{ fontSize: 12 }}>
          Opens the live war-room console: check off the run-of-show, record validation results and
          deviations, and export the as-executed PIR record.
        </span>
      </div>
      {error && <div style={{ color: "var(--crit)", fontSize: 12.5, marginTop: 8 }}>Could not start the run: {error}</div>}
      {listError && (
        <div className="panel" role="status" style={{ borderColor: "var(--risk)", padding: "8px 12px", marginTop: 10 }}>
          <b style={{ color: "var(--risk)" }}>Existing runs could not be listed.</b>{" "}
          <span className="dim" style={{ fontSize: 12.5 }}>
            {listError} — this is <b>not evidence that no run is open</b> for this snapshot. Reload
            before starting a new one; two live war rooms over one cutover produce two conflicting
            as-executed records.
          </span>{" "}
          <button className="btn ghost" style={{ padding: "2px 9px", fontSize: 11 }} onClick={reload}>Retry</button>
        </div>
      )}
      {listLoading && !runs && !listError && (
        <div className="faint" style={{ fontSize: 11.5, marginTop: 8 }}>Checking for existing runs…</div>
      )}
      {(runs || []).length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 10 }}>
          {(runs || []).map((r) => (
            <ExecutionRunCard key={r.id} run={r} onReceiptBound={reload} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function CutoverPlanner({ snapId }: { snapId: number }) {
  const { data, error, loading } = useAsync(() => api.cutover(snapId), [snapId]);
  const { data: meta } = useAsync(() => api.meta(), []);
  const canDownload = (meta?.deliverables || []).some((d) => d.key === "cutover" && d.available);
  if (loading) return <div className="panel"><SkelLines n={6} label="Building cutover plan…" /></div>;
  if (error) return <ErrorBox msg={error} />;
  const plan = data!;
  const s = plan.summary;
  const fleetBaselineBlockers: CurrentBaselineBlocker[] = Array.isArray(plan.baseline_blockers)
    ? plan.baseline_blockers
    : Array.isArray(s.current_baseline?.blockers) ? s.current_baseline.blockers : [];
  const fleetUnboundBlockers = unboundBaselineBlockers(
    fleetBaselineBlockers, plan.waves,
  );
  const reportedUnbound = typeof s.n_unbound_baseline_blockers === "number"
    ? s.n_unbound_baseline_blockers : fleetUnboundBlockers.length;
  const showFleetBaseline = !plan.waves.length || reportedUnbound > 0 || fleetUnboundBlockers.length > 0;
  const fleetBaselinePanel = showFleetBaseline ? (
    <CurrentBaselinePanel
      gate={s.current_baseline}
      blockers={fleetUnboundBlockers}
      scope="fleet"
      title="Fleet current-baseline gate"
      subtitle="Fleet acceptance receipt; unbound rows remain outside scheduled-wave display limits"
      rowTestId="unbound-baseline-blocker"
      fullOperationalCount={fleetBaselineBlockers.length}
      footer={(reportedUnbound > 0 || fleetUnboundBlockers.length > 0) ? (
        <div data-testid="unbound-baseline-disclosure" style={{ padding: "8px 10px", borderTop: "1px solid var(--border-faint)", fontSize: 11.5 }}>
          <b style={{ color: "var(--watch)" }}>
            {Math.max(reportedUnbound, fleetUnboundBlockers.length)} unbound blocker(s)
          </b>{" "}
          <span className="dim">
            are not assigned to a scheduled wave. Every materialized row is shown above, outside ordinary validation caps; disposition them at fleet scope before acceptance.
          </span>
          {reportedUnbound > fleetUnboundBlockers.length && (
            <div style={{ color: "var(--crit)", marginTop: 4 }}>
              The plan reports {reportedUnbound} unbound blocker(s), but only {fleetUnboundBlockers.length} row(s) are materialized in this receipt. Do not interpret the missing detail as clear evidence.
            </div>
          )}
        </div>
      ) : undefined}
    />
  ) : null;
  if (!plan.waves.length) {
    return (
      <div className="panel">
        <h3>Cutover plan · run-of-show</h3>
        <div className="faint" style={{ fontSize: 13 }}>No migration waves were derived from this snapshot.</div>
        {fleetBaselinePanel}
      </div>
    );
  }

  return (
    <div className="panel pad-lg">
      <div className="spread" style={{ alignItems: "flex-start", marginBottom: 4, flexWrap: "wrap", gap: 10 }}>
        <h3 style={{ marginBottom: 0 }}>Cutover plan · run-of-show</h3>
        <div className="row-flex" style={{ gap: 10 }}>
          {canDownload && (
            <a className="btn" href={api.deliverableUrl(snapId, "cutover")} download>
              ↓ Download plan <span className="chip mono" style={{ fontSize: 9, padding: "1px 6px" }}>DOCX</span>
            </a>
          )}
          <GateBadge gate={s.verdict} big />
        </div>
      </div>
      <div className="dim" style={{ fontSize: 13, margin: "10px 0 16px", maxWidth: 760 }}>{s.statement}</div>

      {fleetBaselinePanel}

      <div className="row-flex" style={{ gap: 26, padding: "14px 0", borderTop: "1px solid var(--border-faint)", borderBottom: "1px solid var(--border-faint)" }}>
        <Stat value={<CountUp value={s.n_waves} />} label="waves" />
        <Stat value={<CountUp value={s.n_devices} />} label="devices" />
        <Stat value={<CountUp value={s.n_make_before_break} />} label="make-before-break" color="var(--ok)" />
        <Stat value={<CountUp value={s.n_hard_cutover} />} label={`hard-cutover · ${s.hard_cutover_endpoints} ep`} color="var(--risk)" />
        <Stat value={s.est_window_label} label="est. total window" color={s.est_window_minutes ? "var(--risk)" : "var(--ok)"} />
        <span style={{ flex: 1 }} />
        <div className="row-flex" style={{ gap: 8 }}>
          {(["GO", "CONDITIONAL GO", "NO-GO"] as const).map((g) =>
            s.gates[g] ? <span key={g} className="chip gate" style={{ ["--gc" as any]: gateColor(g) }}><b>{s.gates[g]}</b> {g}</span> : null,
          )}
        </div>
      </div>

      <details className="methodology" style={{ margin: "12px 0 10px" }}>
        <summary className="faint" style={{ fontSize: 11, cursor: "pointer" }}>
          Waves are sequenced <b>pilot-first</b> — the safest zero-outage wave proves the method before the higher-risk hard-cutover waves run. Window estimates are first-order planning anchors. <span style={{ textDecoration: "underline" }}>Methodology</span>
        </summary>
        {(s.methodology && s.methodology.length > 0) && (
          <ul className="faint" style={{ fontSize: 11, margin: "8px 0 0", paddingLeft: 18, lineHeight: 1.6 }}>
            {s.methodology.map((m, i) => <li key={i}>{m}</li>)}
          </ul>
        )}
      </details>

      <div className="wave-list">
        {plan.waves.map((w, i) => <WaveCard key={w.group + w.order} w={w} i={i} />)}
      </div>

      <ExecutionRuns snapId={snapId} />
    </div>
  );
}
