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
 *                only looping animation in the product; it exists to distinguish a live trace
 *                overlay from a static screenshot of a path.
 *   arrowheads   not animated. Direction is permanent information and does not need movement.
 *   stop glyph   not animated. An alarm that pulses is decoration; an alarm that is simply THERE,
 *                octagonal, and red is read faster.
 * Under `prefers-reduced-motion` the draw-on completes instantly and the packet never runs. The end
 * state is identical: reduced motion removes movement, never information.
 */
import {
  BufferGeometry,
  ConeGeometry,
  CylinderGeometry,
  Group,
  InstancedMesh,
  Matrix4,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  Quaternion,
  TorusGeometry,
  Vector3,
  type PerspectiveCamera,
} from "three";
import { Line2 } from "three/addons/lines/Line2.js";
import { LineGeometry } from "three/addons/lines/LineGeometry.js";
import { bandOfOutcome } from "../core/claims";
import type { Trace } from "../core/types";
import { createCableMaterial } from "./geometry/cables";
import type { TokenPalette } from "./materials";

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
  /** Anchor for the stop glyph and any per-host marker. */
  anchorOf(host: string): { x: number; y: number; z: number; top: number } | null;
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
  /** Hops that could not be drawn because no cable joins them. Surfaced, never silently skipped. */
  undrawnHops(): string[];
  dispose(): void;
}

const _v = new Vector3();
const _a = new Vector3();
const _b = new Vector3();
const _tangent = new Vector3();
const _q = new Quaternion();
const _scale = new Vector3(1, 1, 1);
const _m = new Matrix4();
const UP = new Vector3(0, 1, 0);

/** The blocked-hop alarm: an octagonal prism, billboarded. Shape first, colour second. */
function stopGlyphGeometry(): BufferGeometry {
  // An 8-sided cylinder read face-on is an octagon; using a prism rather than a flat polygon means
  // the glyph still reads when the camera is not exactly perpendicular to it.
  // Sized so the octagon SHAPE survives at overview distance and through the bloom. At 2.4 units
  // it was six pixels across and read as a red dot — colour with no second channel, which is the
  // one thing the alarm treatment must never be.
  const g = new CylinderGeometry(5.4, 5.4, 1.2, 8, 1);
  g.applyMatrix4(new Matrix4().makeRotationX(Math.PI / 2));
  g.applyMatrix4(new Matrix4().makeRotationZ(Math.PI / 8));
  return g;
}

/**
 * The UNDECIDED terminal glyph: an OPEN RING, billboarded.
 *
 * It exists because this file used to divide traces in two — `outcome !== "delivered"` — and hand
 * the red octagonal alarm to everything on the wrong side of that line. An indeterminate trace
 * therefore ended in the same stop sign, in the same critical red, as a flow a filter genuinely
 * dropped: the canvas asserted a definite failure the engine had explicitly refused to assert.
 * `claims.ts :: bandOfOutcome` owns that mapping and it has three values, not two.
 *
 * The shape is the first channel and it is deliberately the opposite of a stop sign: a filled
 * octagon is an instruction, an open ring is a hole in the evidence. Colour is the second channel
 * (`--claim-indeterminate`), never the only one.
 */
function undecidedGlyphGeometry(): BufferGeometry {
  // Radius matched to the octagon's so the two marks occupy the same visual weight at the same
  // distance — an undecided result is not a quieter result than a denial.
  return new TorusGeometry(4.6, 1.05, 8, 20);
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
    roughness: 0.5,
    emissiveIntensity: 1.9,
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
    roughness: 0.5,
    emissiveIntensity: 1.9,
  });
  const undecided = new Mesh(undecidedGeometry, undecidedMaterial);
  undecided.name = "trace-undecided";
  undecided.frustumCulled = false;
  undecided.visible = false;
  group.add(undecided);

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

  const applyTint = (t: TokenPalette): void => {
    const accent = t.color("--accent");
    const critical = t.color("--sev-critical");
    pathMaterial.color.copy(accent);
    blockedMaterial.color.copy(critical);
    arrowMaterial.color.copy(accent).multiplyScalar(0.25);
    arrowMaterial.emissive.copy(accent);
    packetMaterial.color.copy(accent).multiplyScalar(0.3);
    packetMaterial.emissive.copy(accent).multiplyScalar(1.15);
    stopMaterial.color.copy(critical).multiplyScalar(0.3);
    stopMaterial.emissive.copy(critical);
    /* Never the critical token: "the model could not decide" is not a fault of the network, and
       painting it in the alarm colour is how an undecided result gets read as a denied one. */
    const undecidedTint = t.color("--claim-indeterminate");
    undecidedMaterial.color.copy(undecidedTint).multiplyScalar(0.3);
    undecidedMaterial.emissive.copy(undecidedTint);
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

  const overlay: FlowOverlay = {
    group,

    emissiveObjects(): Object3D[] {
      return [path, blocked, arrows, packet, stop, undecided];
    },

    setTrace(trace: Trace | null, activeHop: number | null, source: TraceSegmentSource): void {
      undrawn = [];
      sphere = null;
      if (trace === null || trace.hops.length === 0) {
        group.visible = false;
        path.visible = false;
        blocked.visible = false;
        stop.visible = false;
        undecided.visible = false;
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
        for (let p = startAt; p < poly.length; p += 3) {
          acc.push(poly[p] ?? 0, poly[p + 1] ?? 0, poly[p + 2] ?? 0);
        }
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

      /* THE TERMINAL TREATMENT, IN THREE STATES.
         The terminal hop is where the answer is, and which mark it gets is decided by
         `claims.ts :: bandOfOutcome`, not by a local test:
           REFUTED      the 6 px terminal segment plus the octagonal alarm — a fact about the packet.
           UNDETERMINED the open ring, in the indeterminate token, and NO alarm segment: the
                        simulation declined to decide, so there is nothing to alarm about yet.
           RESOLVED     neither. An alarm on a delivered path is the inverse of the honesty rule.
         This used to be `outcome !== "delivered"`, which handed the red stop sign to every
         indeterminate and out-of-scope result as well. */
      const last = trace.hops[trace.hops.length - 1];
      const band = bandOfOutcome(trace.outcome);
      const refuted = band === "REFUTED";
      const anchor = last === undefined ? null : source.anchorOf(last.host);
      if (band === "UNDETERMINED" && anchor !== null) {
        undecided.position.set(anchor.x, anchor.top + 11, anchor.z);
        undecided.visible = true;
      } else {
        undecided.visible = false;
      }
      if (refuted && last !== undefined) {
        if (anchor !== null) {
          stop.position.set(anchor.x, anchor.top + 11, anchor.z);
          stop.visible = true;
        } else {
          stop.visible = false;
        }
        if (totalLength > 0) {
          const tailFrom = Math.max(0, totalLength - Math.min(totalLength * 0.5, 34));
          const tail: number[] = [];
          for (let i = 0; i < cumulative.length; i += 1) {
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
      }

      return dirty;
    },

    pathSphere(): { center: [number, number, number]; radius: number } | null {
      return sphere;
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
      group.clear();
    },
  };

  return overlay;
}
