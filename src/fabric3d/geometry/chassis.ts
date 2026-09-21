/**
 * chassis.ts — rack hardware, built to read as hardware at the silhouette.
 *
 * The test this geometry has to pass is the one a critic applies without knowing they are applying
 * it: at overview distance a box is a box, and a box is a placeholder. What separates a chassis from
 * a placeholder is a bevelled edge that catches the key light, a faceplate that is genuinely proud
 * of the body, port openings with real depth behind them, and a rack ear that breaks the rectangle.
 * All four are silhouette-level features, which is why they survive being 40 pixels tall.
 *
 * Everything here is merged per material and then instanced, because the second test is the draw
 * call budget: the entire fabric renders in under 120 calls (asserted in scene.ts), and a
 * per-device Mesh would spend that on the switches alone.
 *
 * Openings without CSG. Two techniques, chosen per feature:
 *   - port bank: a GRID of thin metal bars with a dark backplate 0.22 units behind it. The gaps
 *     between bars are real holes and carry real parallax.
 *   - SFP cage / console: a dark plate seated 0.03 units proud of a slightly larger metal plate,
 *     so the metal reads as a surround. Two boxes instead of eighteen, at the size where parallax
 *     would not be visible anyway.
 *
 * Coordinates: origin at the chassis CENTRE (layout.ts publishes node.y as the centre plane, which
 * is why `bounds` is ±CHASSIS_EXTENT.height/2 around it), front face towards +Z, which is the side
 * the default camera is on.
 */
import {
  BoxGeometry,
  BufferGeometry,
  EdgesGeometry,
  LatheGeometry,
  Matrix4,
  PlaneGeometry,
  RingGeometry,
  Vector2,
} from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { CHASSIS_EXTENT } from "../layout";

export type ChassisKind = "device" | "router" | "ap";

export interface ChassisParts {
  /** Painted metal shell. */
  body: BufferGeometry;
  /** Brushed faceplate, frame bars, cage surrounds, rack-ear plates' inner faces. */
  bezel: BufferGeometry;
  /** Cavities: port backplate, port jacks, cage mouths, vent slots. */
  dark: BufferGeometry;
  /** Anodised rack ears. */
  rail: BufferGeometry;
  /** Emissive activity indicators. */
  led: BufferGeometry;
  /** Half-extents of the whole assembly, for pick proxies and the hover shell. */
  half: [number, number, number];
  /** Y of the top face, for the uncollected hatch decal and the billboarded stop glyph. */
  topY: number;
  dispose(): void;
}

/**
 * The mesh is sized from the frozen layout constant rather than from the brief's own numbers.
 * design-brief.md §4.4 gives 9.0 x 1.8 x 5.4 for a switch, which was written against a ~140-unit
 * scene; `layout.ts` — which is frozen and owns the actual positions — reserves 16 x 5 x 11 per
 * node. Using the brief's absolute figures would leave every chassis sitting in a third of its own
 * footprint. The brief's *proportions* are preserved exactly: 5 : 1 : 3 for a switch and
 * 3.46 : 1 : 2.08 for a router, scaled to fit the reserved extent with clearance.
 */
const FIT = 0.95;
const W = CHASSIS_EXTENT.width * FIT;
const D = CHASSIS_EXTENT.depth * 0.83;

interface KindSpec {
  width: number;
  height: number;
  depth: number;
  /** Corner radius. Never zero: a hard-edged box has no highlight along its edge. */
  bevel: number;
  portCols: number;
  portRows: number;
  cages: number;
  ventSlots: number;
  /** Rack ears exist on rack-mount kit and not on a ceiling access point. */
  ears: boolean;
}

const SPEC: Readonly<Record<ChassisKind, KindSpec>> = Object.freeze({
  device: { width: W, height: 3.04, depth: D, bevel: 0.3, portCols: 12, portRows: 2, cages: 4, ventSlots: 16, ears: true },
  router: { width: W, height: 4.4, depth: D, bevel: 0.32, portCols: 6, portRows: 1, cages: 2, ventSlots: 12, ears: true },
  ap: { width: 7.2, height: 1.9, depth: 7.2, bevel: 0.3, portCols: 0, portRows: 0, cages: 0, ventSlots: 0, ears: false },
});

export function chassisSpec(kind: string): KindSpec {
  return SPEC[normaliseKind(kind)];
}

/** Anything the snapshot calls something else is drawn as a switch — never dropped, never hidden. */
export function normaliseKind(kind: string): ChassisKind {
  return kind === "router" || kind === "ap" ? kind : "device";
}

/* ── primitives ────────────────────────────────────────────────────────────── */

const m4 = new Matrix4();

function box(w: number, h: number, d: number): BufferGeometry {
  return new BoxGeometry(w, h, d).toNonIndexed();
}

function rbox(w: number, h: number, d: number, segments: number, radius: number): BufferGeometry {
  // RoundedBoxGeometry clamps its own radius, but a radius larger than half the smallest edge
  // produces a pill, not a bevel; clamping here keeps small frame bars from turning into tubes.
  const r = Math.min(radius, Math.min(w, h, d) * 0.28);
  return new RoundedBoxGeometry(w, h, d, Math.max(1, segments), r);
}

function at(g: BufferGeometry, x: number, y: number, z: number): BufferGeometry {
  g.applyMatrix4(m4.makeTranslation(x, y, z));
  return g;
}

/**
 * Bake texture density into the UVs rather than setting `texture.repeat`, because the ORM and
 * normal maps are shared by the chassis, the decks and the ground, and a shared texture can only
 * carry one repeat. Baking keeps one texture serving three very different world scales.
 */
function uvScale(g: BufferGeometry, s: number): BufferGeometry {
  const uv = g.getAttribute("uv");
  if (uv === undefined) return g;
  for (let i = 0; i < uv.count; i += 1) uv.setXY(i, uv.getX(i) * s, uv.getY(i) * s);
  uv.needsUpdate = true;
  return g;
}

function mergeOrEmpty(parts: BufferGeometry[]): BufferGeometry {
  if (parts.length === 0) return new BufferGeometry();
  const merged = mergeGeometries(parts, false);
  for (const p of parts) p.dispose();
  if (merged === null) throw new Error("chassis: geometry merge failed — mismatched attributes");
  merged.computeBoundingBox();
  merged.computeBoundingSphere();
  return merged;
}

/* ── the rack-mount kinds ──────────────────────────────────────────────────── */

function buildRackMount(spec: KindSpec, bevelSegments: number, fineDetail: boolean): ChassisParts {
  const { width: w, height: h, depth: d, bevel } = spec;
  const hz = d / 2;

  const bodyParts: BufferGeometry[] = [uvScale(rbox(w, h, d, bevelSegments, bevel), 3)];
  const bezelParts: BufferGeometry[] = [];
  const darkParts: BufferGeometry[] = [];
  const railParts: BufferGeometry[] = [];
  const ledParts: BufferGeometry[] = [];

  /* Faceplate. A frame proud of the body by 0.34, with a 0.32-deep well behind it. That well is
     the single feature doing the most work: it is what stops the front face reading as a decal. */
  const frameZ = hz + 0.17;
  const frameT = 0.34;
  const barH = 0.42;
  const barW = 0.4;
  const innerW = w - 2 * barW - 0.6;
  const innerH = h - 2 * barH - 0.34;

  bezelParts.push(at(uvScale(rbox(w - 0.6, barH, frameT, 1, 0.08), 2), 0, h / 2 - barH / 2 - 0.17, frameZ));
  bezelParts.push(at(uvScale(rbox(w - 0.6, barH, frameT, 1, 0.08), 2), 0, -h / 2 + barH / 2 + 0.17, frameZ));
  bezelParts.push(at(uvScale(rbox(barW, innerH, frameT, 1, 0.08), 2), -innerW / 2 - barW / 2, 0, frameZ));
  bezelParts.push(at(uvScale(rbox(barW, innerH, frameT, 1, 0.08), 2), innerW / 2 + barW / 2, 0, frameZ));

  // The well's back wall. Everything mounted on the faceplate reads against this.
  darkParts.push(at(box(innerW, innerH, 0.12), 0, 0, hz - 0.15));

  /* Regions across the faceplate: indicators | ports | cages. Laid out left to right the way real
     kit is, so the eye finds the status block in the same place on every device. */
  const ledRegion = 1.9;
  const cageRegion = spec.cages === 0 ? 0 : spec.cages * 1.05 + 0.3;
  const portRegion = Math.max(0, innerW - ledRegion - cageRegion - 0.5);
  const portLeft = -innerW / 2 + ledRegion + 0.25;

  if (spec.portCols > 0 && spec.portRows > 0 && portRegion > 0.8) {
    const cols = spec.portCols;
    const rows = spec.portRows;
    const cellW = portRegion / cols;
    const bankH = Math.min(innerH - 0.5, rows * 0.78);
    const cellH = bankH / rows;
    const barT = 0.16;
    const gridZ = hz + 0.04;

    // Horizontal separators, then verticals: the bars ARE the metal and the gaps are the ports.
    for (let r = 0; r <= rows; r += 1) {
      const y = -bankH / 2 + r * cellH;
      bezelParts.push(at(box(portRegion + barT, barT, 0.2), portLeft + portRegion / 2, y, gridZ));
    }
    for (let c = 0; c <= cols; c += 1) {
      const x = portLeft + c * cellW;
      bezelParts.push(at(box(0.18, bankH + barT, 0.2), x, 0, gridZ));
    }
    // The contact block inside each opening. Small, but it is what gives the bank its texture at
    // distance — a flat dark rectangle behind a grid reads as a printed pattern.
    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        const x = portLeft + (c + 0.5) * cellW;
        const y = -bankH / 2 + (r + 0.5) * cellH;
        darkParts.push(at(box(cellW * 0.6, cellH * 0.44, 0.08), x, y, hz - 0.06));
      }
    }
  }

  if (spec.cages > 0) {
    const cageW = 0.86;
    const cageH = Math.min(0.7, innerH * 0.42);
    const right = innerW / 2 - 0.2;
    for (let i = 0; i < spec.cages; i += 1) {
      const x = right - (i + 0.5) * 1.05;
      const y = spec.cages > 2 && i % 2 === 1 ? -cageH * 0.62 : cageH * 0.62;
      bezelParts.push(at(uvScale(rbox(cageW, cageH, 0.3, 1, 0.05), 2), x, y, hz + 0.1));
      // Seated 0.03 proud of the surround so the pair can never be coplanar; z-fighting at this
      // scale would flicker across the whole fabric as the camera moves.
      darkParts.push(at(box(cageW - 0.22, cageH - 0.2, 0.06), x, y, hz + 0.26));
    }
  }

  /* Status block: one band indicator bar plus three activity pips. Emissive, and driven by the
     instance colour, so the band a device is in is legible from the overview without a label. */
  const ledX = -innerW / 2 + ledRegion / 2 - 0.05;
  ledParts.push(at(box(1.15, 0.2, 0.07), ledX, innerH / 2 - 0.3, hz + 0.24));
  for (let i = 0; i < 3; i += 1) {
    ledParts.push(at(box(0.16, 0.16, 0.06), ledX - 0.42 + i * 0.42, innerH / 2 - 0.72, hz + 0.24));
  }

  /* The lid panel. A shallow inset covering most of the top, raised 0.05 off the shell so a
     hairline seam runs right around it.
     This is the single highest-value piece of detail in the whole chassis: the top face is the
     largest surface the default camera sees, and an unbroken rectangle of it is what made the
     earlier build read as a box with a picture of ports on the front. The seam catches the key
     light along two edges and puts a real highlight where there was a flat field. */
  bodyParts.push(
    at(uvScale(rbox(w - 1.1, 0.1, d - 1.1, 1, 0.07), 3), 0, h / 2 - 0.01, 0),
  );
  if (fineDetail) {
    // Two fixing screws on the lid's centre line. Small, but they are what set the SCALE of the
    // whole object: without a known-size feature a chassis could be any size at all.
    for (const sx of [-1, 1]) {
      darkParts.push(at(box(0.22, 0.09, 0.22), sx * (w / 2 - 1.0), h / 2 + 0.05, -d / 2 + 0.75));
    }
  }

  /* Ventilation. On the TOP face, because the default camera looks down at ~30 degrees and the top
     is the largest visible surface — vents on the sides would be invisible work. */
  if (fineDetail && spec.ventSlots > 0) {
    const slots = spec.ventSlots;
    const bankW = w * 0.42;
    const pitch = bankW / slots;
    const slotD = d * 0.5;
    for (let i = 0; i < slots; i += 1) {
      const x = w * 0.26 - bankW / 2 + i * pitch;
      darkParts.push(at(box(pitch * 0.45, 0.1, slotD), x, h / 2 - 0.03, -d * 0.06));
    }
    // A shallow recessed tray around the louvers, so the slots sit in a panel rather than on the lid.
    bodyParts.push(at(uvScale(rbox(bankW + 0.5, 0.08, slotD + 0.5, 1, 0.06), 2), w * 0.26, h / 2 - 0.08, -d * 0.06));
  }

  /* Rack ears. They break the rectangle at exactly the place the eye checks for scale, and the
     two dimples on each ear are the only sub-centimetre detail worth spending triangles on. */
  if (spec.ears) {
    const earW = 0.78;
    for (const sx of [-1, 1]) {
      const x = sx * (w / 2 + earW / 2 - 0.05);
      railParts.push(at(uvScale(rbox(earW, h * 0.86, 0.36, 1, 0.07), 2), x, 0, hz - 0.02));
      if (fineDetail) {
        for (const sy of [-1, 1]) {
          darkParts.push(at(box(0.2, 0.2, 0.1), x, sy * h * 0.26, hz + 0.14));
        }
      }
    }
  }

  const half: [number, number, number] = [
    w / 2 + (spec.ears ? 0.78 : 0),
    h / 2,
    d / 2 + 0.4,
  ];

  return finish(bodyParts, bezelParts, darkParts, railParts, ledParts, half, h / 2);
}

/* ── the access point ──────────────────────────────────────────────────────── */

/**
 * A lathed profile rather than a cylinder plus a cap. A cylinder's rim is a hard 90-degree edge
 * that catches no light and immediately reads as a primitive; the fillet in this profile is the
 * whole difference between "an access point" and "a disc".
 */
function buildAccessPoint(spec: KindSpec, bevelSegments: number): ChassisParts {
  const r = spec.width / 2;
  const h = spec.height;
  const fillet = 0.34;
  /* Radial resolution, driven by the tier like every other curved form.
   *
   * It was a fixed 48 — 7.5 degrees per facet — which is a countable polygon on the one shape in
   * this scene with no straight edges to hide behind: at 4x DPR the radome's rim reads as a ring of
   * short chords rather than a curve, the C5 "low-poly silhouette on a curved form" case. The
   * `chassisBevelSegments` knob existed and this builder ignored it, so the AP was the one kind
   * whose detail never responded to quality at all.
   *
   * 96 / 64 / 32 for high / balanced / low: 3.75 degrees per facet at high, which is below the
   * facet width a 4x-DPR crop can resolve at this camera distance. There are exactly 2 access
   * points in the snapshot and the geometry is shared per kind, so high costs about 200 extra
   * triangles against the ~231,000 the frame already draws. */
  const radial = Math.max(24, bevelSegments * 32);
  const profile: Vector2[] = [
    new Vector2(0, -h / 2),
    new Vector2(r - fillet, -h / 2),
    new Vector2(r - fillet * 0.35, -h / 2 + fillet * 0.3),
    new Vector2(r, -h / 2 + fillet),
    new Vector2(r, h / 2 - fillet),
    new Vector2(r - fillet * 0.35, h / 2 - fillet * 0.3),
    new Vector2(r - fillet, h / 2),
    new Vector2(0, h / 2),
  ];
  const body = uvScale(new LatheGeometry(profile, radial).toNonIndexed(), 3);

  // The seam ring where the radome meets the base casting — the one feature that tells a viewer
  // this is a two-part moulding and not a puck.
  const bezelParts: BufferGeometry[] = [];
  const ring = new RingGeometry(r - 0.42, r - 0.12, Math.max(18, Math.round(radial * 1.17)), 1).toNonIndexed();
  ring.applyMatrix4(m4.makeRotationX(-Math.PI / 2));
  bezelParts.push(at(ring, 0, h / 2 - 0.02, 0));

  const darkParts: BufferGeometry[] = [];
  const mount = new RingGeometry(r * 0.32, r * 0.58, Math.max(14, Math.round(radial * 0.83)), 1).toNonIndexed();
  mount.applyMatrix4(m4.makeRotationX(Math.PI / 2));
  darkParts.push(at(mount, 0, -h / 2 - 0.01, 0));

  const ledParts: BufferGeometry[] = [
    at(new BoxGeometry(0.9, 0.06, 0.22).toNonIndexed(), 0, h / 2 + 0.01, r * 0.42),
  ];

  return finish([body], bezelParts, darkParts, [], ledParts, [r, h / 2, r], h / 2);
}

function finish(
  bodyParts: BufferGeometry[],
  bezelParts: BufferGeometry[],
  darkParts: BufferGeometry[],
  railParts: BufferGeometry[],
  ledParts: BufferGeometry[],
  half: [number, number, number],
  topY: number,
): ChassisParts {
  const parts: ChassisParts = {
    body: mergeOrEmpty(bodyParts),
    bezel: mergeOrEmpty(bezelParts),
    dark: mergeOrEmpty(darkParts),
    rail: mergeOrEmpty(railParts),
    led: mergeOrEmpty(ledParts),
    half,
    topY,
    dispose(): void {
      parts.body.dispose();
      parts.bezel.dispose();
      parts.dark.dispose();
      parts.rail.dispose();
      parts.led.dispose();
    },
  };
  return parts;
}

export function buildChassis(
  kind: string,
  opts: { bevelSegments: number; fineDetail: boolean },
): ChassisParts {
  const k = normaliseKind(kind);
  const spec = SPEC[k];
  return k === "ap"
    ? buildAccessPoint(spec, opts.bevelSegments)
    : buildRackMount(spec, opts.bevelSegments, opts.fineDetail);
}

/* ── secondary geometry, shared across kinds ───────────────────────────────── */

/**
 * The wireframe silhouette drawn over an uncollected device. Built from the BODY only: running
 * edge detection over the ports and vents of a device we never reached would draw detail we did
 * not observe, which is precisely the lie this treatment exists to prevent.
 */
export function chassisSilhouette(parts: ChassisParts): BufferGeometry {
  // 24 degrees: keeps the bevel's facet ring out of the outline while retaining every real corner.
  return new EdgesGeometry(parts.body, 24);
}

export type StateRingShape = "solid" | "dashed" | "double";

/**
 * The operational-state ring, laid flat on the deck around a chassis footprint.
 *
 * Three SHAPES, not three colours. `up`, `down` and `unknown` must be distinguishable in a
 * greyscale capture (acceptance D8), and a ring on the deck is legible from the default camera
 * elevation in a way a rim on a vertical faceplate is not. Unit radius 1: the instance matrix
 * scales it to the chassis footprint, which is why one geometry serves all three kinds.
 */
export function buildStateRing(shape: StateRingShape): BufferGeometry {
  const flat = (g: BufferGeometry): BufferGeometry => {
    g.applyMatrix4(m4.makeRotationX(-Math.PI / 2));
    return g;
  };
  if (shape === "solid") {
    return flat(new RingGeometry(0.93, 1.0, 72, 1).toNonIndexed());
  }
  if (shape === "double") {
    const inner = flat(new RingGeometry(0.86, 0.915, 72, 1).toNonIndexed());
    const outer = flat(new RingGeometry(0.955, 1.01, 72, 1).toNonIndexed());
    return mergeOrEmpty([inner, outer]);
  }
  const dashes: BufferGeometry[] = [];
  const count = 10;
  const span = (Math.PI * 2) / count;
  for (let i = 0; i < count; i += 1) {
    dashes.push(flat(new RingGeometry(0.93, 1.0, 6, 1, i * span, span * 0.55).toNonIndexed()));
  }
  return mergeOrEmpty(dashes);
}

export type RoleGlyph = "access" | "distribution" | "unobserved";

/**
 * The role glyph, extruded 0.08 off the faceplate.
 *
 * `unobserved` is the important one. 17 of the 26 devices in this snapshot carry `role: null`, and
 * the glyph for that is an OUTLINED dash — a visible mark that says "we did not observe a role",
 * not an absent glyph, which would be indistinguishable from a device whose glyph failed to draw.
 */
export function buildRoleGlyph(glyph: RoleGlyph): BufferGeometry {
  const t = 0.1;
  if (glyph === "access") {
    return mergeOrEmpty([
      at(box(0.62, 0.1, t), 0, 0.17, 0),
      at(box(0.62, 0.1, t), 0, 0, 0),
      at(box(0.62, 0.1, t), 0, -0.17, 0),
    ]);
  }
  if (glyph === "distribution") {
    const armL = box(0.09, 0.42, t);
    armL.applyMatrix4(m4.makeRotationZ(0.62));
    const armR = box(0.09, 0.42, t);
    armR.applyMatrix4(m4.makeRotationZ(-0.62));
    return mergeOrEmpty([at(armL, -0.11, 0, 0), at(armR, 0.11, 0, 0)]);
  }
  // An open rectangle: four thin bars around a hole, never a filled block.
  return mergeOrEmpty([
    at(box(0.62, 0.07, t), 0, 0.16, 0),
    at(box(0.62, 0.07, t), 0, -0.16, 0),
    at(box(0.07, 0.25, t), -0.275, 0, 0),
    at(box(0.07, 0.25, t), 0.275, 0, 0),
  ]);
}

/** Unit quad in the XZ plane, used for hatch decals, contact shadows and the selection halo. */
export function unitDecal(): BufferGeometry {
  const g = new PlaneGeometry(1, 1).toNonIndexed();
  g.applyMatrix4(m4.makeRotationX(-Math.PI / 2));
  return g;
}
