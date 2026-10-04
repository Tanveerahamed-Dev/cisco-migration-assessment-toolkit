import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { diagramPositions, DRAW_LINK_LIMIT, DRAW_NODE_LIMIT, exactEndpoint, rowKey, targetKey, topologyStyle,
  type TopologyLegend, type TopologyRows, type TopologyTarget } from "./topologyData";

function Glyph({ glyph }: { glyph: TopologyLegend["fallback"]["glyph"] }) {
  if (glyph === "router") return <><circle r="15" /><path d="M-9 0H9M0-9V9M5-4L9 0 5 4M-4-5L0-9 4-5" /></>;
  if (glyph === "ap") return <><circle r="5" /><path d="M-11-6Q0-18 11-6M-17-12Q0-29 17-12" /></>;
  if (glyph === "device") return <><rect x="-20" y="-12" width="40" height="24" rx="5" /><path d="M-13 3h5m4 0h5m4 0h5" /></>;
  return <><path d="M0-17L21 0 0 17-21 0Z" />{glyph !== "none" && <text textAnchor="middle" y="5">?</text>}</>;
}

export function TopologyDiagram({ rows, legend, selected, pathNodes, select }: {
  rows: TopologyRows; legend: TopologyLegend; selected: TopologyTarget | null;
  pathNodes: ReadonlySet<string>; select: (target: TopologyTarget) => void;
}) {
  const [layer, setLayer] = useState<"cables" | "structural_links">("cables");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; pan: { x: number; y: number } } | null>(null);
  const nodes = useMemo(() => rows.nodes.slice(0, DRAW_NODE_LIMIT), [rows.nodes]);
  const positions = useMemo(() => diagramPositions(nodes), [nodes]);
  const links = useMemo(() => rows[layer].slice(0, DRAW_LINK_LIMIT), [rows, layer]);
  const drawn = useMemo(() => links.flatMap((row) => {
    const a = exactEndpoint(row.a_nodes, nodes), b = exactEndpoint(row.b_nodes, nodes);
    return a && b ? [{ row, a: positions.get(rowKey(a))!, b: positions.get(rowKey(b))! }] : [];
  }), [links, nodes, positions]);
  const nodeScale = Math.min(1, Math.sqrt(40 / Math.max(1, nodes.length)));
  const selectedKey = selected ? targetKey(selected) : "";
  const activate = (event: KeyboardEvent<SVGGElement | SVGLineElement>, target: TopologyTarget) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(target); }
  };
  return <section className="panel topology-map-panel" aria-label="Topology map">
    <div className="topology-map-toolbar"><h2>2-D topology</h2>
      <label>Map links <select value={layer} onChange={(event) => setLayer(event.target.value as typeof layer)}>
        <option value="cables">Cable map</option><option value="structural_links">Structural graph</option>
      </select></label>
      <button className="btn" onClick={() => setZoom((value) => Math.min(5, value + .25))} aria-label="Zoom in">+</button>
      <button className="btn" onClick={() => setZoom((value) => Math.max(.5, value - .25))} aria-label="Zoom out">−</button>
      <button className="btn" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}>Fit map</button>
    </div>
    <p className="dim">Positions are a layout, not physical locations. Route-hop highlights do not identify physical cable use.</p>
    <svg className="topology-map" viewBox={`${500 + pan.x - 500 / zoom} ${300 + pan.y - 300 / zoom} ${1000 / zoom} ${600 / zoom}`}
      role="img" aria-label="Engine topology diagram" tabIndex={0} aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown"
      onKeyDown={(event) => {
        const movement = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
        if (movement) { event.preventDefault(); setPan((value) => ({ x: value.x + movement[0] * 80 / zoom, y: value.y + movement[1] * 80 / zoom })); }
      }}
      onPointerDown={(event) => {
        if ((event.target as Element).closest('[role="button"]')) return;
        drag.current = { x: event.clientX, y: event.clientY, pan };
        event.currentTarget.setPointerCapture?.(event.pointerId);
      }}
      onPointerMove={(event) => {
        if (!drag.current) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (bounds.width && bounds.height) setPan({ x: drag.current.pan.x - (event.clientX - drag.current.x) * 1000 / zoom / bounds.width,
          y: drag.current.pan.y - (event.clientY - drag.current.y) * 600 / zoom / bounds.height });
      }} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
      <g>
        {drawn.map(({ row, a, b }) => {
          const target = { list: layer, row: { index: row.index, pointer: row.pointer } };
          const { value, entry } = topologyStyle(row.style, legend);
          return <line key={targetKey(target)} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
            className={`topology-edge topology-tone-${entry.tone}${selectedKey === targetKey(target) ? " selected" : ""}`}
            data-stroke={entry.stroke} data-weight={entry.weight} role="button" tabIndex={0}
            aria-label={`Inspect ${layer === "cables" ? "cable" : "structural link"} row ${row.index}: ${value.label}`}
            onClick={() => select(target)} onKeyDown={(event) => activate(event, target)}>
            <title>{value.label} · {row.pointer}</title>
          </line>;
        })}
        {nodes.map((row) => {
          const target = { list: "nodes" as const, row: { index: row.index, pointer: row.pointer } };
          const position = positions.get(rowKey(row))!;
          const { value, entry } = topologyStyle(row.style, legend);
          const label = row.host.state === "published" ? row.host.value : `Node row ${row.index}`;
          return <g key={rowKey(row)} transform={`translate(${position.x} ${position.y}) scale(${nodeScale})`}
            className={`topology-node topology-tone-${entry.tone}${selectedKey === targetKey(target) ? " selected" : ""}${pathNodes.has(rowKey(row)) ? " path-node" : ""}`}
            data-stroke={entry.stroke} data-weight={entry.weight} role="button" tabIndex={0}
            aria-label={`Inspect node ${label}: ${value.label}`} aria-pressed={selectedKey === targetKey(target)}
            onClick={() => select(target)} onKeyDown={(event) => activate(event, target)}>
            <title>{label} · {value.label}</title><circle className="topology-node-halo" r="26" />
            <Glyph glyph={value.glyph} /><text className="topology-node-label" textAnchor="middle" y="38">{label.length > 34 ? `${label.slice(0, 31)}…` : label}</text>
          </g>;
        })}
      </g>
    </svg>
    <p className="dim">Drag empty map space to pan, or focus the map and use arrow keys. Zoom to inspect dense layouts.</p>
    {!nodes.length && <p>No node rows are loaded. Inspect the source evidence state below.</p>}
    <p className="projection-disclosure">Drawing {nodes.length} of {rows.nodes.length} loaded node rows and {drawn.length} of {rows[layer].length} loaded {layer.replaceAll("_", " ")} rows.
      {drawn.length < rows[layer].length && " Links without a unique engine-published join to displayed nodes, or beyond the display budget, remain available in the evidence lists."}
      {(rows.nodes.length > DRAW_NODE_LIMIT || rows[layer].length > DRAW_LINK_LIMIT) && ` Display budget: ${DRAW_NODE_LIMIT} nodes / ${DRAW_LINK_LIMIT} links.`}</p>
    <details className="topology-legend"><summary>Engine legend</summary><ul>{legend.entries.map((entry) =>
      <li key={entry.token}><span className={`topology-legend-swatch topology-tone-${entry.tone}`} data-stroke={entry.stroke} data-weight={entry.weight} />
        <span>{entry.meaning}</span><code>{entry.token}</code></li>)}</ul></details>
  </section>;
}
