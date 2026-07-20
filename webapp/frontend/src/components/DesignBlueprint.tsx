/* The CCDE-grounded target-state DESIGN BLUEPRINT, interactive. Renders the SAME design_blueprint the
   HLD/LLD DOCX and the explorer ✎ Design mode carry (GET /api/snapshots/{id}/design). The requirements
   overlay POSTs a register to /design and the SERVER (compute_design_blueprint) right-sizes every
   decision — the UI never re-derives design intent, so the dashboard and the script stay one source.

   Includes:
   - Requirements form: all 8 REQUIREMENTS_KEYS (tier/apps/convergence/growth/classification/constraints
     /address_space/vlan_zones) → unlocks the live IP addressing plan on the server side.
   - Design-driven NRFU panel: GET /design/nrfu → phased acceptance-test checklist from recommended
     decisions, each traceable to the CCDE principle and the specific devices to verify.
   - n_census_vlans disclosure when the IP plan is in needs-requirement state. */
import { useEffect, useState } from "react";
import { api, ArchitectureCoverage, DesignBlueprint, DesignDecision, DesignNrfu, DesignNrfuItem, DesignTargetState } from "../api";
import { ErrorBox, Loading, useAsync } from "./ui";

export const P_COLOR = (p: string) =>
  p === "Critical" ? "var(--crit)" : p === "High" ? "var(--risk)" : p === "Medium" ? "var(--watch)" : "var(--ok)";
export const scoreColor = (v: number | null) =>
  v == null ? "var(--text-faint)" : v <= 1 ? "var(--crit)" : v <= 2 ? "var(--risk)" : v <= 3 ? "var(--watch)" : "var(--ok)";
export const phaseColor = (ph: string) =>
  ph === "pre-cutover" ? "var(--crit)" : ph === "post-cutover-functional" ? "var(--risk)" : "var(--watch)";

function DecisionCard({ d, i = 0, isResolved }: { d: DesignDecision; i?: number; isResolved?: boolean }) {
  // Staged reveal (CausalFlow's .czreveal idiom): the card list rides .panel's existing mount
  // keyframe, offset per card and CAPPED so a long list never waits seconds. Inert under
  // reduced motion (the kill-switch strips the animation; a lone delay does nothing).
  return (
    <div className="panel" style={{ padding: 12, borderLeft: `3px solid ${P_COLOR(d.priority)}`, marginBottom: 8, animationDelay: `${Math.min(i, 8) * 50}ms` }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <b style={{ fontSize: 13 }}>{d.title}</b>
        {isResolved && (
          <span className="chip" style={{ color: "var(--accent)", borderColor: "var(--accent)", fontWeight: 700, fontSize: 9 }}
                title="This was an open design question until your requirements resolved it">
            ✓ resolved by requirements
          </span>
        )}
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
        {d.evidence.devices.length > 0 ? (
          <>
            <span className="mono">
              {d.evidence.devices.slice(0, 8).join(", ")}
              {d.evidence.devices.length > 8 ? ` +${d.evidence.devices.length - 8}` : ""}
            </span>
            {" · "}
          </>
        ) : (
          <>
            <span style={{ fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 8,
                           border: "1px solid var(--border)", color: "var(--text)", opacity: .7 }}>fleet / VLAN-wide</span>
            {" · "}
          </>
        )}
        {d.principle.citation}
      </div>
    </div>
  );
}

function NrfuItem({ item }: { item: DesignNrfuItem }) {
  const [open, setOpen] = useState(false);
  const col = phaseColor(item.phase);
  return (
    <div className="panel" style={{ padding: 10, borderLeft: `3px solid ${col}`, marginBottom: 6 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", cursor: "pointer" }}
           onClick={() => setOpen(!open)} role="button" aria-expanded={open} tabIndex={0}
           onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(!open); } }}>
        <span className="chip" style={{ fontSize: 9, color: col, borderColor: col, flexShrink: 0 }}>{item.phase}</span>
        <span className="chip" style={{ fontSize: 9, color: P_COLOR(item.priority), borderColor: P_COLOR(item.priority), flexShrink: 0 }}>{item.priority}</span>
        <b style={{ fontSize: 12, flex: 1 }}>{item.title}</b>
        <span className="faint" style={{ fontSize: 11 }}>{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        // .ros-reveal: entrance-only reveal-up: instant close is the house pattern (no exit animation).
        <div className="ros-reveal" style={{ marginTop: 8 }}>
          {item.setup && <div style={{ fontSize: 12, marginBottom: 4 }}><b>Setup:</b> <span className="dim">{item.setup}</span></div>}
          <div style={{ fontSize: 12, marginBottom: 4 }}><b>Verify:</b> <span className="dim">{item.description}</span></div>
          <div style={{ fontSize: 12, marginBottom: 4 }}><b>Pass criteria:</b> <span className="dim">{item.pass_criteria}</span></div>
          {item.devices.length > 0 && (
            <div className="faint" style={{ fontSize: 11, marginBottom: 4 }}>
              <b>Devices ({item.devices.length}):</b>{" "}
              <span className="mono">{item.devices.slice(0, 10).join(", ")}{item.devices.length > 10 ? ` +${item.devices.length - 10}` : ""}</span>
            </div>
          )}
          <div className="faint" style={{ fontSize: 10 }}>{item.principle_citation}</div>
        </div>
      )}
    </div>
  );
}

function NrfuPanel({ snapId, register }: { snapId: number; register: Record<string, unknown> | null }) {
  // Right-size the checklist server-side when a requirements register is applied, else the baseline —
  // never re-derive NRFU items or their phases in JS (one source of truth: the Python engine).
  const { data, error, loading } = useAsync(
    () => (register ? api.designNrfuOverlay(snapId, register) : api.designNrfu(snapId)),
    [snapId, register]
  );
  if (loading) return <Loading />;
  if (error) return <ErrorBox msg={error} />;
  const nrfu = data as DesignNrfu;
  const byPhase: Record<string, DesignNrfuItem[]> = {};
  for (const it of nrfu.items) {
    (byPhase[it.phase] = byPhase[it.phase] || []).push(it);
  }
  const phases = ["pre-cutover", "post-cutover-functional", "post-cutover-operational"] as const;
  const phaseLabel: Record<string, string> = {
    "pre-cutover": "Pre-cutover (before wave executes)",
    "post-cutover-functional": "Post-cutover functional (core acceptance)",
    "post-cutover-operational": "Post-cutover operational (baseline)",
  };
  return (
    <div>
      <div className="faint" style={{ fontSize: 11, marginBottom: 10 }}>{nrfu.note}</div>
      {phases.map((ph) =>
        (byPhase[ph] || []).length > 0 ? (
          <div key={ph} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: phaseColor(ph), marginBottom: 6 }}>
              {phaseLabel[ph]} · {(byPhase[ph] || []).length}
            </div>
            {(byPhase[ph] || []).map((it) => <NrfuItem key={it.decision_id} item={it} />)}
          </div>
        ) : null
      )}
    </div>
  );
}

function ArchitectureCoveragePanel({ snapId }: { snapId: number }) {
  // Architecture-coverage SSOT — computed server-side by the SAME engine function the explorer/CLI use
  // (never re-derived in JS). Which architecture classes were observed vs not, across both ingestion channels.
  const { data, error, loading } = useAsync(() => api.architectureCoverage(snapId), [snapId]);
  // Domain lenses (Phase-3 / D6) selected by the engine from the SAME coverage — a secondary, non-blocking
  // signal: the coverage grid renders even if this fetch is slow/fails (chips just don't show).
  const packs = useAsync(() => api.domainPacks(snapId), [snapId]);
  if (loading) return <Loading />;
  if (error) return <ErrorBox msg={error} />;
  const cov = data as ArchitectureCoverage;
  const s = cov.summary;
  const col = (st: string) => (st === "finding" ? "var(--crit)" : st === "clean" ? "var(--ok, #2e7d32)" : "var(--text-faint)");
  const ord: Record<string, number> = { finding: 0, clean: 1, "not-observed": 2 };
  const rows = [...cov.classes].sort((a, b) => (ord[a.status] - ord[b.status]) || a.label.localeCompare(b.label));
  return (
    <div>
      <div className="faint" style={{ fontSize: 11, marginBottom: 10 }}>
        Which architecture classes the engine assessed in this fleet, across both ingestion channels (SSH
        show-text + JSON controller-REST). <b>Not observed</b> means no evidence was captured — coverage-honest,
        not “healthy”. The same architecture_coverage map the engine publishes.
      </div>
      <div style={{ display: "flex", gap: 16, marginBottom: 10, fontSize: 12, flexWrap: "wrap" }}>
        <span><b>{s.n_observed}</b>/{s.n_classes} observed</span>
        <span style={{ color: "var(--crit)" }}><b>{s.n_with_findings}</b> findings</span>
        <span><b>{s.n_clean}</b> clean</span>
        <span className="faint"><b>{s.n_not_observed}</b> not observed</span>
        <span className="faint">· {s.by_channel.ssh} SSH · {s.by_channel.json} JSON</span>
      </div>
      {packs.data && (
        <div style={{ margin: "0 0 12px", padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6 }}>
          <div style={{ fontSize: 12, fontWeight: 700, marginBottom: packs.data.selected.length ? 6 : 0 }}>
            Domain lenses engaged{" "}
            <span className="faint" style={{ fontWeight: 400, fontSize: 11 }}>
              · evidence-selected review packs (D6) — a lens loads only where its architecture is observed
            </span>
          </div>
          {packs.data.selected.length ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {packs.data.selected.map((p) => (
                <span
                  key={p.pack}
                  title={`triggered by: ${p.triggered_by.join(", ")}${p.with_findings.length ? ` · findings: ${p.with_findings.join(", ")}` : ""}`}
                  style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, padding: "3px 9px", borderRadius: 14, color: "#fff", background: p.with_findings.length ? "var(--crit, #c62828)" : "var(--ok, #2e7d32)" }}
                >
                  <b>{p.pack.toUpperCase()}</b> {p.title}
                  {p.with_findings.length ? <span style={{ fontSize: 10, opacity: 0.9 }}>· {p.with_findings.length} finding(s)</span> : null}
                </span>
              ))}
            </div>
          ) : (
            <div className="faint" style={{ fontSize: 11 }}>{packs.data.note}</div>
          )}
        </div>
      )}
      {rows.map((c) => (
        <div key={c.key} style={{ display: "flex", gap: 8, alignItems: "center", padding: "3px 0", opacity: c.status === "not-observed" ? 0.55 : 1 }}>
          <span style={{ minWidth: 86, textAlign: "center", fontSize: 10, fontWeight: 700, color: "#fff", background: col(c.status), borderRadius: 4, padding: "1px 6px" }}>{c.status}</span>
          <span style={{ fontSize: 9, padding: "1px 5px", border: "1px solid var(--border)", borderRadius: 4 }}>{c.channel}</span>
          <span style={{ flex: 1, fontSize: 12 }}>{c.label}</span>
          <span className="faint" style={{ fontSize: 11 }}>
            {c.status === "finding" ? `${c.n_hosts} host(s) · ${c.findings.length} finding(s)`
              : c.status === "clean" ? `${c.n_hosts} host(s) · clean` : "not observed"}
          </span>
        </div>
      ))}
    </div>
  );
}

function TargetState({ ts }: { ts: DesignTargetState }) {
  const bom = ts.replacement_bom, ap = ts.addressing_plan, wp = ts.wave_plan, sp = ts.segmentation_plan, amg = ts.aci_move_groups;
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
            <div className="dim" style={{ fontSize: 12 }}>
              Needs <b>{ap.requirement_needed}</b>
              {ap.n_census_vlans != null ? (
                <> — {ap.n_census_vlans} census VLAN(s) total
                {ap.n_unsizable != null && ap.n_unsizable > 0 && (
                  <>, {ap.n_unsizable} querier-only / VLAN-1 with no auto-sized subnet</>
                )}
                {ap.observed_vlans != null && (
                  <>, {ap.observed_vlans} with observed access port or L3 SVI (sizeable).</>
                )}
                </>
              ) : ap.observed_vlans != null ? (
                <> ({ap.observed_vlans} VLAN(s) observed)</>
              ) : null}
              {". "}{ap.note}
              <div style={{ marginTop: 6, fontSize: 11, color: "var(--watch)" }}>
                Supply <b>address_space</b> (e.g. 10.0.0.0/16) in the requirements form above to generate the candidate IP plan.
                Optionally add <b>vlan_zones</b> (JSON: {"{"}zone: [vlan_ids]{"}"}") for zone-aware allocation with one summarisable block per zone.
              </div>
            </div>
          )}
        </>
      )}
      {sp && (
        <>
          <div style={{ fontSize: 13, fontWeight: 700, margin: "12px 0 6px" }}>Target segmentation</div>
          <div className="dim" style={{ fontSize: 12 }}>{sp.observed}</div>
          {sp.status === "candidate" && sp.target_zones && sp.target_zones.length > 0 && (
            <div style={{ marginTop: 4 }}>
              {sp.target_zones.map((z) => (
                <span key={z} style={{ fontSize: 11, fontWeight: 700, padding: "1px 6px", borderRadius: 8,
                                       border: "1px solid var(--border)", marginRight: 4 }}>{z}</span>
              ))}
            </div>
          )}
          <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>
            {sp.status === "needs-requirement"
              ? <>Needs <b>{sp.requirement_needed}</b> — {sp.target}</>
              : sp.target}
          </div>
          {sp.status === "needs-requirement" && (
            <div style={{ marginTop: 6, fontSize: 11, color: "var(--watch)" }}>
              Supply <b>data_classification</b> (e.g. PCI, corp) in the requirements form above to propose the VLAN-to-zone map.
            </div>
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
      {amg && amg.groups && amg.groups.length > 0 && (
        <>
          <div style={{ fontSize: 13, fontWeight: 700, margin: "12px 0 6px" }}>ACI move-groups · {amg.n_tenants}</div>
          <div className="faint" style={{ fontSize: 11, marginBottom: 4 }}>{amg.n_epgs} EPG(s) · {amg.n_segmentation_gaps} segmentation gap(s). {amg.note}</div>
          <table className="tbl"><thead><tr><th>Tenant</th><th className="num">EPGs</th><th className="num">VRFs</th><th className="num">BDs</th><th>Segmentation</th></tr></thead>
            <tbody>{amg.groups.slice(0, 40).map((g) => (
              <tr key={g.tenant}><td>{g.tenant}</td><td className="num">{g.n_epgs}</td><td className="num">{g.n_vrfs}</td><td className="num">{g.n_bds}</td>
                <td style={{ color: g.segmentation_gap ? "var(--crit)" : undefined }}>{g.segmentation_gap ? `⚠ unenforced: ${g.unenforced_vrfs.join(", ")}` : "enforced"}</td></tr>
            ))}</tbody></table>
        </>
      )}
    </div>
  );
}

type Tab = "blueprint" | "nrfu";

export default function DesignBlueprintPanel({ snapId }: { snapId: number }) {
  const { data, error, loading } = useAsync(() => api.design(snapId), [snapId]);
  const [over, setOver] = useState<DesignBlueprint | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab>("blueprint");
  // NRFU mounts on FIRST visit and then stays mounted (hidden, not unmounted, when the user
  // tabs away) — its fetched checklist survives tab switches instead of refetching every time.
  const [nrfuOpened, setNrfuOpened] = useState(false);
  // Requirements form — all 9 REQUIREMENTS_KEYS
  const [tier, setTier] = useState("");
  const [apps, setApps] = useState("");
  const [conv, setConv] = useState("");
  const [growth, setGrowth] = useState("");
  const [fabricMode, setFabricMode] = useState("");   // fabric_operating_model: nxos-evpn | aci
  const [dataClass, setDataClass] = useState("");
  const [budget, setBudget] = useState(false);
  const [addrSpace, setAddrSpace] = useState("");
  const [vlanZones, setVlanZones] = useState("");
  const [zonesErr, setZonesErr] = useState("");
  const [register, setRegister] = useState<Record<string, unknown> | null>(null);
  const [liveMsg, setLiveMsg] = useState("");   // assistive-tech announcements for the aria-live status region
  const [copied, setCopied] = useState(false);  // "Copy design brief" feedback

  // Reset the overlay + form when the snapshot changes — otherwise snapshot A's right-sized blueprint and
  // requirements leak onto snapshot B (the data re-fetches via useAsync, but `over`/`register`/fields do not).
  useEffect(() => {
    setOver(null); setRegister(null); setTab("blueprint"); setNrfuOpened(false);
    setTier(""); setApps(""); setConv(""); setGrowth("");
    setDataClass(""); setBudget(false); setAddrSpace(""); setVlanZones(""); setZonesErr(""); setFabricMode("");
    setLiveMsg("");   // drop any stale announcement when the snapshot changes
  }, [snapId]);

  if (loading) return <div className="panel"><h3>Design engineer · target-state blueprint</h3><Loading /></div>;
  if (error) return <div className="panel"><h3>Design engineer · target-state blueprint</h3><ErrorBox msg={error} /></div>;
  const bp = (over || data) as DesignBlueprint;
  const s = bp.summary;
  const rec = bp.decisions.filter((d) => d.status === "recommended");
  const needs = bp.decisions.filter((d) => d.status === "needs-requirement");
  // #17: which open design questions did the supplied requirements just RESOLVE? A pure client-side delta
  // between the two blueprints already in state (base `data` vs right-sized `over`) -- no API call, no recompute.
  const resolvedIds = new Set<string>();
  if (over) {
    const wasNeeds = new Set((data as DesignBlueprint).decisions
      .filter((d) => d.status === "needs-requirement").map((d) => d.id));
    for (const d of over.decisions) if (d.status === "recommended" && wasNeeds.has(d.id)) resolvedIds.add(d.id);
  }

  // #16: copy the CURRENTLY-DISPLAYED blueprint (right-sized `over` when present, else base) as a readable
  // text brief -- a quick handoff alongside the full DOCX. Pure client-side serialise of the in-state object.
  const copyBrief = () => {
    const L: string[] = ["DESIGN BRIEF — target-state blueprint", s.headline,
      `${s.n_recommended} recommended · ${s.n_needs_requirement} open question(s) · ${s.n_critical} critical`];
    if (register && Object.keys(register).length) {
      L.push("", "Requirements applied: " + Object.entries(register)
        .map(([k, v]) => `${k}=${Array.isArray(v) ? (v as unknown[]).join("/") : String(v)}`).join(", "));
    }
    L.push("", "RECOMMENDED DECISIONS");
    for (const d of rec) {
      L.push(`- [${d.priority}] ${d.title}`);
      if (d.driver) L.push(`    Why: ${d.driver}`);
      if (d.recommended_action) L.push(`    Target: ${d.recommended_action}`);
    }
    L.push("", "TRADE-OFF SCORECARD");
    for (const a of bp.tradeoff_scorecard) L.push(`- ${a.label}: ${a.score == null ? "n/a" : a.score + "/4"} · ${a.posture}`);
    if (bp.target_state?.dimensions?.length) {
      L.push("", "TARGET-STATE ARCHITECTURE");
      for (const dim of bp.target_state.dimensions) L.push(`- ${dim.area}: ${dim.current} → ${dim.target}`);
    }
    if (needs.length) {
      L.push("", "OPEN DESIGN QUESTIONS (need a requirement)");
      for (const d of needs) L.push(`- ${d.title} (needs ${d.requirements_needed.join(", ")})`);
    }
    const txt = L.join("\n");
    const done = () => { setCopied(true); setLiveMsg("Design brief copied to the clipboard."); window.setTimeout(() => setCopied(false), 1800); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done).catch(done);
    else done();
  };

  const applyReqs = async () => {
    setZonesErr("");
    const req: Record<string, unknown> = {};
    if (tier) req.availability_tier = tier;
    if (apps.trim()) req.critical_apps = apps.split(",").map((x) => x.trim()).filter(Boolean);
    if (conv.trim()) {
      const n = Number(conv);                       // keep a legitimate 0; fall back to raw only if non-numeric
      req.convergence_budget_ms = Number.isFinite(n) ? n : conv.trim();
    }
    if (growth.trim()) req.growth_horizon = growth.trim();
    if (fabricMode) req.fabric_operating_model = fabricMode;
    if (dataClass.trim()) req.data_classification = dataClass.split(",").map((x) => x.trim()).filter(Boolean);
    if (budget) req.constraints = ["budget-limited"];
    if (addrSpace.trim()) req.address_space = addrSpace.trim();
    if (vlanZones.trim()) {
      try {
        req.vlan_zones = JSON.parse(vlanZones.trim());
      } catch {
        setZonesErr("vlan_zones must be valid JSON, e.g. {\"PCI\": [10, 20], \"corp\": [30]}");
        return;
      }
    }
    setBusy(true);
    try {
      const nbp = await api.designOverlay(snapId, req);
      setOver(nbp);
      setRegister(req);                              // drives the NRFU panel to the right-sized checklist
      // Non-visual feedback: read the recomputed shape STRAIGHT off the server-returned blueprint (the engine
      // compute_design_blueprint stays the single source of truth — no client-side recount).
      const ns = nbp.summary;
      const ipPlan = nbp.target_state?.addressing_plan?.status === "candidate";
      const wasNeeds = new Set((data as DesignBlueprint).decisions
        .filter((d) => d.status === "needs-requirement").map((d) => d.id));
      const nResolved = nbp.decisions.filter((d) => d.status === "recommended" && wasNeeds.has(d.id)).length;
      setLiveMsg(
        `Requirements applied; the engine recomputed the target-state blueprint: ` +
        `${ns.n_recommended} recommended decision${ns.n_recommended === 1 ? "" : "s"}, ` +
        `${ns.n_needs_requirement} open question${ns.n_needs_requirement === 1 ? "" : "s"}, ` +
        `${ns.n_critical} critical.` +
        (nResolved ? ` ${nResolved} open question${nResolved === 1 ? "" : "s"} resolved by your requirements.` : "") +
        (ipPlan ? " A net-new IP addressing plan was generated." : "")
      );
    } catch {
      setLiveMsg("Could not apply requirements; the baseline blueprint is unchanged.");
    } finally {
      setBusy(false);
    }
  };
  const clearReqs = () => {
    setOver(null); setRegister(null); setTier(""); setApps(""); setConv(""); setGrowth("");
    setDataClass(""); setBudget(false); setAddrSpace(""); setVlanZones(""); setZonesErr(""); setFabricMode("");
    setLiveMsg("Requirements cleared; the baseline blueprint has been restored.");
  };
  const selectTab = (t: Tab, label: string) => {
    setTab(t);
    if (t === "nrfu") setNrfuOpened(true);
    setLiveMsg(`${label} tab selected.`);
  };

  return (
    <div className="panel" aria-busy={busy}>
      <h3>Design engineer · target-state blueprint</h3>
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{liveMsg}</div>
      <div className="dim" style={{ fontSize: 12, marginTop: 4 }}>{s.headline}</div>
      <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>
        {s.n_recommended} recommended · {s.n_needs_requirement} need a requirement · {s.n_critical} critical
        {" — "}the same CCDE-grounded design_blueprint behind the HLD/LLD DOCX and the explorer ✎ Design mode.
      </div>

      {/* Tab bar */}
      <div role="tablist" aria-label="Design blueprint views"
           style={{ display: "flex", gap: 4, marginTop: 12, borderBottom: "1px solid var(--border)" }}>
        {([["blueprint", "Design blueprint"], ["nrfu", `NRFU checklist`]] as [Tab, string][]).map(([t, label]) => (
          <button key={t} role="tab" id={`dbptab-${t}`} aria-controls={`dbppanel-${t}`} aria-selected={tab === t}
            onClick={() => selectTab(t, label)}
            style={{ background: tab === t ? "var(--accent)" : "transparent",
                     color: tab === t ? "#fff" : "var(--text)", border: "none",
                     borderRadius: "4px 4px 0 0", padding: "4px 12px", cursor: "pointer", fontSize: 12, fontWeight: tab === t ? 700 : 400 }}>
            {label}
          </button>
        ))}
      </div>

      {/* Both tabpanels stay MOUNTED and toggle via the `hidden` attribute (the correct ARIA
          tabpanel treatment): switching tabs no longer unmounts the other panel's subtree, so its
          fetched data — the coverage grid + domain packs here, the NRFU checklist below — survives
          the toggle instead of refetching with a spinner flash on every switch. hidden→shown also
          restarts .tabfade, which is what gives the switch its fade (no key-remount involved). */}
      <div role="tabpanel" id="dbppanel-blueprint" aria-labelledby="dbptab-blueprint"
           className="tabfade" hidden={tab !== "blueprint"}>
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

          {/* Requirements form — all 8 REQUIREMENTS_KEYS */}
          <div className="panel" style={{ padding: 12, marginTop: 12, background: "var(--surface-2)" }}>
            <div style={{ fontSize: 13, fontWeight: 700 }}>Right-size to requirements (the WHY)</div>
            <div className="faint" style={{ fontSize: 11, marginTop: 2 }}>{bp.requirements_model.note}</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10, alignItems: "flex-start" }}>
              <select value={tier} onChange={(e) => setTier(e.target.value)} aria-label="availability tier">
                <option value="">availability tier…</option>
                <option value="gold">gold</option>
                <option value="silver">silver</option>
                <option value="bronze">bronze</option>
              </select>
              <input placeholder="critical apps (voice,video)" value={apps} onChange={(e) => setApps(e.target.value)} />
              <input placeholder="convergence ms" value={conv} onChange={(e) => setConv(e.target.value)} style={{ width: 120 }} />
              <input placeholder="growth horizon" value={growth} onChange={(e) => setGrowth(e.target.value)} style={{ width: 140 }} />
              <select value={fabricMode} onChange={(e) => setFabricMode(e.target.value)} aria-label="fabric operating model"
                      title="DC fabric operating model: standalone NX-OS VXLAN-EVPN (default) vs Cisco ACI policy fabric">
                <option value="">fabric model…</option>
                <option value="nxos-evpn">NX-OS VXLAN-EVPN</option>
                <option value="aci">Cisco ACI</option>
              </select>
              <input placeholder="data classification (PCI,corp)" value={dataClass} onChange={(e) => setDataClass(e.target.value)} style={{ width: 180 }} aria-label="data classification" />
              <label style={{ fontSize: 12, alignSelf: "center" }}>
                <input type="checkbox" checked={budget} onChange={(e) => setBudget(e.target.checked)} /> budget-limited
              </label>
            </div>
            {/* IP plan requirements — unlock the addressing_plan */}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8, alignItems: "flex-start" }}>
              <input placeholder="address space (e.g. 10.0.0.0/16)" value={addrSpace}
                     onChange={(e) => setAddrSpace(e.target.value)} style={{ width: 200 }}
                     aria-label="target address space" title="Supply to generate the net-new IP addressing plan" />
              <div style={{ display: "flex", flexDirection: "column", gap: 2, flex: 1 }}>
                <textarea placeholder={'vlan_zones JSON (optional) — e.g. {"PCI":[10,20],"corp":[30]} for zone-aware allocation'}
                          value={vlanZones} onChange={(e) => setVlanZones(e.target.value)}
                          rows={2} style={{ width: "100%", fontFamily: "monospace", fontSize: 11, resize: "vertical" }}
                          aria-label="VLAN zones" />
                {zonesErr && <div style={{ color: "var(--crit)", fontSize: 11 }}>{zonesErr}</div>}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
              <button onClick={applyReqs} disabled={busy}>{busy ? "…" : "Right-size"}</button>
              {over && <button onClick={clearReqs}>Reset</button>}
              {over && (
                <span className="faint" style={{ fontSize: 11 }}>
                  Decisions re-ranked by effective priority for the supplied requirements (computed server-side).
                </span>
              )}
            </div>
          </div>

          <div style={{ marginTop: 14 }}>
            {resolvedIds.size > 0 && (
              <div className="ros-reveal" style={{ marginBottom: 10, padding: "8px 12px", borderRadius: 6,
                            background: "var(--surface-2)", border: "1px solid var(--accent)", fontSize: 12 }}>
                <b>✓ {resolvedIds.size} open design question{resolvedIds.size === 1 ? "" : "s"} resolved by your requirements</b>
                {" — "}
                <span className="dim">{rec.filter((d) => resolvedIds.has(d.id)).map((d) => d.title).join("; ")}</span>
              </div>
            )}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>Target-state design decisions · {rec.length}</div>
              <span style={{ flex: 1 }} />
              <button onClick={copyBrief} style={{ fontSize: 11 }}
                      title="Copy the displayed blueprint (decisions, scorecard, target-state, requirements) to the clipboard">
                {copied ? "✓ Copied" : "Copy design brief"}
              </button>
            </div>
            {/* key = overlay identity so Right-size/Reset REMOUNTS the list (each card replays its .panel
                entrance + capped stagger) instead of patching re-ranked cards in place — cards keep the
                same key={d.id} but the server re-ranks them, so an in-place patch teleports cards with no
                cue. Depends ONLY on `over`, never on `tab`, so a tab switch never remounts this. */}
            <div key={over ? "right-sized" : "baseline"}>
              {rec.length
                ? rec.map((d, i) => <DecisionCard key={d.id} d={d} i={i} isResolved={resolvedIds.has(d.id)} />)
                : <div className="dim" style={{ fontSize: 13 }}>No evidence-grounded design decisions for this snapshot.</div>}
            </div>
          </div>

          {bp.target_state && <TargetState ts={bp.target_state} />}

          {needs.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>Open design questions · {needs.length}</div>
              <div className="faint" style={{ fontSize: 11, marginBottom: 6 }}>
                Design top-down from the WHY: these depend on requirements the assessment cannot observe — the
                engine surfaces the question, it never assumes the answer. Supply the requirement above to resolve.
              </div>
              {needs.map((d) => (
                <div key={d.id} style={{ fontSize: 12, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
                  <b>{d.title}</b> <span className="faint">— needs {d.requirements_needed.join(", ")}</span>
                </div>
              ))}
            </div>
          )}

          <div style={{ fontSize: 13, fontWeight: 700, margin: "18px 0 6px" }}>Architecture coverage <span className="faint" style={{ fontWeight: 400, fontSize: 11 }}>· universal-coverage map, both ingestion channels</span></div>
          <ArchitectureCoveragePanel snapId={snapId} />

          <div className="faint" style={{ fontSize: 11, marginTop: 12 }}>{bp.coverage.caveat}</div>
        </div>

      {/* Lazy on FIRST visit (the latch), then kept mounted-but-hidden like the blueprint panel —
          the checklist keeps loading/updating (register changes refire its useAsync) while hidden,
          so returning to this tab is instant. */}
      {nrfuOpened && (
        <div role="tabpanel" id="dbppanel-nrfu" aria-labelledby="dbptab-nrfu"
             className="tabfade" hidden={tab !== "nrfu"} style={{ marginTop: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>Design-driven NRFU/ATP checklist</div>
          <div className="faint" style={{ fontSize: 11, marginBottom: 10 }}>
            One acceptance-test item per recommended design decision, phased across pre-cutover →
            post-cutover-functional → post-cutover-operational. Each item is traceable to the CCDE principle
            and the specific devices to verify. Independent of the design authors (proposer ≠ verifier).
          </div>
          <NrfuPanel snapId={snapId} register={register} />
        </div>
      )}
    </div>
  );
}
