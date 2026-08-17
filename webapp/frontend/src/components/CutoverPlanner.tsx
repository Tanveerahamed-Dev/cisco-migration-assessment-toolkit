import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { api, CutoverWave, gateColor } from "../api";
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

type BaselineBlocker = {
  device?: string;
  wave?: string;
  category?: string;
  severity?: string;
  check?: string;
  command?: string;
  expect?: string;
  why?: string;
  evidence_state?: string;
  baseline_state?: string;
  projection_custody?: string;
  source_key?: string;
};

type CurrentBaselineGate = {
  schema?: string;
  verdict?: "BLOCKED" | "INDETERMINATE" | "CLEAR" | "NOT_ASSESSED" | string;
  assessed?: boolean;
  note?: string;
  summary?: {
    n_items?: number;
    n_blockers?: number;
    n_blockers_returned?: number;
    blockers_capped?: boolean;
    by_state?: Partial<Record<"degraded" | "review" | "not_verified", number>>;
  };
  blockers?: BaselineBlocker[];
  integrity?: { valid?: boolean; failures?: string[] };
};

type CutoverWaveWithBaseline = CutoverWave & {
  current_baseline?: CurrentBaselineGate;
  baseline_blockers?: BaselineBlocker[];
  validation: Array<CutoverWave["validation"][number] & BaselineBlocker>;
};

const BASELINE_GATE_COLOR: Record<string, string> = {
  BLOCKED: "var(--crit)",
  INDETERMINATE: "var(--watch)",
  NOT_ASSESSED: "var(--text-faint)",
  CLEAR: "var(--ok)",
};

function baselineBlockerKey(row: BaselineBlocker) {
  return [row.device, row.wave, row.category, row.check, row.source_key, row.expect]
    .map((part) => String(part || "").trim())
    .join("\u0000");
}

function isBaselineBlocker(row: BaselineBlocker) {
  const state = String(row.evidence_state || "").trim().toLowerCase();
  if (state === "degraded" || state === "review" || state === "not_verified") return true;
  const expected = String(row.expect || "").trim();
  return /^PRE-CUTOVER (?:DEGRADED|REVIEW) — BLOCKER:/i.test(expected)
    || /^(?:ROUTING|ETHERCHANNEL) BASELINE NOT VERIFIED(?:\s+—\s+BLOCKER)?(?::|\b)/i.test(expected);
}

function displayBaselineBlockersForWave(w: CutoverWaveWithBaseline): BaselineBlocker[] {
  const rows = [
    ...(Array.isArray(w.baseline_blockers) ? w.baseline_blockers : []),
    ...(Array.isArray(w.current_baseline?.blockers) ? w.current_baseline.blockers : []),
    ...w.validation.filter(isBaselineBlocker),
  ];
  return Array.from(new Map(rows.map((row) => [baselineBlockerKey(row), row])).values());
}

/** Use the explicit wave receipt as authority; fall back only for mixed-version API payloads. */
function boundBaselineBlockersForWave(w: CutoverWaveWithBaseline): BaselineBlocker[] {
  if (Array.isArray(w.baseline_blockers)) return w.baseline_blockers;
  if (Array.isArray(w.current_baseline?.blockers)) return w.current_baseline.blockers;
  return w.validation.filter(isBaselineBlocker);
}

/** Multiset subtraction preserves repeated top-level rows while removing only bound occurrences. */
function unboundBaselineBlockers(
  allRows: BaselineBlocker[], waves: CutoverWaveWithBaseline[],
): BaselineBlocker[] {
  const boundCounts = new Map<string, number>();
  waves.forEach((wave) => boundBaselineBlockersForWave(wave).forEach((row) => {
    const key = baselineBlockerKey(row);
    boundCounts.set(key, (boundCounts.get(key) || 0) + 1);
  }));
  return allRows.filter((row) => {
    const key = baselineBlockerKey(row);
    const remaining = boundCounts.get(key) || 0;
    if (!remaining) return true;
    boundCounts.set(key, remaining - 1);
    return false;
  });
}

function BaselineBlockerRow({ row, index, testId = "baseline-blocker" }: {
  row: BaselineBlocker;
  index: number;
  testId?: string;
}) {
  const state = String(row.evidence_state || row.baseline_state || "review").trim().toLowerCase();
  const degraded = state === "degraded";
  const tone = degraded ? "var(--crit)" : "var(--watch)";
  return (
    <div data-testid={testId} key={`${baselineBlockerKey(row)}\u0000${index}`}
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

function CurrentBaselinePanel({
  gate, blockers, scope, title = "Current baseline gate",
  subtitle = "Current observed state, separate from before→after change detection",
  rowTestId = "baseline-blocker", footer, fullOperationalCount,
}: {
  gate?: CurrentBaselineGate;
  blockers: BaselineBlocker[];
  scope?: string;
  title?: string;
  subtitle?: string;
  rowTestId?: string;
  footer?: ReactNode;
  fullOperationalCount?: number;
}) {
  if (!gate && blockers.length === 0 && !footer) return null;
  const verdict = gate?.verdict || (blockers.some((row) =>
    String(row.evidence_state || row.baseline_state || "").trim().toLowerCase() === "degraded") ? "BLOCKED" : "INDETERMINATE");
  const color = BASELINE_GATE_COLOR[verdict] || "var(--text-dim)";
  const testSuffix = scope ? `-${scope}` : "";
  const counts = gate?.summary?.by_state || {};
  const stateCount = (state: "degraded" | "review" | "not_verified") => {
    const supplied = counts[state];
    if (typeof supplied === "number" && Number.isFinite(supplied) && supplied >= 0) return supplied;
    return blockers.filter((row) => String(row.evidence_state || row.baseline_state || "").trim().toLowerCase() === state).length;
  };
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
          {gate?.note || (verdict === "CLEAR"
            ? "No producer-declared baseline blocker was found in observed validation scope."
            : `${blockers.length} producer-declared baseline blocker(s) require disposition.`)}
        </div>
        {verdict === "CLEAR" && (
          <div className="faint" data-testid={`current-baseline-clear-boundary${testSuffix}`} style={{ fontSize: 10.5, marginTop: 4 }}>
            CLEAR is bounded to the validation evidence collected in this snapshot; it is not cutover authorization.
          </div>
        )}
        <div className="faint" style={{ fontSize: 10.5, marginTop: 4 }}>
          {stateCount("degraded")} degraded · {stateCount("review")} review · {stateCount("not_verified")} not verified
          {gate?.integrity?.valid === false && " · validation-plan integrity failed"}
        </div>
      </div>
      {blockers.map((row, index) => (
        <BaselineBlockerRow row={row} index={index} testId={rowTestId}
          key={`${baselineBlockerKey(row)}\u0000${index}`} />
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

function WaveCard({ w, i }: { w: CutoverWaveWithBaseline; i: number }) {
  const [open, setOpen] = useState(false);
  const split: Record<string, number> = {};
  if (w.make_before_break.length) split["make-before-break"] = w.make_before_break.length;
  if (w.hard_cutover.length) split["hard-cutover"] = w.hard_cutover.length;
  const splitColor = (k: string) => (k === "make-before-break" ? "var(--ok)" : "var(--risk)");
  const br = w.blast_radius;
  // The API supplies an explicit per-wave list. Retain a metadata-derived fallback so a mixed-version
  // backend cannot strand a producer-declared blocker after the ordinary ten-row display cap.
  const baselineBlockers = displayBaselineBlockersForWave(w);
  const blockerKeys = new Set(baselineBlockers.map(baselineBlockerKey));
  const ordinaryValidation = w.validation.filter((row) => !blockerKeys.has(baselineBlockerKey(row)));

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

      <CurrentBaselinePanel gate={w.current_baseline} blockers={baselineBlockers} />

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
  const STATUS_COLOR: Record<string, string> = {
    in_progress: "var(--accent)", completed: "var(--ok)", aborted: "var(--crit)",
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
        <div className="row-flex" style={{ marginTop: 10 }}>
          {(runs || []).map((r) => (
            <Link key={r.id} to={`/executions/${r.id}`} className="chip" style={{ textDecoration: "none" }}>
              <span className="dot" style={{ background: STATUS_COLOR[r.status] || "var(--text-faint)" }} />
              {r.label} · <span className="faint">{r.status.replace("_", " ")}</span>
            </Link>
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
  const fleetBaselineBlockers: BaselineBlocker[] = Array.isArray(plan.baseline_blockers)
    ? plan.baseline_blockers
    : Array.isArray(s.current_baseline?.blockers) ? s.current_baseline.blockers : [];
  const fleetUnboundBlockers = unboundBaselineBlockers(
    fleetBaselineBlockers, plan.waves as CutoverWaveWithBaseline[],
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
