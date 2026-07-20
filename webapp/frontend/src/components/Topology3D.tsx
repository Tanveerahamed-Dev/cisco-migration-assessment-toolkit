import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from "react";
import * as THREE from "three";
import { bandColor } from "../api";
import { Loading } from "./ui";

// This whole module is lazy-imported by TopologyGraph, so neither three.js nor the graph engine
// (~750KB gzip combined) touch the initial bundle — they load only when a user opens the 3D fabric.
const ForceGraph3D = lazy(() => import("react-force-graph-3d")) as unknown as ComponentType<any>;

const reduceMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/* Resolve the design-token colours (CSS `var(--…)`) to concrete rgb() strings WebGL can use,
   re-resolving whenever the theme flips. Same band vocabulary as the SVG view. */
const BANDS = ["Excellent", "Good", "Fair", "Poor", "Critical"];
function useThemeColors() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const mo = new MutationObserver(() => setTick((t) => t + 1));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);
  return useMemo(() => {
    const probe = document.createElement("span");
    probe.style.cssText = "position:absolute;visibility:hidden;pointer-events:none";
    document.body.appendChild(probe);
    const get = (expr: string) => { probe.style.color = ""; probe.style.color = expr; return getComputedStyle(probe).color || "#888"; };
    const bands: Record<string, string> = {};
    for (const b of BANDS) bands[b] = get(bandColor(b));
    const out = { bg: get("var(--surface-2)"), crit: get("var(--crit)"), edge: get("var(--border-strong)"), accent: get("var(--accent)"), faint: get("var(--text-faint)"), bands };
    document.body.removeChild(probe);
    return out;
  }, [tick]);
}

/* Build a 3-D rack-mount switch CHASSIS mesh (replaces the default sphere so the fabric reads as
   switches, not globes — mirrors the explorer): a wide low box tinted by health band with an
   emissive front LED strip so it glows. THREE.Color parses the rgb() strings from useThemeColors. */
export function switchMesh(color: string, degree: number, big: boolean): THREE.Object3D {
  const c = new THREE.Color(color);
  const w = 7 + Math.min(11, degree), h = big ? 3.4 : 2.2, d = 5;
  const g = new THREE.Group();
  // chassis body (lit by the scene; faint self-emissive so it never goes fully black)
  g.add(new THREE.Mesh(new THREE.BoxGeometry(w, h, d),
    new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.2, metalness: 0.4, roughness: 0.5 })));
  // dark front face-plate
  const plate = new THREE.Mesh(new THREE.BoxGeometry(w * 0.9, h * 0.72, 0.4),
    new THREE.MeshStandardMaterial({ color: 0x0d1119, metalness: 0.5, roughness: 0.7 }));
  plate.position.set(0, 0, d / 2); g.add(plate);
  // two emissive port banks (read as lit RJ45 rows)
  for (let r = 0; r < 2; r++) {
    const strip = new THREE.Mesh(new THREE.BoxGeometry(w * 0.58, h * 0.13, 0.2), new THREE.MeshBasicMaterial({ color: c }));
    strip.position.set(-w * 0.06, (r ? -1 : 1) * h * 0.17, d / 2 + 0.22); g.add(strip);
  }
  // SFP+ uplink cages (right) + a status LED (left)
  for (let s = 0; s < 2; s++) {
    const sfp = new THREE.Mesh(new THREE.BoxGeometry(w * 0.07, h * 0.42, 0.3), new THREE.MeshBasicMaterial({ color: c }));
    sfp.position.set(w * (0.33 + s * 0.1), 0, d / 2 + 0.22); g.add(sfp);
  }
  const led = new THREE.Mesh(new THREE.SphereGeometry(h * 0.13, 8, 8), new THREE.MeshBasicMaterial({ color: c }));
  led.position.set(-w * 0.41, h * 0.18, d / 2 + 0.22); g.add(led);
  return g;
}

/** Tooltip label for a fabric node. SECURITY: react-force-graph-3d renders a STRING nodeLabel as
 *  innerHTML (its tooltip does `tooltipEl.html(content)`), so a device-derived id/band bearing HTML
 *  metacharacters would EXECUTE — stored XSS, reachable via a crafted uploaded snapshot whose node id is
 *  e.g. `SW1<img src=x onerror=…>`, with no CSP backstop. We HTML-escape the assembled label to inert
 *  text. The id itself is left untouched (it is the force-graph edge-linking key; escaping it would break
 *  link resolution). The 2D view is already safe — it renders the id as an escaped JSX <text> node. */
export function topoNodeLabel(n: any): string {
  const raw = `${n.id} · ${n.band || "—"} ${n.score ?? ""}${n.keystone ? " · keystone" : ""}`;
  return raw.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* True-3D fabric (mirrors the offline explorer's 3D mode): a WebGL force-directed graph,
   switch-chassis nodes coloured by health band, links flagged for single-points-of-failure.
   The parent keeps this mounted once opened and flips `active`: while inactive (hidden behind
   display:none) the engine's rAF loop is PAUSED, so a hidden fabric costs zero frames but keeps
   its camera pose, settled layout and WebGL context for an instant, coherent return. */
export default function Topology3D({ raw, sel, hover, active, onPick, onHover }: {
  raw: { nodes: any[]; edges: any[] };
  sel: string | null;
  hover: string | null;
  active: boolean;
  onPick: (id: string | null) => void;
  onHover: (id: string | null) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const fg = useRef<any>(null);
  const [dim, setDim] = useState({ w: 840, h: 480 });
  const colors = useThemeColors();

  useEffect(() => {
    if (!wrap.current) return;
    // Skip zero-width reports: the parent hides this layer with display:none, which would
    // otherwise "resize" the canvas to the 320px floor and back on every toggle.
    const ro = new ResizeObserver((es) => { for (const e of es) { if (!e.contentRect.width) continue; setDim({ w: Math.max(320, Math.round(e.contentRect.width)), h: 480 }); } });
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  // fresh copies each load so the library can mutate x/y/z without touching our cached graph
  const graphData = useMemo(() => ({
    nodes: raw.nodes.map((n) => ({ ...n })),
    links: raw.edges.map((e) => ({ ...e })),
  }), [raw]);

  // Pause/resume the engine's own rAF loop with visibility (real 3d-force-graph API). The ref
  // mirror lets onEngineTick self-pause the edge case where the lazy chunk resolves while hidden
  // (the [active] effect ran before the ref existed, so it couldn't pause anything yet).
  const activeRef = useRef(active);
  useEffect(() => { activeRef.current = active; }, [active]);
  useEffect(() => {
    const g = fg.current;
    if (!g?.pauseAnimation) return;
    if (active) g.resumeAnimation(); else g.pauseAnimation();
  }, [active]);

  // fly the camera to a clicked node (coords exist once the simulation has ticked). Re-runs on
  // activation, so a selection made in 2D is flown to when the user re-enters 3D.
  useEffect(() => {
    if (!active || !sel || !fg.current) return;
    const n: any = graphData.nodes.find((x: any) => x.id === sel);
    if (!n || n.x == null) return;
    const dist = Math.hypot(n.x, n.y, n.z ?? 0) || 1;
    const r = 1 + 150 / dist;
    fg.current.cameraPosition({ x: n.x * r, y: n.y * r, z: (n.z ?? 0) * r }, n, 800);
  }, [sel, graphData, active]);

  // STABLE mesh factory (identity changes only on a theme flip): the library treats a changed
  // nodeThreeObject reference as "rebuild every node's mesh", so an inline closure over sel/hover
  // would dispose + reallocate the whole fleet's meshes on every click and hover. Selection and
  // hover emphasis are applied by direct material mutation below instead — same band colour here.
  const nodeObj = useCallback(
    (n: any) => switchMesh(colors.bands[n.band] ?? colors.faint, n.degree ?? 0, (n.degree ?? 0) >= 4 || !!n.keystone),
    [colors]);

  /* Neighbor-aware dim, IDENTICAL semantics to the 2D view (focus = sel ?? hover; the focus node
     and its direct neighbors stay full, everything else drops to opacity .25; the selected
     chassis additionally glows brighter — the 3D analogue of 2D's accent stroke). Applied by
     mutating the already-built materials via the library's node.__threeObj back-reference —
     never by swapping the mesh factory, which would trigger the full-fleet rebuild above. */
  const applyDim = useCallback(() => {
    const focus = sel ?? hover;
    const nbrs = new Set<string>();
    if (focus) {
      nbrs.add(focus);
      for (const e of raw.edges) {
        if (e.source === focus) nbrs.add(e.target);
        else if (e.target === focus) nbrs.add(e.source);
      }
    }
    let touched = false;
    for (const n of graphData.nodes as any[]) {
      const obj: THREE.Object3D | undefined = n.__threeObj;
      if (!obj) continue;
      touched = true;
      const faded = focus ? !nbrs.has(n.id) : false;
      obj.traverse((o: any) => {
        const m = o.material;
        if (!m) return;
        if (m.transparent !== faded) { m.transparent = faded; m.needsUpdate = true; }
        m.opacity = faded ? 0.25 : 1;
      });
      const chassis: any = obj.children?.[0];
      if (chassis?.material?.emissiveIntensity !== undefined)
        chassis.material.emissiveIntensity = n.id === sel ? 0.55 : 0.2;
    }
    return touched;
  }, [sel, hover, raw, graphData]);

  // Re-apply on state change; the engine-tick hook below covers the window before the library
  // has attached __threeObj (fresh mount, or a graphData swap that rebuilt every node).
  const dimInit = useRef(false);
  useEffect(() => { dimInit.current = false; }, [graphData]);
  useEffect(() => { applyDim(); }, [applyDim, colors, active]);

  return (
    <div ref={wrap} style={{ position: "relative", border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden", background: "var(--surface-2)", boxShadow: "var(--shadow)" }}>
      <Suspense fallback={<div style={{ height: 480, display: "grid", placeItems: "center" }}><Loading label="Loading 3D engine…" /></div>}>
        <ForceGraph3D
          ref={fg}
          width={dim.w}
          height={dim.h}
          graphData={graphData}
          backgroundColor={colors.bg}
          showNavInfo={false}
          warmupTicks={reduceMotion() ? 80 : 0}
          cooldownTime={reduceMotion() ? 0 : 14000}
          nodeVal={(n: any) => 1.5 + Math.min(9, (n.degree ?? 0)) + (n.keystone ? 3 : 0)}
          nodeThreeObject={nodeObj}
          nodeThreeObjectExtend={false}
          nodeLabel={topoNodeLabel}
          onEngineTick={() => {
            if (!activeRef.current) { fg.current?.pauseAnimation?.(); return; }
            if (!dimInit.current) dimInit.current = applyDim();
          }}
          linkColor={(l: any) => (l.is_bridge ? colors.crit : colors.edge)}
          linkWidth={(l: any) => (l.is_bridge ? 1.4 : 0.4)}
          linkOpacity={0.5}
          linkDirectionalParticles={(l: any) => (reduceMotion() ? 0 : l.is_bridge ? 4 : 2)}
          linkDirectionalParticleWidth={(l: any) => (l.is_bridge ? 2.4 : 1.2)}
          linkDirectionalParticleSpeed={(l: any) => (l.is_bridge ? 0.012 : 0.006)}
          linkDirectionalParticleColor={(l: any) => (l.is_bridge ? colors.crit : colors.accent)}
          enableNodeDrag={false}
          onNodeClick={(n: any) => onPick(n.id)}
          onNodeHover={(n: any) => onHover(n ? n.id : null)}
          onBackgroundClick={() => onPick(null)}
        />
      </Suspense>
      <div style={{ position: "absolute", left: 10, bottom: 10, fontSize: 11, color: "var(--text-faint)", pointerEvents: "none", background: "color-mix(in srgb, var(--surface) 70%, transparent)", backdropFilter: "blur(8px)", border: "1px solid var(--border)", borderRadius: 7, padding: "4px 8px" }}>
        drag to orbit · scroll to zoom · click a switch to focus
      </div>
    </div>
  );
}
