/* The CCDE-grounded target-state DESIGN BLUEPRINT, interactive. Renders the SAME design_blueprint the
   HLD/LLD DOCX and the explorer ✎ Design mode carry (GET /api/snapshots/{id}/design). The requirements
   overlay POSTs a register to /design and the SERVER (compute_design_blueprint) right-sizes every
   decision — the UI never re-derives design intent, so the dashboard and the script stay one source. */
import { useState } from "react";
import { api, DesignBlueprint, DesignDecision, DesignTargetState } from "../api";
import { ErrorBox, Loading, useAsync } from "./ui";

const P_COLOR = (p: string) =>
  p === "Critical" ? "var(--crit)" : p === "High" ? "var(--risk)" : p === "Medium" ? "var(--watch)" : "var(--ok)";
const scoreColor = (v: number | null) =>
  v == null ? "var(--text-faint)" : v <= 1 ? "var(--crit)" : v <= 2 ? "var(--risk)" : v <= 3 ? "var(--watch)" : "var(--ok)";

function DecisionCard({ d }: { d: DesignDecision }) {
  return (
    <div className="panel" style={{ padding: 12, borderLeft: `3px solid ${P_COLOR(d.priority)}`, marginBottom: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <b style={{ fontSize: 13 }}>{d.title}</b>
        <span style={{ flex: 1 }} />
        {d.effective_priority != null && (
          <span className="faint mono" style={{ fontSize: 11 }}>weight {d.effective_priority}</span>
        )}
        <span className="chip" style={{ color: P_COLOR(d.priority), borderColor: P_COLOR(d.priority), fontWeight: 700, fontSize: 10 }}>
          {d.priority}
        </span>
      </div>
      <div className="dim" style={{ fontSize: 12, marginTop: 6 }}>{d.evidence.summary}</div>
      <div style={{ fontSize: 12, marginTop: 6 }}><b>Why:</b> <span className="dim">{d.driver}</span></div>
      <div style={{ fontSize: 12, marginTop: 4 }}><b>Target pattern:</b> <span className="dim">{d.recommended_action}</span></div>
      {d.alternatives && <div style={{ fontSize: 12, marginTop: 4 }}><b>Alternatives:</b> <span className="dim">{d.alternatives}</span></div>}
      <div style={{ fontSize: 12, marginTop: 4 }}><b>Trade-offs:</b> <span className="dim">{d.tradeoffs}</span></div>
      <div style={{ marginTop: 6 }}>
        {d.axes.map((a) => (
          <span key={a} className="chip" style={{ fontSize: 10, marginRight: 4 }}>{a}</span>
        ))}
      </div>
      <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>
        {d.evidence.devices.length > 0 && (
          <>
            <span className="mono">
              {d.evidence.devices.slice(0, 8).join(", ")}
              {d.evidence.devices.length > 8 ? ` +${d.evidence.devices.length - 8}` : ""}
            </span>
            {" · "}
          </>
        )}
        {d.principle.citation}
      </div>
    </div>
  );
}

function TargetState({ ts }: { ts: DesignTargetState }) {
  const bom = ts.replacement_bom, ap = ts.addressing_plan, wp = ts.wave_plan;
  return (
    <div style={{ marginTop: 14 }}>
      {ts.dimensions && ts.dimensions.length > 0 && (
        <>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>Proposed target-state architecture · {ts.dimensions.length}</div>
          {ts.dimensions.map((d) => {
            const col = d.requirement_needed ? "var(--watch)" : d.confidence === "Recommended" ? "var(--risk)" : "var(--ok)";
            return (
              <div key={d.area} className="panel" style={{ padding: 10, borderLeft: `3px solid ${col}`, marginBottom: 8 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <b style={{ fontSize: 13 }}>{d.area}</b><span style={{ flex: 1 }} />
                  <span className="chip" style={{ fontSize: 10, color: col, borderColor: col }}>{d.requirement_needed ? `needs ${d.requirement_needed}` : d.confidence}</span>
                </div>
                <div className="dim" style={{ fontSize: 12, marginTop: 4 }}><b>Current:</b> {d.current}</div>
                <div style={{ fontSize: 12, marginTop: 4 }}><b>Target:</b> <span className="dim">{d.target}</span></div>
                <div style={{ fontSize: 12, marginTop: 4 }}><b>Why:</b> <span className="dim">{d.rationale}</span></div>
              </div>
            );
          })}
        </>
      )}
      {bom && (bom.n_replace > 0 || bom.n_refresh > 0) && (
        <>
          <div style={{ fontSize: 13, fontWeight: 700, margin: "12px 0 6px" }}>Replacement BoM · {bom.n_replace} replace / {bom.n_refresh} refresh</div>
          <table className="tbl"><thead><tr><th>Current model</th><th>Disposition</th><th className="num">Qty</th></tr></thead>
            <tbody>
              {bom.replace_now.map(([m, q]) => <tr key={"r" + m}><td className="mono">{m}</td><td style={{ color: "var(--crit)" }}>Replace</td><td className="num">{q}</td></tr>)}
              {bom.refresh_soon.map(([m, q]) => <tr key={"f" + m}><td className="mono">{m}</td><td style={{ color: "var(--watch)" }}>Refresh</td><td className="num">{q}</td></tr>)}
            </tbody></table>
          <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>{bom.note}</div>
        </>
      )}
      {ap && (
        <>
          <div style={{ fontSize: 13, fontWeight: 700, margin: "12px 0 6px" }}>Net-new IP plan</div>
          {ap.status === "candidate" && ap.subnets ? (
            <>
              {ap.zones && ap.zones.length > 0 && (
                <table className="tbl"><thead><tr><th>Zone</th><th>Summary prefix</th><th className="num">VLANs</th></tr></thead>
                  <tbody>{ap.zones.map((z) => <tr key={z.zone}><td>{z.zone}</td><td className="mono">{z.summary}</td><td className="num">{z.n_vlans}</td></tr>)}</tbody></table>
              )}
              <table className="tbl" style={{ marginTop: 6 }}><thead><tr><th className="num">VLAN</th><th className="num">Hosts</th><th>Subnet</th></tr></thead>
                <tbody>{ap.subnets.slice(0, 40).map((sn) => <tr key={sn.vlan}><td className="num">{sn.vlan}</td><td className="num">{sn.hosts}</td><td className="mono">{sn.subnet}{sn.note ? ` · ${sn.note}` : ""}</td></tr>)}</tbody></table>
              <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>{ap.note}</div>
            </>
          ) : (
            <div className="dim" style={{ fontSize: 12 }}>Needs <b>{ap.requirement_needed}</b>{ap.observed_vlans != null ? ` (${ap.observed_vlans} VLAN(s) observed)` : ""}. {ap.note}</div>
          )}
        </>
      )}
      {wp && wp.waves && wp.waves.length > 0 && (
        <>
          <div style={{ fontSize: 13, fontWeight: 700, margin: "12px 0 6px" }}>Migration waves · {wp.n_waves}</div>
          <div className="faint" style={{ fontSize: 11, marginBottom: 4 }}>{wp.n_move_groups} move-group(s), largest {wp.largest_group} · cap {wp.wave_cap}. {wp.note}</div>
          <table className="tbl"><thead><tr><th className="num">Wave</th><th>Kind</th><th className="num">Switches</th></tr></thead>
            <tbody>{wp.waves.slice(0, 40).map((w) => <tr key={w.wave}><td className="num">{w.wave}</td><td>{w.kind}</td><td className="num">{w.n_switches}</td></tr>)}</tbody></table>
        </>
      )}
    </div>
  );
}

export default function DesignBlueprintPanel({ snapId }: { snapId: number }) {
  const { data, error, loading } = useAsync(() => api.design(snapId), [snapId]);
  const [over, setOver] = useState<DesignBlueprint | null>(null);
  const [busy, setBusy] = useState(false);
  const [tier, setTier] = useState("");
  const [apps, setApps] = useState("");
  const [conv, setConv] = useState("");
  const [growth, setGrowth] = useState("");
  const [dataClass, setDataClass] = useState("");
  const [budget, setBudget] = useState(false);

  if (loading) return <div className="panel"><h3>Design engineer · target-state blueprint</h3><Loading /></div>;
  if (error) return <div className="panel"><h3>Design engineer · target-state blueprint</h3><ErrorBox msg={error} /></div>;
  const bp = (over || data) as DesignBlueprint;
  const s = bp.summary;
  const rec = bp.decisions.filter((d) => d.status === "recommended");
  const needs = bp.decisions.filter((d) => d.status === "needs-requirement");

  const applyReqs = async () => {
    const req: Record<string, unknown> = {};
    if (tier) req.availability_tier = tier;
    if (apps.trim()) req.critical_apps = apps.split(",").map((x) => x.trim()).filter(Boolean);
    if (conv.trim()) req.convergence_budget_ms = Number(conv) || conv;
    if (growth.trim()) req.growth_horizon = growth.trim();
    if (dataClass.trim()) req.data_classification = dataClass.split(",").map((x) => x.trim()).filter(Boolean);
    if (budget) req.constraints = ["budget-limited"];
    setBusy(true);
    try {
      setOver(await api.designOverlay(snapId, req));
    } catch {
      /* keep the base blueprint on error */
    } finally {
      setBusy(false);
    }
  };
  const clearReqs = () => {
    setOver(null); setTier(""); setApps(""); setConv(""); setGrowth(""); setDataClass(""); setBudget(false);
  };

  return (
    <div className="panel">
      <h3>Design engineer · target-state blueprint</h3>
      <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{s.headline}</div>
      <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>
        {s.n_recommended} recommended · {s.n_needs_requirement} need a requirement · {s.n_critical} critical
        {" — "}the same CCDE-grounded design_blueprint behind the HLD/LLD DOCX and the explorer ✎ Design mode.
      </div>

      <table className="tbl" style={{ marginTop: 12 }}>
        <thead><tr><th>Trade-off axis</th><th className="num">Score</th><th>Posture</th></tr></thead>
        <tbody>
          {bp.tradeoff_scorecard.map((a) => (
            <tr key={a.axis}>
              <td><b>{a.label}</b></td>
              <td className="num" style={{ color: scoreColor(a.score), fontWeight: 700 }}>{a.score == null ? "—" : `${a.score}/4`}</td>
              <td className="dim">{a.posture}{a.target_weight && a.target_weight !== 1 ? ` · ×${a.target_weight}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="panel" style={{ padding: 12, marginTop: 12, background: "var(--surface-2)" }}>
        <div style={{ fontSize: 13, fontWeight: 700 }}>Right-size to requirements (the WHY)</div>
        <div className="faint" style={{ fontSize: 11, marginTop: 2 }}>{bp.requirements_model.note}</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10, alignItems: "center" }}>
          <select value={tier} onChange={(e) => setTier(e.target.value)} aria-label="availability tier">
            <option value="">availability tier…</option>
            <option value="gold">gold</option>
            <option value="silver">silver</option>
            <option value="bronze">bronze</option>
          </select>
          <input placeholder="critical apps (voice,video)" value={apps} onChange={(e) => setApps(e.target.value)} />
          <input placeholder="convergence ms" value={conv} onChange={(e) => setConv(e.target.value)} style={{ width: 120 }} />
          <input placeholder="growth horizon" value={growth} onChange={(e) => setGrowth(e.target.value)} style={{ width: 140 }} />
          <input placeholder="data classification (PCI,corp)" value={dataClass} onChange={(e) => setDataClass(e.target.value)} style={{ width: 180 }} aria-label="data classification" />
          <label style={{ fontSize: 12 }}>
            <input type="checkbox" checked={budget} onChange={(e) => setBudget(e.target.checked)} /> budget-limited
          </label>
          <button onClick={applyReqs} disabled={busy}>{busy ? "…" : "Right-size"}</button>
          {over && <button onClick={clearReqs}>Reset</button>}
        </div>
        {over && (
          <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
            Decisions re-ranked by effective priority for the supplied requirements (computed server-side).
          </div>
        )}
      </div>

      <div style={{ marginTop: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>Target-state design decisions · {rec.length}</div>
        {rec.length
          ? rec.map((d) => <DecisionCard key={d.id} d={d} />)
          : <div className="dim" style={{ fontSize: 13 }}>No evidence-grounded design decisions for this snapshot.</div>}
      </div>

      {bp.target_state && <TargetState ts={bp.target_state} />}

      {needs.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>Open design questions · {needs.length}</div>
          <div className="faint" style={{ fontSize: 11, marginBottom: 6 }}>
            Design top-down from the WHY: these depend on requirements the assessment cannot observe — the
            engine surfaces the question, it never assumes the answer.
          </div>
          {needs.map((d) => (
            <div key={d.id} style={{ fontSize: 12, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <b>{d.title}</b> <span className="faint">— needs {d.requirements_needed.join(", ")}</span>
            </div>
          ))}
        </div>
      )}

      <div className="faint" style={{ fontSize: 11, marginTop: 12 }}>{bp.coverage.caveat}</div>
    </div>
  );
}
