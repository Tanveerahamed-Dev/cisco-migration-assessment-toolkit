import { lazy, Suspense, useEffect, useMemo, useRef, useState, type ComponentType } from "react";
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

/* True-3D fabric (mirrors the offline explorer's 3D mode): a WebGL force-directed graph,
   switch-chassis nodes coloured by health band, links flagged for single-points-of-failure. */
export default function Topology3D({ raw, sel, onPick }: { raw: { nodes: any[]; edges: any[] }; sel: string | null; onPick: (id: string | null) => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const fg = useRef<any>(null);
  const [dim, setDim] = useState({ w: 840, h: 480 });
  const colors = useThemeColors();

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver((es) => { for (const e of es) setDim({ w: Math.max(320, Math.round(e.contentRect.width)), h: 480 }); });
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  // fresh copies each load so the library can mutate x/y/z without touching our cached graph
  const graphData = useMemo(() => ({
    nodes: raw.nodes.map((n) => ({ ...n })),
    links: raw.edges.map((e) => ({ ...e })),
  }), [raw]);

  // fly the camera to a clicked node (coords exist once the simulation has ticked)
  useEffect(() => {
    if (!sel || !fg.current) return;
    const n: any = graphData.nodes.find((x: any) => x.id === sel);
    if (!n || n.x == null) return;
    const dist = Math.hypot(n.x, n.y, n.z ?? 0) || 1;
    const r = 1 + 150 / dist;
    fg.current.cameraPosition({ x: n.x * r, y: n.y * r, z: (n.z ?? 0) * r }, n, 800);
  }, [sel, graphData]);

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
          nodeThreeObject={(n: any) => switchMesh(
            sel && n.id !== sel ? colors.faint : (colors.bands[n.band] ?? colors.faint),
            n.degree ?? 0, (n.degree ?? 0) >= 4 || !!n.keystone)}
          nodeThreeObjectExtend={false}
          nodeLabel={(n: any) => `${n.id} · ${n.band || "—"} ${n.score ?? ""}${n.keystone ? " · keystone" : ""}`}
          linkColor={(l: any) => (l.is_bridge ? colors.crit : colors.edge)}
          linkWidth={(l: any) => (l.is_bridge ? 1.4 : 0.4)}
          linkOpacity={0.5}
          linkDirectionalParticles={(l: any) => (reduceMotion() ? 0 : l.is_bridge ? 4 : 2)}
          linkDirectionalParticleWidth={(l: any) => (l.is_bridge ? 2.4 : 1.2)}
          linkDirectionalParticleSpeed={(l: any) => (l.is_bridge ? 0.012 : 0.006)}
          linkDirectionalParticleColor={(l: any) => (l.is_bridge ? colors.crit : colors.accent)}
          enableNodeDrag={false}
          onNodeClick={(n: any) => onPick(n.id)}
          onBackgroundClick={() => onPick(null)}
        />
      </Suspense>
      <div style={{ position: "absolute", left: 10, bottom: 10, fontSize: 11, color: "var(--text-faint)", pointerEvents: "none", background: "color-mix(in srgb, var(--surface) 70%, transparent)", backdropFilter: "blur(8px)", border: "1px solid var(--border)", borderRadius: 7, padding: "4px 8px" }}>
        drag to orbit · scroll to zoom · click a switch to focus
      </div>
    </div>
  );
}
