import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { api, gateColor } from "../api";
import type {
  Campaign,
  CutoverChangeIntentInput,
  CurrentBaselineBlocker,
  CurrentBaselineGate,
  ExecCheck,
  ExecStep,
  ExecutionState,
  ExecWave,
  SnapshotMeta,
} from "../api";
import ComparisonDecision from "../components/ComparisonDecision";
import { CountUp, ErrorBox, Loading, SevChip, useAsync, useToast } from "../components/ui";

/* The cutover execution console (war room): the snapshot's gated run-of-show, made live.
   Steps are checked off with timestamps, validation checks pass/fail against their captured
   baselines, waves are closed out, deviations are scribed — and the whole record exports as a
   Post-Implementation Review / as-executed change record (standard change-management closure). */

const WAVE_STATE_LABEL: Record<string, string> = {
  pending: "not started", active: "in progress", complete: "complete",
  rolled_back: "rolled back", deferred: "deferred",
};
const WAVE_STATE_COLOR: Record<string, string> = {
  pending: "var(--text-faint)", active: "var(--accent)", complete: "var(--ok)",
  rolled_back: "var(--crit)", deferred: "var(--watch)",
};
export const OUTCOME_COLOR = (o: string) =>
  o === "SUCCESSFUL" ? "var(--ok)"
    : o === "ROLLED BACK" || o === "ABORTED" ? "var(--crit)"
      : "var(--watch)";
const EVENT_KIND_COLOR: Record<string, string> = {
  deviation: "var(--crit)", finish: "var(--accent)", run: "var(--accent)",
  gate: "var(--ok)", check: "var(--ok)", step: "var(--text-dim)", note: "var(--watch)",
};

const BASELINE_COLOR: Record<string, string> = {
  BLOCKED: "var(--crit)", INDETERMINATE: "var(--watch)",
  NOT_ASSESSED: "var(--text-faint)", CLEAR: "var(--ok)",
};

function FrozenBaselineGate({ gate, blockerCount, scope }: {
  gate?: CurrentBaselineGate;
  blockerCount?: number;
  scope: string;
}) {
  if (!gate) return null; // Legacy execution records pre-date this frozen receipt.
  const verdict = gate.verdict || "NOT_ASSESSED";
  const color = BASELINE_COLOR[verdict] || "var(--text-dim)";
  const n = blockerCount ?? gate.n_blockers ?? gate.summary?.n_blockers ?? 0;
  return (
    <div role="status" data-testid={`execution-baseline-${scope}`}
      style={{ border: `1px solid ${color}`, borderRadius: 8, padding: "8px 10px", marginTop: 10, background: verdict === "BLOCKED" ? "var(--crit-soft)" : verdict === "INDETERMINATE" ? "var(--watch-soft)" : undefined }}>
      <div className="spread" style={{ gap: 8 }}>
        <div>
          <b>Start-snapshot baseline · {scope}</b>
          <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>Frozen when this execution record was created</div>
        </div>
        <span className="chip" data-testid={`execution-baseline-verdict-${scope}`} style={{ color, borderColor: color }}>
          <span className="dot" /> {verdict.replaceAll("_", " ")}
        </span>
      </div>
      {gate.note && <div className="dim" style={{ fontSize: 11.5, marginTop: 5 }}>{gate.note}</div>}
      {verdict === "CLEAR" ? (
        <div className="faint" style={{ fontSize: 10.5, marginTop: 4 }}>CLEAR is bounded to the frozen validation evidence; it is not authorization by itself.</div>
      ) : (
        <div style={{ color, fontSize: 11.5, marginTop: 4 }}>
          {n} blocker(s). This run cannot turn a non-clear start snapshot into a plain successful acceptance; re-collect and start a new run.
        </div>
      )}
    </div>
  );
}

type BaselineReceiptRow = {
  device?: string;
  wave?: string;
  category?: string;
  check?: string;
  expect?: string;
  source_key?: string;
  evidence_state?: string;
  baseline_state?: string;
  baseline_blocker?: boolean;
};

function baselineReceiptKey(row: BaselineReceiptRow): string {
  return [row.device, row.wave, row.category, row.check, row.source_key, row.expect]
    .map((part) => String(part || "").trim())
    .join("\u0000");
}

function checkIsBaselineBlocker(row: BaselineReceiptRow): boolean {
  const state = String(row.baseline_state || row.evidence_state || "").trim().toLowerCase();
  return row.baseline_blocker === true || ["degraded", "review", "not_verified"].includes(state);
}

function boundExecutionBlockers(wave: ExecWave): BaselineReceiptRow[] {
  if (Array.isArray(wave.baseline_blockers)) return wave.baseline_blockers;
  if (Array.isArray(wave.current_baseline?.blockers)) return wave.current_baseline.blockers;
  return wave.checks.filter(checkIsBaselineBlocker);
}

function frozenUnboundBlockers(ex: ExecutionState): CurrentBaselineBlocker[] {
  // New records freeze an explicit occurrence-preserving subset. Multiset subtraction is the
  // compatibility path for records that froze only the full plan-level list.
  if (Array.isArray(ex.unbound_baseline_blockers)) return ex.unbound_baseline_blockers;
  const allRows = Array.isArray(ex.baseline_blockers)
    ? ex.baseline_blockers
    : Array.isArray(ex.plan_summary?.current_baseline?.blockers)
      ? ex.plan_summary.current_baseline.blockers : [];
  const boundCounts = new Map<string, number>();
  ex.waves.forEach((wave) => boundExecutionBlockers(wave).forEach((row) => {
    const key = baselineReceiptKey(row);
    boundCounts.set(key, (boundCounts.get(key) || 0) + 1);
  }));
  return allRows.filter((row) => {
    const key = baselineReceiptKey(row);
    const remaining = boundCounts.get(key) || 0;
    if (!remaining) return true;
    boundCounts.set(key, remaining - 1);
    return false;
  });
}

function FrozenUnboundBaselineReceipt({ blockers, reportedCount, diagnosticCapped }: {
  blockers: CurrentBaselineBlocker[];
  reportedCount?: number;
  diagnosticCapped?: boolean;
}) {
  const reported = typeof reportedCount === "number" ? reportedCount : blockers.length;
  if (!blockers.length && !reported) return null;
  return (
    <section aria-label="Frozen unbound start-snapshot blockers" data-testid="execution-unbound-baseline-receipt"
      style={{ border: "1px solid var(--watch)", borderRadius: 8, marginTop: 10, overflow: "hidden" }}>
      <div className="spread" style={{ gap: 8, padding: "8px 10px", background: "var(--watch-soft)" }}>
        <div>
          <b>Unbound start-snapshot blockers</b>
          <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>
            Frozen at run creation · outside scheduled execution waves
          </div>
        </div>
        <span className="chip" style={{ color: "var(--watch)", borderColor: "var(--watch)" }}>
          {Math.max(reported, blockers.length)} UNBOUND
        </span>
      </div>
      <div className="dim" style={{ fontSize: 11.5, padding: "8px 10px" }}>
        These rows could not be assigned to an execution wave, so they are not actionable wave checks.
        They remain fleet acceptance blockers. REVIEW and NOT VERIFIED withhold acceptance without asserting a definite fault.
      </div>
      {blockers.map((row, index) => {
        const state = String(row.baseline_state || row.evidence_state || "review").trim().toLowerCase();
        const tone = state === "degraded" ? "var(--crit)" : "var(--watch)";
        return (
          <div data-testid="execution-unbound-baseline-blocker"
            key={`${baselineReceiptKey(row)}\u0000${index}`}
            style={{ borderTop: "1px solid var(--border-faint)", borderLeft: `3px solid ${tone}`, padding: "9px 10px" }}>
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
              Evidence: <span className="mono">{state}</span>
              {row.projection_custody && <> · custody: <span className="mono">{row.projection_custody}</span></>}
              {row.source_key && <> · source: <span className="mono">{row.source_key}</span></>}
            </div>
          </div>
        );
      })}
      {reported > blockers.length ? (
        <div style={{ color: "var(--crit)", fontSize: 11.5, padding: "8px 10px", borderTop: "1px solid var(--border-faint)" }}>
          The frozen summary reports {reported} unbound blocker(s), but only {blockers.length} row(s) are present. Do not interpret omitted detail as clear evidence.
        </div>
      ) : diagnosticCapped ? (
        <div className="faint" style={{ fontSize: 10.5, padding: "7px 10px", borderTop: "1px solid var(--border-faint)" }}>
          The diagnostic gate sample was capped; this execution receipt retains all {blockers.length} unbound operational row(s).
        </div>
      ) : null}
    </section>
  );
}

export function fmtClock(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
function fmtTime(ts: string | null): string {
  return ts ? new Date(ts).toLocaleTimeString() : "";
}

/* live elapsed clock — recomputed from started_at each tick, so it can't drift */
function useElapsed(startedAt: string, endedAt: string | null, live: boolean): number {
  const calc = () => {
    const end = endedAt ? new Date(endedAt).getTime() : Date.now();
    return Math.max(0, Math.floor((end - new Date(startedAt).getTime()) / 1000));
  };
  const [elapsed, setElapsed] = useState(calc);
  useEffect(() => {
    setElapsed(calc());
    if (!live) return;
    const t = setInterval(() => setElapsed(calc()), 1000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startedAt, endedAt, live]);
  return elapsed;
}

function StepRow({ s, i, live, onSet }:
  { s: ExecStep; i: number; live: boolean; onSet: (index: number, status: string) => void }) {
  const done = s.status === "done";
  const skipped = s.status === "skipped";
  // Pop the tick on a pending/skipped -> done transition. A key-remount is the house replay pattern
  // elsewhere (CausalFlow/CableMap), but this button is live-clicked/keyboard-activated mid-checklist —
  // remounting it would drop focus to <body> and break Tab flow through the steps. A one-shot class,
  // cleared on animationend, replays the pop without touching the DOM node.
  const prevStatus = useRef(s.status);
  const [pop, setPop] = useState(false);
  useEffect(() => {
    if (prevStatus.current !== "done" && s.status === "done") setPop(true);
    prevStatus.current = s.status;
  }, [s.status]);
  return (
    <div className={`estep ${s.status}`}>
      <button
        className={`tick ${s.status}${pop ? " tick-pop" : ""}`} disabled={!live}
        title={done || skipped ? "Reset to pending" : "Mark step done"}
        aria-label={done || skipped ? `Reset step ${i + 1}` : `Mark step ${i + 1} done`}
        onClick={() => onSet(i, done || skipped ? "pending" : "done")}
        onAnimationEnd={() => setPop(false)}
      >
        {done ? "✓" : skipped ? "⊘" : ""}
      </button>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="ph">{s.phase}</div>
        <div className="ac">{s.action}</div>
        {(s.at || s.note) && (
          <div className="meta">
            {s.status !== "pending" && <b style={{ color: skipped ? "var(--watch)" : "var(--ok)" }}>{s.status}</b>}
            {s.at && <span> · {fmtTime(s.at)}</span>}
            {s.by && <span> · {s.by}</span>}
            {s.note && <span> · {s.note}</span>}
          </div>
        )}
      </div>
      {live && s.status === "pending" && (
        <button className="btn ghost" style={{ padding: "3px 9px", fontSize: 11 }}
          onClick={() => onSet(i, "skipped")} title="Skip this step (recorded as a deviation input)">
          skip
        </button>
      )}
    </div>
  );
}

function CheckRow({ c, i, live, onSet }:
  { c: ExecCheck; i: number; live: boolean; onSet: (index: number, result: string, observed: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [observed, setObserved] = useState(c.observed);
  const baselineState = String(c.baseline_state || c.evidence_state || "").trim().toLowerCase();
  const baselineBlocker = c.baseline_blocker === true
    || ["degraded", "review", "not_verified"].includes(baselineState);
  const resColor = c.result === "pass" ? "var(--ok)" : c.result === "fail" ? "var(--crit)" : "var(--text-faint)";
  return (
    <div className="checkrow" data-testid={baselineBlocker ? "execution-baseline-blocker" : undefined}
      style={baselineBlocker ? { borderLeft: `3px solid ${baselineState === "degraded" ? "var(--crit)" : "var(--watch)"}`, paddingLeft: 8, background: baselineState === "degraded" ? "var(--crit-soft)" : "var(--watch-soft)" } : undefined}>
      <SevChip sev={c.severity} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="row-flex" style={{ gap: 6, flexWrap: "wrap" }}>
          <b style={{ fontSize: 12.5 }}>{c.check}</b>
          {baselineBlocker && (
            <span className="chip" style={{ color: baselineState === "degraded" ? "var(--crit)" : "var(--watch)" }}>
              START-SNAPSHOT {baselineState.replaceAll("_", " ").toUpperCase()} BLOCKER
            </span>
          )}
        </div>
        <div className="cmd" style={{ marginTop: 4 }}>{c.command}</div>
        <div className="dim" style={{ fontSize: 11, marginTop: 3 }}>
          <b style={{ color: "var(--text-dim)" }}>{baselineBlocker ? "observed baseline / acceptance:" : "expect:"}</b> {c.expect}
        </div>
        {baselineBlocker && (
          <div className="faint" style={{ fontSize: 10.5, marginTop: 4 }}>
            Evidence: <span className="mono">{baselineState}</span>
            {c.projection_custody && <> · custody: <span className="mono">{c.projection_custody}</span></>}
            {c.source_key && <> · source: <span className="mono">{c.source_key}</span></>}
          </div>
        )}
        {c.result !== "pending" && !editing && (
          <div className="meta" style={{ marginTop: 4 }}>
            <b style={{ color: resColor, textTransform: "uppercase" }}>{c.result}</b>
            {c.at && <span> · {fmtTime(c.at)}</span>}
            {c.by && <span> · {c.by}</span>}
            {c.observed && <span> · observed: {c.observed}</span>}
          </div>
        )}
        {editing && (
          <div className="row-flex" style={{ marginTop: 6 }}>
            <input value={observed} onChange={(e) => setObserved(e.target.value)} autoFocus
              placeholder="Observed result (what the command actually showed)…" style={{ flex: 1, fontSize: 12 }}
              onKeyDown={(e) => { if (e.key === "Enter") { onSet(i, "fail", observed); setEditing(false); } }} />
            <button className="btn danger" style={{ padding: "6px 12px", fontSize: 12 }}
              onClick={() => { onSet(i, "fail", observed); setEditing(false); }}>Record FAIL</button>
            <button className="btn ghost" style={{ padding: "6px 10px", fontSize: 12 }}
              onClick={() => setEditing(false)}>cancel</button>
          </div>
        )}
      </div>
      {live && !editing && (
        <div className="row-flex" style={{ gap: 5, flex: "none" }}>
          <button className={`vbtn pass ${c.result === "pass" ? "on" : ""}`}
            disabled={baselineBlocker}
            title={baselineBlocker ? "A start-snapshot blocker cannot be recorded as plain PASS; re-collect a clear snapshot and start a new run" : undefined}
            onClick={() => onSet(i, "pass", "")}>{baselineBlocker ? "PASS BLOCKED" : "PASS"}</button>
          <button className={`vbtn fail ${c.result === "fail" ? "on" : ""}`}
            onClick={() => { setObserved(c.observed); setEditing(true); }}>FAIL</button>
          <button className={`vbtn na ${c.result === "na" ? "on" : ""}`} onClick={() => onSet(i, "na", "")}>N/A</button>
        </div>
      )}
    </div>
  );
}

function WaveRunCard({ w, waveState, live, act }: {
  w: ExecWave;
  waveState: string;
  live: boolean;
  act: {
    step: (wave: string, index: number, status: string) => void;
    check: (wave: string, index: number, result: string, observed: string) => void;
    closeout: (wave: string, decision: string, note: string) => void;
  };
}) {
  const [note, setNote] = useState("");
  const [showChecks, setShowChecks] = useState(true);
  const closed = !!w.closeout.decision;
  const nDone = w.steps.filter((s) => s.status !== "pending").length;
  const nPass = w.checks.filter((c) => c.result === "pass").length;
  const nFail = w.checks.filter((c) => c.result === "fail").length;
  // audit FE-13: the counter below read `nFail ? crit : ok`, so a wave whose validation checks were
  // ALL still pending (nPass = nFail = 0) rendered in exactly the green a wave that passed every
  // check does. That is "not observed" wearing the colour of "healthy" on the one strip an engineer
  // scans right before pressing "✓ Complete wave" — and colour was the only signal, so a colour-blind
  // reader had none at all. Green now means VERIFIED (every check recorded, none failed); anything
  // unrecorded is neutral AND named in the label.
  const nPending = w.checks.filter((c) => c.result === "pending").length;
  const checkTone = nFail ? "var(--crit)" : nPending || !nPass ? "var(--text-faint)" : "var(--ok)";

  return (
    <div className="wave-card" style={{ ["--gc" as any]: WAVE_STATE_COLOR[waveState] || "var(--border)" }}>
      <div className="wh">
        <span className="ordno">{w.order}</span>
        <span className="wname">{w.group}</span>
        <span className="chip gate" style={{ ["--gc" as any]: gateColor(w.gate) }}>
          <span className="dot" /> plan: {w.gate}
        </span>
        <span className="chip tag">{w.strategy}</span>
        <span className="chip wavestate" style={{ color: WAVE_STATE_COLOR[waveState], borderColor: "var(--border)" }}>
          {WAVE_STATE_LABEL[waveState] || waveState}
        </span>
        <span className="wmeta">
          <span><span className="num">{nDone}/{w.steps.length}</span><span className="lbl">steps</span></span>
          <span><span className="num" style={{ color: checkTone }}>{nPass}✓ {nFail}✗</span><span className="lbl">checks{nPending ? ` · ${nPending} unrecorded` : ""}</span></span>
          <span><span className="num" style={{ color: w.est_window_minutes ? "var(--risk)" : "var(--ok)" }}>{w.est_window_label}</span><span className="lbl">planned window</span></span>
        </span>
      </div>

      {w.gate === "NO-GO" && !closed && (
        <div className="nogowarn ros-reveal">
          The plan gated this wave <b>NO-GO</b> ({w.blockers.filter((b) => b.status === "fail").length} failing
          readiness check(s) · {w.baseline_blockers?.length || 0} start-snapshot baseline blocker(s)). Executing it anyway is an override — confirm the blockers are cleared and scribe why.
        </div>
      )}

      <FrozenBaselineGate gate={w.current_baseline} blockerCount={w.baseline_blockers?.length} scope={w.group} />

      <div className="exec-steps" style={{ marginTop: 10 }}>
        {w.steps.map((s, i) => (
          <StepRow key={i} s={s} i={i} live={live && !closed} onSet={(idx, st) => act.step(w.group, idx, st)} />
        ))}
      </div>

      {w.checks.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <button className="btn" style={{ padding: "5px 11px", fontSize: 12 }} onClick={() => setShowChecks((v) => !v)}
            aria-expanded={showChecks}>
            {showChecks ? "▾" : "▸"} Validation checks
            <span className="chip mono" style={{ fontSize: 9, padding: "1px 6px" }}>{nPass + nFail}/{w.checks.length} recorded</span>
          </button>
          {showChecks && (
            <div className="ros-reveal" style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
              {w.checks.map((c, i) => (
                <CheckRow key={i} c={c} i={i} live={live && !closed} onSet={(idx, r, o) => act.check(w.group, idx, r, o)} />
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ marginTop: 14, borderTop: "1px solid var(--border-faint)", paddingTop: 12 }}>
        {closed ? (
          <div className="meta" style={{ fontSize: 12.5 }}>
            Closed out <b style={{ color: WAVE_STATE_COLOR[waveState] }}>{w.closeout.decision}</b>
            {w.closeout.at && <span> · {fmtTime(w.closeout.at)}</span>}
            {w.closeout.by && <span> · {w.closeout.by}</span>}
            {w.closeout.note && <span> — {w.closeout.note}</span>}
          </div>
        ) : live ? (
          <div className="row-flex">
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Closeout note (optional)…"
              style={{ flex: 1, minWidth: 180, fontSize: 12 }} />
            <button className="btn" style={{ color: "var(--ok)" }}
              onClick={() => act.closeout(w.group, "COMPLETE", note)}>✓ Complete wave</button>
            <button className="btn danger" onClick={() => act.closeout(w.group, "ROLLED BACK", note)}>↩ Roll back</button>
            <button className="btn ghost" onClick={() => act.closeout(w.group, "DEFERRED", note)}>Defer</button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function EventLog({ ex, live, onLog }:
  { ex: ExecutionState; live: boolean; onLog: (kind: string, text: string) => void }) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState<"note" | "deviation">("note");
  const submit = () => {
    if (!text.trim()) return;
    onLog(kind, text.trim());
    setText("");
  };
  const rows = useMemo(() => [...ex.events].reverse(), [ex.events]);
  return (
    <div className="panel">
      <h3>Live log · {ex.events.length} entries</h3>
      {live && (
        <div className="row-flex" style={{ marginBottom: 12 }}>
          <select value={kind} onChange={(e) => setKind(e.target.value as any)} style={{ width: 110, flex: "none" }}>
            <option value="note">note</option>
            <option value="deviation">deviation</option>
          </select>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Scribe an entry — what just happened?"
            style={{ flex: 1 }} onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
          <button className="btn" onClick={submit}>Log</button>
        </div>
      )}
      <div className="evlog">
        {rows.length === 0 && (
          <div className="faint" style={{ fontSize: 12.5, padding: "4px 0" }}>
            No entries yet — steps, checks and notes land here as they happen.
          </div>
        )}
        {rows.map((e, i) => (
          <div className="evrow evrow-in" key={ex.events.length - i}>
            <span className="t mono">{fmtTime(e.at)}</span>
            <span className="k mono" style={{ color: EVENT_KIND_COLOR[e.kind] || "var(--text-dim)" }}>{e.kind}</span>
            <span style={{ flex: 1 }}>
              {e.wave && <b className="dim">{e.wave} · </b>}{e.text}
              {e.by && <span className="faint"> — {e.by}</span>}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ExecutionPage() {
  const { id } = useParams();
  const eid = Number(id);
  const { data, error, loading } = useAsync(() => api.getExecution(eid), [eid]);
  const [ex, setEx] = useState<ExecutionState | null>(null);
  const queueRef = useRef<Promise<unknown>>(Promise.resolve());
  const [operator, setOperator] = useState<string>(() => localStorage.getItem("assesshub-operator") || "");
  const [afterSnapshotId, setAfterSnapshotId] = useState<number | "">("");
  const [changeIntentText, setChangeIntentText] = useState("");
  const [compareBusy, setCompareBusy] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);
  const { toast, node: toastNode } = useToast();
  const { data: snapMeta } = useAsync<SnapshotMeta | null>(
    () => (ex ? api.getSnapshot(ex.snapshot_id) : Promise.resolve(null)), [ex?.snapshot_id]);
  const comparisonPolicy = ex?.comparison_policy;
  const { data: campaign } = useAsync<Campaign | null>(
    () => (comparisonPolicy && snapMeta
      ? api.getCampaign(snapMeta.campaign_id)
      : Promise.resolve(null)),
    [comparisonPolicy?.schema, snapMeta?.campaign_id],
  );

  useEffect(() => { if (data) setEx(data); }, [data]);
  useEffect(() => { localStorage.setItem("assesshub-operator", operator); }, [operator]);

  const live = ex?.status === "in_progress";
  const elapsed = useElapsed(ex?.started_at || new Date().toISOString(), ex?.ended_at || null, !!live);

  if (loading && !ex) return <div className="container"><Loading label="Opening the war room…" /></div>;
  if (error && !ex) return <div className="container"><ErrorBox msg={error} /></div>;
  if (!ex) return null;
  const unboundBaselineBlockers = frozenUnboundBlockers(ex);

  // Mutations are serialized through one promise chain: rapid clicks otherwise race on separate
  // connections, and an out-of-order response would setEx an older state (reverting ticks and
  // inviting duplicate timeline entries on re-click).
  const apply = (fn: () => Promise<ExecutionState>) => {
    queueRef.current = queueRef.current
      .then(fn)
      .then(setEx)
      .catch((e) => toast(e.message || String(e)));
  };

  const bindPostChangeComparison = () => {
    if (afterSnapshotId === "") {
      toast("Choose the post-change snapshot first.");
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
      } catch (e: any) {
        const message = `Expected-change intent is not valid JSON: ${e?.message || String(e)}`;
        setCompareError(message);
        toast("Fix the expected-change intent before binding evidence.");
        return;
      }
    }
    setCompareBusy(true);
    setCompareError(null);
    queueRef.current = queueRef.current
      .then(() => changeIntent
        ? api.compareExecution(eid, afterSnapshotId, changeIntent)
        : api.compareExecution(eid, afterSnapshotId))
      .then((updated) => {
        setEx(updated);
        setAfterSnapshotId("");
        setChangeIntentText("");
        toast("Post-change evidence bound to an immutable canonical comparison receipt.");
      })
      .catch((e) => {
        const message = e.message || String(e);
        setCompareError(message);
        toast(message);
      })
      .finally(() => setCompareBusy(false));
  };

  const act = {
    step: (wave: string, index: number, status: string) =>
      apply(() => api.execStep(eid, wave, index, status, "", operator)),
    check: (wave: string, index: number, result: string, observed: string) =>
      apply(() => api.execCheck(eid, wave, index, result, observed, operator)),
    closeout: (wave: string, decision: string, note: string) => {
      if (decision !== "COMPLETE" && !window.confirm(`Close out this wave as ${decision}?`)) return;
      apply(() => api.execCloseout(eid, wave, decision, note, operator));
    },
  };
  const finish = (status: "completed" | "aborted") => {
    const open = ex.waves.filter((w) => !w.closeout.decision).length;
    // Predict the verdict the backend will derive: a rolled-back wave dominates PARTIAL.
    const rolledBack = ex.waves.some((w) => w.closeout.decision === "ROLLED BACK");
    const predicted = rolledBack ? "ROLLED BACK" : "PARTIALLY IMPLEMENTED";
    // audit FE-10: the warning used to key on `open` alone — waves with NO decision. But the backend
    // (webapp/backend/execution.py :: _derive_outcome) is
    //     `if not decisions or any(d != "COMPLETE" for d in decisions): return OUTCOME_PARTIAL`
    // so a wave closed out DEFERRED (or ROLLED BACK) also forces PARTIALLY IMPLEMENTED while
    // leaving `open === 0`. That combination hit the unconditional "the outcome is derived for the
    // PIR" wording, which warns of nothing — the engineer signs off expecting SUCCESSFUL and the
    // PIR reads PARTIALLY IMPLEMENTED. Count every wave that will NOT satisfy the backend's
    // COMPLETE test, not just the un-closed ones.
    const notComplete = ex.waves.filter((w) => w.closeout.decision !== "COMPLETE").length;
    const frozenBaseline = ex.plan_summary?.current_baseline;
    const baselineForcesPartial = !!frozenBaseline && frozenBaseline.verdict !== "CLEAR";
    const canonicalVerdict = ex.latest_comparison?.cutover_gate?.verdict;
    const canonicalForcesPartial = ex.comparison_policy?.canonical_gate_required === true
      && canonicalVerdict !== "PASS";
    const msg = status === "aborted"
      ? "Abort this run? The record is kept and the PIR will show ABORTED."
      : open ? `${open} wave(s) are not closed out — finishing now derives a ${predicted} outcome. Finish anyway?`
        : notComplete
          ? `${notComplete} wave(s) closed out as something other than COMPLETE — finishing now derives a ${predicted} outcome. Finish anyway?`
          : baselineForcesPartial
            ? `The start-snapshot current-baseline gate is ${frozenBaseline.verdict}. Finishing now derives a PARTIALLY IMPLEMENTED outcome; re-collect a CLEAR snapshot and start a new run for successful acceptance. Finish anyway?`
          : canonicalForcesPartial
            ? `The latest canonical post-change gate is ${canonicalVerdict || "NOT VERIFIED"}. Finishing now derives a PARTIALLY IMPLEMENTED outcome; bind a comparison whose server-owned cutover gate is PASS for successful acceptance. Finish anyway?`
          : "Finish this run? It becomes read-only and the outcome is derived for the PIR.";
    if (!window.confirm(msg)) return;
    apply(() => api.execFinish(eid, status, "", operator));
  };

  const p = ex.progress;
  const stateByGroup = new Map(p.waves.map((x) => [x.group, x.state]));
  const waveState = (g: string) => stateByGroup.get(g) || "pending";
  // From the live ticking clock, not the server-frozen progress value — otherwise the OVER alarm
  // can't fire between mutations, exactly when the team is heads-down.
  const overBudget = p.planned_window_minutes > 0 && elapsed > p.planned_window_minutes * 60;
  const executionStartedAt = Date.parse(ex.started_at);
  const snapshotIdHighWatermark = comparisonPolicy?.snapshot_id_high_watermark
    ?? ex.snapshot_id;
  const candidates = (campaign?.snapshots || []).filter((snapshot) => {
    const uploadedAt = Date.parse(snapshot.uploaded_at);
    return snapshot.id > snapshotIdHighWatermark
      && Number.isFinite(executionStartedAt)
      && Number.isFinite(uploadedAt)
      && uploadedAt > executionStartedAt;
  });
  const receipts = Array.isArray(ex.comparison_receipts) ? ex.comparison_receipts : [];
  const latestStored = ex.latest_comparison
    ? receipts.find((row) => row.id === ex.latest_comparison!.receipt_id)
    : receipts[receipts.length - 1];
  const latestComparison = latestStored?.receipt.comparison;
  const canonicalVerdict = ex.latest_comparison?.cutover_gate?.verdict;
  const canonicalRequiredWithoutPass = ex.comparison_policy?.canonical_gate_required === true
    && canonicalVerdict !== "PASS";
  const baselinePreventsSuccess = !!ex.plan_summary?.current_baseline
    && ex.plan_summary.current_baseline.verdict !== "CLEAR";

  return (
    <div className="container">
      <div className="breadcrumb">
        <Link to="/campaigns">Campaigns</Link>
        {snapMeta && <> / <Link to={`/campaigns/${snapMeta.campaign_id}`}>campaign</Link> / <Link to={`/snapshots/${ex.snapshot_id}`}>{snapMeta.label}</Link></>}
        {" / "}{ex.label}
      </div>

      <div className="page-head">
        <div>
          <h1>{ex.label}</h1>
          <div className="sub">
            Cutover execution run · started {new Date(ex.started_at).toLocaleString()}
            {ex.ended_at && <> · ended {new Date(ex.ended_at).toLocaleString()}</>}
          </div>
        </div>
        <span style={{ flex: 1 }} />
        {ex.outcome ? (
          <span className="gatebadge" style={{ ["--gc" as any]: OUTCOME_COLOR(ex.outcome) }}>
            <span className="dot" /> {ex.outcome}
          </span>
        ) : (
          <span className="gatebadge" style={{ ["--gc" as any]: "var(--accent)" }}>
            <span className="dot" /> LIVE
          </span>
        )}
      </div>

      {latestComparison ? (
        <ComparisonDecision
          value={latestComparison}
          exportFilename={`execution-${eid}-comparison-receipt-${latestStored?.id || "latest"}.json`}
        />
      ) : comparisonPolicy ? (
        <section aria-label="Canonical post-change cutover decision" data-testid="execution-canonical-gate-missing"
          style={{ border: "1px solid var(--text-faint)", borderRadius: 9, padding: "10px 11px", marginBottom: 12 }}>
          <div className="spread" style={{ gap: 8 }}>
            <div>
              <b>Canonical post-change cutover decision</b>
              <div className="faint" style={{ fontSize: 10.5, marginTop: 2 }}>No immutable comparison receipt has been bound to this run</div>
            </div>
            <span className="chip" style={{ color: "var(--text-faint)", borderColor: "var(--text-faint)" }}>NOT VERIFIED</span>
          </div>
          <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
            A new execution can be successful only when its latest server-owned cutover_gate/1 receipt is PASS.
          </div>
        </section>
      ) : (
        <section aria-label="Legacy execution comparison status" data-testid="execution-comparison-legacy"
          style={{ border: "1px solid var(--border-faint)", borderRadius: 9, padding: "9px 11px", marginBottom: 12 }}>
          <b>Post-change comparison · legacy execution</b>
          <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>
            This run predates immutable canonical comparison receipts. It remains unchanged and cannot be reinterpreted or backfilled.
          </div>
        </section>
      )}

      {comparisonPolicy && live && (
        <section aria-label="Bind post-change evidence" data-testid="execution-compare-form" className="panel"
          style={{ marginBottom: 12 }}>
          <h3>Bind post-change evidence</h3>
          <div className="dim" style={{ fontSize: 12, marginBottom: 8 }}>
            Select a newer snapshot uploaded after this run began. The server rechecks temporal order, campaign, engagement, source hashes, subjects, owner versions, and support profiles before appending an immutable receipt.
          </div>
          <div className="row-flex" style={{ gap: 8, flexWrap: "wrap" }}>
            <label htmlFor="execution-after-snapshot" className="faint" style={{ fontSize: 11 }}>After snapshot</label>
            <select id="execution-after-snapshot" aria-label="After snapshot" value={afterSnapshotId}
              onChange={(event) => setAfterSnapshotId(event.target.value === "" ? "" : Number(event.target.value))}
              disabled={compareBusy || candidates.length === 0} style={{ minWidth: 220 }}>
              <option value="">choose post-change evidence…</option>
              {candidates.map((snapshot) => (
                <option key={snapshot.id} value={snapshot.id}>{snapshot.label} · snapshot {snapshot.id}</option>
              ))}
            </select>
            <button type="button" className="btn primary" onClick={bindPostChangeComparison}
              disabled={compareBusy || afterSnapshotId === ""}>
              {compareBusy ? "Comparing…" : "Bind and compare"}
            </button>
          </div>
          <details style={{ marginTop: 9 }}>
            <summary className="faint" style={{ cursor: "pointer", fontSize: 11.5 }}>
              Expected family changes (optional, frozen into this receipt)
            </summary>
            <div className="faint" style={{ fontSize: 10.5, margin: "6px 0" }}>
              Reviewable planned transitions can be reconciled; blocks, coverage loss, and
              incompatibility remain non-PASS regardless of intent.
            </div>
            <textarea aria-label="Execution expected family changes JSON" value={changeIntentText}
              onChange={(event) => setChangeIntentText(event.target.value)} rows={5}
              placeholder={'{"expected_changes":[{"family":"fhrp_redundancy_domain","transitions":["intent_changed"],"subjects":[],"reason":"planned active role move"}],"note":"CAB-1234"}'}
              style={{ width: "100%", fontFamily: "var(--mono)", fontSize: 11 }} />
          </details>
          {candidates.length === 0 && (
            <div className="faint" style={{ fontSize: 11, marginTop: 7 }}>
              No post-start snapshot is available in this campaign yet.
            </div>
          )}
          {compareError && <div style={{ marginTop: 8 }}><ErrorBox msg={compareError} /></div>}
          {receipts.length > 0 && (
            <div className="faint" style={{ fontSize: 10.5, marginTop: 7 }}>
              {receipts.length} immutable comparison receipt(s) retained · latest receipt {ex.latest_comparison?.receipt_id ?? "not identified"}
            </div>
          )}
        </section>
      )}

      <FrozenBaselineGate gate={ex.plan_summary?.current_baseline}
        blockerCount={ex.plan_summary?.n_baseline_blockers} scope="run" />
      <FrozenUnboundBaselineReceipt
        blockers={unboundBaselineBlockers}
        reportedCount={ex.plan_summary?.n_unbound_baseline_blockers}
        diagnosticCapped={ex.plan_summary?.baseline_blockers_capped}
      />

      {/* console strip: clock + progress + actions */}
      <div className="panel execbar">
        <div>
          <div className="clock mono" style={{ color: overBudget ? "var(--crit)" : "var(--text)" }}>{fmtClock(elapsed)}</div>
          <div className="lbl">elapsed{p.planned_window_minutes ? ` · planned window ${ex.plan_summary?.est_window_label || ""}` : ""}{overBudget ? " · OVER" : ""}</div>
        </div>
        <div className="execprog">
          <div className="track"><div className="fill" style={{ width: `${p.pct}%` }} /></div>
          <div className="lbl"><b><CountUp value={p.pct} />%</b> · {p.n_steps_done} of {p.n_steps} steps done{p.n_steps_skipped ? ` · ${p.n_steps_skipped} skipped` : ""}</div>
        </div>
        <div className="execstat">
          {/* audit FE-13 (run scope): same rule as the per-wave counter — `0✓ 0✗` in green reads as
              "no failures", when it is really "nothing recorded". The server already publishes the
              pending count in progress.checks, so name it rather than re-deriving one here. */}
          <b style={{ color: p.checks.pass && !p.checks.pending ? "var(--ok)" : "var(--text-faint)" }}>{p.checks.pass}✓</b>
          <b style={{ color: p.checks.fail ? "var(--crit)" : "var(--text-faint)" }}>{p.checks.fail}✗</b>
          <span className="lbl">validation{p.checks.pending ? ` · ${p.checks.pending} pending` : ""}</span>
        </div>
        <div className="execstat">
          <b style={{ color: p.n_deviations ? "var(--risk)" : "var(--text-faint)" }}><CountUp value={p.n_deviations} /></b>
          <span className="lbl">deviations</span>
        </div>
        <span style={{ flex: 1 }} />
        {live && (
          <input value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="Operator (signs every action)…"
            style={{ width: 200, flex: "none", fontSize: 12 }} title="Recorded as 'by' on every step, check, and closeout" />
        )}
        <a className="btn" href={api.executionReportUrl(eid)} download>
          ↓ {live ? "Interim record" : "PIR report"} <span className="chip mono" style={{ fontSize: 9, padding: "1px 6px" }}>DOCX</span>
        </a>
        {live && (
          <>
            <button className="btn primary" onClick={() => finish("completed")}
              title={baselinePreventsSuccess
                ? "Finishing this frozen non-clear baseline can only derive PARTIALLY IMPLEMENTED"
                : canonicalRequiredWithoutPass
                  ? "A new execution requires a latest canonical PASS gate for SUCCESSFUL"
                  : undefined}>
              ■ Finish run{baselinePreventsSuccess || canonicalRequiredWithoutPass ? " · partial" : ""}
            </button>
            <button className="btn danger" onClick={() => finish("aborted")}>Abort</button>
          </>
        )}
      </div>

      <div className="grid" style={{ marginTop: 16, gap: 16 }}>
        <div className="wave-list">
          {ex.waves.map((w) => (
            <WaveRunCard key={w.order} w={w} waveState={waveState(w.group)} live={!!live} act={act} />
          ))}
        </div>
        <EventLog ex={ex} live={!!live} onLog={(k, t) => apply(() => api.execEvent(eid, k, t, "", operator))} />
      </div>
      {toastNode}
    </div>
  );
}
