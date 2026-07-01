import { useMemo, useRef, useState } from "react";
import {
  forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation,
  type SimulationNodeDatum,
} from "d3-force";
import { api, bandColor } from "../api";
import { ErrorBox, Loading, useAsync } from "./ui";

interface GNode extends SimulationNodeDatum {
  id: string; band: string; score: number | null; role: string; degree: number; keystone: boolean;
}
interface GEdge { source: GNode; target: GNode; is_bridge: boolean; pairs_cut: number; }

const W = 840;
const H = 470;

/** Settle a static force-directed layout (deterministic — d3 seeds positions by phyllotaxis). */
function layout(raw: { nodes: any[]; edges: any[] }): { nodes: GNode[]; links: GEdge[] } {
  const nodes: GNode[] = raw.nodes.map((n) => ({ ...n }));
  const links: any[] = raw.edges.map((e) => ({ ...e }));
  const sim = forceSimulation(nodes)
    .force("link", forceLink(links).id((d: any) => d.id).distance(78).strength(0.6))
    .force("charge", forceManyBody().strength(-300))
    .force("center", forceCenter(W / 2, H / 2))
    .force("collide", forceCollide(24))
    .stop();
  sim.tick(330);
  // clamp into the viewbox with a little padding
  for (const n of nodes) {
    n.x = Math.max(26, Math.min(W - 26, n.x ?? W / 2));
    n.y = Math.max(26, Math.min(H - 26, n.y ?? H / 2));
  }
  return { nodes, links: links as GEdge[] };
}

const radius = (n: GNode) => 8 + Math.min(10, n.degree * 1.4) + (n.keystone ? 2 : 0);

export default function TopologyGraph({ snapId }: { snapId: number }) {
  const g = useAsync(() => api.graph(snapId), [snapId]);
  const view = useMemo(() => (g.data ? layout(g.data) : null), [g.data]);
  const [hover, setHover] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [t, setT] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  if (g.loading) return <Loading label="Building topology…" />;
  if (g.error) return <ErrorBox msg={g.error} />;
  if (!view || !view.nodes.length) return <div className="faint" style={{ fontSize: 13 }}>No topology to draw.</div>;

  const focus = sel || hover;
  const neighbors = new Set<string>();
  if (focus) {
    neighbors.add(focus);
    for (const e of view.links) {
      if (e.source.id === focus) neighbors.add(e.target.id);
      if (e.target.id === focus) neighbors.add(e.source.id);
    }
  }
  const dim = (id: string) => (focus ? !neighbors.has(id) : false);
  const selNode = sel ? view.nodes.find((n) => n.id === sel) : null;
  const selDeg = sel ? view.links.filter((e) => e.source.id === sel || e.target.id === sel).length : 0;

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const k = Math.max(0.5, Math.min(3, t.k * (e.deltaY < 0 ? 1.12 : 0.89)));
    setT((p) => ({ ...p, k }));
  };
  const onDown = (e: React.MouseEvent) => { drag.current = { x: e.clientX, y: e.clientY, ox: t.x, oy: t.y }; };
  const onMove = (e: React.MouseEvent) => {
    if (!drag.current) return;
    setT((p) => ({ ...p, x: drag.current!.ox + (e.clientX - drag.current!.x), y: drag.current!.oy + (e.clientY - drag.current!.y) }));
  };
  const onUp = () => { drag.current = null; };

  // audit-5 FH#21: derive the legend from the bands actually present, so the engine's 'Insufficient Data' band
  // (uncollected devices — e.g. 50 of the 303 AJ fleet) is EXPLAINED rather than silently absent from the legend
  // while those nodes still render. Canonical order; fall back to the standard five if none match.
  const _bandsPresent = ["Excellent", "Good", "Fair", "Poor", "Critical", "Insufficient Data"]
    .filter((b) => view.nodes.some((n) => (n.band || "") === b));
  const legendBands = _bandsPresent.length ? _bandsPresent : ["Excellent", "Good", "Fair", "Poor", "Critical"];

  return (
    <div>
      <div className="spread" style={{ marginBottom: 10 }}>
        <div className="legend" style={{ margin: 0 }}>
          {legendBands.map((b) => (
            <span className="item" key={b}><span className="sw" style={{ background: bandColor(b) }} /> {b}</span>
          ))}
          <span className="item"><span style={{ width: 16, height: 0, borderTop: "2px solid var(--crit)", display: "inline-block" }} /> single point of failure</span>
        </div>
        <div className="row-flex" style={{ gap: 6 }}>
          <button className="btn ghost" style={{ padding: "4px 9px" }} onClick={() => setT({ x: 0, y: 0, k: 1 })}>Reset view</button>
          {sel && <button className="btn ghost" style={{ padding: "4px 9px" }} onClick={() => setSel(null)}>Clear selection</button>}
        </div>
      </div>

      <div style={{ position: "relative", border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface-2)", overflow: "hidden" }}>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block", cursor: drag.current ? "grabbing" : "grab" }}
          onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={() => { onUp(); setHover(null); }}>
          <g transform={`translate(${t.x},${t.y}) scale(${t.k})`}>
            {view.links.map((e, i) => {
              const lit = focus ? (e.source.id === focus || e.target.id === focus) : false;
              const faded = focus && !lit;
              return (
                <line key={i} x1={e.source.x} y1={e.source.y} x2={e.target.x} y2={e.target.y}
                  stroke={e.is_bridge ? "var(--crit)" : "var(--border-strong)"}
                  strokeWidth={lit ? 3 : e.is_bridge ? 1.8 : 1.2}
                  strokeOpacity={faded ? 0.12 : e.is_bridge ? 0.7 : 0.5} />
              );
            })}
            {view.nodes.map((n) => {
              const r = radius(n);
              const faded = dim(n.id);
              return (
                <g key={n.id} transform={`translate(${n.x},${n.y})`} style={{ cursor: "pointer", opacity: faded ? 0.25 : 1 }}
                  onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}
                  onClick={() => setSel((s) => (s === n.id ? null : n.id))}>
                  {n.keystone && <circle r={r + 4} fill="none" stroke="var(--accent)" strokeWidth={1.5} strokeDasharray="2 2" />}
                  <circle r={r} fill={bandColor(n.band || "")} stroke={sel === n.id ? "var(--text)" : "var(--bg)"} strokeWidth={sel === n.id ? 2.5 : 1.5} />
                  <text y={r + 12} textAnchor="middle" fontSize={11} fontWeight={600} fill="var(--text-dim)"
                    style={{ pointerEvents: "none", fontFamily: "var(--mono)" }}>{n.id}</text>
                </g>
              );
            })}
          </g>
        </svg>
        {selNode && (
          <div style={{ position: "absolute", top: 10, right: 10, background: "var(--surface)", border: "1px solid var(--border-strong)", borderRadius: 9, padding: "10px 13px", boxShadow: "var(--shadow)", maxWidth: 240, fontSize: 12 }}>
            <div className="row-flex" style={{ gap: 8, marginBottom: 6 }}>
              <span className="sw" style={{ width: 11, height: 11, borderRadius: 3, background: bandColor(selNode.band || "") }} />
              <b className="mono" style={{ fontSize: 14 }}>{selNode.id}</b>
            </div>
            <div className="dim">Band: <b style={{ color: "var(--text)" }}>{selNode.band || "—"}</b> · score {selNode.score ?? "—"}/100</div>
            <div className="dim">Role: {selNode.role || "—"}</div>
            <div className="dim">{selDeg} link{selDeg === 1 ? "" : "s"}{selNode.keystone ? " · keystone" : ""}</div>
          </div>
        )}
      </div>
      <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
        {view.nodes.length} nodes · {view.links.length} links · click a node to trace its blast radius · scroll to zoom, drag to pan.
      </div>
    </div>
  );
}
