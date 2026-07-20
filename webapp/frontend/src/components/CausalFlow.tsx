/* CAUSAL FLOW — every finding family as one trigger -> mechanism -> impact -> mitigation story, interactive.
   Renders the SAME unified model the explorer's Causal Flow mode shows (GET /api/snapshots/{id}/causal_flows
   -> engine compute_causal_flows). The server computes the flows; the UI never re-derives causal intent, so
   the dashboard and the explorer cannot disagree (proven: identical counts for any given snapshot).

   Visual (research-grounded): a left->right four-stage chain for a simple cause->effect; a BOWTIE for a
   multi-cause cross-layer compound (causes converge on a centre top-event, ⊘ = no preventive control today,
   ✓ FIX = the mitigation to add). Connector width ∝ blast magnitude (Sankey); severity = colour + shape +
   label (WCAG redundant). All motion is gated behind prefers-reduced-motion (see styles.css). */
import { useEffect, useState, type ReactNode } from "react";
import { api, CausalFlowItem, CausalFlows, sevColor } from "../api";
import { ErrorBox, Loading, useAsync } from "./ui";

const STAGES = [
  { key: "trigger", label: "Trigger", tok: "crit" },
  { key: "mechanism", label: "Mechanism", tok: "risk" },
  { key: "impact", label: "Impact", tok: "watch" },
  { key: "mitigation", label: "Mitigation", tok: "ok" },
] as const;

type Sev = "Critical" | "High" | "Medium" | "Low" | "Info";
const SEV_ORDER: Sev[] = ["Critical", "High", "Medium", "Low", "Info"];
export function czSev(s: string): Sev {
  const t = (s || "").toLowerCase();
  if (t.includes("crit")) return "Critical";
  if (t === "high" || t.includes("warn") || t.includes("error")) return "High";
  if (t.includes("med")) return "Medium";
  if (t.includes("low")) return "Low";
  return (SEV_ORDER as string[]).includes(s) ? (s as Sev) : "Info";
}
// connector stroke-width ∝ blast magnitude (Sankey: a heavier flow reaches more endpoints)
export function czWidth(b: number) { return Math.round((2.6 + Math.min(8.6, Math.log2(1 + (b || 0)) * 1.18)) * 10) / 10; }
// greedy word-wrap into <=maxLines lines of <=maxChars (ellipsis the last if truncated)
export function wrap(s: string, maxChars: number, maxLines: number): string[] {
  const words = String(s || "").split(/\s+/).filter(Boolean), out: string[] = [];
  let cur = "";
  for (const w of words) {
    if (!cur) { cur = w; continue; }
    if ((cur + " " + w).length <= maxChars) cur += " " + w;
    else { out.push(cur); cur = w; if (out.length === maxLines - 1) break; }
  }
  if (cur && out.length < maxLines) out.push(cur);
  const consumed = out.join(" ").split(/\s+/).filter(Boolean).length;
  if (consumed < words.length && out.length) out[out.length - 1] = out[out.length - 1].replace(/.$/, "…");
  return out.length ? out : ["—"];
}

/* severity glyph: shape is the redundant, colour-independent channel (WCAG 1.4.1) */
function SevShape({ sev, s = 12 }: { sev: string; s?: number }) {
  const c = sevColor(sev), cv = czSev(sev);
  if (cv === "Critical" || cv === "High") return <path d={`M0 ${s} L${s / 2} 0 L${s} ${s} Z`} fill={c} />;
  if (cv === "Medium") return <path d={`M${s / 2} 0 L${s} ${s / 2} L${s / 2} ${s} L0 ${s / 2} Z`} fill={c} />;
  if (cv === "Low") return <rect width={s} height={s} rx={2} fill={c} />;
  return <circle cx={s / 2} cy={s / 2} r={s / 2} fill={c} />;
}
function SevBadge({ sev, s = 11 }: { sev: string; s?: number }) {
  return <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} style={{ verticalAlign: -1 }} aria-hidden>
    <SevShape sev={sev} s={s} /></svg>;
}
const Arrow = () => (
  <defs><marker id="czArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="var(--border-strong)" /></marker></defs>
);
const svgStyle = { width: "100%", display: "block", borderRadius: 9, background: "var(--surface-2)", border: "1px solid var(--border)" } as const;
const stageLabelStyle = { font: "700 8.5px var(--sans)", letterSpacing: "1.1px", textTransform: "uppercase" } as const;
const nodeTextStyle = { font: "550 10px var(--sans)" } as const;

/* Linear chain: four stage boxes + magnitude-scaled animated connectors + severity ribbon + blast tag. */
function LinearFlow({ f }: { f: CausalFlowItem }) {
  const W = 470, padX = 12, n = 4, boxW = 99, gap = (W - 2 * padX - n * boxW) / (n - 1);
  const boxH = 66, top = 46, H = top + boxH + 34, cy = top + boxH / 2;
  const xOf = (i: number) => padX + i * (boxW + gap);
  const sc = sevColor(f.severity), fw = czWidth(f.blast);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" style={svgStyle}
      aria-label={`${czSev(f.severity)} ${f.family_label}: ${f.trigger} leads to ${f.impact}; mitigated by ${f.mitigation}`}>
      <Arrow />
      <g className="czreveal" style={{ animationDelay: ".02s" }}>
        <g transform={`translate(${padX},11)`}><SevShape sev={f.severity} s={13} /></g>
        <text x={padX + 20} y={21} style={{ font: "800 10px var(--sans)", letterSpacing: ".5px" }} fill={sc}>
          {czSev(f.severity).toUpperCase()} <tspan fill="var(--text-dim)" style={{ fontWeight: 600 }}>· {f.family_label}</tspan>
        </text>
        {f.confidence ? <text x={W - padX} y={21} textAnchor="end" style={{ font: "600 10px var(--sans)" }} fill="var(--text-dim)">{f.confidence}</text> : null}
      </g>
      {[0, 1, 2].map((i) => { const x1 = xOf(i) + boxW, x2 = xOf(i + 1); return (
        <g key={"c" + i}>
          <line className="czbase-line" x1={x1} y1={cy} x2={x2} y2={cy} markerEnd="url(#czArrow)" />
          <line className="czflow-line" x1={x1} y1={cy} x2={x2} y2={cy} style={{ strokeWidth: fw }} />
        </g>); })}
      {STAGES.map((st, i) => {
        const x = xOf(i), lines = wrap(String(f[st.key] ?? "—"), 16, 4), ty = cy - ((lines.length - 1) * 11) / 2;
        return (
          <g key={st.key} className="czreveal" style={{ animationDelay: `${(0.1 + i * 0.1).toFixed(2)}s` }}>
            <rect x={x} y={top} width={boxW} height={boxH} rx={9} fill={`var(--${st.tok}-soft)`} stroke={`var(--${st.tok})`} strokeWidth={1.5} />
            <text x={x + boxW / 2} y={top - 7} textAnchor="middle" style={stageLabelStyle} fill={`var(--${st.tok})`}>{st.label}</text>
            <text x={x + boxW / 2} y={ty} textAnchor="middle" style={nodeTextStyle} fill="var(--text)">
              {lines.map((ln, k) => <tspan key={k} x={x + boxW / 2} dy={k === 0 ? 0 : 11}>{ln}</tspan>)}
            </text>
            {st.key === "impact" && f.blast > 0
              ? <text x={x + boxW / 2} y={top + boxH + 16} textAnchor="middle" fill={sc} style={{ font: "800 10px var(--sans)" }}>▣ {f.blast} {f.blast_unit}</text>
              : null}
          </g>);
      })}
    </svg>
  );
}

/* Bowtie: N causes (each with NO preventive control today, ⊘) converge on a centre top-event, then a single
   propagation edge reaches the impact, with the mitigation drawn as a barrier (✓ FIX) on the recovery edge. */
function BowtieFlow({ f }: { f: CausalFlowItem }) {
  const threats = (f.threats || []).slice(0, 3), tn = Math.max(1, threats.length);
  const W = 470, padX = 12, thX = padX, thW = 140, thH = 42, tgap = 14;
  const evX = 190, evW = 112, evH = 74, conX = W - padX - 104, conW = 104, conH = 74;
  const H = Math.max(182, 90 + tn * (thH + tgap)), cy = H / 2, evY = cy - evH / 2, conY = cy - conH / 2;
  const blockH = tn * thH + (tn - 1) * tgap, ty0 = cy - blockH / 2;
  const sc = sevColor(f.severity), fw = czWidth(f.blast);
  const evLines = wrap(f.top_event || f.title, 19, 4), coLines = wrap(f.impact || f.consequence || "impact", 17, 4);
  const bx = (evX + evW + conX) / 2 - 24;
  return (
    <svg viewBox={`0 0 ${W} ${H + 10}`} role="img" style={svgStyle}
      aria-label={`Bowtie for ${f.title}: ${threats.length} causes with no preventive control today converge on ${f.top_event || f.title}, causing ${f.impact}; mitigated by ${f.mitigation}`}>
      <Arrow />
      <g className="czreveal" style={{ animationDelay: ".02s" }}>
        <g transform={`translate(${padX},8)`}><SevShape sev={f.severity} s={12} /></g>
        <text x={padX + 18} y={18} style={{ font: "800 10px var(--sans)" }} fill={sc}>
          {czSev(f.severity).toUpperCase()} <tspan fill="var(--text-dim)" style={{ fontWeight: 600 }}>· {f.family_label} · bowtie</tspan></text>
      </g>
      {threats.map((t, i) => {
        const yy = ty0 + i * (thH + tgap), tcy = yy + thH / 2, sx = thX + thW, ex = evX;
        const d = `M${sx} ${tcy} C ${sx + 30} ${tcy}, ${ex - 30} ${cy}, ${ex} ${cy}`;
        const lines = wrap(String(t), 26, 3), tyt = tcy - ((lines.length - 1) * 10) / 2 + 3;
        const px = (sx + ex) / 2, py = (tcy + cy) / 2;
        return (
          <g key={"t" + i}>
            <path className="czbase-line" d={d} markerEnd="url(#czArrow)" />
            <path className="czflow-line" d={d} style={{ strokeWidth: Math.max(2, fw - 1) }} />
            <g className="czreveal" style={{ animationDelay: `${(0.08 + i * 0.06).toFixed(2)}s` }}>
              <rect x={thX} y={yy} width={thW} height={thH} rx={7} fill="var(--crit-soft)" stroke="var(--crit)" strokeWidth={1.5} />
              <text x={thX + thW / 2} y={tyt} textAnchor="middle" style={{ font: "9px var(--sans)" }} fill="var(--text)">
                {lines.map((ln, k) => <tspan key={k} x={thX + thW / 2} dy={k === 0 ? 0 : 10}>{ln}</tspan>)}</text>
            </g>
            <g><title>No preventive control here today — this is why the cause reaches the top event</title>
              <circle cx={px} cy={py} r={7} fill="var(--surface)" stroke="var(--crit)" strokeWidth={1.4} strokeDasharray="2.5 2" opacity={0.9} />
              <line x1={px - 5} y1={py - 5} x2={px + 5} y2={py + 5} stroke="var(--crit)" strokeWidth={1.4} opacity={0.9} /></g>
          </g>);
      })}
      <line className="czbase-line" x1={evX + evW} y1={cy} x2={conX} y2={cy} markerEnd="url(#czArrow)" />
      <line className="czflow-line" x1={evX + evW} y1={cy} x2={conX} y2={cy} style={{ strokeWidth: fw }} />
      <g className="czreveal" style={{ animationDelay: ".46s" }}><title>The mitigation to add — the control that breaks the chain</title>
        <rect x={bx} y={cy - 13} width={48} height={26} rx={6} fill="var(--ok-soft)" stroke="var(--ok)" strokeWidth={1.5} />
        <text x={bx + 24} y={cy + 3} textAnchor="middle" style={{ font: "800 7px var(--sans)", letterSpacing: ".4px" }} fill="var(--ok)">✓ FIX</text></g>
      <g className="czreveal" style={{ animationDelay: ".28s" }}>
        <rect x={evX} y={evY} width={evW} height={evH} rx={10} fill="var(--watch-soft)" stroke="var(--watch)" strokeWidth={2.2} />
        <text x={evX + evW / 2} y={evY - 7} textAnchor="middle" style={stageLabelStyle} fill="var(--watch)">Top event</text>
        <text x={evX + evW / 2} y={cy - ((evLines.length - 1) * 11) / 2} textAnchor="middle" style={nodeTextStyle} fill="var(--text)">
          {evLines.map((ln, k) => <tspan key={k} x={evX + evW / 2} dy={k === 0 ? 0 : 11}>{ln}</tspan>)}</text></g>
      <g className="czreveal" style={{ animationDelay: ".34s" }}>
        <rect x={conX} y={conY} width={conW} height={conH} rx={9} fill="var(--watch-soft)" stroke="var(--watch)" strokeWidth={1.5} />
        <text x={conX + conW / 2} y={conY - 7} textAnchor="middle" style={stageLabelStyle} fill="var(--watch)">Impact</text>
        <text x={conX + conW / 2} y={cy - ((coLines.length - 1) * 11) / 2} textAnchor="middle" style={nodeTextStyle} fill="var(--text)">
          {coLines.map((ln, k) => <tspan key={k} x={conX + conW / 2} dy={k === 0 ? 0 : 11}>{ln}</tspan>)}</text>
        {f.blast > 0 ? <text x={conX + conW / 2} y={conY + conH + 15} textAnchor="middle" fill={sc} style={{ font: "800 10px var(--sans)" }}>▣ {f.blast} {f.blast_unit}</text> : null}</g>
    </svg>
  );
}

function FlowDiagram({ f }: { f: CausalFlowItem }) {
  return f.shape === "bowtie" && (f.threats || []).length >= 2 ? <BowtieFlow f={f} /> : <LinearFlow f={f} />;
}

function FChip({ on, onClick, children, ct }: { on: boolean; onClick: () => void; children: ReactNode; ct: number }) {
  return (
    <button type="button" className={`czfchip${on ? " on" : ""}`} aria-pressed={on} onClick={onClick}>
      {children}<span className="ct">{ct}</span>
    </button>
  );
}

function EvidenceChips({ f }: { f: CausalFlowItem }) {
  const ev = f.evidence || {};
  const chips: ReactNode[] = [];
  // W3-2 (NotebookLM teardown): the coverage-honest grounding signals, computed in the engine SSOT
  // (causal.evidence_precision / evidence_grounding) so all surfaces agree. Precision = how precisely this claim
  // is grounded (never the fake-precise LINE without raw show-text); the ⚠ flags a citation whose snapshot path
  // no longer resolves (the format-fidelity / SSOT-drift guard).
  if (ev.precision) chips.push(
    <span key="prec" className="czchip"
      title="How precisely this claim is grounded — BLOCK: a specific snapshot path · DEVICE: named host(s) · FLEET: fleet aggregate. (LINE, a raw show-command line, is reserved until raw-output capture.)">
      <b>◎ {ev.precision}</b>
    </span>);
  if (ev.grounded === false) chips.push(
    <span key="ungrounded" className="czchip" style={{ color: "var(--crit)", borderColor: "var(--crit)" }}
      title={`Citation does not resolve in this snapshot — ${(ev.dangling || []).join(", ")}`}>
      ⚠ citation unresolved
    </span>);
  if (ev.citation) chips.push(<span key="cite" className="czchip" style={{ fontFamily: "var(--sans)", fontStyle: "italic" }}>{ev.citation}</span>);
  if (ev.layers) chips.push(<span key="lay" className="czchip"><b>layers</b> {ev.layers}</span>);
  // ev.count is the decision's metric (ports / VLANs / member-legs / ... per the title), NOT a device count --
  // label it unit-neutrally rather than the old hard-coded 'device(s)' (a live mislabel on the real AJ data).
  if (typeof ev.count === "number") chips.push(<span key="cnt" className="czchip"><b>{ev.count}</b> affected</span>);
  if (ev.wave) chips.push(<span key="wave" className="czchip"><b>wave</b> {ev.wave}</span>);
  if (f.hosts && f.hosts.length) chips.push(<span key="hosts" className="czchip">{f.hosts.slice(0, 5).join(", ")}{f.hosts.length > 5 ? ` +${f.hosts.length - 5}` : ""}</span>);
  if (ev.fields && ev.fields.length) chips.push(<span key="src" className="czchip"><b>src</b> {ev.fields.join(", ")}</span>);
  return chips.length ? <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 8 }}>{chips}</div> : null;
}

export default function CausalFlowPanel({ snapId }: { snapId: number }) {
  const { data, error, loading } = useAsync(() => api.causalFlows(snapId), [snapId]);
  const [fam, setFam] = useState("all");
  const [sev, setSev] = useState<string>("all");
  const [sel, setSel] = useState(0);
  useEffect(() => { setFam("all"); setSev("all"); setSel(0); }, [snapId]);

  if (loading) return <div className="panel"><h3>Causal Flow · every finding's root-cause story</h3><Loading /></div>;
  if (error) return <div className="panel"><h3>Causal Flow · every finding's root-cause story</h3><ErrorBox msg={error} /></div>;
  const cf = data as CausalFlows;
  if (!cf || !cf.flows?.length) return null;   // data-gated: older snapshots without findings show nothing

  const famSet = fam === "all" ? cf.flows : cf.flows.filter((f) => f.family === fam);
  const sevCounts: Record<string, number> = {};
  famSet.forEach((f) => { const s = czSev(f.severity); sevCounts[s] = (sevCounts[s] || 0) + 1; });
  const view = famSet.filter((f) => sev === "all" || czSev(f.severity) === sev);
  const idx = Math.min(sel, Math.max(0, view.length - 1));
  const cur = view[idx];
  const pick = (k: "fam" | "sev", v: string) => { if (k === "fam") setFam(v); else setSev(v); setSel(0); };
  const CAP = 40;

  return (
    <div className="panel">
      <h3>Causal Flow · every finding's root-cause story</h3>
      <div className="faint" style={{ fontSize: 11, marginTop: 4 }}>
        {cf.summary.n_flows} causal flow{cf.summary.n_flows === 1 ? "" : "s"} · {cf.summary.n_critical} critical ·
        {" "}{cf.summary.n_families} famil{cf.summary.n_families === 1 ? "y" : "ies"}
        {" — "}the SAME unified model the explorer's Causal Flow mode renders: structural SPOFs, cross-layer
        compounds, design decisions and the migration punch-list, each as one trigger → mechanism → impact → mitigation story.
      </div>

      {/* filter toolbar — overview → filter → details-on-demand */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, margin: "10px 0 6px" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center" }}>
          <span className="faint" style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".7px", textTransform: "uppercase" }}>Family</span>
          <FChip on={fam === "all"} onClick={() => pick("fam", "all")} ct={cf.summary.n_flows}><span>⁂</span> All</FChip>
          {cf.families.map((fm) => (
            <FChip key={fm.key} on={fam === fm.key} onClick={() => pick("fam", fm.key)} ct={fm.n}><span>{fm.icon}</span> {fm.label}</FChip>
          ))}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, alignItems: "center" }}>
          <span className="faint" style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: ".7px", textTransform: "uppercase" }}>Severity</span>
          <FChip on={sev === "all"} onClick={() => pick("sev", "all")} ct={famSet.length}>All</FChip>
          {SEV_ORDER.filter((s) => sevCounts[s]).map((s) => (
            <FChip key={s} on={sev === s} onClick={() => pick("sev", s)} ct={sevCounts[s]}><SevBadge sev={s} s={10} /> {s}</FChip>
          ))}
        </div>
      </div>

      {!view.length ? (
        <div className="dim" style={{ fontSize: 13, padding: "12px 0" }}>No findings match this filter. Clear the family or severity filter to see more.</div>
      ) : cur ? (
        <>
          {/* selected flow — keyed on cur.key so switching cards remounts the SVG and replays .czreveal */}
          <div style={{ fontSize: 13, fontWeight: 700, margin: "8px 0 6px" }}>Causal flow — {cur.title}</div>
          <FlowDiagram key={cur.key} f={cur} />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 9 }}>
            {STAGES.map((st) => (
              <span key={st.key} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text-dim)" }}>
                <span style={{ width: 9, height: 9, borderRadius: 3, background: `var(--${st.tok})`, display: "inline-block" }} />{st.label}
              </span>
            ))}
          </div>
          {cur.shape === "bowtie" && (cur.threats || []).length >= 2 && (
            <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>
              Bowtie: contributing causes (left) converge on the central <b>top event</b>, then propagate to the impact (right).{" "}
              <span style={{ color: "var(--crit)" }}>⊘</span> = <b>no preventive control today</b> (why each cause reaches the event);{" "}
              <span style={{ color: "var(--ok)", fontWeight: 700 }}>✓ FIX</span> = the mitigation to add.
            </div>
          )}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", margin: "9px 0 2px" }}>
            {cur.blast > 0 && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text-dim)" }}>
                <span style={{ font: "800 15px var(--sans)", color: "var(--text)" }}>{cur.blast}</span> {cur.blast_unit}
                <span style={{ height: 7, borderRadius: 4, background: sevColor(cur.severity), opacity: 0.9, minWidth: 4, width: Math.round(Math.min(120, czWidth(cur.blast) * 11)) }} />
              </span>
            )}
            {cur.confidence && (
              <span style={{ fontSize: 10, fontWeight: 600, color: /observ/i.test(cur.confidence) ? "var(--ok)" : "var(--text-dim)", border: `1px dashed ${/observ/i.test(cur.confidence) ? "var(--ok)" : "var(--border-strong)"}`, borderRadius: 5, padding: "2px 7px" }}>
                confidence: {cur.confidence}
              </span>
            )}
          </div>
          <div className="panel" style={{ padding: 10, borderLeft: `3px solid ${sevColor(cur.severity)}`, marginTop: 8, background: "var(--surface-2)" }}>
            <div style={{ fontSize: 12 }}><b>Trigger:</b> <span className="dim">{cur.trigger || "—"}</span></div>
            <div style={{ fontSize: 12, marginTop: 4 }}><b>Mechanism:</b> <span className="dim">{cur.mechanism || "—"}</span></div>
            <div style={{ fontSize: 12, marginTop: 4 }}><b>Impact:</b> <span className="dim">{cur.impact || "—"}</span></div>
            <div style={{ fontSize: 12, marginTop: 4, color: "var(--ok)" }}><b>Mitigation:</b> {cur.mitigation || "—"}</div>
            <EvidenceChips f={cur} />
          </div>
          {(cur.alternatives || cur.tradeoffs) && (
            <div className="panel" style={{ padding: 10, marginTop: 8 }}>
              {cur.alternatives && <div style={{ fontSize: 12 }}><b>Alternatives weighed:</b> <span className="dim">{cur.alternatives}</span></div>}
              {cur.tradeoffs && <div style={{ fontSize: 12, marginTop: 4 }}><b>Trade-offs:</b> <span className="dim">{cur.tradeoffs}</span></div>}
            </div>
          )}

          {/* card list — keyed on the active filter so a filter change remounts the cards and replays
              each .panel's reveal-up, staggered per-card (capped so a long list doesn't crawl in) */}
          <div style={{ fontSize: 13, fontWeight: 700, margin: "14px 0 6px" }}>
            {fam === "all" ? "All findings" : view[0]?.family_label} <span className="faint" style={{ fontWeight: 400 }}>{Math.min(CAP, view.length)} of {view.length}</span>
          </div>
          <div key={fam + "|" + sev}>
            {view.slice(0, CAP).map((c, i) => (
              <div key={c.key} role="button" tabIndex={0} aria-pressed={i === idx}
                onClick={() => setSel(i)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(i); } }}
                className="panel" style={{ padding: "8px 10px", marginBottom: 6, cursor: "pointer",
                  borderLeft: `3px solid ${sevColor(c.severity)}`, boxShadow: i === idx ? "0 0 0 2px var(--accent)" : undefined,
                  animationDelay: `${Math.min(i, 8) * 50}ms` }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <SevBadge sev={c.severity} s={10} /><b style={{ fontSize: 12, flex: 1 }}>{c.title}</b>
                  <span className="chip" style={{ fontSize: 10, color: sevColor(c.severity), borderColor: sevColor(c.severity) }}>{czSev(c.severity)}</span>
                </div>
                <div className="faint mono" style={{ fontSize: 11, marginTop: 2 }}>
                  {c.icon} {c.family_label}{c.hosts.length ? " · " + c.hosts.slice(0, 3).join(", ") : ""}{c.blast > 0 ? ` · ${c.blast} ${c.blast_unit}` : ""}
                </div>
                <div className="dim" style={{ fontSize: 12, marginTop: 2 }}>{c.impact}</div>
              </div>
            ))}
          </div>
          {view.length > CAP && (
            <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>…and {view.length - CAP} more in this filter — narrow by family or severity to see them.</div>
          )}
        </>
      ) : null}
    </div>
  );
}
