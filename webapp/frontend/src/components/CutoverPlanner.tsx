import { useState, type ReactNode } from "react";
import { api, CutoverWave, gateColor } from "../api";
import { ErrorBox, Loading, SegBar, SevChip, useAsync } from "./ui";

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

function WaveCard({ w }: { w: CutoverWave }) {
  const [open, setOpen] = useState(false);
  const split: Record<string, number> = {};
  if (w.make_before_break.length) split["make-before-break"] = w.make_before_break.length;
  if (w.hard_cutover.length) split["hard-cutover"] = w.hard_cutover.length;
  const splitColor = (k: string) => (k === "make-before-break" ? "var(--ok)" : "var(--risk)");
  const br = w.blast_radius;

  return (
    <div className="wave-card" style={{ ["--gc" as any]: gateColor(w.gate) }}>
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

      <div style={{ marginTop: 12 }}>
        <button className="btn" onClick={() => setOpen((v) => !v)} style={{ padding: "6px 12px", fontSize: 12 }}>
          {open ? "▾" : "▸"} Run-of-show
          <span className="chip mono" style={{ fontSize: 9, padding: "1px 6px" }}>{w.run_of_show.length} steps · {w.validation.length} checks · {w.remediation.length} fixes</span>
        </button>
      </div>

      {open && (
        <div style={{ marginTop: 12 }}>
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

          {w.validation.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div className="lbl" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".5px", color: "var(--text-faint)", marginBottom: 6 }}>
                Post-cutover validation ({w.validation.length}) · run after the cut, compare to baseline
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {w.validation.slice(0, 10).map((v, i) => (
                  <div key={i} style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 10, alignItems: "start" }}>
                    <SevChip sev={v.severity} />
                    <div>
                      <div style={{ fontSize: 12.5 }}><b>{v.check}</b></div>
                      <div className="cmd" style={{ marginTop: 4 }}>{v.command}</div>
                      <div className="dim" style={{ fontSize: 11, marginTop: 3 }}><b style={{ color: "var(--text-dim)" }}>expect:</b> {v.expect}</div>
                    </div>
                  </div>
                ))}
                {w.validation.length > 10 && <div className="faint" style={{ fontSize: 11 }}>+{w.validation.length - 10} more in the Validation-plan section.</div>}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function CutoverPlanner({ snapId }: { snapId: number }) {
  const { data, error, loading } = useAsync(() => api.cutover(snapId), [snapId]);
  const { data: meta } = useAsync(() => api.meta(), []);
  const canDownload = (meta?.deliverables || []).some((d) => d.key === "cutover" && d.available);
  if (loading) return <div className="panel"><Loading label="Building cutover plan…" /></div>;
  if (error) return <ErrorBox msg={error} />;
  const plan = data!;
  const s = plan.summary;
  if (!plan.waves.length) {
    return (
      <div className="panel">
        <h3>Cutover plan · run-of-show</h3>
        <div className="faint" style={{ fontSize: 13 }}>No migration waves were derived from this snapshot.</div>
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

      <div className="row-flex" style={{ gap: 26, padding: "14px 0", borderTop: "1px solid var(--border-faint)", borderBottom: "1px solid var(--border-faint)" }}>
        <Stat value={s.n_waves} label="waves" />
        <Stat value={s.n_devices} label="devices" />
        <Stat value={s.n_make_before_break} label="make-before-break" color="var(--ok)" />
        <Stat value={`${s.n_hard_cutover}`} label={`hard-cutover · ${s.hard_cutover_endpoints} ep`} color="var(--risk)" />
        <Stat value={s.est_window_label} label="est. total window" color={s.est_window_minutes ? "var(--risk)" : "var(--ok)"} />
        <span style={{ flex: 1 }} />
        <div className="row-flex" style={{ gap: 8 }}>
          {(["GO", "CONDITIONAL GO", "NO-GO"] as const).map((g) =>
            s.gates[g] ? <span key={g} className="chip gate" style={{ ["--gc" as any]: gateColor(g) }}><b>{s.gates[g]}</b> {g}</span> : null,
          )}
        </div>
      </div>

      <div className="faint" style={{ fontSize: 11, margin: "12px 0 10px" }}>
        Waves are sequenced <b>pilot-first</b> — the safest zero-outage wave proves the method before the higher-risk hard-cutover waves run. Window estimates are first-order planning anchors.
      </div>

      <div className="wave-list">
        {plan.waves.map((w) => <WaveCard key={w.group + w.order} w={w} />)}
      </div>
    </div>
  );
}
