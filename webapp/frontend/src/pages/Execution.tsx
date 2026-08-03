import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { api, ExecCheck, ExecStep, ExecutionState, ExecWave, gateColor, SnapshotMeta } from "../api";
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
  const resColor = c.result === "pass" ? "var(--ok)" : c.result === "fail" ? "var(--crit)" : "var(--text-faint)";
  return (
    <div className="checkrow">
      <SevChip sev={c.severity} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5 }}><b>{c.check}</b></div>
        <div className="cmd" style={{ marginTop: 4 }}>{c.command}</div>
        <div className="dim" style={{ fontSize: 11, marginTop: 3 }}>
          <b style={{ color: "var(--text-dim)" }}>expect:</b> {c.expect}
        </div>
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
          <button className={`vbtn pass ${c.result === "pass" ? "on" : ""}`} onClick={() => onSet(i, "pass", "")}>PASS</button>
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
          check(s)). Executing it anyway is an override — confirm the blockers are cleared and scribe why.
        </div>
      )}

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
  const { toast, node: toastNode } = useToast();
  const { data: snapMeta } = useAsync<SnapshotMeta | null>(
    () => (ex ? api.getSnapshot(ex.snapshot_id) : Promise.resolve(null)), [ex?.snapshot_id]);

  useEffect(() => { if (data) setEx(data); }, [data]);
  useEffect(() => { localStorage.setItem("assesshub-operator", operator); }, [operator]);

  const live = ex?.status === "in_progress";
  const elapsed = useElapsed(ex?.started_at || new Date().toISOString(), ex?.ended_at || null, !!live);

  if (loading && !ex) return <div className="container"><Loading label="Opening the war room…" /></div>;
  if (error && !ex) return <div className="container"><ErrorBox msg={error} /></div>;
  if (!ex) return null;

  // Mutations are serialized through one promise chain: rapid clicks otherwise race on separate
  // connections, and an out-of-order response would setEx an older state (reverting ticks and
  // inviting duplicate timeline entries on re-click).
  const apply = (fn: () => Promise<ExecutionState>) => {
    queueRef.current = queueRef.current
      .then(fn)
      .then(setEx)
      .catch((e) => toast(e.message || String(e)));
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
    const msg = status === "aborted"
      ? "Abort this run? The record is kept and the PIR will show ABORTED."
      : open ? `${open} wave(s) are not closed out — finishing now derives a ${predicted} outcome. Finish anyway?`
        : notComplete
          ? `${notComplete} wave(s) closed out as something other than COMPLETE — finishing now derives a ${predicted} outcome. Finish anyway?`
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
            <button className="btn primary" onClick={() => finish("completed")}>■ Finish run</button>
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
