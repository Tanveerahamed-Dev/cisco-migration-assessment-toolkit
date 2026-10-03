/** Same Scope geometry, engine-owned encodings. No legacy scene, cable classifier or forwarding imports. */
import {
  AmbientLight, BoxGeometry, BufferGeometry, Color, DirectionalLight, EdgesGeometry,
  Group, InstancedMesh, LineBasicMaterial, LineSegments, Matrix4, MeshStandardMaterial,
  OctahedronGeometry, PerspectiveCamera, Raycaster, Scene, Vector2, WebGLRenderer,
  type Material,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { releaseFocusFrom } from "../app/focus-return";
import { holds } from "../core/own";
import { buildChassis } from "../fabric3d/geometry/chassis";
import { ContractRefusal } from "./errors";
import { pathPositions, placeNodes, rowKey, suppliedStyle, uniquePosition, type Position, type PositionedNode } from "./geometry";
import type { CompleteTopology, Legend, PathDocument, Style } from "./types";
import type { SelectionTarget } from "../../../webapp/frontend/src/projectionEmbed";

type Entry = Legend["entries"][number];
export type LinkLayer = "cables" | "structural_links";
export type Renderer = Pick<WebGLRenderer, "domElement" | "setSize" | "setPixelRatio" | "render" | "dispose" | "forceContextLoss">;
export type SceneView = Readonly<{ select(target: SelectionTarget | null): void; path(value: PathDocument | null): void;
  layer(value: LinkLayer): void; reset(): void; theme(): void; render(): void; dispose(): void }>;
export type SceneOptions = Readonly<{
  makeRenderer?: (canvas: HTMLCanvasElement) => Renderer;
  onSelect(target: SelectionTarget | null): void;
  onFailure(): void;
}>;
const TONES: Readonly<Record<Entry["tone"], string>> = {
  neutral: "--text-muted", muted: "--unobserved-edge", info: "--accent", warning: "--sev-medium", danger: "--sev-critical",
};

export function createContractScene(canvas: HTMLCanvasElement, model: CompleteTopology, options: SceneOptions): SceneView {
  const nodes = placeNodes(model);
  const legend = model.document.payload.legend;
  const entries = new Map(legend.entries.map((entry) => [entry.token, entry]));
  if (entries.size !== legend.entries.length || !entries.has(legend.fallback.token)) throw new ContractRefusal("UNSUPPORTED_CONTRACT");
  const entryFor = (style: Style): Entry => {
    const entry = entries.get(style.token);
    if (!entry || !holds(TONES, entry.tone) ||
      !["solid", "dashed", "dotted"].includes(entry.stroke) || !["normal", "strong"].includes(entry.weight)) {
      throw new ContractRefusal("UNSUPPORTED_CONTRACT");
    }
    return entry;
  };
  const token = (name: string): Color => {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    if (!value) throw new ContractRefusal("RENDER_FAILED");
    return new Color(value);
  };
  let renderer: Renderer;
  try { renderer = options.makeRenderer?.(canvas) ?? new WebGLRenderer({ canvas, antialias: true, alpha: false }); }
  catch { throw new ContractRefusal("WEBGL_UNAVAILABLE"); }
  const scene = new Scene();
  const camera = new PerspectiveCamera(45, 1, 0.1, 10_000);
  let controls: OrbitControls;
  try { controls = new OrbitControls(camera, canvas); }
  catch { renderer.dispose(); renderer.forceContextLoss(); throw new ContractRefusal("RENDER_FAILED"); }
  controls.enableDamping = false; // No idle animation; reduced-motion users get the same immediate controls.
  controls.minPolarAngle = Math.PI / 12;
  controls.maxPolarAngle = Math.PI * 0.48;
  const geometries = new Set<BufferGeometry>();
  const materials = new Set<Material>();
  const ownedGeometry = <T extends BufferGeometry>(value: T): T => { geometries.add(value); return value; };
  const ownedMaterial = <T extends Material>(value: T): T => { materials.add(value); return value; };
  const base = new Group(), links = new Group(), overlay = new Group(), selection = new Group();
  scene.add(base, links, overlay, selection);
  scene.add(new AmbientLight(0xffffff, 1.7));
  const light = new DirectionalLight(0xffffff, 2.2);
  light.position.set(100, 180, 80); scene.add(light);
  const batches: { mesh: InstancedMesh; nodes: readonly PositionedNode[] }[] = [];
  const pickables: InstancedMesh[] = [];
  const linkTargets = new Map<LineSegments2, readonly SelectionTarget[]>();
  let disposed = false, initializing = true, frame: number | null = null;
  let labels: CSS2DRenderer | null = null;
  let currentLayer: LinkLayer = "cables";
  let currentPath: PathDocument | null = null;
  let selected: SelectionTarget | null = null;
  const ray = new Raycaster(), pointer = new Vector2();

  function clear(group: Group): void {
    for (const object of [...group.children]) {
      group.remove(object);
      if (object instanceof LineSegments || object instanceof LineSegments2) {
        if (object instanceof LineSegments2) linkTargets.delete(object);
        object.geometry.dispose(); geometries.delete(object.geometry);
        const all = Array.isArray(object.material) ? object.material : [object.material];
        for (const material of all) { material.dispose(); materials.delete(material); }
      }
    }
  }
  function render(): void {
    if (disposed) return;
    try { renderer.render(scene, camera); labels?.render(scene, camera); }
    catch {
      if (initializing) throw new ContractRefusal("RENDER_FAILED");
      dispose(); options.onFailure();
    }
  }
  function requestRender(): void {
    if (disposed || frame !== null) return;
    frame = requestAnimationFrame(() => { frame = null; render(); });
  }
  function dispose(): void {
    if (disposed) return;
    disposed = true;
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    resizeObserver?.disconnect();
    window.removeEventListener("resize", resize);
    canvas.removeEventListener("click", clicked);
    canvas.removeEventListener("webglcontextlost", contextLost);
    controls.removeEventListener("change", requestRender);
    controls.dispose();
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
    geometries.clear(); materials.clear(); scene.clear();
    linkTargets.clear();
    if (labels) { releaseFocusFrom(labels.domElement, null); labels.domElement.remove(); labels = null; }
    try { renderer.dispose(); } finally { renderer.forceContextLoss(); }
  }
  function contextLost(event: Event): void { event.preventDefault(); if (!disposed) { dispose(); options.onFailure(); } }
  function resize(): void {
    if (disposed) return;
    const width = Math.max(1, canvas.clientWidth), height = Math.max(1, canvas.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height, false);
    labels?.setSize(width, height);
    for (const material of materials) if (material instanceof LineMaterial) material.resolution.set(width, height);
    camera.aspect = width / height; camera.updateProjectionMatrix(); requestRender();
  }
  const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
  function reset(): void {
    if (disposed) return;
    const span = Math.max(40, ...[...nodes.values()].flatMap(({ position }) => [Math.abs(position.x) * 2 + 32, Math.abs(position.z) * 2 + 30]));
    controls.target.set(0, 0, 0); camera.position.set(span * 0.6, span * 0.85, span * 1.05);
    camera.far = span * 10; camera.updateProjectionMatrix();
    controls.minDistance = 20; controls.maxDistance = span * 4; controls.update(); render();
  }
  function line(group: Group, coordinates: readonly number[], entry: Entry): LineSegments2 | null {
    if (!coordinates.length) return null;
    const geometry = ownedGeometry(new LineSegmentsGeometry()); geometry.setPositions([...coordinates]);
    const material = ownedMaterial(new LineMaterial({ color: token(TONES[entry.tone]), dashed: entry.stroke !== "solid",
      dashSize: entry.stroke === "dotted" ? 0.7 : 3, gapSize: 2 }));
    // WebGL's ordinary LineBasicMaterial ignores widths; the owned engine weight uses real wide-line geometry.
    material.linewidth = entry.weight === "strong" ? 3 : 1.5;
    material.resolution.set(Math.max(1, canvas.clientWidth), Math.max(1, canvas.clientHeight));
    const object = new LineSegments2(geometry, material); object.computeLineDistances(); group.add(object); return object;
  }
  function segment(a: Position, b: Position, elevation: number): number[] {
    const values: number[] = [];
    const point = (t: number): Position => ({ x: a.x + (b.x - a.x) * t,
      y: a.y + (b.y - a.y) * t + 4 + Math.sin(Math.PI * t) * elevation, z: a.z + (b.z - a.z) * t });
    for (let step = 0; step < 12; step++) {
      const start = point(step / 12), end = point((step + 1) / 12);
      values.push(start.x, start.y, start.z, end.x, end.y, end.z);
    }
    return values;
  }
  function drawLinks(): void {
    if (disposed) return;
    clear(links);
    const coordinates = new Map<Entry, { values: number[]; targets: SelectionTarget[] }>();
    for (const row of model.rows[currentLayer]) {
      const a = uniquePosition(row.a_nodes, nodes), b = uniquePosition(row.b_nodes, nodes);
      if (!a || !b) continue;
      const entry = entryFor(suppliedStyle(row.style, legend));
      const batch = coordinates.get(entry) ?? { values: [], targets: [] };
      batch.values.push(...segment(a.position, b.position, 5 + row.index % 4 * 2));
      const target: SelectionTarget = { list: currentLayer, row: { index: row.index, pointer: row.pointer } };
      for (let index = 0; index < 12; index++) batch.targets.push(target);
      coordinates.set(entry, batch);
    }
    for (const [entry, batch] of coordinates) { const object = line(links, batch.values, entry); if (object) linkTargets.set(object, batch.targets); }
  }
  function drawPath(): void {
    if (disposed) return;
    clear(overlay);
    if (!currentPath) return;
    const points = pathPositions(currentPath, nodes);
    const coordinates: number[] = [];
    for (const node of points) {
      if (!node) continue;
      for (let step = 0; step < 24; step++) {
        const a = step / 24 * Math.PI * 2, b = (step + 1) / 24 * Math.PI * 2;
        coordinates.push(node.position.x + Math.cos(a) * 11, 5, node.position.z + Math.sin(a) * 8,
          node.position.x + Math.cos(b) * 11, 5, node.position.z + Math.sin(b) * 8);
      }
    }
    for (let index = 1; index < points.length; index++) {
      const a = points[index - 1], b = points[index];
      if (a && b) coordinates.push(...segment(a.position, b.position, 18));
    }
    line(overlay, coordinates, entryFor(suppliedStyle(currentPath.payload.style, currentPath.payload.legend)));
  }
  function selectionNodes(): readonly PositionedNode[] {
    if (!selected) return [];
    if (selected.list === "nodes") {
      const node = nodes.get(rowKey(selected.row)); return node ? [node] : [];
    }
    const row = model.rows[selected.list].find((candidate) => rowKey(candidate) === rowKey(selected!.row));
    if (!row) return [];
    if ("a_nodes" in row && "b_nodes" in row) return [uniquePosition(row.a_nodes, nodes), uniquePosition(row.b_nodes, nodes)].filter((value): value is PositionedNode => value !== null);
    if ("node_refs" in row) { const node = uniquePosition(row.node_refs, nodes); return node ? [node] : []; }
    return [];
  }
  function drawSelection(): void {
    if (disposed) return;
    clear(selection);
    for (const node of selectionNodes()) {
      const box = new BoxGeometry(19, 9, 14);
      const geometry = ownedGeometry(new EdgesGeometry(box)); box.dispose();
      const material = ownedMaterial(new LineBasicMaterial({ color: token("--text"), linewidth: 2 }));
      const outline = new LineSegments(geometry, material);
      outline.position.set(node.position.x, node.position.y, node.position.z); selection.add(outline);
    }
  }
  function theme(): void {
    if (disposed) return;
    scene.background = token("--bg");
    for (const { mesh, nodes: batch } of batches) {
      batch.forEach((node, index) => mesh.setColorAt(index, token(TONES[entryFor(suppliedStyle(node.row.style, legend)).tone])));
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
    drawLinks(); drawPath(); drawSelection(); render();
  }
  function clicked(event: MouseEvent): void {
    if (disposed) return;
    const bounds = canvas.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    pointer.set((event.clientX - bounds.left) / bounds.width * 2 - 1, -(event.clientY - bounds.top) / bounds.height * 2 + 1);
    ray.setFromCamera(pointer, camera);
    const hit = ray.intersectObjects([...pickables, ...linkTargets.keys()], false)[0];
    if (hit?.object instanceof LineSegments2 && hit.faceIndex !== undefined && hit.faceIndex !== null) {
      options.onSelect(linkTargets.get(hit.object)?.[hit.faceIndex] ?? null); return;
    }
    const batch = hit && batches.find((candidate) => candidate.mesh === hit.object);
    const node = batch && hit.instanceId !== undefined ? batch.nodes[hit.instanceId] : undefined;
    options.onSelect(node ? { list: "nodes", row: { index: node.row.index, pointer: node.row.pointer } } : null);
  }
  try {
    labels = new CSS2DRenderer(); labels.domElement.className = "contract-scope-labels";
    labels.domElement.setAttribute("aria-hidden", "true"); canvas.parentElement?.append(labels.domElement);
    const grouped = new Map<Style["glyph"], PositionedNode[]>();
    for (const node of nodes.values()) {
      const style = suppliedStyle(node.row.style, legend); entryFor(style);
      if (!["device", "router", "ap", "unknown", "none"].includes(style.glyph)) throw new ContractRefusal("UNSUPPORTED_CONTRACT");
      const list = grouped.get(style.glyph) ?? []; list.push(node); grouped.set(style.glyph, list);
      const text = document.createElement("span"); text.className = "contract-scope-node-label";
      text.textContent = node.row.host.state === "published" ? node.row.host.value : node.row.host.state;
      const label = new CSS2DObject(text); label.position.set(node.position.x, node.position.y + 7, node.position.z); base.add(label);
    }
    for (const [glyph, batch] of grouped) {
      const parts = glyph === "device" || glyph === "router" || glyph === "ap" ? buildChassis(glyph, { bevelSegments: 2, fineDetail: false }) : null;
      const shapes = parts ? [parts.body, parts.bezel, parts.dark, parts.rail, parts.led] : [new OctahedronGeometry(6)];
      for (const shape of shapes) {
        const mesh = new InstancedMesh(ownedGeometry(shape), ownedMaterial(new MeshStandardMaterial({ roughness: 0.65, metalness: 0.2 })), batch.length);
        batch.forEach(({ position }, index) => mesh.setMatrixAt(index, new Matrix4().makeTranslation(position.x, position.y, position.z)));
        mesh.instanceMatrix.needsUpdate = true; mesh.computeBoundingSphere();
        base.add(mesh); batches.push({ mesh, nodes: batch }); pickables.push(mesh);
      }
    }
    canvas.addEventListener("click", clicked); canvas.addEventListener("webglcontextlost", contextLost);
    controls.addEventListener("change", requestRender); window.addEventListener("resize", resize); resizeObserver?.observe(canvas);
    controls.listenToKeyEvents(canvas);
    reset(); resize(); theme(); initializing = false;
  } catch (error) { dispose(); throw error instanceof ContractRefusal ? error : new ContractRefusal("RENDER_FAILED"); }
  return {
    select(target) {
      if (disposed) return;
      selected = target;
      if (target?.list === "cables" || target?.list === "structural_links") { currentLayer = target.list; drawLinks(); }
      drawSelection(); render();
    },
    path(value) { if (!disposed) { currentPath = value; drawPath(); render(); } },
    layer(value) { if (!disposed) { currentLayer = value; drawLinks(); render(); } },
    reset, theme, render, dispose,
  };
}
