import { useMemo, useRef, useState } from "react";
import { api, type CableMap as CableMapModel, type CableMapNode, type CableOp } from "../api";
import { ErrorBox, SkelLines, useAsync, usePositionTween, useReducedMotion, type Pt } from "./ui";

// Nokia-EDA-style physical cable map. Renders the engine's compute_cable_map SSOT (the SAME model the
// explorer's Cable Map mode draws): role-tiered lanes, node rects with port stubs, cables anchored to
// ports and coloured by operational status. 'unknown' is the coverage-honest [NOT OBSERVED] neutral —
// an uncollected device / a port with no observed status is grey + dashed, never a fake green.

const OPCOL: Record<CableOp, string> = { up: "var(--ok)", down: "var(--crit)", unknown: "var(--text-faint)" };
const NW = 176, NH = 50, GX = 40, GY = 116, PAD = 60;

interface Pos { x: number; y: number }

export function shortName(h: string) { return h.length > 22 ? h.slice(0, 21) + "…" : h; }
export function majorityRole(cm: CableMapModel, k: number) {
  const rs: Record<string, number> = {};
  cm.nodes.filter((n) => n.tier === k).forEach((n) => { if (n.role) rs[n.role] = (rs[n.role] || 0) + 1; });
  const top = Object.entries(rs).sort((a, b) => b[1] - a[1])[0];
  return top ? top[0] : "";
}

// Fleet-scale declutter (same semantics as the explorer's cablemap view): fabric-only hides
// positively-identified edge endpoints (AP / phone) — switches, routers and unknowns always stay;
// tier focus keeps one lane + its direct peers. Empty lanes compact (tier remapped on COPIES).
const EDGE_KINDS = new Set(["ap", "phone", "endpoint"]);
type FilteredModel = CableMapModel & { _raw: { n: number; c: number } };
export function filterModel(cm: CableMapModel, fabricOnly: boolean, tierSel: number | null): FilteredModel {
  let nodes = cm.nodes, cables = cm.cables;
  if (fabricOnly) {
    const hide = new Set(nodes.filter((n) => EDGE_KINDS.has(n.kind)).map((n) => n.host));
    if (hide.size) {
      nodes = nodes.filter((n) => !hide.has(n.host));
      cables = cables.filter((c) => !hide.has(c.a) && !hide.has(c.b));
    }
  }
  if (tierSel != null) {
    const inTier = new Set(nodes.filter((n) => n.tier === tierSel).map((n) => n.host));
    cables = cables.filter((c) => inTier.has(c.a) || inTier.has(c.b));
    const keep = new Set(inTier); cables.forEach((c) => { keep.add(c.a); keep.add(c.b); });
    nodes = nodes.filter((n) => keep.has(n.host));
  }
  const live = new Set(nodes.map((n) => n.host));
  const remap = new Map<number, number>(); let next = 0;
  cm.tiers.forEach((t, k) => { if (t.some((h) => live.has(h))) remap.set(k, next++); });
  const tiers: string[][] = []; remap.forEach((nk, k) => { tiers[nk] = cm.tiers[k].filter((h) => live.has(h)); });
  if (nodes !== cm.nodes || tierSel != null)
    nodes = nodes.map((n) => (remap.has(n.tier) ? { ...n, tier: remap.get(n.tier)! } : n));
  return { ...cm, nodes, cables, tiers, _raw: { n: cm.nodes.length, c: cm.cables.length } };
}
function cablePath(a: Pos, b: Pos, orient: "v" | "h") {
  if (orient === "h") { const mx = (a.x + b.x) / 2; return `M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`; }
  const my = (a.y + b.y) / 2; return `M${a.x},${a.y} C${a.x},${my} ${b.x},${my} ${b.x},${b.y}`;
}

/** Deterministic tier-lane layout + per-node port anchors. Vertical = tiers top→bottom (ports on
 *  top/bottom edges); horizontal = tiers left→right (ports on left/right edges). */
function layout(cm: CableMapModel, orient: "v" | "h") {
  const V = orient !== "h";
  const alongStep = (V ? NW : NH) + GX, depthStep = (V ? NH : NW) + GY;
  const pos: Record<string, Pos> = {};
  const widest = Math.max(1, ...cm.tiers.map((t) => t.length));
  const span = (widest - 1) * alongStep;
  cm.tiers.forEach((t, k) => {
    const rowSpan = (t.length - 1) * alongStep, off = (span - rowSpan) / 2;
    t.forEach((h, i) => {
      const along = PAD + off + i * alongStep, depth = PAD + k * depthStep;
      pos[h] = V ? { x: along, y: depth } : { x: depth, y: along };
    });
  });
  const nodeByHost: Record<string, CableMapNode> = {};
  cm.nodes.forEach((n) => (nodeByHost[n.host] = n));
  const anch: Record<string, Record<string, Pos>> = {};
  cm.nodes.forEach((n) => {
    const p = pos[n.host]; if (!p) return; anch[n.host] = {};
    const near: typeof n.ports = [], far: typeof n.ports = [];   // near = peer in a lower tier (up/left), far = higher (down/right)
    n.ports.forEach((pt) => {
      const peer = nodeByHost[pt.peer]; const peerTier = peer ? peer.tier : n.tier + 1;
      (peerTier < n.tier ? near : far).push(pt);
    });
    const place = (arr: typeof n.ports, sign: number) => arr.forEach((pt, i) => {
      const frac = (i + 1) / (arr.length + 1);
      anch[n.host][pt.name] = V ? { x: p.x - NW / 2 + frac * NW, y: p.y + sign * (NH / 2) }
                                : { x: p.x + sign * (NW / 2), y: p.y - NH / 2 + frac * NH };
    });
    place(near, -1); place(far, 1);
  });
  const alongTot = PAD * 2 + span, depthTot = PAD * 2 + (cm.tiers.length - 1) * depthStep + (V ? NH : NW);
  const W = Math.max(600, V ? alongTot : depthTot);
  const H = Math.max(300, V ? depthTot : alongTot);
  return { pos, anch, W, H, V };
}

export default function CableMap({ snapId }: { snapId: number }) {
  const g = useAsync(() => api.cableMap(snapId), [snapId]);
  const [orient, setOrient] = useState<"v" | "h">("v");
  const [fabricOnly, setFabricOnly] = useState(false);
  const [tierSel, setTierSel] = useState<number | null>(null);
  const model = useMemo(
    () => (g.data && g.data.nodes.length ? filterModel(g.data, fabricOnly, tierSel) : null),
    [g.data, fabricOnly, tierSel],
  );
  const view = useMemo(() => (model ? layout(model, orient) : null), [model, orient]);
  // Tween node centres across a relayout (orientation flip, tier/fabric filter change). useMemo keeps
  // the Map reference stable across renders that don't touch the layout (selection, pan/zoom), so the
  // hook's effect only refires when `view` itself changes — its own caller contract.
  const centerTargets = useMemo(() => {
    const m = new Map<string, Pt>();
    if (view) Object.entries(view.pos).forEach(([host, p]) => m.set(host, p));
    return m;
  }, [view]);
  const shownCenters = usePositionTween(centerTargets);
  const reduced = useReducedMotion();
  const [sel, setSel] = useState<{ kind: "node" | "cable"; id: string | number } | null>(null);
  const [t, setT] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  if (g.loading) return <SkelLines label="Building cable map…" />;
  if (g.error) return <ErrorBox msg={g.error} />;
  const raw = g.data;
  if (!raw || !raw.nodes.length || !model || !view)
    return <div className="faint" style={{ fontSize: 13 }}>No cable map — this snapshot has no CDP/LLDP topology links.</div>;
  const cm = model;   // everything below renders the FILTERED view; `raw` keeps the fleet totals

  const { pos, anch, W, H, V } = view;
  const nodeByHost: Record<string, CableMapNode> = {}; cm.nodes.forEach((n) => (nodeByHost[n.host] = n));
  // shownPos = the (possibly mid-tween) node centre; falls back to target before the hook has a shown
  // value for it. Cable endpoints are absolute-positioned, so they need an explicit shift by the OWNER
  // node's (shown - target) delta or they visibly desync from the chassis mid-flight. Port-stub rects
  // (rendered inside the node's own <g>) do NOT need this: they're already local-offset from the
  // TARGET centre, so translating that <g> to `shownPos` carries them along for free — same math,
  // just inherited through nesting instead of recomputed.
  const shownPos = (host: string): Pos => shownCenters.get(host) ?? pos[host];
  const cableAnchor = (host: string, port: string): Pos | undefined => {
    const a = anch[host]?.[port] ?? pos[host];
    const p = pos[host], s = shownPos(host);
    return a && p && s ? { x: a.x + (s.x - p.x), y: a.y + (s.y - p.y) } : a;
  };
  const selHost = sel?.kind === "node" ? String(sel.id) : null;
  const selCab = sel?.kind === "cable" ? Number(sel.id) : null;
  const nbrs = new Set<string>();
  if (selHost) { nbrs.add(selHost); cm.cables.forEach((c) => { if (c.a === selHost) nbrs.add(c.b); if (c.b === selHost) nbrs.add(c.a); }); }
  const selNode = selHost ? nodeByHost[selHost] : null;
  const selCable = selCab != null ? cm.cables[selCab] : null;

  const onWheel = (e: React.WheelEvent) => { const k = Math.max(0.4, Math.min(2.6, t.k * (e.deltaY < 0 ? 1.12 : 0.89))); setT((p) => ({ ...p, k })); };
  const onDown = (e: React.MouseEvent) => { drag.current = { x: e.clientX, y: e.clientY, ox: t.x, oy: t.y }; };
  const onMove = (e: React.MouseEvent) => { if (!drag.current) return; setT((p) => ({ ...p, x: drag.current!.ox + (e.clientX - drag.current!.x), y: drag.current!.oy + (e.clientY - drag.current!.y) })); };
  const onUp = () => { drag.current = null; };

  return (
    <div>
      <div className="spread" style={{ marginBottom: 10 }}>
        <div className="legend" style={{ margin: 0 }}>
          <span className="item"><span style={{ width: 16, borderTop: "3px solid var(--ok)", display: "inline-block" }} /> up</span>
          <span className="item"><span style={{ width: 16, borderTop: "3px solid var(--crit)", display: "inline-block" }} /> down</span>
          <span className="item"><span style={{ width: 16, borderTop: "3px dashed var(--text-faint)", display: "inline-block" }} /> [NOT OBSERVED]</span>
          <span className="item">▬ thick = port-channel</span>
        </div>
        <div className="row-flex" style={{ gap: 8 }}>
          <span className="faint" style={{ fontSize: 12 }}>
            {cm.summary.op.up} up · {cm.summary.op.down} down · {cm.summary.op.unknown} not observed
          </span>
          <button className="btn ghost" style={{ padding: "4px 9px" }} onClick={() => { setOrient((o) => (o === "h" ? "v" : "h")); setT({ x: 0, y: 0, k: 1 }); }}>⇅ {orient === "h" ? "Horizontal" : "Vertical"}</button>
          <button className="btn ghost"
            style={{ padding: "4px 9px", ...(fabricOnly ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}) }}
            title="Hide positively-identified edge endpoints (APs / IP phones). Switches, routers and unknowns always stay."
            onClick={() => { setFabricOnly((v) => !v); setSel(null); }}>{fabricOnly ? "☑" : "☐"} Fabric only</button>
          <button className="btn ghost" style={{ padding: "4px 9px" }} onClick={() => setT({ x: 0, y: 0, k: 1 })}>Reset view</button>
          {sel && <button className="btn ghost" style={{ padding: "4px 9px" }} onClick={() => setSel(null)}>Clear</button>}
        </div>
      </div>

      <div className="row-flex" style={{ gap: 4, flexWrap: "wrap", alignItems: "center", marginBottom: 8 }}>
        <span className="faint" style={{ fontSize: 11 }}>TIER</span>
        <button className="btn ghost" style={{ padding: "2px 8px", fontSize: 11, ...(tierSel == null ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}) }}
          onClick={() => { setTierSel(null); setSel(null); }}>ALL</button>
        {raw.tiers.map((tr, k) => {
          if (!tr.length) return null;
          const role = majorityRole(raw, k);
          return (
            <button key={k} className="btn ghost" title={`${tr.length} node(s)`}
              style={{ padding: "2px 8px", fontSize: 11, ...(tierSel === k ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}) }}
              onClick={() => { setTierSel((s) => (s === k ? null : k)); setSel(null); }}>
              T{k}{role ? " · " + role.toUpperCase() : ""}
            </button>
          );
        })}
        {(fabricOnly || tierSel != null) && (
          <span className="faint" style={{ fontSize: 11 }}>
            · showing <b>{cm.nodes.length}</b>/{cm._raw.n} nodes, <b>{cm.cables.length}</b>/{cm._raw.c} cables
          </span>
        )}
      </div>

      <div style={{ position: "relative", border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface-2)", overflow: "hidden" }}>
        {cm.nodes.length === 0 && (
          <div className="faint" style={{ position: "absolute", top: 12, left: 12, fontSize: 12 }}>
            Every node is hidden by the current filter — clear the tier / fabric filters above.
          </div>
        )}
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", maxHeight: "72vh", display: "block", cursor: drag.current ? "grabbing" : "grab" }}
          onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp} onClick={() => setSel(null)}>
          {/* CSS (not XML) transform so pan/zoom eases via `transition` — SVG-on-CSS transform uses
              px units, unlike the attribute form. Suppressed while a drag is in flight (the ref read
              mirrors the cursor check above) so panning never fights a lagging transition; the
              reduced-motion check is belt-and-suspenders alongside the styles.css kill-switch. */}
          <g style={{
            transform: `translate(${t.x}px, ${t.y}px) scale(${t.k})`,
            transition: reduced || drag.current ? "none" : "transform var(--motion) var(--ease)",
          }}>
            {/* tier lane bands + labels */}
            {cm.tiers.map((tr, k) => {
              if (!tr.length) return null;
              const p0 = pos[tr[0]]; const role = majorityRole(cm, k);
              const label = `TIER ${k}${role ? " · " + role.toUpperCase() : ""}`;
              return (
                <g key={"lane" + k}>
                  {k % 2 === 1 && (V
                    ? <rect x={0} y={p0.y - NH / 2 - 16} width={W} height={NH + 32} fill="var(--surface-3)" opacity={0.5} />
                    : <rect x={p0.x - NW / 2 - 16} y={0} width={NW + 32} height={H} fill="var(--surface-3)" opacity={0.5} />)}
                  {V
                    ? <text x={12} y={p0.y - NH / 2 - 20} fontSize={11} fontWeight={700} fill="var(--text-faint)">{label}</text>
                    : <text x={p0.x - NW / 2 - 12} y={16} fontSize={11} fontWeight={700} fill="var(--text-faint)">{label}</text>}
                </g>
              );
            })}
            {/* cables (under nodes) */}
            {cm.cables.map((c, i) => {
              const aA = cableAnchor(c.a, c.a_port);
              const aB = cableAnchor(c.b, c.b_port);
              if (!aA || !aB) return null;
              const touch = !selHost || c.a === selHost || c.b === selHost;
              const isSel = selCab === i;
              return (
                <path key={"c" + i} d={cablePath(aA, aB, orient)} fill="none" stroke={OPCOL[c.op_status]}
                  strokeWidth={isSel ? (c.is_pc ? 6 : 3.5) : c.is_pc ? 4.5 : 2}
                  strokeOpacity={selHost && !touch ? 0.1 : 0.82} strokeLinecap="round"
                  strokeDasharray={c.op_status === "unknown" ? "5 5" : undefined}
                  style={{ cursor: "pointer" }} onClick={(e) => { e.stopPropagation(); setSel({ kind: "cable", id: i }); }} />
              );
            })}
            {/* nodes */}
            {cm.nodes.map((n) => {
              const p = pos[n.host]; if (!p) return null;
              const sp = shownPos(n.host);   // chassis rides the tween; anchors below stay p-relative (see shownPos)
              const on = !selHost || nbrs.has(n.host); const isSel = selHost === n.host;
              return (
                <g key={n.host} transform={`translate(${sp.x},${sp.y})`} style={{ cursor: "pointer", opacity: on ? 1 : 0.28 }}
                  onClick={(e) => { e.stopPropagation(); setSel((s) => (s?.kind === "node" && s.id === n.host ? null : { kind: "node", id: n.host })); }}>
                  <rect x={-NW / 2} y={-NH / 2} rx={9} width={NW} height={NH} fill="var(--surface)"
                    stroke={isSel ? "var(--accent)" : n.collected ? "var(--border-strong)" : "var(--text-faint)"}
                    strokeWidth={isSel ? 2.4 : n.collected ? 1.5 : 1.3} strokeDasharray={n.collected ? undefined : "4 4"} />
                  <circle cx={-NW / 2 + 13} cy={-NH / 2 + 13} r={5} fill={OPCOL[n.op_status]} stroke="var(--surface)" strokeWidth={1.5} />
                  {n.badges.slice(0, 3).map((b, bi) => (
                    <circle key={b} cx={NW / 2 - 12 - bi * 13} cy={-NH / 2 + 12} r={4}
                      fill={b === "uncollected" ? "var(--text-faint)" : b === "links-down" ? "var(--crit)" : "var(--watch)"} />
                  ))}
                  <text x={0} y={-1} textAnchor="middle" fontSize={12.5} fontWeight={700} fill="var(--text)" style={{ pointerEvents: "none" }}>{shortName(n.host)}</text>
                  <text x={0} y={14} textAnchor="middle" fontSize={10} fill="var(--text-dim)" style={{ pointerEvents: "none" }}>{(n.role || "—") + " · T" + n.tier + " · " + n.ports.length + "p"}</text>
                  {Object.entries(anch[n.host] || {}).map(([pn, a]) => {
                    const port = n.ports.find((pp) => pp.name === pn);
                    return <rect key={pn} x={a.x - p.x - 3} y={a.y - p.y - 3} width={6} height={6} rx={1.5}
                      fill={OPCOL[port ? port.op_status : "unknown"]} stroke="var(--surface)" strokeWidth={1} />;
                  })}
                </g>
              );
            })}
          </g>
        </svg>

        {(selNode || selCable) && (
          // key = selection identity so each new pick REMOUNTS (replaying .tabfade) rather than
          // patching the same node in place — the app's established tab/detail-panel entrance idiom.
          <div key={selNode ? `n:${selHost}` : `c:${selCab}`} className="tabfade"
            style={{ position: "absolute", top: 10, right: 10, background: "var(--surface)", border: "1px solid var(--border-strong)", borderRadius: 9, padding: "11px 13px", boxShadow: "var(--shadow)", maxWidth: 290, fontSize: 12, maxHeight: "66vh", overflow: "auto" }}>
            {selNode && (
              <>
                <div className="row-flex" style={{ gap: 8, marginBottom: 6 }}>
                  <span style={{ width: 10, height: 10, borderRadius: "50%", background: OPCOL[selNode.op_status], display: "inline-block" }} />
                  <b className="mono" style={{ fontSize: 13 }}>{selNode.host}</b>
                </div>
                <div className="dim">Status: <b style={{ color: OPCOL[selNode.op_status] }}>{selNode.op_status}{selNode.collected ? "" : " · [NOT OBSERVED]"}</b></div>
                <div className="dim">Role / tier: {selNode.role || "—"} · T{selNode.tier} · kind {selNode.kind || "—"}</div>
                <div className="dim">Cabled ports: {selNode.ports.length}{selNode.badges.length ? " · " + selNode.badges.join(", ") : ""}</div>
                {selNode.ports.length > 0 && (
                  <table className="tbl" style={{ marginTop: 8, fontSize: 11 }}>
                    <thead><tr><th>Local</th><th>Peer</th><th>Port</th><th>St</th></tr></thead>
                    <tbody>{selNode.ports.map((pt) => (
                      <tr key={pt.name}><td className="mono">{pt.name}</td><td>{pt.peer}</td><td className="mono">{pt.peer_port || "—"}</td>
                        <td style={{ color: OPCOL[pt.op_status] }}>{pt.op_status}{pt.is_pc ? "·LAG" : ""}</td></tr>
                    ))}</tbody>
                  </table>
                )}
              </>
            )}
            {selCable && (
              <>
                <b style={{ fontSize: 13 }}>Cable</b>
                <div className="dim mono" style={{ marginTop: 4 }}>{selCable.a} · {selCable.a_port}</div>
                <div className="dim mono">{selCable.b} · {selCable.b_port}</div>
                <div className="dim" style={{ marginTop: 4 }}>Status: <b style={{ color: OPCOL[selCable.op_status] }}>{selCable.op_status}</b>{selCable.speed ? <> · speed <b>{selCable.speed}</b></> : null}</div>
                <div className="dim">{selCable.is_pc ? `Port-channel · ${selCable.members.length} members` : "Single link"}{selCable.confirmation ? " · " + selCable.confirmation : ""}</div>
              </>
            )}
          </div>
        )}
      </div>
      <div className="faint" style={{ fontSize: 11, marginTop: 8 }}>
        {cm.summary.n_nodes} nodes · {cm.summary.n_cables} cables · {cm.summary.n_tiers} tiers · physical CDP/LLDP cabling in role tiers · click a node or cable for detail · scroll to zoom, drag to pan.
      </div>
    </div>
  );
}
