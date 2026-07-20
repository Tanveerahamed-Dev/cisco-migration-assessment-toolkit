import { lazy, Suspense, useMemo, useRef, useState } from "react";
import { api, bandColor } from "../api";
import { shortName } from "./CableMap";
import { ErrorBox, Loading, useAsync } from "./ui";

// Device-fidelity topology: role-tiered lanes of switch-chassis rects — the same visual language as
// the CableMap and the 3D fabric's rack-mount meshes, so the product reads as one system. Health band
// is encoded as the status LED + a subtle chassis tint (never ball size/fill — there are no balls),
// keystones as a corner badge, single-point-of-failure links in --crit.
// The 3D fabric stays code-split: it pulls three.js + react-force-graph-3d (~750KB gzip), so it loads
// only when the user toggles 3D. This SVG view stays the eager default + reduced-motion path.
const Topology3D = lazy(() => import("./Topology3D"));

interface Pos { x: number; y: number }
export interface LaidNode {
  id: string; band: string; score: number | null; role: string; degree: number; keystone: boolean;
  x: number; y: number; lane: number;
}
export interface LaidEdge {
  source: LaidNode; target: LaidNode; is_bridge: boolean; pairs_cut: number;
  a: Pos; b: Pos;   // stub anchors on the two chassis edges
}
export interface LaneMeta { key: string; label: string; count: number; top: number; height: number }

// CableMap family metrics — the two views must read as one product.
const NW = 176, NH = 50, GX = 40, PAD = 60, ROW_GAP = 30, LANE_GAP = 84, MAXROW = 10;
const ROLE_ORDER = ["core", "distribution", "access", "edge"];

/** Deterministic role-tiered lane layout (replaces the earlier force-directed scatter): lanes in
 *  core → distribution → access → edge order (other roles after, unclassified last), barycenter-ordered
 *  within each lane to keep linked switches near each other, wrapped into rows of MAXROW at fleet
 *  scale, with per-link stub anchors on the facing chassis edges. Pure + exported for unit tests. */
export function layout(raw: { nodes: any[]; edges: any[] }): {
  nodes: LaidNode[]; links: LaidEdge[]; lanes: LaneMeta[]; W: number; H: number;
} {
  const nodes: LaidNode[] = raw.nodes.map((n) => ({ ...n, x: 0, y: 0, lane: 0 }));
  if (!nodes.length) return { nodes: [], links: [], lanes: [], W: 600, H: 300 };
  const byId = new Map(nodes.map((n) => [n.id, n]));

  // Lanes: canonical role order, then any other observed roles alphabetically, unclassified ("") last.
  const present = new Set(nodes.map((n) => n.role || ""));
  const extras = [...present].filter((r) => r && !ROLE_ORDER.includes(r)).sort();
  const laneKeys = [...ROLE_ORDER.filter((r) => present.has(r)), ...extras, ...(present.has("") ? [""] : [])];
  const laneOf = new Map(laneKeys.map((k, i) => [k, i]));
  nodes.forEach((n) => { n.lane = laneOf.get(n.role || "") ?? 0; });

  const nbrs = new Map<string, string[]>();
  const addNbr = (a: string, b: string) => { const l = nbrs.get(a); if (l) l.push(b); else nbrs.set(a, [b]); };
  for (const e of raw.edges) {
    if (byId.has(e.source) && byId.has(e.target)) { addNbr(e.source, e.target); addNbr(e.target, e.source); }
  }

  // Within-lane order: alphabetical seed, then barycenter sweeps (down, up, down) pulling each switch
  // toward the mean position of its cross-lane neighbours — deterministic, id tiebreak.
  const lanes: LaidNode[][] = laneKeys.map(() => []);
  nodes.forEach((n) => lanes[n.lane].push(n));
  lanes.forEach((l) => l.sort((a, b) => a.id.localeCompare(b.id)));
  const orderIx = new Map<string, number>();
  const reindex = () => lanes.forEach((l) => l.forEach((n, i) => orderIx.set(n.id, i)));
  reindex();
  const sweep = (ks: number[]) => {
    for (const k of ks) {
      const score = new Map<string, number>();
      for (const n of lanes[k]) {
        const xs = (nbrs.get(n.id) || []).map((id) => byId.get(id)!).filter((m) => m.lane !== k);
        score.set(n.id, xs.length
          ? xs.reduce((s, m) => s + (orderIx.get(m.id) ?? 0), 0) / xs.length
          : (orderIx.get(n.id) ?? 0));
      }
      lanes[k].sort((a, b) => (score.get(a.id)! - score.get(b.id)!) || a.id.localeCompare(b.id));
      reindex();
    }
  };
  const down = lanes.map((_, i) => i);
  sweep(down); sweep([...down].reverse()); sweep(down);

  // Geometry: rows of MAXROW per lane, rows centred, lanes stacked top→bottom.
  const laneRows = lanes.map((l) => { const rs: LaidNode[][] = []; for (let i = 0; i < l.length; i += MAXROW) rs.push(l.slice(i, i + MAXROW)); return rs; });
  const maxRowLen = Math.max(1, ...laneRows.flat().map((r) => r.length));
  const W = Math.max(600, PAD * 2 + (maxRowLen - 1) * (NW + GX) + NW);
  const laneMeta: LaneMeta[] = [];
  let y = PAD;
  laneRows.forEach((rows, k) => {
    const height = rows.length * NH + (rows.length - 1) * ROW_GAP;
    laneMeta.push({
      key: laneKeys[k], label: laneKeys[k] ? laneKeys[k].toUpperCase() : "UNCLASSIFIED",
      count: lanes[k].length, top: y, height,
    });
    rows.forEach((row, ri) => {
      const off = (W - PAD * 2 - ((row.length - 1) * (NW + GX) + NW)) / 2;
      row.forEach((n, ci) => {
        n.x = PAD + off + NW / 2 + ci * (NW + GX);
        n.y = y + ri * (NH + ROW_GAP) + NH / 2;
      });
    });
    y += height + LANE_GAP;
  });
  const H = Math.max(300, y - LANE_GAP + PAD);

  // Links + stub anchors: each endpoint claims a stub slot on the chassis edge facing its peer
  // (same-row peers meet on the top edge and arc over), slots spread by peer position.
  const links: LaidEdge[] = [];
  for (const e of raw.edges) {
    const s = byId.get(e.source), t = byId.get(e.target);
    if (!s || !t) continue;
    links.push({ source: s, target: t, is_bridge: !!e.is_bridge, pairs_cut: Number(e.pairs_cut) || 0, a: { x: 0, y: 0 }, b: { x: 0, y: 0 } });
  }
  type Slot = { l: LaidEdge; end: "a" | "b"; ox: number; oid: string };
  const slots = new Map<string, { top: Slot[]; bottom: Slot[] }>();
  nodes.forEach((n) => slots.set(n.id, { top: [], bottom: [] }));
  for (const l of links) {
    const sSide = l.target.y > l.source.y ? "bottom" : "top";
    const tSide = l.source.y > l.target.y ? "bottom" : "top";
    slots.get(l.source.id)![sSide].push({ l, end: "a", ox: l.target.x, oid: l.target.id });
    slots.get(l.target.id)![tSide].push({ l, end: "b", ox: l.source.x, oid: l.source.id });
  }
  nodes.forEach((n) => {
    const s = slots.get(n.id)!;
    (["top", "bottom"] as const).forEach((side) => {
      const arr = [...s[side]].sort((p, q) => (p.ox - q.ox) || p.oid.localeCompare(q.oid));
      arr.forEach((slot, i) => {
        const frac = (i + 1) / (arr.length + 1);
        slot.l[slot.end] = { x: n.x - NW / 2 + frac * NW, y: n.y + (side === "top" ? -NH / 2 : NH / 2) };
      });
    });
  });
  return { nodes, links, lanes: laneMeta, W, H };
}

/** Cable path between two stub anchors: vertical cubic across lanes, an over-the-top arc within a row. */
export function linkPath(l: LaidEdge): string {
  const { a, b } = l;
  if (a.y === b.y) {
    const lift = 34 + Math.abs(a.x - b.x) * 0.05;
    return `M${a.x},${a.y} C${a.x},${a.y - lift} ${b.x},${b.y - lift} ${b.x},${b.y}`;
  }
  const my = (a.y + b.y) / 2;
  return `M${a.x},${a.y} C${a.x},${my} ${b.x},${my} ${b.x},${b.y}`;
}

const unassessed = (n: { band: string }) => !n.band || n.band === "Insufficient Data";

export default function TopologyGraph({ snapId }: { snapId: number }) {
  const g = useAsync(() => api.graph(snapId), [snapId]);
  const [linkedOnly, setLinkedOnly] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [mode, setMode] = useState<"2d" | "3d">("2d");
  // Once 3D has been opened it stays MOUNTED for the life of this panel (hidden + paused in 2D
  // mode), so camera pose, settled layout and selection survive toggling — the engine is never
  // torn down and rebuilt. The flag never resets to false.
  const [opened3d, setOpened3d] = useState(false);
  const [t, setT] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  const model = useMemo(() => {
    if (!g.data) return null;
    if (!linkedOnly) return g.data;
    // Coverage-honest declutter (CableMap's "Fabric only" sibling): hide only link-less switches,
    // always disclosing the count — hidden is hidden, never silently absent.
    const keep = new Set(g.data.nodes.filter((n: any) => n.degree > 0).map((n: any) => n.id));
    return {
      nodes: g.data.nodes.filter((n: any) => keep.has(n.id)),
      edges: g.data.edges.filter((e: any) => keep.has(e.source) && keep.has(e.target)),
    };
  }, [g.data, linkedOnly]);
  const view = useMemo(() => (model ? layout(model) : null), [model]);

  if (g.loading) return <Loading label="Building topology…" />;
  if (g.error) return <ErrorBox msg={g.error} />;
  if (!g.data || !g.data.nodes.length || !view)
    return <div className="faint" style={{ fontSize: 13 }}>No topology to draw.</div>;
  const nUnlinked = g.data.nodes.filter((n: any) => !n.degree).length;

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
  const selNode = sel ? view.nodes.find((n) => n.id === sel) ?? g.data.nodes.find((n: any) => n.id === sel) : null;
  const selDeg = sel ? view.links.filter((e) => e.source.id === sel || e.target.id === sel).length : 0;

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const k = Math.max(0.4, Math.min(3, t.k * (e.deltaY < 0 ? 1.12 : 0.89)));
    setT((p) => ({ ...p, k }));
  };
  const onDown = (e: React.MouseEvent) => { drag.current = { x: e.clientX, y: e.clientY, ox: t.x, oy: t.y }; };
  const onMove = (e: React.MouseEvent) => {
    if (!drag.current) return;
    setT((p) => ({ ...p, x: drag.current!.ox + (e.clientX - drag.current!.x), y: drag.current!.oy + (e.clientY - drag.current!.y) }));
  };
  const onUp = () => { drag.current = null; };

  const segBtn = (m: "2d" | "3d", label: string) => (
    <button
      className="btn ghost"
      aria-pressed={mode === m}
      style={{ padding: "4px 11px", borderRadius: 0, fontWeight: 650,
        background: mode === m ? "linear-gradient(135deg, var(--accent), var(--accent-dim))" : "transparent",
        color: mode === m ? "#fff" : "var(--text-dim)" }}
      onClick={() => { setMode(m); setHover(null); if (m === "3d") setOpened3d(true); }}
    >{label}</button>
  );

  const selPanel = (glass: boolean) => selNode && (
    <div style={{ position: "absolute", top: 10, right: 10, background: glass ? "color-mix(in srgb, var(--surface) 80%, transparent)" : "var(--surface)", backdropFilter: glass ? "blur(12px)" : undefined, border: "1px solid var(--border-strong)", borderRadius: 9, padding: "10px 13px", boxShadow: "var(--shadow)", maxWidth: 240, fontSize: 12 }}>
      <div className="row-flex" style={{ gap: 8, marginBottom: 6 }}>
        <span className="sw" style={{ width: 11, height: 11, borderRadius: 3, background: bandColor(selNode.band || "") }} />
        <b className="mono" style={{ fontSize: 14 }}>{selNode.id}</b>
      </div>
      <div className="dim">Band: <b style={{ color: "var(--text)" }}>{selNode.band || "—"}</b> · score {selNode.score ?? "—"}/100</div>
      <div className="dim">Role: {selNode.role || "—"}</div>
      <div className="dim">{selDeg} link{selDeg === 1 ? "" : "s"}{selNode.keystone ? " · keystone" : ""}</div>
    </div>
  );

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
          <span className="item"><span style={{ width: 9, height: 9, background: "var(--accent)", transform: "rotate(45deg)", display: "inline-block" }} /> keystone</span>
        </div>
        <div className="row-flex" style={{ gap: 8 }}>
          {linkedOnly && (
            <span className="faint" style={{ fontSize: 12 }}>showing <b>{view.nodes.length}</b>/{g.data.nodes.length} switches</span>
          )}
          {nUnlinked > 0 && (
            <button className="btn ghost"
              style={{ padding: "4px 9px", ...(linkedOnly ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}) }}
              title={`Hide the ${nUnlinked} switch(es) with no observed CDP link (uncollected or standalone). The count stays disclosed — hidden, never silently absent.`}
              onClick={() => { setLinkedOnly((v) => !v); setSel(null); }}>{linkedOnly ? "☑" : "☐"} Linked only</button>
          )}
          <div className="row-flex" style={{ gap: 0, border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }} role="group" aria-label="Topology view mode">
            {segBtn("2d", "2D")}
            {segBtn("3d", "3D")}
          </div>
          {mode === "2d" && <button className="btn ghost" style={{ padding: "4px 9px" }} onClick={() => setT({ x: 0, y: 0, k: 1 })}>Reset view</button>}
          {sel && <button className="btn ghost" style={{ padding: "4px 9px" }} onClick={() => setSel(null)}>Clear selection</button>}
        </div>
      </div>

      {/* 3D layer: mounted once, then only HIDDEN (display:none replays .tabfade on return, and
          CSS animations restart from none→shown — no React remount, so the WebGL context, camera
          pose and settled simulation all survive). It renders the SAME linkedOnly-filtered `model`
          as 2D — passing the raw graph here let the two views silently disagree on node/edge counts. */}
      {opened3d && (
        <div className="tabfade" style={{ position: "relative", display: mode === "3d" ? undefined : "none" }}>
          <Suspense fallback={<div style={{ height: 480, display: "grid", placeItems: "center", border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface-2)" }}><Loading label="Loading 3D engine…" /></div>}>
            <Topology3D raw={model!} sel={sel} hover={hover} active={mode === "3d"}
              onPick={(id) => setSel((s) => (s === id ? null : id))} onHover={setHover} />
          </Suspense>
          {selPanel(true)}
        </div>
      )}
      {mode === "2d" && (
      <div className="tabfade" style={{ position: "relative", border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface-2)", overflow: "hidden" }}>
        {view.nodes.length === 0 && (
          <div className="faint" style={{ position: "absolute", top: 12, left: 12, fontSize: 12 }}>
            Every switch is hidden by the current filter — clear “Linked only” above.
          </div>
        )}
        <svg viewBox={`0 0 ${view.W} ${view.H}`} style={{ width: "100%", height: "auto", maxHeight: "72vh", display: "block", cursor: drag.current ? "grabbing" : "grab" }}
          onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={() => { onUp(); setHover(null); }}>
          <g transform={`translate(${t.x},${t.y}) scale(${t.k})`}>
            {/* role lane bands + labels */}
            {view.lanes.map((lane, k) => (
              <g key={"lane" + lane.key}>
                {k % 2 === 1 && (
                  <rect x={0} y={lane.top - 16} width={view.W} height={lane.height + 32} fill="var(--surface-3)" opacity={0.5} />
                )}
                <text x={12} y={lane.top - 22} fontSize={11} fontWeight={700} fill="var(--text-faint)">
                  {lane.label} · {lane.count}
                </text>
              </g>
            ))}
            {/* links (under the chassis) */}
            {view.links.map((e, i) => {
              const lit = focus ? (e.source.id === focus || e.target.id === focus) : false;
              const faded = focus && !lit;
              return (
                <path key={i} d={linkPath(e)} fill="none"
                  stroke={e.is_bridge ? "var(--crit)" : "var(--border-strong)"}
                  strokeWidth={lit ? 3 : e.is_bridge ? 1.8 + Math.min(1.6, e.pairs_cut * 0.2) : 1.4}
                  strokeOpacity={faded ? 0.1 : e.is_bridge ? 0.75 : 0.55} strokeLinecap="round" />
              );
            })}
            {/* switch chassis */}
            {view.nodes.map((n) => {
              const faded = dim(n.id);
              const na = unassessed(n);
              const stubs = view.links.flatMap((l) =>
                l.source.id === n.id ? [{ p: l.a, crit: l.is_bridge }] :
                l.target.id === n.id ? [{ p: l.b, crit: l.is_bridge }] : []);
              return (
                <g key={n.id} transform={`translate(${n.x},${n.y})`} style={{ cursor: "pointer", opacity: faded ? 0.25 : 1 }}
                  onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}
                  onClick={() => setSel((s) => (s === n.id ? null : n.id))}>
                  <rect x={-NW / 2} y={-NH / 2} rx={9} width={NW} height={NH}
                    fill={na ? "var(--surface)" : `color-mix(in srgb, var(--surface) 86%, ${bandColor(n.band)})`}
                    stroke={sel === n.id ? "var(--accent)" : na ? "var(--text-faint)" : "var(--border-strong)"}
                    strokeWidth={sel === n.id ? 2.4 : 1.5} strokeDasharray={na && sel !== n.id ? "4 4" : undefined} />
                  <circle cx={-NW / 2 + 13} cy={-NH / 2 + 13} r={5} fill={bandColor(n.band || "")} stroke="var(--surface)" strokeWidth={1.5}>
                    <title>{n.band || "[NOT OBSERVED]"}</title>
                  </circle>
                  {n.keystone && (
                    <g transform={`translate(${NW / 2 - 13}, ${-NH / 2 + 13})`}>
                      <rect x={-4.5} y={-4.5} width={9} height={9} transform="rotate(45)" fill="var(--accent)" stroke="var(--surface)" strokeWidth={1} />
                      <title>keystone — high blast-radius device</title>
                    </g>
                  )}
                  <text x={0} y={-1} textAnchor="middle" fontSize={12.5} fontWeight={700} fill="var(--text)"
                    style={{ pointerEvents: "none", fontFamily: "var(--mono)" }}>{shortName(n.id)}</text>
                  <text x={0} y={14} textAnchor="middle" fontSize={10} fill="var(--text-dim)" style={{ pointerEvents: "none" }}>
                    {(n.role || "unclassified") + " · " + (n.score ?? "—") + " · " + n.degree + " link" + (n.degree === 1 ? "" : "s")}
                  </text>
                  {stubs.map((s, si) => (
                    <rect key={si} x={s.p.x - n.x - 3} y={s.p.y - n.y - 3} width={6} height={6} rx={1.5}
                      fill={s.crit ? "var(--crit)" : "var(--border-strong)"} stroke="var(--surface)" strokeWidth={1} />
                  ))}
                </g>
              );
            })}
          </g>
        </svg>
        {selPanel(false)}
      </div>
      )}
      <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
        {view.nodes.length} switches · {view.links.length} links · {mode === "3d"
          ? "true-3D fabric — drag to orbit, scroll to zoom, click a switch to focus."
          : "role-tiered fabric — click a switch to trace its blast radius · scroll to zoom, drag to pan."}
      </div>
    </div>
  );
}
