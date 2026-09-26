/**
 * layout.ts — where every device sits in 3-D space. Pure math: no three.js, no DOM, no clock.
 *
 * The view has to read like a network drawing, not a force-directed hairball, so the pipeline is
 * the classical layered one (Sugiyama), adapted to three dimensions:
 *
 *   1. LAYER   — the snapshot's tiers are grouped by hop distance from the hub tier, and the hub
 *                sits at the top. The tier *number* in the snapshot is a cable-map bucket, not a
 *                depth: in the reference fabric the core is tier 2, with access (1) and
 *                distribution (3) both one hop away. Reading the numbers as a Y ordering would
 *                hang the core off the middle of the drawing.
 *   2. ORDER   — barycentre sweeps inside each layer, keeping the best ordering seen, measured by
 *                the standard adjacent-layer crossing count.
 *   3. EMBED   — the 1-D order is laid into an X/Z grid COLUMN-major, so X stays monotonic in the
 *                order. That is what makes step 2 pay: the crossings the sweeps removed are the
 *                crossings the viewer would have seen from the default camera. Each deeper layer
 *                is stepped toward the camera in Z, so under the steep default view the tiers
 *                read as separate horizontal bands, top to bottom.
 *
 * Coverage honesty applies to geometry too. A device with no observed tier is still placed — never
 * dropped — but in a synthetic bucket that `observedTier: null` marks as not-observed, so no
 * surface can read its Y plane as evidence. The hub tier is chosen from the engine's own link
 * betweenness, and the basis of that choice is published in `diagnostics.rootTier`; it is never
 * inferred from a hostname. An absent route hint is likewise a positive claim — "the straight
 * cable is geometrically clear" — computed, not assumed, and re-verified by the test. So is a
 * PRESENT one: the suggested curve is measured against every chassis and either reports the
 * clearance it achieved or says it never found one, because an unevaluated remedy is not a remedy.
 */
import type { Cite, Device, Link } from "../core/types";
import type { CameraFraming, LayoutResult, NodePosition } from "./contract";

export type Vec3 = [number, number, number];

/* ── geometry contract shared with the renderer ─────────────────────────────
   The renderer builds its chassis mesh from CHASSIS_EXTENT and every pitch below is derived from
   it, so widening the mesh widens the spacing in the same edit. Geometry and layout cannot drift
   apart into intersecting boxes. Units are arbitrary "fabric units"; the camera scales to them. */
export const CHASSIS_EXTENT = Object.freeze({ width: 16, height: 5, depth: 11 });

/** Clear air between neighbouring chassis. Cables leave a rack sideways, so X is the roomier axis. */
export const NODE_GAP_X = 18;
export const NODE_GAP_Z = 17;
export const NODE_PITCH_X = CHASSIS_EXTENT.width + NODE_GAP_X;
export const NODE_PITCH_Z = CHASSIS_EXTENT.depth + NODE_GAP_Z;

/** Deterministic per-node jitter: enough to break the CAD lattice, far too small to reorder anything. */
export const JITTER_AMPLITUDE = 1.2;

/**
 * The guaranteed floor on centre-to-centre distance, and the number the renderer may assume when
 * sizing halos or labels. The tightest possible pair is two nodes stacked in Z in one column, each
 * jittered toward the other: NODE_PITCH_Z − 2·JITTER_AMPLITUDE. Every other pair (same row, next
 * column, next group, next layer) is further apart by construction.
 */
export const MIN_NODE_SEPARATION = NODE_PITCH_Z - 2 * JITTER_AMPLITUDE;

/**
 * Vertical distance between layers: ≥2× the deepest node pitch, leaving room for a tier band.
 * 80, not 64: with a tier wrapped into a block, an uplink to a FRONT row runs down its column over
 * the rows behind it, and at 64 core1→access2 passed 10.5 from access4 (72: still 11.5). At 80
 * every shipped cable is straight and clear, which layout.test.ts asserts rather than assumes.
 */
export const TIER_Y_PITCH = 80;

/** Clear X between the outer columns of two tier groups sharing a layer — one full node pitch. */
export const GROUP_GAP_X = NODE_PITCH_X;

/** Alternate columns shift in Z so a column behind is never perfectly eclipsed by the one in front. */
export const COLUMN_STAGGER_Z = NODE_PITCH_Z / 4;

/** A tier of ≤3 reads as one row; a longer one wraps into a block (see TARGET_TIER_ASPECT). */
export const SINGLE_ROW_MAX = 3;

/**
 * Target footprint aspect (X span : Z span) for a wide tier: near-square.
 *
 * This was 3:1, and the blind panel called the result damning: six chassis per row at the stage's
 * full width left each hostname ~60 px for an ~80 px label, so at 1440×900 11 of 26 labels were
 * dropped and four more sat on other devices' chassis (access14 over access16, access3 over
 * access17, …). The label is the unit that has to fit, not the chassis. A square block gives each
 * column the width of a label; the steep camera (VIEW_DIRECTION) keeps its back rows visible, and
 * the per-layer Z step (step 7) keeps a deep block from hanging over the tier beneath it.
 */
export const TARGET_TIER_ASPECT = 1;

/** Clear Z between the front row of one layer and the back row of the next (see step 7). */
export const LAYER_Z_GAP = NODE_GAP_Z;

/** A cable passing within this of another chassis centre is obstructed and gets a route hint. */
export const ROUTE_CLEARANCE = 12;
/** Obstruction is only interesting away from the ends; the endpoints themselves are not in the way. */
export const ROUTE_T_MARGIN = 0.05;
/**
 * APEX displacement of an intra-tier bow from the straight chord — the height the drawn cable
 * actually reaches, not the control point that produces it. A quadratic Bezier's apex sits at half
 * its control-point offset, so a constant applied directly to the control point buys only half the
 * clearance it names; `controlFor` does that doubling in one place so this number stays true.
 */
export const INTRA_TIER_BOW = 26;
/** Apex displacement behind the fabric of a cross-block detour — behind, never across the subject. */
export const SPAN_CLEARANCE = 48;
/**
 * Chords used to measure a suggested curve against the chassis. The polyline sits just inside the
 * curve, so it UNDERSTATES clearance: an error in the safe direction for a claim of clearance. At
 * 48 chords the sag over a fabric-scale cable is under a tenth of a unit against a 12-unit limit.
 */
export const ROUTE_CURVE_SAMPLES = 48;
/**
 * How many progressively wider detours are tried before a hint is published as unresolved. Bounded
 * because an unbounded search would always "succeed" by flinging the cable out of the frame, which
 * is a worse drawing than an honest "this one is still obstructed".
 */
export const ROUTE_DETOUR_STEPS = 6;

/**
 * Camera offset direction from target to eye: straight in front and steeply above (polar ≈ 32°,
 * inside camera.ts's [28°, 78°] clamp), with NO azimuth.
 *
 * It was [0.15, 0.55, 1] — a 3/4 isometric view. The blind panel's finding was that the
 * isometric slabs "read as a demo, carry no extra information, and widen the nodes so more labels
 * collide". Looking down steeply, a chassis reads as a flat tile of its role colour; with no
 * azimuth, every row of a tier is a horizontal band on screen, so the tiers read as core / middle
 * / edge bands top to bottom; and a row's labels sit on one baseline instead of a diagonal.
 */
export const VIEW_DIRECTION: Vec3 = [0, 1.6, 1];

export const DEFAULT_SEED = 0x5ca1ab1e;
export const DEFAULT_SWEEPS = 12;
export const DEFAULT_FOV_DEG = 45;
export const DEFAULT_ASPECT = 16 / 9;
export const DEFAULT_MARGIN = 1.15;
export const DEFAULT_FOCUS_MARGIN = 1.35;

/* ── result contract (extends contract.ts, which is frozen) ────────────────── */

export interface LayoutNode extends NodePosition {
  host: string;
  /**
   * The tier as OBSERVED. `null` means the snapshot never placed this device in a tier: `tier`
   * then holds the synthetic bucket it was drawn in, which is a drawing decision and not evidence.
   * A surface that labels the synthetic number as the device's tier is a coverage-honesty defect.
   */
  observedTier: number | null;
  /** Hop distance of this node's tier from the hub tier. 0 = top plane. */
  layer: number;
  /** Position within the layer after crossing reduction; X is monotonic in it. */
  rank: number;
  groupKey: string;
  /** false = topology-only neighbour. The renderer must not draw it as an assessed device. */
  collected: boolean;
  /**
   * Neighbours actually PLACED. It is a floor on the device's degree, not the degree: when
   * `droppedAdjacency` is non-zero, links naming this device were excluded for want of a device
   * record at the far end, and this count understates the topology by exactly that much.
   */
  degree: number;
  /** Links naming this device that carry no geometry because their far endpoint is unplaced. */
  droppedAdjacency: number;
  cite: Cite;
}

export interface FabricTierBounds {
  tier: number;
  layer: number;
  y: number;
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
  count: number;
  centerX: number;
  centerZ: number;
  columns: number;
  /** null when this tier is the synthetic bucket for devices with no observed tier. */
  observedTier: number | null;
  nodeIds: string[];
}

export interface BoundingSphere {
  center: Vec3;
  radius: number;
}

export interface FabricCameraFraming extends CameraFraming {
  up: Vec3;
  fovDeg: number;
  aspect: number;
  near: number;
  far: number;
  boundingSphere: BoundingSphere;
}

/**
 * A cable needs a control point only when the straight route is obstructed; the kind decides the
 * shape of the detour.
 *
 * There is deliberately no "spans non-adjacent layers" kind. Layers are BFS depths over the tier
 * adjacency graph, and every link IS an edge of that graph, so the depths of its two endpoints
 * can differ by at most one: a cable that has to arc around an intervening tier plane cannot
 * exist under this layering. The contract's case — a cable between tiers that are far apart in
 * the snapshot's numbering — is real and is served by `cross-tier-plane`, since hop-equal tiers
 * (access and distribution here) share a Y plane. The invariant is published as
 * `diagnostics.linksSpanningNonAdjacentLayers` rather than merely asserted in this comment.
 */
export type RouteHintKind = "intra-tier" | "cross-tier-plane" | "adjacent-obstructed";

/**
 * "cleared" is a MEASURED outcome: the suggested curve was sampled against every other chassis and
 * none of them is within ROUTE_CLEARANCE of it. "unresolved" means the bounded detour search never
 * found such a curve — the best one found is still published, because a cable drawn round a
 * partial detour beats one drawn straight through a chassis, but a renderer must not present it as
 * a solved route and must not let the hint's mere existence read as "handled".
 */
export type RouteResolution = "cleared" | "unresolved";

export interface RouteHint {
  linkId: string;
  kind: RouteHintKind;
  /** Suggested control point for a quadratic cable curve. */
  mid: Vec3;
  /** Distance from the straight route to the nearest obstructing chassis centre; null = none found. */
  clearance: number | null;
  blockedBy: string[];
  /**
   * Clearance of the SUGGESTED curve — the remedy measured, not the problem. Without it the hint
   * asserts a fix it never computed. null = never measured, which no emitted hint is.
   */
  routedClearance: number | null;
  /** Chassis the suggested curve STILL passes within ROUTE_CLEARANCE of. Empty iff "cleared". */
  routedBlockedBy: string[];
  resolution: RouteResolution;
  /** Apex displacement of the suggested curve from the straight chord — what the detour buys. */
  apexOffset: number;
  reason: string;
}

export type RootTierBasis = "link-betweenness" | "tier-graph-center" | "lowest-tier-index";

export interface RootTierEvidence {
  tier: number;
  basis: RootTierBasis;
  /** Highest observed link betweenness incident to the tier; null = centrality never computed. */
  maxBetweenness: number | null;
  meanBetweenness: number | null;
  observations: number;
  /**
   * Links that never reached this computation because an endpoint has no device record. The basis
   * above was derived on the surviving graph; a reader cannot weigh it without this denominator.
   */
  droppedLinks: number;
  detail: string;
}

export interface TierDisagreement {
  host: string;
  deviceTier: number;
  cableMapTier: number;
}

/**
 * How one cable-map group was reconciled with the device records. The partition names GROUPS; it
 * does not number tiers, and its array index is an artifact of serialisation. A group's tier is
 * therefore taken from what its members are RECORDED at, or it is left null.
 */
export type CableMapGroupBasis =
  | "device-consensus"
  | "device-majority"
  | "no-consensus"
  | "no-member-tier";

export interface CableMapGroup {
  index: number;
  members: number;
  /** The tier this group vouches for; null = the evidence does not support a number. */
  tier: number | null;
  basis: CableMapGroupBasis;
  /** Distinct tiers found on the members' own device records, sorted. */
  memberTiers: number[];
}

export interface DroppedAdjacency {
  host: string;
  /** Link ids naming this device whose OTHER endpoint has no device record. */
  droppedLinks: string[];
}

export interface LayoutDiagnostics {
  rootTier: RootTierEvidence;
  /** Placed, never dropped — but in a synthetic bucket that must be labelled "tier not observed". */
  devicesWithoutObservedTier: string[];
  syntheticTier: number | null;
  tierDisagreements: TierDisagreement[];
  /** One row per cable-map group, so the reconciliation above can be audited rather than trusted. */
  cableMapGroups: CableMapGroup[];
  cableMapHostsWithoutDevice: string[];
  /** Links naming a host with no device record: they contribute no geometry and are listed here. */
  linksWithUnplacedEndpoint: string[];
  /**
   * Placed by tier alone: no placed neighbour AND no dropped link — so "this device has no
   * neighbours" is a claim the evidence supports. A device whose links were merely dropped appears
   * in `hostsWithDroppedAdjacency` instead; missing evidence is not an absence of neighbours.
   */
  isolatedHosts: string[];
  /** Devices whose published degree understates their adjacency, and by which links. */
  hostsWithDroppedAdjacency: DroppedAdjacency[];
  tiersUnreachableFromRoot: number[];
  /** Links whose endpoints land more than one layer apart. Empty by construction (see
      RouteHintKind); a non-empty list means the layering invariant broke and cables are being
      drawn through tier planes. */
  linksSpanningNonAdjacentLayers: string[];
  sweeps: number;
  crossingsInitial: number;
  crossingsFinal: number;
}

export interface FabricLayout extends LayoutResult {
  nodes: LayoutNode[];
  byId: ReadonlyMap<string, LayoutNode>;
  tierBounds: FabricTierBounds[];
  framing: FabricCameraFraming;
  /** Y of each layer, index = hop distance from the hub tier. */
  layerY: number[];
  adjacency: ReadonlyMap<string, readonly string[]>;
  routeHints: RouteHint[];
  diagnostics: LayoutDiagnostics;
}

export interface LayoutOptions {
  devices: readonly Device[];
  links: readonly Link[];
  /**
   * `fabric.tiers` (the cable map's own tier partition). Optional: `device.tier` alone is enough.
   * When both are present they are reconciled — the device record wins and any disagreement is
   * reported rather than silently resolved.
   */
  tiers?: readonly (readonly string[])[];
  seed?: number;
  /** 0 = publish the naive snapshot ordering unchanged. Used to measure what the sweeps buy. */
  sweeps?: number;
  /**
   * Vertical distance between layers, for a renderer that wants a flatter fabric. Clamped up to
   * MIN_NODE_SEPARATION: the separation guarantee the renderer sizes its meshes against outranks a
   * caller asking for a pitch that would let two chassis touch across planes.
   */
  tierYPitch?: number;
  fovDeg?: number;
  aspect?: number;
  margin?: number;
}

/* ── deterministic noise ───────────────────────────────────────────────────── */

const fnv1a = (s: string): number => {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
};

/** mulberry32 — small, fast, and fully determined by its seed. */
const mulberry32 = (seed: number): (() => number) => {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};

/** Jitter is keyed by node id, not by iteration index, so input order cannot move a chassis. */
const jitterFor = (id: string, seed: number): [number, number] => {
  const rnd = mulberry32(fnv1a(id) ^ (seed >>> 0));
  return [(rnd() * 2 - 1) * JITTER_AMPLITUDE, (rnd() * 2 - 1) * JITTER_AMPLITUDE];
};

/* ── small helpers ─────────────────────────────────────────────────────────── */

const must = <T>(v: T | undefined, what: string): T => {
  if (v === undefined) throw new Error(`layout: ${what}`);
  return v;
};

const length3 = (v: Vec3): number => Math.hypot(v[0], v[1], v[2]);
const normalize = (v: Vec3): Vec3 => {
  const l = length3(v) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
};

/**
 * A supplied option must be a real number. Substituting the default for a NaN would hide the
 * caller's bug behind a plausible-looking fabric; clamping it would do the same. `Math.max(floor,
 * NaN)` is NaN, so every clamp downstream of an unchecked option is inert exactly when it matters.
 */
function finiteOption(name: string, v: number | undefined, fallback: number): number {
  if (v === undefined) return fallback;
  if (!Number.isFinite(v)) throw new Error(`layout: ${name} must be a finite number, got ${v}`);
  return v;
}

function rangedOption(name: string, v: number, lo: number, hi: number): number {
  if (v <= lo || v >= hi) throw new Error(`layout: ${name} must be in (${lo}, ${hi}), got ${v}`);
  return v;
}

/** Point on the quadratic Bezier through a and b with control point c. */
function quadraticAt(a: Vec3, c: Vec3, b: Vec3, t: number): Vec3 {
  const u = 1 - t;
  return [
    u * u * a[0] + 2 * u * t * c[0] + t * t * b[0],
    u * u * a[1] + 2 * u * t * c[1] + t * t * b[1],
    u * u * a[2] + 2 * u * t * c[2] + t * t * b[2],
  ];
}

/**
 * The control point that puts the curve's APEX `apex` units along `dir` from the chord midpoint.
 * At t=0.5 a quadratic reaches the midpoint of (chord mid, control), i.e. half the control offset —
 * the whole reason a detour constant applied straight to the control point under-delivers by 2×.
 */
function controlFor(mid: Vec3, dir: Vec3, apex: number): Vec3 {
  return [mid[0] + dir[0] * 2 * apex, mid[1] + dir[1] * 2 * apex, mid[2] + dir[2] * 2 * apex];
}

/** Distance from p to segment ab, with the clamped parameter along the segment. */
function pointToSegment(p: Vec3, a: Vec3, b: Vec3): { distance: number; t: number } {
  const ab: Vec3 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const len2 = ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2];
  const raw = len2 === 0 ? 0 : ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1] + (p[2] - a[2]) * ab[2]) / len2;
  const t = Math.max(0, Math.min(1, raw));
  const c: Vec3 = [a[0] + ab[0] * t, a[1] + ab[1] * t, a[2] + ab[2] * t];
  return { distance: Math.hypot(p[0] - c[0], p[1] - c[1], p[2] - c[2]), t };
}

/**
 * Clearance of a suggested curve, measured the same way the straight route is: nearest chassis
 * centre away from the endpoints. Sampling as a polyline rather than as points means the measure
 * covers the whole curve and not just the samples, and it errs low — the chords cut the corner the
 * curve rounds — so "clear" is never claimed on the strength of a gap between samples.
 */
function curveClearance(
  a: Vec3,
  control: Vec3,
  b: Vec3,
  obstacles: readonly { id: string; p: Vec3 }[],
): { nearest: number | null; blockedBy: string[] } {
  const pts: Vec3[] = [];
  for (let i = 0; i <= ROUTE_CURVE_SAMPLES; i += 1) {
    pts.push(quadraticAt(a, control, b, ROUTE_T_MARGIN + ((1 - 2 * ROUTE_T_MARGIN) * i) / ROUTE_CURVE_SAMPLES));
  }
  let nearest: number | null = null;
  const blockedBy: string[] = [];
  for (const o of obstacles) {
    let d = Infinity;
    for (let i = 1; i < pts.length; i += 1) {
      d = Math.min(d, pointToSegment(o.p, must(pts[i - 1], "curve sample"), must(pts[i], "curve sample")).distance);
    }
    if (nearest === null || d < nearest) nearest = d;
    if (d < ROUTE_CLEARANCE) blockedBy.push(o.id);
  }
  return { nearest, blockedBy: blockedBy.sort() };
}

/**
 * Widen the detour until the curve is actually clear, or run out of attempts and say so. Each step
 * adds one chassis-and-clearance of apex, so the first candidate is exactly the documented constant
 * and the ladder only grows where that constant provably fails.
 *
 * `dirs` is ordered by preference, not by merit: the first entry is the direction the drawing wants
 * and a later one is tried only after the preferred ladder provably fails, so a fallback can never
 * quietly displace a detour that reads correctly.
 */
function solveDetour(
  a: Vec3,
  mid: Vec3,
  b: Vec3,
  dirs: readonly Vec3[],
  baseApex: number,
  step: number,
  obstacles: readonly { id: string; p: Vec3 }[],
): { control: Vec3; apexOffset: number; nearest: number | null; blockedBy: string[]; resolution: RouteResolution } {
  let best: { control: Vec3; apexOffset: number; nearest: number | null; blockedBy: string[] } | null = null;
  for (const dir of dirs) {
    for (let i = 0; i < ROUTE_DETOUR_STEPS; i += 1) {
      const apexOffset = baseApex + i * step;
      const control = controlFor(mid, dir, apexOffset);
      const { nearest, blockedBy } = curveClearance(a, control, b, obstacles);
      if (blockedBy.length === 0) return { control, apexOffset, nearest, blockedBy, resolution: "cleared" };
      // Keep the widest clearance seen, not the last tried: the ladder is not guaranteed monotone
      // once a detour starts sweeping past a different row of chassis.
      if (best === null || (nearest ?? -Infinity) > (best.nearest ?? -Infinity)) {
        best = { control, apexOffset, nearest, blockedBy };
      }
    }
  }
  // ROUTE_DETOUR_STEPS is positive and `dirs` is never empty, so the ladder always ran; the throw
  // is here because a future zero would otherwise publish a hint with no geometry behind it.
  if (best === null) throw new Error("layout: detour ladder produced no candidate");
  return { ...best, resolution: "unresolved" };
}

/** Columns for a tier of n nodes: the count whose footprint lands nearest TARGET_TIER_ASPECT. */
function columnsFor(n: number): number {
  if (n <= SINGLE_ROW_MAX) return Math.max(1, n);
  const cols = Math.round(Math.sqrt((n * TARGET_TIER_ASPECT * NODE_PITCH_Z) / NODE_PITCH_X));
  return Math.min(n, Math.max(1, cols));
}

/** n items into `cols` columns, front-loaded, never differing by more than one — no ragged tail. */
function balancedColumns(n: number, cols: number): number[] {
  const base = Math.floor(n / cols);
  const extra = n % cols;
  return Array.from({ length: cols }, (_, i) => base + (i < extra ? 1 : 0));
}

/* ── layering ──────────────────────────────────────────────────────────────── */

interface Group {
  key: string;
  tier: number;
  ids: string[];
}
interface Layer {
  depth: number;
  groups: Group[];
}

/** Group order is part of the ordering, so a snapshot captures both levels verbatim. */
const snapshotOrder = (layers: Layer[]): Group[][] =>
  layers.map((l) => l.groups.map((g) => ({ key: g.key, tier: g.tier, ids: [...g.ids] })));

function restoreOrder(layers: Layer[], snap: Group[][]): void {
  layers.forEach((layer, li) => {
    layer.groups = must(snap[li], `missing layer snapshot ${li}`).map((g) => ({
      key: g.key,
      tier: g.tier,
      ids: [...g.ids],
    }));
  });
}

/* ── the engine ────────────────────────────────────────────────────────────── */

export function computeLayout(opts: LayoutOptions): FabricLayout {
  const seed = finiteOption("seed", opts.seed, DEFAULT_SEED) >>> 0;
  const sweepCount = Math.max(0, Math.trunc(finiteOption("sweeps", opts.sweeps, DEFAULT_SWEEPS)));
  const fovDeg = rangedOption("fovDeg", finiteOption("fovDeg", opts.fovDeg, DEFAULT_FOV_DEG), 0, 180);
  const aspect = rangedOption("aspect", finiteOption("aspect", opts.aspect, DEFAULT_ASPECT), 0, Infinity);
  const margin = rangedOption("margin", finiteOption("margin", opts.margin, DEFAULT_MARGIN), 0, Infinity);
  const tierYPitch = Math.max(
    MIN_NODE_SEPARATION,
    finiteOption("tierYPitch", opts.tierYPitch, TIER_Y_PITCH),
  );

  /* 1 — devices, in an order that does not depend on the caller's array order. */
  const devices = [...opts.devices].sort(
    (a, b) => a.order - b.order || a.id.localeCompare(b.id),
  );
  /** Links name hosts; devices are keyed by id. Resolve through both so neither spelling is lost. */
  const idOfHost = new Map<string, string>();
  for (const d of devices) {
    idOfHost.set(d.id, d.id);
    if (!idOfHost.has(d.host)) idOfHost.set(d.host, d.id);
  }

  /* 2 — tier membership, reconciled between the device record and the cable map.
     The cable map is a PARTITION: it says which devices share a tier, never which number that tier
     has. Adopting a group's array position as its number fabricates evidence precisely for the
     devices that have none — a device whose own record is null has nothing to disagree with, so
     the positional artifact would be published as `observedTier` and never cross-checked, and a
     reordering of the same partition would silently move it to another plane. Each group's number
     is therefore taken from what its own members are RECORDED at, or left null. */
  const recordTierOfHost = new Map<string, number | null>();
  for (const d of devices) {
    recordTierOfHost.set(d.id, d.tier);
    if (!recordTierOfHost.has(d.host)) recordTierOfHost.set(d.host, d.tier);
  }
  const tierGroups = opts.tiers ?? [];
  const cableMapGroups: CableMapGroup[] = tierGroups.map((hosts, index) => {
    const counts = new Map<number, number>();
    for (const h of hosts) {
      const t = recordTierOfHost.get(h);
      if (t !== undefined && t !== null) counts.set(t, (counts.get(t) ?? 0) + 1);
    }
    const memberTiers = [...counts.keys()].sort((a, b) => a - b);
    if (memberTiers.length === 0) {
      return { index, members: hosts.length, tier: null, basis: "no-member-tier", memberTiers };
    }
    if (memberTiers.length === 1) {
      return {
        index,
        members: hosts.length,
        tier: must(memberTiers[0], "consensus tier"),
        basis: "device-consensus",
        memberTiers,
      };
    }
    // Members disagree. A strict plurality still carries the group (and every dissenter is reported
    // below as a TierDisagreement); a tie carries nothing, and the group vouches for no number.
    const ranked = [...counts].sort((a, b) => b[1] - a[1] || a[0] - b[0]);
    const top = must(ranked[0], "plurality");
    const runnerUp = must(ranked[1], "runner-up");
    return top[1] > runnerUp[1]
      ? { index, members: hosts.length, tier: top[0], basis: "device-majority", memberTiers }
      : { index, members: hosts.length, tier: null, basis: "no-consensus", memberTiers };
  });
  const cableTier = new Map<string, number>();
  cableMapGroups.forEach((g) => {
    if (g.tier === null) return;
    for (const h of must(tierGroups[g.index], `tier group ${g.index}`)) {
      if (!cableTier.has(h)) cableTier.set(h, g.tier);
    }
  });
  const tierDisagreements: TierDisagreement[] = [];
  const observedTierOf = new Map<string, number | null>();
  const devicesWithoutObservedTier: string[] = [];
  let maxObservedTier = -1;
  for (const d of devices) {
    const fromCable = cableTier.get(d.host) ?? cableTier.get(d.id) ?? null;
    if (d.tier !== null && fromCable !== null && d.tier !== fromCable) {
      tierDisagreements.push({ host: d.host, deviceTier: d.tier, cableMapTier: fromCable });
    }
    const t = d.tier ?? fromCable;
    observedTierOf.set(d.id, t);
    if (t === null) devicesWithoutObservedTier.push(d.id);
    else maxObservedTier = Math.max(maxObservedTier, t);
  }
  devicesWithoutObservedTier.sort();
  const syntheticTier = devicesWithoutObservedTier.length > 0 ? maxObservedTier + 1 : null;
  const tierOf = (id: string): number => observedTierOf.get(id) ?? syntheticTier ?? 0;
  // Every host the cable map names, not just the ones a resolved group contributed: a group that
  // vouches for no tier still names hosts, and an unknown one there is the same coverage gap.
  const cableMapHostsWithoutDevice = [...new Set(tierGroups.flat())]
    .filter((h) => !idOfHost.has(h))
    .sort();

  /* 3 — adjacency over placed devices only. */
  const adjacency = new Map<string, Set<string>>();
  for (const d of devices) adjacency.set(d.id, new Set());
  const linksWithUnplacedEndpoint: string[] = [];
  /** Links naming a placed device whose far end is unplaced: adjacency this device HAS but that no
      geometry can carry. Without it a device whose evidence was dropped is indistinguishable from
      one that genuinely has no neighbours, and the drawing states a topology fact it cannot know. */
  const droppedByHost = new Map<string, string[]>();
  const placedLinks: { link: Link; a: string; b: string }[] = [];
  for (const link of opts.links) {
    const a = idOfHost.get(link.a);
    const b = idOfHost.get(link.b);
    if (a === undefined || b === undefined) {
      linksWithUnplacedEndpoint.push(link.id);
      // At most one end can have resolved here, and it is the one losing an adjacency.
      const resolved = a ?? b;
      if (resolved !== undefined) droppedByHost.set(resolved, [...(droppedByHost.get(resolved) ?? []), link.id]);
      continue;
    }
    placedLinks.push({ link, a, b });
    if (a === b) continue; // a self-adjacency carries no placement information
    must(adjacency.get(a), `no adjacency slot for ${a}`).add(b);
    must(adjacency.get(b), `no adjacency slot for ${b}`).add(a);
  }
  const adjSorted = new Map<string, string[]>(
    [...adjacency].map(([k, v]) => [k, [...v].sort()]),
  );
  const hostsWithDroppedAdjacency: DroppedAdjacency[] = [...droppedByHost]
    .map(([host, droppedLinks]) => ({ host, droppedLinks: [...droppedLinks].sort() }))
    .sort((a, b) => a.host.localeCompare(b.host));
  // "No neighbours" is a positive structural claim, so it requires that none were dropped either.
  const isolatedHosts = devices
    .filter((d) => (adjSorted.get(d.id) ?? []).length === 0 && (droppedByHost.get(d.id) ?? []).length === 0)
    .map((d) => d.id);

  /* 4 — the tier graph, and the hub tier chosen from the engine's own centrality.
     Absence of centrality is NOT a score of zero: a tier with no observed betweenness is simply
     not a candidate on that criterion, and the decision falls through to structure. */
  const tierList = [...new Set(devices.map((d) => tierOf(d.id)))].sort((a, b) => a - b);
  const tierNeighbours = new Map<number, Set<number>>(tierList.map((t) => [t, new Set<number>()]));
  const interTierLinkCount = new Map<number, number>(tierList.map((t) => [t, 0]));
  const btwObs = new Map<number, number[]>(tierList.map((t) => [t, []]));
  for (const { link, a, b } of placedLinks) {
    const ta = tierOf(a);
    const tb = tierOf(b);
    if (ta !== tb) {
      must(tierNeighbours.get(ta), `tier ${ta}`).add(tb);
      must(tierNeighbours.get(tb), `tier ${tb}`).add(ta);
      interTierLinkCount.set(ta, must(interTierLinkCount.get(ta), `tier ${ta}`) + 1);
      interTierLinkCount.set(tb, must(interTierLinkCount.get(tb), `tier ${tb}`) + 1);
    }
    if (link.betweenness !== null && Number.isFinite(link.betweenness)) {
      must(btwObs.get(ta), `tier ${ta}`).push(link.betweenness);
      if (ta !== tb) must(btwObs.get(tb), `tier ${tb}`).push(link.betweenness);
    }
  }
  const nonAccessRoles = new Map<number, number>(tierList.map((t) => [t, 0]));
  for (const d of devices) {
    if (d.role !== null && d.role.toLowerCase() !== "access") {
      const t = tierOf(d.id);
      nonAccessRoles.set(t, must(nonAccessRoles.get(t), `tier ${t}`) + 1);
    }
  }

  const eccentricity = (from: number): number => {
    const seen = new Map<number, number>([[from, 0]]);
    const queue = [from];
    let ecc = 0;
    for (let i = 0; i < queue.length; i += 1) {
      const cur = must(queue[i], "bfs queue");
      const d = must(seen.get(cur), "bfs depth");
      ecc = Math.max(ecc, d);
      for (const nb of must(tierNeighbours.get(cur), `tier ${cur}`)) {
        if (!seen.has(nb)) {
          seen.set(nb, d + 1);
          queue.push(nb);
        }
      }
    }
    // A tier that reaches less of the fabric is a worse hub than one that reaches all of it.
    return ecc + (tierList.length - seen.size) * 1000;
  };

  const stats = tierList.map((tier) => {
    const obs = must(btwObs.get(tier), `tier ${tier}`);
    const max = obs.length > 0 ? Math.max(...obs) : null;
    const mean = obs.length > 0 ? obs.reduce((s, v) => s + v, 0) / obs.length : null;
    return {
      tier,
      max,
      mean,
      observations: obs.length,
      ecc: eccentricity(tier),
      inter: must(interTierLinkCount.get(tier), `tier ${tier}`),
      roles: must(nonAccessRoles.get(tier), `tier ${tier}`),
    };
  });
  const hasEdges = [...tierNeighbours.values()].some((s) => s.size > 0);
  const withCentrality = stats.filter((s) => s.observations > 0);
  let rootBasis: RootTierBasis;
  let rootStat;
  if (withCentrality.length > 0) {
    // Primary: the single most central observed link touching the tier. In a classic core/dist/
    // access stack the top core↔dist link touches both tiers, so the mean breaks that tie in
    // favour of the tier whose OTHER links are also central — the core.
    rootBasis = "link-betweenness";
    rootStat = [...withCentrality].sort(
      (a, b) =>
        (b.max ?? 0) - (a.max ?? 0) ||
        (b.mean ?? 0) - (a.mean ?? 0) ||
        b.inter - a.inter ||
        b.roles - a.roles ||
        a.tier - b.tier,
    )[0];
  } else if (hasEdges) {
    // No centrality was computed anywhere: fall back to the centre of the tier graph.
    rootBasis = "tier-graph-center";
    rootStat = [...stats].sort(
      (a, b) => a.ecc - b.ecc || b.inter - a.inter || b.roles - a.roles || a.tier - b.tier,
    )[0];
  } else {
    rootBasis = "lowest-tier-index";
    rootStat = stats[0];
  }
  const root = must(rootStat, "no tiers to lay out");
  const rootDetail =
    rootBasis === "link-betweenness"
      ? `tier ${root.tier} carries the highest observed link betweenness (max ${root.max}, mean ` +
        `${(root.mean ?? 0).toFixed(2)} over ${root.observations} links with centrality)`
      : rootBasis === "tier-graph-center"
        ? `no link betweenness was observed; tier ${root.tier} is the centre of the tier adjacency graph`
        : `no inter-tier adjacency was observed; tier ${root.tier} taken as the lowest tier index`;
  const rootTier: RootTierEvidence = {
    tier: root.tier,
    basis: rootBasis,
    maxBetweenness: root.max,
    meanBetweenness: root.mean,
    observations: root.observations,
    droppedLinks: linksWithUnplacedEndpoint.length,
    // The basis above was derived on the surviving graph. Where links were excluded, the sentence
    // carries that denominator, so the evidence string cannot be quoted as if it saw everything.
    detail:
      linksWithUnplacedEndpoint.length > 0
        ? `${rootDetail}; computed without ${linksWithUnplacedEndpoint.length} links whose endpoint ` +
          `has no device record`
        : rootDetail,
  };

  /* 5 — hop depth of each tier from the hub. Unreachable tiers land one layer below the deepest
     reachable one and are named in diagnostics: they are drawn, but their depth is not evidence. */
  const depthOfTier = new Map<number, number>([[root.tier, 0]]);
  const queue = [root.tier];
  for (let i = 0; i < queue.length; i += 1) {
    const cur = must(queue[i], "bfs queue");
    const d = must(depthOfTier.get(cur), "bfs depth");
    for (const nb of [...must(tierNeighbours.get(cur), `tier ${cur}`)].sort((a, b) => a - b)) {
      if (!depthOfTier.has(nb)) {
        depthOfTier.set(nb, d + 1);
        queue.push(nb);
      }
    }
  }
  const tiersUnreachableFromRoot = tierList.filter((t) => !depthOfTier.has(t));
  const deepestReachable = Math.max(0, ...[...depthOfTier.values()]);
  for (const t of tiersUnreachableFromRoot) depthOfTier.set(t, deepestReachable + 1);
  const maxDepth = Math.max(...[...depthOfTier.values()]);

  /* 6 — initial ordering: the snapshot's own order, untouched. Sweeps must earn their reduction
     against THIS baseline, not against a head start from a smarter seed ordering. */
  const layers: Layer[] = Array.from({ length: maxDepth + 1 }, (_, depth) => ({ depth, groups: [] }));
  for (const tier of tierList) {
    const depth = must(depthOfTier.get(tier), `tier ${tier} depth`);
    const ids = devices.filter((d) => tierOf(d.id) === tier).map((d) => d.id);
    if (ids.length === 0) continue;
    must(layers[depth], `layer ${depth}`).groups.push({ key: `t${tier}`, tier, ids });
  }
  for (const layer of layers) layer.groups.sort((a, b) => a.tier - b.tier);

  const layerOf = new Map<string, number>();
  for (const layer of layers) for (const g of layer.groups) for (const id of g.ids) layerOf.set(id, layer.depth);

  const rankOf = new Map<string, number>();
  const refreshRanks = (): void => {
    for (const layer of layers) {
      let r = 0;
      for (const g of layer.groups) for (const id of g.ids) rankOf.set(id, r++);
    }
  };
  const sizeOfLayer = (depth: number): number =>
    (layers[depth]?.groups ?? []).reduce((s, g) => s + g.ids.length, 0);

  const crossings = (): number => {
    const edges: { layer: number; u: number; v: number }[] = [];
    for (const { a, b } of placedLinks) {
      const la = layerOf.get(a);
      const lb = layerOf.get(b);
      if (la === undefined || lb === undefined || Math.abs(la - lb) !== 1) continue;
      const upper = la < lb ? a : b;
      const lower = la < lb ? b : a;
      edges.push({
        layer: Math.min(la, lb),
        u: must(rankOf.get(upper), `rank ${upper}`),
        v: must(rankOf.get(lower), `rank ${lower}`),
      });
    }
    let n = 0;
    for (let i = 0; i < edges.length; i += 1) {
      for (let j = i + 1; j < edges.length; j += 1) {
        const e = must(edges[i], "edge");
        const f = must(edges[j], "edge");
        if (e.layer !== f.layer) continue;
        if ((e.u - f.u) * (e.v - f.v) < 0) n += 1;
      }
    }
    return n;
  };

  /** One barycentre pass over a layer against a fixed reference layer. */
  const reorderLayer = (layer: Layer, refDepth: number): void => {
    const size = sizeOfLayer(layer.depth);
    const refSize = sizeOfLayer(refDepth);
    const scale = size > 1 && refSize > 1 ? (refSize - 1) / (size - 1) : 1;
    const bary = new Map<string, number>();
    for (const g of layer.groups) {
      for (const id of g.ids) {
        let sum = 0;
        let n = 0;
        for (const nb of adjSorted.get(id) ?? []) {
          if (layerOf.get(nb) === refDepth) {
            sum += must(rankOf.get(nb), `rank ${nb}`);
            n += 1;
          }
        }
        // No neighbour in the reference layer: hold position, mapped into the reference's scale so
        // a parentless node is not flung to one end by a scale mismatch.
        bary.set(id, n > 0 ? sum / n : must(rankOf.get(id), `rank ${id}`) * scale);
      }
    }
    for (const g of layer.groups) {
      g.ids.sort(
        (a, b) =>
          must(bary.get(a), `bary ${a}`) - must(bary.get(b), `bary ${b}`) ||
          // Equal barycentre = equal crossing cost, so the tie is spent on readability: the
          // better-connected device takes the inner slot and single-homed leaves fall outboard.
          // Without this, the snapshot's own ordering drops a topology-only AP between the two
          // distribution switches and their port-channel has to be drawn around it.
          (adjSorted.get(b) ?? []).length - (adjSorted.get(a) ?? []).length ||
          must(rankOf.get(a), `rank ${a}`) - must(rankOf.get(b), `rank ${b}`),
      );
    }
    // Tier groups stay contiguous: a WAN router interleaved into a row of access switches would
    // shave a crossing or two and destroy the reading of the drawing. Groups move as blocks.
    const groupBary = new Map<string, number>(
      layer.groups.map((g) => [
        g.key,
        g.ids.reduce((s, id) => s + must(bary.get(id), `bary ${id}`), 0) / g.ids.length,
      ]),
    );
    const groupRank = new Map<string, number>(
      layer.groups.map((g) => [g.key, Math.min(...g.ids.map((id) => must(rankOf.get(id), `rank ${id}`)))]),
    );
    layer.groups.sort(
      (a, b) =>
        must(groupBary.get(a.key), `bary ${a.key}`) - must(groupBary.get(b.key), `bary ${b.key}`) ||
        must(groupRank.get(a.key), `rank ${a.key}`) - must(groupRank.get(b.key), `rank ${b.key}`),
    );
    refreshRanks();
  };

  refreshRanks();
  const crossingsInitial = crossings();
  let best = snapshotOrder(layers);
  let bestCrossings = crossingsInitial;
  for (let s = 0; s < sweepCount; s += 1) {
    if (s % 2 === 0) {
      for (let d = 1; d <= maxDepth; d += 1) reorderLayer(must(layers[d], `layer ${d}`), d - 1);
    } else {
      for (let d = maxDepth - 1; d >= 0; d -= 1) reorderLayer(must(layers[d], `layer ${d}`), d + 1);
    }
    const c = crossings();
    // Barycentre sweeps are not monotone; keeping the best seen is what makes "never worse than
    // the ordering we started from" a guarantee rather than a hope.
    if (c < bestCrossings) {
      bestCrossings = c;
      best = snapshotOrder(layers);
    }
  }
  restoreOrder(layers, best);
  refreshRanks();
  const crossingsFinal = crossings();

  /* 7 — embed the ordering into X/Z, one layer at a time, top down. */
  const posOf = new Map<string, { x: number; y: number; z: number }>();
  const layerY: number[] = [];
  const groupGeometry = new Map<string, { centerX: number; columns: number }>();

  /* Each layer also steps TOWARD the camera by its own half-depth plus the previous layer's, so a
     deep tier (the access block wraps into several rows) never hangs down over the layer beneath
     it on screen. The blind panel measured the alternative: with every layer centred on z = 0, the
     back rows of one tier and the front rows of the next shared screen space, and labels landed on
     other devices' chassis. Y stays one plane per tier; only the plane's Z centre moves. */
  const halfDepthOf = (layer: Layer): number => {
    let rows = 1;
    for (const g of layer.groups) {
      for (const c of balancedColumns(g.ids.length, columnsFor(g.ids.length))) rows = Math.max(rows, c);
    }
    return ((rows - 1) / 2) * NODE_PITCH_Z + COLUMN_STAGGER_Z + CHASSIS_EXTENT.depth / 2;
  };
  let layerZ = 0;
  let prevHalfDepth = 0;

  for (let depth = 0; depth <= maxDepth; depth += 1) {
    const layer = must(layers[depth], `layer ${depth}`);
    const y = (maxDepth - depth) * tierYPitch;
    layerY.push(y);
    const halfDepth = halfDepthOf(layer);
    if (depth > 0) layerZ += prevHalfDepth + halfDepth + LAYER_Z_GAP;
    prevHalfDepth = halfDepth;

    const metrics = layer.groups.map((g) => {
      const columns = columnsFor(g.ids.length);
      const counts = balancedColumns(g.ids.length, columns);
      const width = (columns - 1) * NODE_PITCH_X;
      // Desired centre = the mean X of this group's parents. A group whose parents are one switch
      // lands directly beneath it, which is what makes topology-only leaves cluster under the
      // device that reported them instead of being packed wherever there was room.
      let sum = 0;
      let n = 0;
      for (const id of g.ids) {
        for (const nb of adjSorted.get(id) ?? []) {
          const p = posOf.get(nb);
          if (p !== undefined && layerOf.get(nb) === depth - 1) {
            sum += p.x;
            n += 1;
          }
        }
      }
      return { group: g, columns, counts, width, desired: n > 0 ? sum / n : 0 };
    });

    const centers: number[] = [];
    metrics.forEach((m, i) => {
      let c = m.desired;
      if (i > 0) {
        const prev = must(metrics[i - 1], "previous group");
        const floorX = must(centers[i - 1], "previous centre") + prev.width / 2 + GROUP_GAP_X + m.width / 2;
        if (c < floorX) c = floorX;
      }
      centers.push(c);
    });
    // Packing pushes groups right; slide the whole layer back so its weighted centre sits on the
    // weighted centre its parents asked for. Otherwise the fabric drifts off-axis layer by layer.
    const totalNodes = metrics.reduce((s, m) => s + m.group.ids.length, 0) || 1;
    const wantMean = metrics.reduce((s, m) => s + m.desired * m.group.ids.length, 0) / totalNodes;
    const haveMean = metrics.reduce(
      (s, m, i) => s + must(centers[i], "centre") * m.group.ids.length,
      0,
    ) / totalNodes;
    const shift = wantMean - haveMean;

    metrics.forEach((m, gi) => {
      const centerX = must(centers[gi], "centre") + shift;
      groupGeometry.set(m.group.key, { centerX, columns: m.columns });
      let index = 0;
      for (let col = 0; col < m.columns; col += 1) {
        const count = must(m.counts[col], `column ${col}`);
        for (let row = 0; row < count; row += 1) {
          const id = must(m.group.ids[index], `node ${index}`);
          index += 1;
          // Serpentine within the column so rank-adjacent nodes stay spatially adjacent across a
          // column break; X remains monotonic in rank, which is what the sweeps optimised.
          const slot = col % 2 === 1 ? count - 1 - row : row;
          const [jx, jz] = jitterFor(id, seed);
          posOf.set(id, {
            x: centerX - m.width / 2 + col * NODE_PITCH_X + jx,
            // Y is never jittered: one tier, one plane, is an invariant the renderer draws bands from.
            y,
            z:
              layerZ +
              (slot - (count - 1) / 2) * NODE_PITCH_Z +
              (col % 2 === 1 ? COLUMN_STAGGER_Z : -COLUMN_STAGGER_Z) +
              jz,
          });
        }
      }
    });
  }

  /* 8 — publish nodes. */
  const nodes: LayoutNode[] = devices.map((d) => {
    const p = must(posOf.get(d.id), `unplaced device ${d.id}`);
    return {
      id: d.id,
      host: d.host,
      x: p.x,
      y: p.y,
      z: p.z,
      tier: tierOf(d.id),
      observedTier: observedTierOf.get(d.id) ?? null,
      layer: must(layerOf.get(d.id), `layer of ${d.id}`),
      rank: must(rankOf.get(d.id), `rank of ${d.id}`),
      groupKey: `t${tierOf(d.id)}`,
      collected: d.collected,
      degree: (adjSorted.get(d.id) ?? []).length,
      droppedAdjacency: (droppedByHost.get(d.id) ?? []).length,
      cite: d.cite,
    };
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));

  const tierBounds: FabricTierBounds[] = tierList.map((tier) => {
    const members = nodes.filter((n) => n.tier === tier);
    const xs = members.map((n) => n.x);
    const zs = members.map((n) => n.z);
    const geom = groupGeometry.get(`t${tier}`);
    return {
      tier,
      layer: must(depthOfTier.get(tier), `tier ${tier} depth`),
      y: must(members[0], `empty tier ${tier}`).y,
      minX: Math.min(...xs),
      maxX: Math.max(...xs),
      minZ: Math.min(...zs),
      maxZ: Math.max(...zs),
      count: members.length,
      centerX: geom?.centerX ?? (Math.min(...xs) + Math.max(...xs)) / 2,
      centerZ: (Math.min(...zs) + Math.max(...zs)) / 2,
      columns: geom?.columns ?? members.length,
      observedTier: syntheticTier !== null && tier === syntheticTier ? null : tier,
      nodeIds: members.map((n) => n.id),
    };
  });
  tierBounds.sort((a, b) => b.y - a.y || a.tier - b.tier);

  /* 9 — bounds and framing. The box is padded by the chassis half-extent: the camera must frame
     the geometry the renderer draws, not the abstract centre points. */
  const hx = CHASSIS_EXTENT.width / 2;
  const hy = CHASSIS_EXTENT.height / 2;
  const hz = CHASSIS_EXTENT.depth / 2;
  const min: Vec3 = [
    Math.min(...nodes.map((n) => n.x)) - hx,
    Math.min(...nodes.map((n) => n.y)) - hy,
    Math.min(...nodes.map((n) => n.z)) - hz,
  ];
  const max: Vec3 = [
    Math.max(...nodes.map((n) => n.x)) + hx,
    Math.max(...nodes.map((n) => n.y)) + hy,
    Math.max(...nodes.map((n) => n.z)) + hz,
  ];
  const center: Vec3 = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];
  const framing = frameSphere(sphereOver(nodes, center), fovDeg, aspect, margin);

  /* 10 — cable route hints. A hint exists exactly when the straight cable is NOT clear, so the
     absence of a hint is a computed claim about geometry, not an untested default — and the hint
     it is replaced by is itself measured, so the PRESENCE of a hint is not a claim either. */
  const routeHints: RouteHint[] = [];
  /** Provably always empty under hop layering — published so the invariant is checked, not assumed. */
  const linksSpanningNonAdjacentLayers: string[] = [];
  for (const { link, a, b } of placedLinks) {
    const na = byId.get(a);
    const nb = byId.get(b);
    if (na === undefined || nb === undefined || a === b) continue;
    const pa: Vec3 = [na.x, na.y, na.z];
    const pb: Vec3 = [nb.x, nb.y, nb.z];
    let nearest: number | null = null;
    const blockedBy: string[] = [];
    let blockerZ = 0;
    for (const other of nodes) {
      if (other.id === a || other.id === b) continue;
      const { distance, t } = pointToSegment([other.x, other.y, other.z], pa, pb);
      if (t <= ROUTE_T_MARGIN || t >= 1 - ROUTE_T_MARGIN) continue;
      if (nearest === null || distance < nearest) nearest = distance;
      if (distance < ROUTE_CLEARANCE) {
        blockedBy.push(other.id);
        blockerZ += other.z;
      }
    }
    const span = Math.abs(na.layer - nb.layer);
    if (span >= 2) linksSpanningNonAdjacentLayers.push(link.id);
    if (blockedBy.length === 0) continue;
    const mid: Vec3 = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2, (pa[2] + pb[2]) / 2];
    const blocked = [...blockedBy].sort();
    const obstacles = nodes
      .filter((o) => o.id !== a && o.id !== b)
      .map((o) => ({ id: o.id, p: [o.x, o.y, o.z] as Vec3 }));

    /* A detour is a DIRECTION and a wanted apex displacement, never a control point: the control
       point is derived from the apex so the constants below describe the cable the renderer draws.
       Each shape is then measured against every other chassis and widened until it is genuinely
       clear, because the hint's whole purpose is the claim "routed around this", and a remedy that
       is never evaluated is not a remedy. */
    let kind: RouteHintKind;
    let dirs: Vec3[];
    let baseApex: number;
    let reason: string;
    if (span === 0 && na.tier === nb.tier) {
      // Both ends on one plane in one block: a short bow over the chassis between them reads as a
      // patch lead and keeps the cable inside its own tier band.
      kind = "intra-tier";
      // Down is not an alternative: it would drop the patch lead through its own tier plane.
      dirs = [[0, 1, 0]];
      baseApex = INTRA_TIER_BOW;
      reason = `same tier plane with ${blocked.length} chassis between the ends; bowed above the tier`;
    } else if (span === 0 || span >= 2) {
      // A run between two blocks crosses the width of the drawing. Detour behind the fabric, never
      // in front: drawn across the near face it would obscure exactly what the user is inspecting,
      // and a bow tall enough to clear that distance would leave the tier band entirely.
      kind = "cross-tier-plane";
      // Only backwards. In front it would obscure the very face the user is inspecting.
      dirs = [[0, 0, -1]];
      // Measured from this cable's own midpoint so the apex lands SPAN_CLEARANCE behind the whole
      // drawing, wherever in the drawing the cable happens to sit.
      baseApex = mid[2] - (min[2] - SPAN_CLEARANCE);
      reason =
        `tier ${na.tier}→${nb.tier} across ${blocked.length} chassis on the same plane; ` +
        `routed behind the fabric`;
    } else {
      kind = "adjacent-obstructed";
      // Away from the blockers' centroid first; the opposite side is a legitimate sideways
      // detour too, and is tried only if the preferred one cannot be widened into the clear.
      const away = mid[2] >= blockerZ / blocked.length ? 1 : -1;
      dirs = [[0, 0, away], [0, 0, -away]];
      baseApex = ROUTE_CLEARANCE + hz + NODE_GAP_Z / 2;
      reason = `straight route passes within ${ROUTE_CLEARANCE} of ${blocked.length} chassis`;
    }
    const detour = solveDetour(pa, mid, pb, dirs, baseApex, ROUTE_CLEARANCE + hz, obstacles);
    routeHints.push({
      linkId: link.id,
      kind,
      mid: detour.control,
      clearance: nearest,
      blockedBy: blocked,
      routedClearance: detour.nearest,
      routedBlockedBy: detour.blockedBy,
      resolution: detour.resolution,
      apexOffset: detour.apexOffset,
      reason:
        detour.resolution === "cleared"
          ? reason
          : `${reason}; the detour is still within ${ROUTE_CLEARANCE} of ` +
            `${detour.blockedBy.length} chassis after ${ROUTE_DETOUR_STEPS} attempts`,
    });
  }
  const linkMidpoints = new Map<string, Vec3>(routeHints.map((h) => [h.linkId, h.mid]));

  /* 11 — post-condition. Validating the inputs is not the same as validating the output: a future
     arithmetic path could produce NaN from finite options, and a NaN fabric fails silently — the
     renderer draws nothing, the camera sits at infinity, and every separation guarantee above
     evaluates to false without anything reporting it. */
  const nonFinite = nodes
    .filter((n) => !Number.isFinite(n.x) || !Number.isFinite(n.y) || !Number.isFinite(n.z))
    .map((n) => n.id);
  if (nonFinite.length > 0) {
    throw new Error(`layout: non-finite coordinates for ${nonFinite.join(", ")}`);
  }
  if (
    ![...framing.position, ...framing.target, framing.near, framing.far, framing.boundingSphere.radius]
      .every((v) => Number.isFinite(v))
  ) {
    throw new Error("layout: non-finite camera framing");
  }

  return {
    nodes,
    byId,
    tierBounds,
    bounds: { min, max },
    framing,
    layerY,
    adjacency: adjSorted,
    linkMidpoints,
    routeHints,
    diagnostics: {
      rootTier,
      devicesWithoutObservedTier,
      syntheticTier,
      tierDisagreements,
      cableMapGroups,
      cableMapHostsWithoutDevice,
      linksWithUnplacedEndpoint,
      isolatedHosts,
      hostsWithDroppedAdjacency,
      tiersUnreachableFromRoot,
      linksSpanningNonAdjacentLayers,
      sweeps: sweepCount,
      crossingsInitial,
      crossingsFinal,
    },
  } satisfies FabricLayout;
}

/* ── framing ───────────────────────────────────────────────────────────────── */

function sphereOver(
  nodes: readonly { x: number; y: number; z: number }[],
  center: Vec3,
): BoundingSphere {
  // Chassis radius is added so the sphere covers the drawn mesh, not just its anchor point.
  const chassisRadius =
    0.5 *
    Math.hypot(CHASSIS_EXTENT.width, CHASSIS_EXTENT.height, CHASSIS_EXTENT.depth);
  let radius = 0;
  for (const n of nodes) {
    radius = Math.max(radius, Math.hypot(n.x - center[0], n.y - center[1], n.z - center[2]));
  }
  return { center, radius: radius + chassisRadius };
}

function frameSphere(
  sphere: BoundingSphere,
  fovDeg: number,
  aspect: number,
  margin: number,
): FabricCameraFraming {
  const vHalf = (fovDeg * Math.PI) / 360;
  const hHalf = Math.atan(Math.tan(vHalf) * aspect);
  // The tighter of the two half-angles governs: fit the sphere to the narrow axis or it spills.
  const distance = (margin * sphere.radius) / Math.sin(Math.min(vHalf, hHalf));
  const dir = normalize(VIEW_DIRECTION);
  const position: Vec3 = [
    sphere.center[0] + dir[0] * distance,
    sphere.center[1] + dir[1] * distance,
    sphere.center[2] + dir[2] * distance,
  ];
  return {
    position,
    target: [...sphere.center] as Vec3,
    up: [0, 1, 0],
    fovDeg,
    aspect,
    near: Math.max(0.1, distance - sphere.radius * 2),
    far: distance + sphere.radius * 4,
    boundingSphere: sphere,
  };
}

/**
 * Camera framing for one device and the neighbourhood around it, used when the user drills in.
 *
 * `hops` is a GRAPH radius, not a metric one: "its immediate neighbours" is a topology question,
 * and the metric extent that follows from it depends on how far those neighbours happen to have
 * been placed. Returns null for a host this layout does not contain — a caller must decide what to
 * do about an unknown host rather than silently receive the overview framing, which would show the
 * user a view that answers a different question from the one they asked.
 *
 * Exported as a free function rather than a method on the result so the result stays plain data:
 * comparable with a deep equality check, serialisable, and safe to hand across a worker boundary.
 */
export function focusFraming(
  layout: FabricLayout,
  hostId: string,
  hops = 1,
  margin = DEFAULT_FOCUS_MARGIN,
): FabricCameraFraming | null {
  const root = layout.byId.get(hostId);
  if (root === undefined) return null;
  const included = new Set<string>([root.id]);
  let frontier = [root.id];
  for (let h = 0; h < Math.max(0, Math.trunc(hops)); h += 1) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const nb of layout.adjacency.get(id) ?? []) {
        if (!included.has(nb)) {
          included.add(nb);
          next.push(nb);
        }
      }
    }
    frontier = next;
  }
  const members = [...included]
    .map((id) => layout.byId.get(id))
    .filter((n): n is LayoutNode => n !== undefined);
  const center: Vec3 = [
    (Math.min(...members.map((n) => n.x)) + Math.max(...members.map((n) => n.x))) / 2,
    (Math.min(...members.map((n) => n.y)) + Math.max(...members.map((n) => n.y))) / 2,
    (Math.min(...members.map((n) => n.z)) + Math.max(...members.map((n) => n.z))) / 2,
  ];
  const sphere = sphereOver(members, center);
  return frameSphere(sphere, layout.framing.fovDeg, layout.framing.aspect, margin);
}
