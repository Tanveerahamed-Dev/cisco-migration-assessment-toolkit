import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { DRAW_LINK_LIMIT, DRAW_NODE_LIMIT, rowKey, targetKey, topologyStyle,
  type TopologyLegend, type TopologyRows, type TopologyTarget } from "./topologyData";
import { CHASSIS_HEIGHT, CHASSIS_WIDTH, chassisLinks, displayedNodes, forceTopologyLayout, matchesLoadedNode, publishedPortLabels } from "./topologyGeometry";
import "./topologyWorkbenchMap.css";

const NO_PATH = new Set<string>();
function Glyph({ glyph }: { glyph: TopologyLegend["fallback"]["glyph"] }) {
  if (glyph === "router") return <><circle r="15" /><path d="M-9 0H9M0-9V9M5-4L9 0 5 4M-4-5L0-9 4-5" /></>;
  if (glyph === "ap") return <><circle r="5" /><path d="M-11-6Q0-18 11-6M-17-12Q0-29 17-12" /></>;
  if (glyph === "device") return <><rect x="-20" y="-12" width="40" height="24" rx="5" /><path d="M-13 3h5m4 0h5m4 0h5" /></>;
  return <><path d="M0-17L21 0 0 17-21 0Z" />{glyph !== "none" && <text textAnchor="middle" y="5">?</text>}</>;
}

export interface NetworkCanvasProps {
  rows: TopologyRows; legend: TopologyLegend; selected: TopologyTarget | null;
  pathNodes?: ReadonlySet<string>; select: (target: TopologyTarget) => void;
}

export function NetworkCanvas({ rows, legend, selected, pathNodes = NO_PATH, select }: NetworkCanvasProps) {
  const hatchId = useId().replaceAll(":", "");
  const pendingId = `${hatchId}-pending`;
  const [layer, setLayer] = useState<"cables" | "structural_links">("cables");
  const [collectedOnly, setCollectedOnly] = useState(false);
  const [query, setQuery] = useState("");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; pan: { x: number; y: number } } | null>(null);
  const nodes = useMemo(() => displayedNodes(rows.nodes, collectedOnly), [rows.nodes, collectedOnly]);
  const sourceLinks = rows[layer];
  const links = useMemo(() => sourceLinks.slice(0, DRAW_LINK_LIMIT), [sourceLinks]);
  const layout = useMemo(() => forceTopologyLayout(nodes, links), [nodes, links]);
  const drawn = useMemo(() => chassisLinks(nodes, links, layout.positions), [nodes, links, layout]);
  const selectedKey = selected ? targetKey(selected) : "";
  const fit = () => { setZoom(1); setPan({ x: 0, y: 0 }); };
  const activate = (event: KeyboardEvent<SVGGElement | SVGPathElement>, target: TopologyTarget) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(target); }
  };
  return <section className="network-topology-map" aria-label="Topology map">
    <div className="network-map-toolbar">
      <h2>Network map</h2>
      <label className="network-map-search">Find device name <input type="search" value={query} placeholder="Highlight loaded names"
        onChange={(event) => setQuery(event.target.value)} /></label>
      <div className="network-map-layers" role="group" aria-label="Layer">
        <button type="button" className="btn" aria-pressed={layer === "cables"} onClick={() => { setLayer("cables"); fit(); }}>Physical</button>
        <button type="button" className="btn" disabled aria-describedby={pendingId}>L2 · VLAN</button>
        <button type="button" className="btn" disabled aria-describedby={pendingId}>L3 · routing</button>
      </div>
      <div className="network-map-colours" role="group" aria-label="Colour by">
        <button type="button" className="btn" aria-pressed="true">Source style</button>
        <button type="button" className="btn" disabled aria-describedby={pendingId}>Health</button>
        <button type="button" className="btn" disabled aria-describedby={pendingId}>Lifecycle</button>
        <button type="button" className="btn" disabled aria-describedby={pendingId}>Findings</button>
      </div>
      <label><input type="checkbox" checked={collectedOnly} onChange={(event) => { setCollectedOnly(event.target.checked); fit(); }} /> Collected devices only</label>
      <div className="network-map-navigation" role="group" aria-label="Map navigation">
        <button className="btn" onClick={() => setZoom((value) => Math.min(16, value * 1.25))} aria-label="Zoom in">+</button>
        <button className="btn" onClick={() => setZoom((value) => Math.max(.5, value / 1.25))} aria-label="Zoom out">−</button>
        <button className="btn" onClick={fit}>Fit map</button>
      </div>
    </div>
    <p className="network-map-pending" id={pendingId}>L2/VLAN, L3/routing and colour overlays await their Python-owned projection contracts. The map currently uses source-provided styles.</p>
    {query.trim() && <p className="network-map-feedback" role="status">{nodes.some((node) => matchesLoadedNode(node, query))
      ? "Matching loaded device names are outlined. Select one to inspect." : "No matching device name in the displayed map. This search matches device names only; MAC/IP lookup follows in Network tools."}</p>}
    <svg className="network-map-canvas" viewBox={`${layout.width / 2 + pan.x - layout.width / 2 / zoom} ${layout.height / 2 + pan.y - layout.height / 2 / zoom} ${layout.width / zoom} ${layout.height / zoom}`}
      role="img" aria-label="Engine topology diagram" tabIndex={0} aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown + - 0"
      onKeyDown={(event) => {
        const movement = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
        if (movement) { event.preventDefault(); setPan((value) => ({ x: value.x + movement[0] * 80 / zoom, y: value.y + movement[1] * 80 / zoom })); }
        if (event.key === "+" || event.key === "=") { event.preventDefault(); setZoom((value) => Math.min(16, value * 1.25)); }
        if (event.key === "-") { event.preventDefault(); setZoom((value) => Math.max(.5, value / 1.25)); }
        if (event.key === "0") { event.preventDefault(); fit(); }
      }}
      onPointerDown={(event) => {
        if ((event.target as Element).closest('[role="button"]')) return;
        drag.current = { x: event.clientX, y: event.clientY, pan };
        event.currentTarget.setPointerCapture?.(event.pointerId);
      }}
      onPointerMove={(event) => {
        if (!drag.current) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        const units = Math.max(layout.width / bounds.width, layout.height / bounds.height) / zoom;
        if (bounds.width && bounds.height) setPan({ x: drag.current.pan.x - (event.clientX - drag.current.x) * units,
          y: drag.current.pan.y - (event.clientY - drag.current.y) * units });
      }} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
      <defs><pattern id={hatchId} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="8" height="8" className="network-map-hatch-base" /><line x1="0" y1="0" x2="0" y2="8" className="network-map-hatch-line" />
      </pattern></defs>
      <g>
        {drawn.map(({ row, a, b, aSide, bSide, path }) => {
          const target = { list: layer, row: { index: row.index, pointer: row.pointer } };
          const { value, entry } = topologyStyle(row.style, legend), ports = publishedPortLabels(row);
          return <g key={targetKey(target)} className={`network-map-cable${selectedKey === targetKey(target) ? " is-selected" : ""}`}>
            <path d={path} className="network-map-edge-hit"
              data-stroke={entry.stroke} data-weight={entry.weight} role="button" tabIndex={0}
              aria-label={`Inspect ${layer === "cables" ? "cable" : "structural link"} row ${row.index}: ${value.label}`}
              aria-pressed={selectedKey === targetKey(target)} onClick={() => select(target)} onKeyDown={(event) => activate(event, target)}>
              <title>{value.label} · {ports ? `${ports.a || "Port not supplied"} ↔ ${ports.b || "Port not supplied"} · ` : ""}{row.pointer}</title>
            </path>
            <path d={path} className={`network-map-edge network-map-tone-${entry.tone}${selectedKey === targetKey(target) ? " selected" : ""}`}
              data-stroke={entry.stroke} data-weight={entry.weight} aria-hidden="true" />
            {ports && <g className="network-map-port-labels" aria-hidden="true">
              <text x={a.x + (aSide === "left" ? -8 : aSide === "right" ? 8 : 0)} y={a.y + (aSide === "bottom" ? 16 : -9)}
                textAnchor={aSide === "left" ? "end" : aSide === "right" ? "start" : "middle"}>{ports.a}</text>
              <text x={b.x + (bSide === "left" ? -8 : bSide === "right" ? 8 : 0)} y={b.y + (bSide === "bottom" ? 16 : -9)}
                textAnchor={bSide === "left" ? "end" : bSide === "right" ? "start" : "middle"}>{ports.b}</text>
            </g>}
          </g>;
        })}
        {nodes.map((row) => {
          const target = { list: "nodes" as const, row: { index: row.index, pointer: row.pointer } }, position = layout.positions.get(rowKey(row))!;
          const { value, entry } = topologyStyle(row.style, legend);
          const label = row.host.state === "published" ? row.host.value : `Node row ${row.index}`;
          const role = row.role.state === "published" ? row.role.value : "Role not supplied";
          const uncollected = row.collected.state === "published" && row.collected.value === false;
          return <g key={rowKey(row)} transform={`translate(${position.x} ${position.y})`}
            className={`network-map-node network-map-tone-${entry.tone} topology-tone-${entry.tone}${selectedKey === targetKey(target) ? " selected" : ""}${pathNodes.has(rowKey(row)) ? " path-node" : ""}${matchesLoadedNode(row, query) ? " name-match" : ""}`}
            data-stroke={entry.stroke} data-weight={entry.weight} role="button" tabIndex={0}
            aria-label={`Inspect node ${label}: ${value.label}`} aria-pressed={selectedKey === targetKey(target)}
            onClick={() => select(target)} onKeyDown={(event) => activate(event, target)}>
            <title>{label} · {role} · {value.label}</title>
            <rect className="network-map-halo" x={-CHASSIS_WIDTH / 2 - 5} y={-CHASSIS_HEIGHT / 2 - 5} width={CHASSIS_WIDTH + 10} height={CHASSIS_HEIGHT + 10} rx="13" />
            <rect className="network-map-chassis" data-uncollected={uncollected || undefined} fill={uncollected ? `url(#${hatchId})` : undefined}
              x={-CHASSIS_WIDTH / 2} y={-CHASSIS_HEIGHT / 2} width={CHASSIS_WIDTH} height={CHASSIS_HEIGHT} rx="9" />
            <g transform="translate(-60 0) scale(.65)"><Glyph glyph={value.glyph} /></g>
            <text className="network-map-node-label" x="-35" y="-2">{label.length > 19 ? `${label.slice(0, 16)}…` : label}</text>
            <text className="network-map-node-role" x="-35" y="16">{role.length > 23 ? `${role.slice(0, 20)}…` : role}</text>
          </g>;
        })}
      </g>
    </svg>
    {!nodes.length && <p className="network-map-feedback">No node rows are displayed. Review the filter and source evidence.</p>}
    <div className="network-map-visible-legend" aria-label="Map legend">
      <span><i className="network-map-hatch-swatch" aria-hidden="true" />Not collected (source flag)</span>
      <span><i className="network-map-selection-swatch" aria-hidden="true" />Selected device or cable</span>
      <span>Colours and line styles follow the source legend.</span>
    </div>
    <details className="network-map-info"><summary>Map info · legend and coverage</summary>
      <label>Additional relationship view <select value={layer} onChange={(event) => { setLayer(event.target.value as typeof layer); fit(); }}>
        <option value="cables">Physical cable map</option><option value="structural_links">Structural graph · host-pair relationships</option>
      </select></label>
      <p>Drag empty map space to pan, or focus the map and use arrow keys. + / − zoom; 0 fits the map. Select a device or cable to inspect it.</p>
      <p>Positions are a force layout, not tiers or physical locations. Route-hop highlights do not identify physical cable use.</p>
      <p>Drawing {nodes.length} of {rows.nodes.length} loaded node rows and {drawn.length} of {rows[layer].length} loaded {layer.replaceAll("_", " ")} rows.
        {collectedOnly && " The collected-device filter hides other node rows and their cables from this picture."}
        {drawn.length < rows[layer].length && " Links without a unique engine-published join to displayed nodes, or beyond the display budget, remain available in the evidence lists."}
        {(rows.nodes.length > DRAW_NODE_LIMIT || rows[layer].length > DRAW_LINK_LIMIT) && ` Display budget: ${DRAW_NODE_LIMIT} nodes / ${DRAW_LINK_LIMIT} links.`}</p>
      <p>Device-name search highlights displayed labels only; it is not a complete MAC or IP lookup. Port labels are published cable ends. Bundle members remain in cable evidence.</p>
      <details className="network-map-legend"><summary>Engine legend</summary><ul>{legend.entries.map((entry) =>
        <li key={entry.token}><span className={`network-map-swatch network-map-tone-${entry.tone}`} data-stroke={entry.stroke} data-weight={entry.weight} />
          <span>{entry.meaning}</span><code>{entry.token}</code></li>)}</ul></details>
    </details>
  </section>;
}
