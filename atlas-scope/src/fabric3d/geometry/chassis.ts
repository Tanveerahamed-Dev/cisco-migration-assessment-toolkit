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
 *   - port bank: ONE plate carrying a mipmapped port-grille texture (materials.ts, GRILLE_*) on a
 *     second UV set. It used to be a GRID of 0.16-0.18-unit metal bars over a dark backplate, and
 *     that grid is geometry below Nyquist at every overview distance: a bar is under one pixel,
 *     so it rasterises in some columns and not others and the bank breaks into glyph-like shapes
 *     ("PUE4I8", "NO35HN") — measured at low tier at every zoom the camera allows, and at high tier
 *     at DPR 1 on access-tier chassis (review/shots/render-audit3/crop2x-core1-low.png,
 *     z-zf-access11.png). Geometry has no mip chain; a texture does. Minified, the grille now
 *     averages to its mean tone instead of aliasing, at every tier and every DPR.
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
  CircleGeometry,
  CylinderGeometry,
  EdgesGeometry,
  Float32BufferAttribute,
  LatheGeometry,
  Matrix4,
  PlaneGeometry,
  RingGeometry,
  Vector2,
} from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { CHASSIS_EXTENT } from "../layout";
import type { RoleGlyphClass } from "../../core/roles";

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

/** The band indicator bar on a rack chassis faceplate (world units). See buildRackMount. */
const LED_BAR_W = 1.7;
const LED_BAR_H = 0.6;

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
  /* THE HOOD: the painted top cover carried forward over the faceplate frame (C5 motion, 2026-09-22).
     MEASURED with review/capture-motion.mjs's own orbit-keys-slow replay plus a per-cluster raycast
     and isolation (removing geometry in-page, one part at a time): every flip-flop cluster the
     harness reported on a chassis edge was the TOP FACE OF THE FRAME'S TOP BAR — a 0.34-deep strip
     of bright bare metal standing proud of the body's front edge, 0.17 below the lid. From the
     camera's range (polar 24-78 degrees) that strip is under a pixel wide at the overview, between
     the band-tinted lid and the ground, so it crawled as the damped orbit crept (0.03 px/frame) —
     not a depth tie (no two surfaces along any cluster ray were within 0.2 units). Removing the bar
     removed the clusters; changing its roughness, normal map or anisotropy did not.
     So the cover now runs over it: body paint from the lid's flat top (the bevel starts at
     hz - bevel) to the faceplate's front plane, down to the bar. Seen from above the lid simply ends
     at the faceplate — one edge, lid to ground — and the metal frame still reads from the front. */
  bodyParts.push(
    at(uvScale(rbox(w - 2 * bevel, 0.17, frameT + bevel, 1, 0.02), 3), 0, h / 2 - 0.085, hz + (frameT - bevel) / 2),
  );
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
    const bankH = Math.min(innerH - 0.5, rows * 0.78);
    const gridZ = hz + 0.04;
    /* One plate, one texture tile per port (see the header). The plate still stands proud of the
       well's back wall, so the bank keeps its silhouette depth against the frame; what moved into
       the texture is only the sub-pixel bar pattern that geometry cannot filter. */
    // grilleUv reads UV0 as 0..1 across the plate, so it runs BEFORE uvScale rescales UV0.
    const plate = box(portRegion, bankH, 0.2);
    grilleUv(plate, cols, rows);
    uvScale(plate, 2);
    bezelParts.push(at(plate, portLeft + portRegion / 2, 0, gridZ));
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
  /* The band bar fills the status region's width and is LED_BAR_H tall. It was 1.15 x 0.2 — about
     5 x 1 px at the overview — and at that size the band hue could not be read off the render at
     all: the chassis BODY cannot carry it either (scene.ts BODY_BAND_TINT history: AgX compresses the lit
     lid's chroma until Poor and Critical sit ~5 dE apart), so in practice the band was read from
     the DOM chip letter, not the 3-D view (C5 audit). */
  const ledX = -innerW / 2 + ledRegion / 2 - 0.05;
  const barTop = innerH / 2 - 0.18;
  ledParts.push(at(box(LED_BAR_W, LED_BAR_H, 0.07), ledX, barTop - LED_BAR_H / 2, hz + 0.24));
  for (let i = 0; i < 3; i += 1) {
    ledParts.push(at(box(0.16, 0.16, 0.06), ledX - 0.42 + i * 0.42, barTop - LED_BAR_H - 0.3, hz + 0.24));
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
    const slotD = d * 0.5;
    /* ONE plate carrying the grille texture, not `slots` dark boxes (C5 critic, 2026-09-22). The
       slats were 0.3-unit geometry at a 0.66-unit pitch — under a pixel at the overview at DPR 1 —
       so the bank of 16 aliased into 3-4 diagonal bars that crawled under a 3 px orbit, at BOTH
       tiers (SMAA cannot recover sub-pixel geometry). This is the port bank's own fix, applied to
       the same class of feature: a texture has a mip chain and geometry does not, so minified the
       vent now averages to its mean tone instead of beating against the pixel grid. */
    const vent = box(bankW, 0.03, slotD);
    ventUv(vent, slots);
    uvScale(vent, 2);
    bezelParts.push(at(vent, w * 0.26, h / 2 + 0.085, -d * 0.06));
    // A shallow recessed tray around the louvers, so the slots sit in a panel rather than on the lid.
    /* BURIED UNTIL 2026-09-21. The slots spanned h/2 - 0.08 .. + 0.02 and this tray h/2 - 0.12 .. - 0.04,
       while the lid panel above tops out at h/2 + 0.04 — so both sat INSIDE the lid and the louvers,
       the high tier's main piece of lid detail, never drew a pixel (found auditing why high and low
       looked alike, C5). Tray now h/2 + 0.04 .. + 0.07 on the lid, slots + 0.07 .. + 0.10 on it. */
    bodyParts.push(at(uvScale(rbox(bankW + 0.5, 0.03, slotD + 0.5, 1, 0.012), 2), w * 0.26, h / 2 + 0.055, -d * 0.06));
  }

  /* OVERVIEW CUES — the part of the hardware the default camera can actually resolve.
     MEASURED (C5 audit, both tiers): at the overview distance each chassis is a ~40 px tinted slab;
     port, ear and LED detail only resolves when dollied in, because it is all on the FRONT face and
     the default view looks steeply down at the LID. So three features are carried on the lid at
     every tier — merged into parts that already exist, so they cost triangles, never draw calls:
       - a front lip: the dark top edge of the faceplate, the line that says "this side is the front";
       - the status bar echoed on the lid's front-left corner, emissive and instance-coloured like
         the faceplate bar, so the band reads from the overview instead of only from the label chip;
       - at the tiers without the louvered vent bank, one dark vent panel where the bank sits.
     Each is sized for ~2 px of depth at the overview (the lid is foreshortened by cos(polar)). */
  const lidY = h / 2 + 0.07;
  darkParts.push(at(box(w - 1.2, 0.06, 0.7), 0, lidY, hz - 0.5));
  ledParts.push(at(box(LED_BAR_W * 2, 0.06, 1.2), -w / 2 + 0.6 + LED_BAR_W, lidY + 0.01, hz - 1.6));
  if (!fineDetail && spec.ventSlots > 0) {
    darkParts.push(at(box(w * 0.42, 0.06, d * 0.5), w * 0.26, lidY, -d * 0.06));
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

/**
 * Second UV set for the port-grille map (materials.ts, `grille`, texture channel 1): one texture
 * tile per port, so a plate of `cols` x `rows` ports repeats the tile that many times.
 */
function grilleUv(g: BufferGeometry, cols: number, rows: number): void {
  const uv = g.getAttribute("uv");
  const out = new Float32Array(uv.count * 2);
  for (let i = 0; i < uv.count; i += 1) {
    out[i * 2] = uv.getX(i) * cols;
    out[i * 2 + 1] = uv.getY(i) * rows;
  }
  g.setAttribute("uv1", new Float32BufferAttribute(out, 2));
}

/**
 * The lid vent bank on the same grille map: one tile per slot across U, and a CONSTANT V on a row
 * of the tile that crosses only bar metal and the dark opening (below the contact block, above the
 * upper-bar shadow). Across the bank that reads as dark slots between metal ribs; the constant V has
 * zero derivative, so the sampler's mip level follows the slot pitch alone and the bank minifies to
 * its mean tone. Exported so a test can pin the row against `grilleTile`.
 */
export const VENT_ROW_V = 0.2;
function ventUv(g: BufferGeometry, slots: number): void {
  const uv = g.getAttribute("uv");
  const out = new Float32Array(uv.count * 2);
  for (let i = 0; i < uv.count; i += 1) {
    out[i * 2] = uv.getX(i) * slots;
    out[i * 2 + 1] = VENT_ROW_V;
  }
  g.setAttribute("uv1", new Float32BufferAttribute(out, 2));
}

/**
 * Every other bezel part samples the grille at ONE constant point inside the tile's metal bar
 * (GRILLE_METAL_UV), which is white, so the map multiplies the bezel colour by exactly 1. A
 * constant UV has zero screen-space derivatives, so the sampler stays on mip 0 — the averaged
 * darker mips of the port openings can never reach the frame, however far away it is.
 */
export const GRILLE_METAL_UV: readonly [number, number] = [0.02, 0.5];
function ensureGrilleUv(g: BufferGeometry): BufferGeometry {
  if (g.getAttribute("uv1") !== undefined) return g;
  const n = g.getAttribute("position").count;
  const out = new Float32Array(n * 2);
  for (let i = 0; i < n; i += 1) {
    out[i * 2] = GRILLE_METAL_UV[0];
    out[i * 2 + 1] = GRILLE_METAL_UV[1];
  }
  g.setAttribute("uv1", new Float32BufferAttribute(out, 2));
  return g;
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
    bezel: mergeOrEmpty(bezelParts.map(ensureGrilleUv)),
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

export interface ChassisBuildOptions {
  bevelSegments: number;
  fineDetail: boolean;
}

function buildChassisUncached(k: ChassisKind, opts: ChassisBuildOptions): ChassisParts {
  const spec = SPEC[k];
  return k === "ap"
    ? buildAccessPoint(spec, opts.bevelSegments)
    : buildRackMount(spec, opts.bevelSegments, opts.fineDetail);
}

/* ── pre-built chassis: the geometry work moved OFF the scene-creation task ──────────────────────
 *
 * Acceptance E5, cold load (review finding, 2026-09-22): `createScene` ran as ONE ~150-260 ms task in
 * the Fabric3D mount effect, and a keystroke fired while it ran waited for all of it. CPU profile of
 * the release build (sourcemapped): buildChassis was ~26 % of that task — the rounded-box bevels,
 * port grids and vent slots of each rack-mount kind, merged. It is pure, deterministic and
 * tier-independent (quality.ts SCENE_DETAIL), so it can be done earlier, one kind per slice with a
 * yield between, exactly as the procedural map bytes already are (materials.ts
 * prepareProceduralMaps). `buildChassis` then hands out CLONES of the prepared parts, so every
 * caller still owns — and disposes — its own geometry, and a later rebuild never shares buffers
 * with a disposed graph. Without a prepare call nothing changes: the parts are built in place. */
const prepared = new Map<string, ChassisParts>();
const preparedKey = (k: ChassisKind, o: ChassisBuildOptions): string =>
  `${k}|${o.bevelSegments}|${o.fineDetail ? 1 : 0}`;

function cloneParts(src: ChassisParts): ChassisParts {
  const parts: ChassisParts = {
    body: src.body.clone(),
    bezel: src.bezel.clone(),
    dark: src.dark.clone(),
    rail: src.rail.clone(),
    led: src.led.clone(),
    half: [src.half[0], src.half[1], src.half[2]],
    topY: src.topY,
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

export function buildChassis(kind: string, opts: ChassisBuildOptions): ChassisParts {
  const k = normaliseKind(kind);
  const ready = prepared.get(preparedKey(k, opts));
  return ready === undefined ? buildChassisUncached(k, opts) : cloneParts(ready);
}

/** Every chassis kind `normaliseKind` can return, so a caller can prepare them all up front. */
export const ALL_CHASSIS_KINDS: readonly ChassisKind[] = Object.freeze(["device", "router", "ap"]);

/** True once every kind in `kinds` has prepared parts for `opts`. */
export function chassisPrepared(kinds: Iterable<string>, opts: ChassisBuildOptions): boolean {
  for (const kind of kinds) if (!prepared.has(preparedKey(normaliseKind(kind), opts))) return false;
  return true;
}

/**
 * Build the parts for every kind in `kinds` ahead of the scene, ONE kind per slice, yielding to the
 * event loop before each. Idempotent: a kind already prepared costs nothing. Yield is
 * `scheduler.yield()` where it exists (resumes ahead of other queued tasks) and a zero timeout
 * otherwise — the same rule as materials.ts prepareProceduralMaps, stated there.
 */
export async function prepareChassis(kinds: Iterable<string>, opts: ChassisBuildOptions): Promise<void> {
  const sched = (globalThis as { scheduler?: { yield?: () => Promise<void> } }).scheduler;
  const yieldNow = (): Promise<void> =>
    typeof sched?.yield === "function"
      ? sched.yield()
      : new Promise<void>((resolve) => {
          setTimeout(resolve, 0);
        });
  const todo = new Set<ChassisKind>();
  for (const kind of kinds) todo.add(normaliseKind(kind));
  for (const k of todo) {
    const key = preparedKey(k, opts);
    if (prepared.has(key)) continue;
    await yieldNow();
    if (!prepared.has(key)) prepared.set(key, buildChassisUncached(k, opts));
  }
}

/* ── secondary geometry, shared across kinds ───────────────────────────────── */

/**
 * The wireframe silhouette drawn over an uncollected device. Built from the BODY only: running
 * edge detection over the ports and vents of a device we never reached would draw detail we did
 * not observe, which is precisely the lie this treatment exists to prevent.
 *
 * Built from the kind's REFERENCE body (one bevel segment, no fine detail), never from the tier's
 * own tessellation. At 24 degrees a single-segment bevel keeps every real corner, but the high
 * tier's three-segment bevel turns each corner into facets under the threshold, and the outline
 * lost its twelve box edges: measured, the uncollected router rendered as a see-through wireframe
 * box at `low` and as an apparently opaque shell at `high` (72 edge vertices against 144). A
 * "never collected" encoding that disappears on better hardware is absence rendered as health.
 */
export function chassisSilhouette(kind: string): BufferGeometry {
  if (normaliseKind(kind) === "ap") return accessPointSilhouette();
  const reference = buildChassis(kind, { bevelSegments: 1, fineDetail: false });
  // 24 degrees: keeps the bevel's facet ring out of the outline while retaining every real corner.
  const edges = new EdgesGeometry(reference.body, 24);
  for (const g of [reference.body, reference.bezel, reference.dark, reference.rail, reference.led]) g.dispose();
  return edges;
}

/**
 * The access point's outline: ONE ring at its widest radius, at mid-height.
 *
 * Edge detection over a lathe is the wrong tool for a curved form. Every break in the fillet
 * profile (seven segments, 15-45 degrees apart) passes the 24-degree threshold somewhere, so the
 * EdgesGeometry of the radome was four or five concentric rings stacked at the rim — MEASURED (C5
 * critic, AP-floor1 dollied in, both tiers): contour lines that read as a stack of coins, and
 * nothing like the rack kinds' clean box outline. The puck's silhouette from any orbit angle is
 * dominated by its widest circle, so that circle is the outline, as line segments.
 */
function accessPointSilhouette(): BufferGeometry {
  const r = SPEC.ap.width / 2;
  const segments = 96;
  const pos = new Float32Array(segments * 6);
  for (let i = 0; i < segments; i += 1) {
    const a0 = (i / segments) * Math.PI * 2;
    const a1 = ((i + 1) / segments) * Math.PI * 2;
    pos.set([Math.cos(a0) * r, 0, Math.sin(a0) * r, Math.cos(a1) * r, 0, Math.sin(a1) * r], i * 6);
  }
  const g = new BufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(pos, 3));
  return g;
}

export type StateRingShape = "solid" | "dashed" | "double";

/**
 * Height (world units — the instance matrix scales the ring in X/Z only) of the low curb every
 * ring band stands on.
 *
 * WHY THE RING IS NOT FLAT. It was a bare RingGeometry lying on the deck: a band 0.07 of the
 * footprint radius wide (~0.8 units) whose near arc, seen at the 12-degree elevation the orbit
 * clamp allows (camera.ts MAX_POLAR 78 degrees), projects to 0.8 x sin 12 = 0.17 units — under one
 * pixel at every overview distance. Coverage that is not there cannot be anti-aliased, so the
 * SOLID ring (`up`) rasterised as a row of dashes that crawled with a 1-2 px camera nudge and read
 * exactly like the DASHED ring (`not collected / unknown`): a meaning collision (C5 critic,
 * reproduced 2026-09-21 on access16 at high tier).
 *
 * A vertical wall keeps its projected height at grazing angles (0.45 x cos 12 = 0.44 units, which
 * with the band's own 0.17 is ~3.6x the old coverage; 0.3 was tried and still broke on the second
 * row back) and is edge-on, i.e. invisible, from above,
 * so the ring's read at the default 32-degree view barely changes. Each band gets an outward wall
 * on its outer edge (the near arc) and an inward wall on its inner edge (the far arc), so it keeps
 * a front-facing surface on every side without a double-sided material.
 */
export const STATE_RING_WALL = 0.45;

/** CylinderGeometry measures theta from +Z towards +X; the flattened RingGeometry from +X towards -Z. */
const RING_TO_CYLINDER_THETA = Math.PI / 2;

/** An open cylinder wall between y0 and y1, facing outwards (or inwards when `inward`). */
function ringWall(
  radius: number,
  y0: number,
  y1: number,
  segments: number,
  thetaStart: number,
  thetaLength: number,
  inward: boolean,
): BufferGeometry {
  const g = new CylinderGeometry(
    radius,
    radius,
    y1 - y0,
    segments,
    1,
    true,
    thetaStart + RING_TO_CYLINDER_THETA,
    thetaLength,
  ).toNonIndexed();
  at(g, 0, (y0 + y1) / 2, 0);
  if (inward) {
    // Reverse the winding and the normals so the face points at the ring's centre.
    for (const name of ["position", "normal", "uv"]) {
      const a = g.getAttribute(name);
      for (let t = 0; t < a.count; t += 3) {
        for (let c = 0; c < a.itemSize; c += 1) {
          const v1 = a.getComponent(t + 1, c);
          a.setComponent(t + 1, c, a.getComponent(t + 2, c));
          a.setComponent(t + 2, c, v1);
        }
      }
    }
    const n = g.getAttribute("normal");
    for (let i = 0; i < n.count; i += 1) n.setXYZ(i, -n.getX(i), -n.getY(i), -n.getZ(i));
  }
  return g;
}

/**
 * The operational-state ring, laid on the deck around a chassis footprint.
 *
 * Three SHAPES, not three colours. `up`, `down` and `unknown` must be distinguishable in a
 * greyscale capture (acceptance D8), and a ring on the deck is legible from the default camera
 * elevation in a way a rim on a vertical faceplate is not. Unit radius 1: the instance matrix
 * scales it to the chassis footprint, which is why one geometry serves all three kinds.
 *
 * Each band is a flat annulus plus a low curb (STATE_RING_WALL). The shapes survive grazing views
 * because the curb carries them too: the dashed ring's curb is dashed with it, and the double
 * ring's outer curb is split into two stacked stripes, so from the side it still reads as two
 * lines rather than one thick one.
 */
export function buildStateRing(shape: StateRingShape): BufferGeometry {
  const flat = (g: BufferGeometry): BufferGeometry => {
    g.applyMatrix4(m4.makeRotationX(-Math.PI / 2));
    return g;
  };
  const band = (
    inner: number,
    outer: number,
    segments: number,
    thetaStart = 0,
    thetaLength = Math.PI * 2,
    outerStripes: readonly (readonly [number, number])[] = [[0, STATE_RING_WALL]],
  ): BufferGeometry[] => [
    flat(new RingGeometry(inner, outer, segments, 1, thetaStart, thetaLength).toNonIndexed()),
    ...outerStripes.map(([y0, y1]) => ringWall(outer, y0, y1, segments, thetaStart, thetaLength, false)),
    ringWall(inner, 0, STATE_RING_WALL, segments, thetaStart, thetaLength, true),
  ];
  if (shape === "solid") {
    return mergeOrEmpty(band(0.93, 1.0, 72));
  }
  if (shape === "double") {
    const h = STATE_RING_WALL;
    return mergeOrEmpty([
      ...band(0.86, 0.915, 72),
      // Two stripes with a gap between them, one wall-height apart: the side view of "two lines".
      ...band(0.955, 1.01, 72, 0, Math.PI * 2, [
        [0, h * 0.8],
        [h * 1.6, h * 2.4],
      ]),
    ]);
  }
  const dashes: BufferGeometry[] = [];
  const count = 10;
  const span = (Math.PI * 2) / count;
  for (let i = 0; i < count; i += 1) {
    dashes.push(...band(0.93, 1.0, 6, i * span, span * 0.55));
  }
  return mergeOrEmpty(dashes);
}

/** One glyph per class the role owner (src/core/roles.ts roleGlyphClass) can return — the type IS the owner's. */
export type RoleGlyph = RoleGlyphClass;

/** Every role glyph, in draw order. Typed against the owner's class set, so a class with no glyph is a type error. */
export const ROLE_GLYPHS: readonly RoleGlyph[] = (() => {
  const all: Record<RoleGlyph, true> = { access: true, distribution: true, other: true, unobserved: true };
  return Object.keys(all) as RoleGlyph[];
})();

/**
 * The role glyph, extruded 0.08 off the faceplate.
 *
 * `unobserved` means the snapshot never stated a role (null or blank; how many devices that is depends on the
 * loaded snapshot — read it from the data, never from this comment). Its glyph is an OUTLINED open rectangle — a
 * visible mark that says "we did not observe a role", not an absent glyph, which would be indistinguishable from
 * a device whose glyph failed to draw.
 *
 * `other` is an OBSERVED role outside access/distribution (core, spine, backbone, ... — the engine emits them).
 * It used to fall through to the unobserved mark, drawing an observed fact as absence. Its glyph is one solid
 * bar: the mark the legend's "Other role" row draws, and nothing like the four-bar open rectangle.
 */
export function buildRoleGlyph(glyph: RoleGlyph): BufferGeometry {
  const t = 0.1;
  if (glyph === "other") {
    return mergeOrEmpty([at(box(0.52, 0.11, t), 0, 0, 0)]);
  }
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
    /* The two arms CROSS where they meet, and at equal thickness their faces there were coplanar
       and overlapping — a depth tie on the lid (C5; `chassis.coplanar.test.ts` found it: planes
       0.0000 apart, overlap 0.019). The right arm is 0.02 thicker, so where the arms cross its faces
       stand 0.01 proud of the left arm's (0.021 world units after the scene's 2.1 scale): resolved
       by the depth buffer, and invisible as a step at any camera distance. */
    const armR = box(0.09, 0.42, t + 0.02);
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

/** Unit-diameter disc in the XZ plane, UV-mapped like `unitDecal` — the hatch on a round lid. */
export function unitDiscDecal(): BufferGeometry {
  const g = new CircleGeometry(0.5, 64).toNonIndexed();
  g.applyMatrix4(m4.makeRotationX(-Math.PI / 2));
  return g;
}

/** Unit quad in the XZ plane, used for hatch decals, contact shadows and the selection halo. */
export function unitDecal(): BufferGeometry {
  const g = new PlaneGeometry(1, 1).toNonIndexed();
  g.applyMatrix4(m4.makeRotationX(-Math.PI / 2));
  return g;
}
