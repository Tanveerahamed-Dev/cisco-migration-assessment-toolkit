/**
 * flow.ts — a forwarding trace drawn ON the fabric.
 *
 * The rule that shapes everything here: the trace follows the REAL cables. It is not a second
 * picture of the path laid over the first one. A separate overlay would let the drawn path and the
 * drawn topology disagree — and a tool whose job is to show you which hop dropped your packet
 * cannot afford a path that is only approximately on the wire it claims.
 *
 * Motion inventory for this file (acceptance C6):
 *   draw-on      240 ms total, eased, regardless of hop count. The progression along the path IS
 *                the hop order, which is why it is animated at all.
 *   packet       ONE marker, 1.6 s per loop, stops after 3 loops and leaves the path drawn. The
 *                only looping animation in the product (design brief 4.8; the dead, unrendered
 *                `stage-pending-spin` spinner that App.css used to declare is removed); it exists
 *                to distinguish a live trace overlay from a static screenshot of a path.
 *   arrowheads   not animated. Direction is permanent information and does not need movement.
 *   stop glyph   not animated. An alarm that pulses is decoration; an alarm that is simply THERE,
 *                octagonal, and red is read faster.
 * Under `prefers-reduced-motion` the draw-on completes instantly and the packet never runs. The end
 * state is identical: reduced motion removes movement, never information.
 */
import {
  BufferGeometry,
  ConeGeometry,
  ExtrudeGeometry,
  Group,
  InstancedMesh,
  Matrix4,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  Quaternion,
  Path,
  Shape,
  Vector3,
  type PerspectiveCamera,
} from "three";
import { Line2 } from "three/addons/lines/Line2.js";
import { LineGeometry } from "three/addons/lines/LineGeometry.js";
import type { Trace } from "../core/types";
import { coverageGamma, createCableMaterial, MIN_STROKE_PX, setCoverageGamma } from "./geometry/cables";
import type { TokenPalette } from "./materials";
import { traceEndOf } from "./traceEnd";

export const DRAW_ON_MS = 240;
export const PACKET_LOOP_MS = 1600;
export const PACKET_LOOPS = 3;

/** World units between arrowheads. Scaled from the brief's 12 for a ~140-unit scene. */
const ARROW_PITCH = 28;

export interface TraceSegmentSource {
  /**
   * The drawn polyline between two adjacent hops, already oriented from `from` to `to`, or null
   * when the snapshot holds no cable between them. A null is drawn as a GAP in the path rather
   * than as a straight line, because inventing a wire to join two hops is inventing topology.
   */
  polylineBetween(from: string, to: string): Float32Array | null;
  /**
   * Anchor for the stop glyph and any per-host marker: the chassis body's centre, its lid height,
   * and (when the host knows it) the body's half-extents. The glyph is placed CLEAR of that body —
   * see `placeTerminalGlyph` — so a source that omits `half` gets a body assumed as tall as its lid.
   */
  anchorOf(host: string): TerminalAnchor | null;
}

export interface TerminalAnchor {
  x: number;
  y: number;
  z: number;
  top: number;
  half?: readonly [number, number, number];
}

/** Outer screen-facing radius of each terminal glyph, bevel included. */
export const STOP_GLYPH_RADIUS = 5.4;
export const UNDECIDED_GLYPH_RADIUS = 4.6 + 1.05;
/** World units of air between a terminal glyph and the chassis it marks, on screen and in space. */
export const GLYPH_CLEARANCE = 2.5;

/**
 * Where a billboarded terminal glyph sits for a given camera: the chassis centre plus the camera's
 * UP vector times (the chassis' bounding radius + the glyph's radius + a clearance).
 *
 * WHY CAMERA-UP AND NOT A FIXED HEIGHT (C5 critic, trace-gpu-t20b-h0.png / up-octagon.png). The
 * glyphs used to hang at `top + 11` world units. From the investigation view's elevated camera the
 * lid of the chassis extends TOWARDS the viewer, so its projection rose up across the lower third
 * of the glyph: the octagon read as sunk into core2, with the selection outline's rim line cutting
 * across it, and the ring penetrated dist1 the same way. No fixed height is right for every pitch.
 * Offsetting along camera-up — which is perpendicular to the view direction — puts the glyph's
 * centre (R + r + gap) away from the chassis centre ACROSS the line of sight, so the glyph and the
 * chassis' bounding sphere are disjoint in space AND in projection, at every orbit angle.
 */
export function placeTerminalGlyph(
  anchor: TerminalAnchor,
  cameraQuaternion: Quaternion,
  glyphRadius: number,
  out: Vector3,
): Vector3 {
  const half = anchor.half ?? [0, Math.max(0, anchor.top - anchor.y), 0];
  const chassisRadius = Math.hypot(half[0], half[1], half[2]);
  out.set(0, 1, 0).applyQuaternion(cameraQuaternion).normalize();
  out.multiplyScalar(chassisRadius + glyphRadius + GLYPH_CLEARANCE);
  out.x += anchor.x;
  out.y += anchor.y;
  out.z += anchor.z;
  return out;
}

export interface FlowOverlay {
  group: Group;
  /** Objects allowed past the bloom threshold: the path, the arrowheads, the packet, the alarm. */
  emissiveObjects(): Object3D[];
  setTrace(trace: Trace | null, activeHop: number | null, source: TraceSegmentSource): void;
  setResolution(width: number, height: number): void;
  setReducedMotion(reduced: boolean): void;
  retint(tokens: TokenPalette): void;
  /** Advance the animation. Returns true when something changed and a frame is owed. */
  update(nowMs: number, camera: PerspectiveCamera): boolean;
  /** Bounding sphere of the drawn path, for re-framing. Null when no trace is drawn. */
  pathSphere(): { center: [number, number, number]; radius: number } | null;
  /** The drawn path's polyline (xyz triples), for re-framing. Empty when no cable was stitched. */
  pathPoints(): Float32Array;
  /** Hops that could not be drawn because no cable joins them. Surfaced, never silently skipped. */
  undrawnHops(): string[];
  /**
   * The billboarded terminal glyph (stop octagon or undecided ring) when one is drawn: the host it
   * marks, its world centre and its screen-facing radius. The label layer needs it: a DOM label
   * has no depth, and one hung at the chassis silhouette was drawn straight across the glyph that
   * floats above that chassis (C5 critic: the 'dist1 ? UNDECIDED' chip over the torus).
   */
  terminalMarker(): { host: string; center: [number, number, number]; radius: number } | null;
  dispose(): void;
}

const _v = new Vector3();
const EMPTY_POINTS = new Float32Array(0);
const _a = new Vector3();
const _b = new Vector3();
const _tangent = new Vector3();
const _q = new Quaternion();
const _scale = new Vector3(1, 1, 1);
const _m = new Matrix4();
const UP = new Vector3(0, 1, 0);
const _qIdentity = new Quaternion();

/**
 * The blocked-hop alarm: a bevelled octagonal plate, billboarded. Shape first, colour second.
 *
 * Sized so the octagon SHAPE survives at overview distance and through the bloom. At 2.4 units it
 * was six pixels across and read as a red dot — colour with no second channel, which is the one
 * thing the alarm treatment must never be.
 *
 * BEVELLED, not a plain prism (C5 critic, up-octagon.png: "a flat, unlit, pastel salmon disc",
 * std 4/255 over 10k pixels). A face-on cylinder cap has ONE normal, so the key light and the
 * environment shade it as one flat colour, and the emission then washed that to pastel. The bevel
 * gives the rim chamfered faces that catch the key and the environment differently, so the plate
 * reads as an object lit by the same rig as the hardware it annotates.
 */
function stopGlyphGeometry(): BufferGeometry {
  const bevel = 0.45;
  const r = STOP_GLYPH_RADIUS - bevel;
  const shape = new Shape();
  for (let k = 0; k < 8; k += 1) {
    // Vertices at 22.5 deg + k * 45 deg: a flat edge on top, like a stop sign.
    const a = Math.PI / 8 + (k * Math.PI) / 4;
    if (k === 0) shape.moveTo(Math.cos(a) * r, Math.sin(a) * r);
    else shape.lineTo(Math.cos(a) * r, Math.sin(a) * r);
  }
  shape.closePath();
  const depth = 0.5;
  const g = new ExtrudeGeometry(shape, {
    depth,
    bevelEnabled: true,
    bevelThickness: bevel,
    bevelSize: bevel,
    bevelSegments: 3,
    curveSegments: 1,
  });
  // Centre the plate on its own origin so billboarding rotates it about its middle.
  g.translate(0, 0, -depth / 2);
  return g;
}

/**
 * The UNDECIDED terminal glyph: an OPEN RING, billboarded.
 *
 * It exists because this file used to divide traces in two — `outcome !== "delivered"` — and hand
 * the red octagonal alarm to everything on the wrong side of that line. An indeterminate trace
 * therefore ended in the same stop sign, in the same critical red, as a flow a filter genuinely
 * dropped: the canvas asserted a definite failure the engine had explicitly refused to assert.
 * `claims.ts :: bandOfTrace` owns that mapping and it has three values, not two. It is the TRACE band,
 * not the outcome word's: a drop over a routing table the snapshot shows to be incomplete is the word
 * "dropped" and the band UNDETERMINED, and the canvas drew it as the red stop octagon while the label
 * over the same glyph said "? UNDECIDED" (C5 critic, trace-gpu-t20b-h0.png).
 *
 * The shape is the first channel and it is deliberately the opposite of a stop sign: a filled
 * octagon is an instruction, an open ring is a hole in the evidence. Colour is the second channel
 * (`--claim-indeterminate`), never the only one.
 */
/** Stroke of the undecided ring's band, world units, bevel included. */
export const UNDECIDED_RING_STROKE = 1.3;
function undecidedGlyphGeometry(): BufferGeometry {
  // Radius matched to the octagon's so the two marks occupy the same visual weight at the same
  // distance — an undecided result is not a quieter result than a denial.
  /* A FLAT BEVELLED ANNULUS, the octagon's own construction, not a TorusGeometry (C5 critic,
     2026-09-22: "a plain shaded torus floating above the node with no tether ... reads as a stock
     three.js primitive dropped into the scene"). The two terminal marks are now one family — the
     same bevelled plate, billboarded, lit by the same rig — differing in the one channel that
     matters: a filled octagon is an instruction, an open ring is a hole in the evidence. The band is
     a flat stroke, like the label chip's outline it sits above, instead of a round tube. */
  const bevel = 0.3;
  const outer = UNDECIDED_GLYPH_RADIUS - bevel;
  const inner = UNDECIDED_GLYPH_RADIUS - UNDECIDED_RING_STROKE + bevel;
  const shape = new Shape();
  shape.absarc(0, 0, outer, 0, Math.PI * 2, false);
  const hole = new Path();
  hole.absarc(0, 0, inner, 0, Math.PI * 2, true);
  shape.holes.push(hole);
  const depth = 0.4;
  const g = new ExtrudeGeometry(shape, {
    depth,
    bevelEnabled: true,
    bevelThickness: bevel,
    bevelSize: bevel,
    bevelSegments: 3,
    curveSegments: 48,
  });
  g.translate(0, 0, -depth / 2);
  return g;
}

/**
 * The tether: a hairline from the marked chassis' lid to the underside of its terminal glyph, so
 * the glyph reads as ATTACHED to that host rather than floating in the air near it. The glyph hangs
 * along camera-up (placeTerminalGlyph), so the tether follows the camera with it.
 */
export function tetherEnds(
  anchor: TerminalAnchor,
  glyphCentre: Vector3,
  glyphRadius: number,
  cameraQuaternion: Quaternion,
  out: Float32Array,
): Float32Array {
  const ux = new Vector3(0, 1, 0).applyQuaternion(cameraQuaternion).normalize();
  out[0] = anchor.x;
  out[1] = anchor.top;
  out[2] = anchor.z;
  out[3] = glyphCentre.x - ux.x * glyphRadius;
  out[4] = glyphCentre.y - ux.y * glyphRadius;
  out[5] = glyphCentre.z - ux.z * glyphRadius;
  return out;
}

export function createFlowOverlay(tokens: TokenPalette): FlowOverlay {
  const group = new Group();
  group.name = "trace";
  group.visible = false;

  // 4 px for the path, 6 px for the blocked terminal segment: the two widths the brief assigns,
  // and the reason the terminal segment is a separate object rather than a colour change.
  // vertexColors OFF: these geometries carry no per-segment colour attribute, and LineMaterial
  // multiplies by a zero vColor when USE_COLOR is defined without one — a black trace path.
  const pathMaterial = createCableMaterial("solid", 4, 1, { vertexColors: false });
  const blockedMaterial = createCableMaterial("solid", 6, 1, { vertexColors: false });
  pathMaterial.dashed = true; // used as a REVEAL mask, not as a dash pattern
  pathMaterial.dashScale = 1;
  pathMaterial.depthTest = true;
  blockedMaterial.depthTest = true;

  const path = new Line2(new LineGeometry(), pathMaterial);
  path.name = "trace-path";
  path.frustumCulled = false;
  path.renderOrder = 4;
  path.visible = false;
  group.add(path);

  const blocked = new Line2(new LineGeometry(), blockedMaterial);
  blocked.name = "trace-blocked";
  blocked.frustumCulled = false;
  blocked.renderOrder = 5;
  blocked.visible = false;
  group.add(blocked);

  const arrowGeometry = new ConeGeometry(1.15, 3.2, 10, 1);
  // Cone points +Y by default; rotate so a quaternion aligning +Z to the tangent orients it.
  arrowGeometry.applyMatrix4(new Matrix4().makeRotationX(Math.PI / 2));
  const arrowMaterial = new MeshStandardMaterial({
    name: "trace-arrow",
    metalness: 0,
    roughness: 0.45,
    emissiveIntensity: 2.4,
    toneMapped: true,
  });
  const arrows = new InstancedMesh(arrowGeometry, arrowMaterial, 64);
  arrows.name = "trace-arrows";
  arrows.frustumCulled = false;
  arrows.count = 0;
  arrows.castShadow = false;
  arrows.receiveShadow = false;
  group.add(arrows);

  const packetGeometry = new ConeGeometry(1.5, 4.4, 12, 1);
  packetGeometry.applyMatrix4(new Matrix4().makeRotationX(Math.PI / 2));
  const packetMaterial = new MeshStandardMaterial({
    name: "trace-packet",
    metalness: 0,
    roughness: 0.4,
    emissiveIntensity: 3.6,
  });
  const packet = new Mesh(packetGeometry, packetMaterial);
  packet.name = "trace-packet";
  packet.frustumCulled = false;
  packet.visible = false;
  group.add(packet);

  const stopGeometry = stopGlyphGeometry();
  const stopMaterial = new MeshStandardMaterial({
    name: "trace-stop",
    metalness: 0,
    /* LIT, with an emission FLOOR — the treatment the undecided ring already got. At 1.9 the
       emission swamped every lighting term and tone mapping flattened the critical red to one
       pastel salmon (C5 critic). The albedo carries the red, the key and environment shade the
       bevel, and the emission keeps it legible on the dark stage and past the bloom threshold. */
    roughness: 0.38,
    emissiveIntensity: 0.55,
  });
  const stop = new Mesh(stopGeometry, stopMaterial);
  stop.name = "trace-stop";
  stop.frustumCulled = false;
  stop.visible = false;
  group.add(stop);

  const undecidedGeometry = undecidedGlyphGeometry();
  const undecidedMaterial = new MeshStandardMaterial({
    name: "trace-undecided",
    metalness: 0,
    /* LIT, not glowing. At emissive 1.9 over a 0.3x albedo the emission swamped every lighting
       term and the torus rendered as one flat lavender (C5 critic, z-torus-low.png). The hue is
       carried by the albedo now and the emission is a floor that keeps it legible on the dark
       stage; the key light and environment shade the tube, so it reads as an object. */
    roughness: 0.35,
    emissiveIntensity: 0.3,
  });
  const undecided = new Mesh(undecidedGeometry, undecidedMaterial);
  undecided.name = "trace-undecided";
  undecided.frustumCulled = false;
  undecided.visible = false;
  group.add(undecided);

  /* The stroke floor (MIN_STROKE_PX): it was 1.5, under design-brief §4.5's 2 CSS px minimum
     (C5 item 8 — every stroke the fabric paints is held to it; stroke-floor.test.ts). */
  const tetherMaterial = createCableMaterial("solid", MIN_STROKE_PX, 1, { vertexColors: false });
  tetherMaterial.depthTest = true;
  const tetherPositions = new Float32Array(6);
  const tetherGeometry = new LineGeometry();
  tetherGeometry.setPositions(tetherPositions);
  const tether = new Line2(tetherGeometry, tetherMaterial);
  tether.name = "trace-tether";
  tether.frustumCulled = false;
  tether.renderOrder = 4;
  tether.visible = false;
  group.add(tether);
  let tetherTint = "";
  // Declared before `applyTint` runs below, which overwrites both on every retint.
  const tetherColours = {
    stop: tokens.color("--sev-critical").clone(),
    undecided: tokens.color("--claim-indeterminate").clone(),
  };

  let points: Float32Array = new Float32Array(0);
  let cumulative: Float32Array = new Float32Array(0);
  let totalLength = 0;
  let reducedMotion = false;
  let revealStart = 0;
  let revealing = false;
  let packetStart = 0;
  let packetRunning = false;
  let undrawn: string[] = [];
  let sphere: { center: [number, number, number]; radius: number } | null = null;
  let terminalHost: string | null = null;
  /** The chassis the terminal glyph marks; the glyph's position follows the camera from it. */
  let terminalAnchor: TerminalAnchor | null = null;

  const applyTint = (t: TokenPalette): void => {
    const accent = t.color("--accent");
    const critical = t.color("--sev-critical");
    pathMaterial.color.copy(accent);
    blockedMaterial.color.copy(critical);
    arrowMaterial.color.copy(accent).multiplyScalar(0.25);
    arrowMaterial.emissive.copy(accent);
    packetMaterial.color.copy(accent).multiplyScalar(0.3);
    packetMaterial.emissive.copy(accent).multiplyScalar(1.15);
    stopMaterial.color.copy(critical).multiplyScalar(0.7);
    stopMaterial.emissive.copy(critical);
    /* Never the critical token: "the model could not decide" is not a fault of the network, and
       painting it in the alarm colour is how an undecided result gets read as a denied one. */
    const undecidedTint = t.color("--claim-indeterminate");
    undecidedMaterial.color.copy(undecidedTint).multiplyScalar(0.42);
    undecidedMaterial.emissive.copy(undecidedTint);
    tetherColours.stop = critical.clone();
    tetherColours.undecided = undecidedTint.clone();
    tetherTint = "";
    /* The trace strokes are cable strokes: their edge coverage is re-fitted to this palette's ground
       so it stays display-linear (geometry/cables.ts coverageGamma — without it the light stage
       washed a stroke's anti-aliased fringe out and the stroke read a pixel thinner). */
    const gamma = coverageGamma(t);
    for (const m of [pathMaterial, blockedMaterial, tetherMaterial]) setCoverageGamma(m, gamma);
  };
  applyTint(tokens);

  const sampleAt = (distance: number, out: Vector3): number => {
    if (cumulative.length < 2) return 0;
    const d = Math.min(Math.max(distance, 0), totalLength);
    // Linear scan. The path is at most a few hundred samples and this runs once per frame for one
    // marker; a binary search here would be optimising the wrong order of magnitude.
    let i = 1;
    while (i < cumulative.length - 1 && (cumulative[i] ?? 0) < d) i += 1;
    const c0 = cumulative[i - 1] ?? 0;
    const c1 = cumulative[i] ?? c0 + 1;
    const t = c1 - c0 < 1e-6 ? 0 : (d - c0) / (c1 - c0);
    _a.set(points[(i - 1) * 3] ?? 0, points[(i - 1) * 3 + 1] ?? 0, points[(i - 1) * 3 + 2] ?? 0);
    _b.set(points[i * 3] ?? 0, points[i * 3 + 1] ?? 0, points[i * 3 + 2] ?? 0);
    out.copy(_a).lerp(_b, t);
    _tangent.subVectors(_b, _a);
    if (_tangent.lengthSq() < 1e-9) _tangent.set(0, 0, 1);
    _tangent.normalize();
    return i;
  };

  const placeArrows = (): void => {
    if (totalLength <= ARROW_PITCH) {
      arrows.count = 0;
      return;
    }
    const n = Math.min(64, Math.floor(totalLength / ARROW_PITCH));
    for (let k = 0; k < n; k += 1) {
      const d = ((k + 0.5) * totalLength) / n;
      sampleAt(d, _v);
      _q.setFromUnitVectors(UP, _tangent);
      // setFromUnitVectors against +Y, then the geometry's own +Z alignment, gives a cone that
      // points along travel; a lookAt here would need a Matrix4 allocation per arrow.
      _m.compose(_v, _q, _scale);
      arrows.setMatrixAt(k, _m);
    }
    arrows.count = n;
    arrows.instanceMatrix.needsUpdate = true;
  };

  const _tetherNext = new Float32Array(6);
  /** Aim the tether at whichever terminal glyph is drawn. Returns true when anything changed. */
  function syncTether(q: Quaternion): boolean {
    const glyph = stop.visible ? stop : undecided.visible ? undecided : null;
    if (glyph === null || terminalAnchor === null) {
      if (!tether.visible) return false;
      tether.visible = false;
      return true;
    }
    let changed = false;
    const r = glyph === stop ? STOP_GLYPH_RADIUS : UNDECIDED_GLYPH_RADIUS;
    tetherEnds(terminalAnchor, glyph.position, r, q, _tetherNext);
    let moved = !tether.visible;
    for (let i = 0; i < 6 && !moved; i += 1) if (_tetherNext[i] !== tetherPositions[i]) moved = true;
    if (moved) {
      tetherPositions.set(_tetherNext);
      tetherGeometry.setPositions(tetherPositions);
      changed = true;
    }
    const tint = glyph === stop ? "stop" : "undecided";
    if (tint !== tetherTint) {
      tetherMaterial.color.copy(tetherColours[tint]);
      tetherTint = tint;
      changed = true;
    }
    if (!tether.visible) {
      tether.visible = true;
      changed = true;
    }
    return changed;
  }

  const overlay: FlowOverlay = {
    group,

    emissiveObjects(): Object3D[] {
      return [path, blocked, arrows, packet, stop, undecided];
    },

    setTrace(trace: Trace | null, activeHop: number | null, source: TraceSegmentSource): void {
      undrawn = [];
      sphere = null;
      terminalHost = null;
      terminalAnchor = null;
      if (trace === null || trace.hops.length === 0) {
        group.visible = false;
        path.visible = false;
        blocked.visible = false;
        stop.visible = false;
        undecided.visible = false;
        tether.visible = false;
        packet.visible = false;
        packetRunning = false;
        revealing = false;
        totalLength = 0;
        return;
      }

      /* Stitch the path out of the cables the hops actually traverse. A hop pair with no cable
         between them leaves a GAP and is reported through undrawnHops(); it is never bridged with
         a straight line, which would draw a wire the snapshot does not contain. */
      const acc: number[] = [];
      /* Where each hop sits on the drawn path, as a point index; -1 for a hop no drawn cable reaches.
         The terminal segment below ends at the hop the trace's ending is drawn on. */
      const hopPoint: number[] = trace.hops.map(() => -1);
      for (let i = 0; i < trace.hops.length - 1; i += 1) {
        const from = trace.hops[i];
        const to = trace.hops[i + 1];
        if (from === undefined || to === undefined) continue;
        const poly = source.polylineBetween(from.host, to.host);
        if (poly === null) {
          undrawn.push(`${from.host} -> ${to.host}`);
          continue;
        }
        const startAt = acc.length === 0 ? 0 : 3;
        if (hopPoint[i] === -1) hopPoint[i] = acc.length === 0 ? 0 : acc.length / 3 - 1;
        for (let p = startAt; p < poly.length; p += 3) {
          acc.push(poly[p] ?? 0, poly[p + 1] ?? 0, poly[p + 2] ?? 0);
        }
        hopPoint[i + 1] = acc.length / 3 - 1;
      }

      if (acc.length < 6) {
        // A single-hop or fully-undrawable trace still has an answer to show; there is simply no
        // line to draw. The stop glyph below still marks the terminal host.
        points = new Float32Array(0);
        cumulative = new Float32Array(0);
        totalLength = 0;
        path.visible = false;
        arrows.count = 0;
      } else {
        points = new Float32Array(acc);
        const n = points.length / 3;
        cumulative = new Float32Array(n);
        let run = 0;
        for (let i = 1; i < n; i += 1) {
          run += Math.hypot(
            (points[i * 3] ?? 0) - (points[(i - 1) * 3] ?? 0),
            (points[i * 3 + 1] ?? 0) - (points[(i - 1) * 3 + 1] ?? 0),
            (points[i * 3 + 2] ?? 0) - (points[(i - 1) * 3 + 2] ?? 0),
          );
          cumulative[i] = run;
        }
        totalLength = run;

        const geom = new LineGeometry();
        geom.setPositions(points);
        path.geometry.dispose();
        path.geometry = geom;
        path.computeLineDistances();
        path.visible = true;
        placeArrows();

        let minX = Infinity;
        let minY = Infinity;
        let minZ = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        let maxZ = -Infinity;
        for (let i = 0; i < n; i += 1) {
          const x = points[i * 3] ?? 0;
          const y = points[i * 3 + 1] ?? 0;
          const z = points[i * 3 + 2] ?? 0;
          minX = Math.min(minX, x);
          maxX = Math.max(maxX, x);
          minY = Math.min(minY, y);
          maxY = Math.max(maxY, y);
          minZ = Math.min(minZ, z);
          maxZ = Math.max(maxZ, z);
        }
        sphere = {
          center: [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2],
          radius: Math.max(6, Math.hypot(maxX - minX, maxY - minY, maxZ - minZ) / 2),
        };
      }

      /* THE TERMINAL TREATMENT, IN THREE STATES, ON THE HOP THE CHIP MARKS.
         Which hop the ending is drawn on, and which ending it is, is `traceEnd.ts :: traceEndOf` —
         the rule the label chip (Fabric3D.tsx `traceMarkOf`) uses, built on the claim layer's bands:
           blocked      the 6 px terminal segment plus the octagonal alarm — a fact about the packet.
           undetermined the open ring, in the indeterminate token, and NO alarm segment: the
                        simulation declined to decide, so there is nothing to alarm about yet.
           delivered    neither. An alarm on a delivered path is the inverse of the honesty rule.
         This used to be `outcome !== "delivered"`, which handed the red stop sign to every
         indeterminate and out-of-scope result as well; and then the trace band on the LAST hop,
         which hung the ring over core1 while the chip said "? UNDECIDED" on core2 (A5 refuter). */
      const end = traceEndOf(trace);
      const refuted = end !== null && end.kind === "blocked";
      const anchor = end === null ? null : source.anchorOf(end.host);
      terminalHost = end === null ? null : end.host;
      terminalAnchor = anchor;
      /* Provisional placement for an unrotated camera; `update` re-places the glyph for the real
         camera before any frame is drawn (see placeTerminalGlyph). */
      if (end !== null && end.kind === "undetermined" && anchor !== null) {
        placeTerminalGlyph(anchor, _qIdentity, UNDECIDED_GLYPH_RADIUS, undecided.position);
        undecided.visible = true;
      } else {
        undecided.visible = false;
      }
      if (refuted && end !== null) {
        if (anchor !== null) {
          placeTerminalGlyph(anchor, _qIdentity, STOP_GLYPH_RADIUS, stop.position);
          stop.visible = true;
        } else {
          stop.visible = false;
        }
        /* The segment runs INTO the stopping host: it ends where the drawn path last reaches that
           host, which for a trace the engine stops there is the end of the path. */
        let endAt = -1;
        for (let i = trace.hops.length - 1; i >= end.index && endAt < 0; i -= 1) {
          if (trace.hops[i]?.host === end.host) endAt = hopPoint[i] ?? -1;
        }
        const endLength = endAt >= 0 ? cumulative[endAt] ?? 0 : 0;
        if (endLength > 0) {
          const tailFrom = Math.max(0, endLength - Math.min(endLength * 0.5, 34));
          const tail: number[] = [];
          for (let i = 0; i <= endAt; i += 1) {
            if ((cumulative[i] ?? 0) >= tailFrom) {
              tail.push(points[i * 3] ?? 0, points[i * 3 + 1] ?? 0, points[i * 3 + 2] ?? 0);
            }
          }
          if (tail.length >= 6) {
            const bg = new LineGeometry();
            bg.setPositions(new Float32Array(tail));
            blocked.geometry.dispose();
            blocked.geometry = bg;
            blocked.computeLineDistances();
            blocked.visible = true;
          } else {
            blocked.visible = false;
          }
        } else {
          blocked.visible = false;
        }
      } else {
        stop.visible = false;
        blocked.visible = false;
      }

      // activeHop steers the packet's resting position when the user is stepping the hop list by
      // keyboard; it never moves the camera and never re-runs the draw-on.
      if (activeHop !== null && totalLength > 0 && trace.hops.length > 1) {
        const frac = Math.min(1, Math.max(0, activeHop / (trace.hops.length - 1)));
        sampleAt(frac * totalLength, _v);
        packet.position.copy(_v);
      }

      group.visible = true;
      revealing = !reducedMotion && totalLength > 0;
      revealStart = 0;
      if (!revealing) {
        pathMaterial.dashSize = Math.max(1, totalLength * 1.01);
        pathMaterial.gapSize = 0.001;
      } else {
        pathMaterial.dashSize = 0;
        pathMaterial.gapSize = Math.max(1, totalLength * 2);
      }
      packetRunning = !reducedMotion && totalLength > 0;
      packetStart = 0;
      packet.visible = packetRunning;
      // Provisional, like the glyphs above; `update` re-aims it for the real camera.
      syncTether(_qIdentity);
    },

    setResolution(width: number, height: number): void {
      pathMaterial.resolution.set(width, height);
      blockedMaterial.resolution.set(width, height);
    },

    setReducedMotion(reduced: boolean): void {
      reducedMotion = reduced;
      if (reduced) {
        revealing = false;
        packetRunning = false;
        packet.visible = false;
        if (totalLength > 0) {
          pathMaterial.dashSize = totalLength * 1.01;
          pathMaterial.gapSize = 0.001;
        }
      }
    },

    retint(t: TokenPalette): void {
      applyTint(t);
    },

    update(nowMs: number, camera: PerspectiveCamera): boolean {
      if (!group.visible) return false;
      let dirty = false;

      if (revealing) {
        if (revealStart === 0) revealStart = nowMs;
        const t = Math.min(1, (nowMs - revealStart) / DRAW_ON_MS);
        // ease-out cubic: the head of the path moves fastest at the start, which is what makes the
        // hop ORDER legible rather than just the path's existence.
        const k = 1 - Math.pow(1 - t, 3);
        pathMaterial.dashSize = totalLength * k * 1.01;
        dirty = true;
        if (t >= 1) {
          revealing = false;
          pathMaterial.dashSize = totalLength * 1.01;
          pathMaterial.gapSize = 0.001;
        }
      }

      if (packetRunning) {
        if (packetStart === 0) packetStart = nowMs;
        const elapsed = nowMs - packetStart;
        const loops = elapsed / PACKET_LOOP_MS;
        if (loops >= PACKET_LOOPS) {
          // Stops and leaves the path drawn. Nothing in this product loops forever.
          packetRunning = false;
          packet.visible = false;
          dirty = true;
        } else {
          const frac = loops - Math.floor(loops);
          sampleAt(frac * totalLength, _v);
          packet.position.copy(_v);
          _q.setFromUnitVectors(UP, _tangent);
          packet.quaternion.copy(_q);
          dirty = true;
        }
      }

      // Billboard by copying the camera's orientation — one quaternion copy, no allocation, and
      // it cannot drift out of plane the way an incremental lookAt can. Both terminal glyphs get
      // it: a ring seen edge-on is a line, which is no shape channel at all.
      for (const glyph of [stop, undecided]) {
        if (!glyph.visible) continue;
        if (!glyph.quaternion.equals(camera.quaternion)) {
          glyph.quaternion.copy(camera.quaternion);
          dirty = true;
        }
        if (terminalAnchor !== null) {
          const r = glyph === stop ? STOP_GLYPH_RADIUS : UNDECIDED_GLYPH_RADIUS;
          placeTerminalGlyph(terminalAnchor, camera.quaternion, r, _v);
          if (!glyph.position.equals(_v)) {
            glyph.position.copy(_v);
            dirty = true;
          }
        }
      }
      if (syncTether(camera.quaternion)) dirty = true;

      return dirty;
    },

    terminalMarker(): { host: string; center: [number, number, number]; radius: number } | null {
      if (terminalHost === null) return null;
      const glyph = stop.visible ? stop : undecided.visible ? undecided : null;
      if (glyph === null) return null;
      const radius = glyph === stop ? STOP_GLYPH_RADIUS : UNDECIDED_GLYPH_RADIUS;
      return { host: terminalHost, center: [glyph.position.x, glyph.position.y, glyph.position.z], radius };
    },

    pathSphere(): { center: [number, number, number]; radius: number } | null {
      return sphere;
    },

    pathPoints(): Float32Array {
      return group.visible && path.visible ? points : EMPTY_POINTS;
    },

    undrawnHops(): string[] {
      return undrawn;
    },

    dispose(): void {
      path.geometry.dispose();
      blocked.geometry.dispose();
      pathMaterial.dispose();
      blockedMaterial.dispose();
      arrowGeometry.dispose();
      arrowMaterial.dispose();
      arrows.dispose();
      packetGeometry.dispose();
      packetMaterial.dispose();
      stopGeometry.dispose();
      stopMaterial.dispose();
      undecidedGeometry.dispose();
      undecidedMaterial.dispose();
      tetherGeometry.dispose();
      tetherMaterial.dispose();
      group.clear();
    },
  };

  return overlay;
}
