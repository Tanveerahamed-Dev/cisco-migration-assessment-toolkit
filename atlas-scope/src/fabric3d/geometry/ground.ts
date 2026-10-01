/**
 * ground.ts — the surfaces the fabric sits on, and the contact that grounds it.
 *
 * Objects that do not sit on anything read as floating, and floating is the fastest way to make a
 * render look unfinished. Three things fix it here, in ascending order of how much they matter:
 *
 *   1. A floor under the lowest tier, so the scene has a bottom rather than a void.
 *   2. A deck per tier, sized to that tier's own extent, fading out at its edges rather than
 *      terminating on a hard rectangle. The fade is why five stacked decks do not read as five
 *      floating slabs.
 *      The fade is only half of that promise: a faded plane that WRITES DEPTH still erases
 *      everything behind its invisible outer band, and the rectangle of erased background is what
 *      a reader sees as the hard edge. materials.ts turns the write off on both planes; see the
 *      comment above `deck` there for the measurement.
 *   3. A contact-shadow decal under every chassis. This one is not decoration: it is the only
 *      grounding cue that survives the `low` quality tier, where the shadow map is switched off.
 *      A scene that grounds its objects only through a shadow map loses them entirely on weak
 *      hardware, silently.
 *
 * Every surface here sits on its own Y plane — deck, contact, halo, state ring — with millimetre
 * separations chosen so no two are ever coplanar. Coplanar transparent surfaces flicker as the
 * camera moves, across the whole fabric at once, and that flicker is unmistakably "a bug".
 */
import {
  BufferAttribute,
  Group,
  InstancedMesh,
  Matrix4,
  Mesh,
  PlaneGeometry,
  Quaternion,
  Vector3,
  type BufferGeometry,
} from "three";
import { CHASSIS_EXTENT, type FabricTierBounds } from "../layout";
import { CONTACT_PLATEAU, type MaterialLibrary } from "../materials";
import { unitDecal } from "./chassis";

/** The plane every chassis stands on, relative to the layout's published node centre. */
export const DECK_DROP = CHASSIS_EXTENT.height / 2;

/** Stacking order above the deck. Separate planes, never coplanar. */
/** A node pad (see `NODE_PAD_SPREAD`) sits between the deck and the contact decal. */
export const Y_PAD = 0.02;
export const Y_CONTACT = 0.05;
export const Y_HALO = 0.11;
export const Y_STATE_RING = 0.17;

/**
 * Contact-decal size as a multiple of the chassis HALF-extent (so 3.6 = 1.8x the half-extent each
 * way). Asymmetric because a rack unit is deeper in shadow across its short axis at this key angle.
 */
export const CONTACT_SPREAD: readonly [number, number] = [3.6, 3.9];

/**
 * Where the chassis silhouette falls in normalised decal radius, on each axis. The plateau in
 * materials.ts must end INSIDE the smaller of these two or the decal is invisible under its own
 * caster — which is what shipped. Asserted by tests/ and by the comment at the decal build below.
 */
export const CONTACT_SILHOUETTE_RADIUS: readonly [number, number] = [
  2 / CONTACT_SPREAD[0],
  2 / CONTACT_SPREAD[1],
];

/**
 * True when the decal's full-strength plateau ends inside the chassis silhouette on BOTH axes —
 * i.e. when the decal is still opaque where the chassis meets its deck, which is the only place a
 * contact shadow is visible at all.
 *
 * Exported and asserted rather than commented: this is the exact relationship that broke, and it
 * broke silently because the two numbers lived in different files with nothing joining them.
 */
export function contactDecalGrounds(
  plateau = CONTACT_PLATEAU,
  silhouette = CONTACT_SILHOUETTE_RADIUS,
): boolean {
  return plateau < silhouette[0] && plateau < silhouette[1];
}

export interface GroundSet {
  group: Group;
  floor: Mesh;
  decks: InstancedMesh;
  /** One faded surface patch under each node the tier deck does not support. See `deckSupport`. */
  pads: InstancedMesh;
  /** Ids of the nodes that needed a pad, in instance order. */
  padded: readonly string[];
  contacts: InstancedMesh;
  /** Deck top Y for each tier index, so callers can place per-tier overlays without recomputing. */
  deckY: Map<number, number>;
  dispose(): void;
}

export interface GroundInput {
  tierBounds: readonly FabricTierBounds[];
  bounds: { min: [number, number, number]; max: [number, number, number] };
  /** Node centre per device, used to place one contact decal each. */
  nodes: readonly { id: string; x: number; y: number; z: number }[];
  /** Footprint half-extents per device id — a router's decal must not be a switch's decal. */
  footprintOf(id: string): readonly [number, number, number];
  materials: MaterialLibrary;
  shadows: boolean;
}

const m4 = new Matrix4();
const _scale = new Vector3();
const _pos = new Vector3();
/** Identity rotation for `Matrix4.compose`; allocating one per instance would be pointless. */
const ZERO_ROT = new Quaternion();

/**
 * A plane carrying two UV sets: channel 0 stays 0..1 for the radial alpha fade, channel 1 tiles for
 * the roughness and AO maps. Without the split, scaling UVs to get visible surface detail would
 * tile the fade as well and turn one soft patch into a grid of soft patches.
 */
function fadedPlane(tiles: number): BufferGeometry {
  const g = new PlaneGeometry(1, 1).toNonIndexed();
  g.applyMatrix4(m4.makeRotationX(-Math.PI / 2));
  const uv = g.getAttribute("uv");
  const tiled = new Float32Array(uv.count * 2);
  for (let i = 0; i < uv.count; i += 1) {
    tiled[i * 2] = uv.getX(i) * tiles;
    tiled[i * 2 + 1] = uv.getY(i) * tiles;
  }
  g.setAttribute("uv1", new BufferAttribute(tiled, 2));
  return g;
}

export function buildGround(input: GroundInput): GroundSet {
  const { tierBounds, bounds, nodes, materials, shadows } = input;
  const group = new Group();
  group.name = "ground";

  /* The floor. Sized generously past the fabric so its faded edge is never the thing the eye
     lands on, and dropped well below the lowest deck so it reads as a room floor rather than as
     another tier. */
  const spanX = bounds.max[0] - bounds.min[0];
  const spanZ = bounds.max[2] - bounds.min[2];
  // 1.7x rather than 2.4x: measured in the browser, the larger floor put a bright plane across the
  // whole frame and made the fabric — the subject — read as small furniture standing on a table.
  const floorSize = Math.max(spanX, spanZ) * 1.7 + 70;
  const floor = new Mesh(fadedPlane(Math.round(floorSize / 26)), materials.ground);
  floor.name = "floor";
  floor.scale.set(floorSize, 1, floorSize);
  floor.position.set(
    (bounds.min[0] + bounds.max[0]) / 2,
    bounds.min[1] - DECK_DROP - 15,
    (bounds.min[2] + bounds.max[2]) / 2,
  );
  // The floor does NOT receive shadows. It sits 15 units below the lowest deck and three tiers
  // below the busiest one, so every shadow reaching it is a projection from something the viewer
  // cannot see casting it. Its grounding is the contact decals. NOT SSAO: the floor, decks and pads
  // write no depth (materials.ts), so the SSAO pass has no ground surface to occlude — measured, the
  // luma under a chassis base is identical at high (SSAO on) and low (off) to within 1/255.
  floor.receiveShadow = false;
  floor.castShadow = false;
  group.add(floor);

  /* Decks. One instance per tier, scaled to that tier's own extent. Padding is clamped so two
     tiers that share a Y plane — this snapshot has two such pairs — can never overlap and fight. */
  const deckGeometry = fadedPlane(6);
  const decks = new InstancedMesh(deckGeometry, materials.deck, Math.max(1, tierBounds.length));
  decks.name = "tier-decks";
  decks.receiveShadow = shadows;
  decks.castShadow = false;
  decks.frustumCulled = false;

  const deckY = new Map<number, number>();
  const padding = deckPadding(tierBounds);
  for (let i = 0; i < tierBounds.length; i += 1) {
    const t = tierBounds[i];
    if (t === undefined) continue;
    const pad = padding[i] ?? 14;
    const w = t.maxX - t.minX + pad * 2;
    const d = t.maxZ - t.minZ + pad * 2;
    const y = t.y - DECK_DROP;
    deckY.set(t.tier, y);
    _pos.set((t.minX + t.maxX) / 2, y, (t.minZ + t.maxZ) / 2);
    _scale.set(w, 1, d);
    decks.setMatrixAt(i, m4.identity().compose(_pos, ZERO_ROT, _scale));
  }
  decks.count = tierBounds.length;
  decks.instanceMatrix.needsUpdate = true;
  group.add(decks);

  /* Node pads. The deck grounds its tier; this grounds each NODE the deck has faded away from.
     Same material as the deck, so a pad reads as more of the same surface rather than as a new
     kind of object, and it takes the cast shadow on the tiers that have one. Only nodes below
     MIN_SURFACE_UNDER_NODE get one: a pad under a node already on the deck would only brighten it.
     See `deckSupport` for the measurement that made this necessary. */
  const support = deckSupport(tierBounds, nodes, padding);
  const padded = nodes.filter((n) => (support.get(n.id) ?? 0) < MIN_SURFACE_UNDER_NODE);
  const padGeometry = fadedPlane(2);
  const pads = new InstancedMesh(padGeometry, materials.deck, Math.max(1, padded.length));
  pads.name = "node-pads";
  pads.receiveShadow = shadows;
  pads.castShadow = false;
  pads.frustumCulled = false;
  for (let i = 0; i < padded.length; i += 1) {
    const n = padded[i];
    if (n === undefined) continue;
    const half = input.footprintOf(n.id);
    _pos.set(n.x, n.y - DECK_DROP + Y_PAD, n.z);
    _scale.set(half[0] * NODE_PAD_SPREAD, 1, half[2] * NODE_PAD_SPREAD);
    pads.setMatrixAt(i, m4.identity().compose(_pos, ZERO_ROT, _scale));
  }
  pads.count = padded.length;
  pads.instanceMatrix.needsUpdate = true;
  group.add(pads);

  /* Contact decals. Scaled from each device's own footprint, so an access point does not get a
     switch-sized smudge under it. Elliptical by construction: the decal is a unit quad and the
     footprint is not square.

     CONTACT_SPREAD and materials.ts's CONTACT_PLATEAU are a PAIR and the pair is the grounding.
     The decal's half-extent is CONTACT_SPREAD/2 times the chassis half-extent, so the chassis
     silhouette falls at normalised decal radius 1 / (CONTACT_SPREAD/2) — 0.555 at an edge midpoint
     here — and the plateau has to end just inside that or the only visible part of the decal is
     its weakest tail. They were implicitly coupled and drifted apart, which is how the fabric
     shipped with nothing grounding it; this asserts the relationship instead of restating it. */
  const contactGeometry = unitDecal();
  const contacts = new InstancedMesh(contactGeometry, materials.contact, Math.max(1, nodes.length));
  contacts.name = "contact-shadows";
  contacts.castShadow = false;
  contacts.receiveShadow = false;
  contacts.frustumCulled = false;
  contacts.renderOrder = 1;
  for (let i = 0; i < nodes.length; i += 1) {
    const n = nodes[i];
    if (n === undefined) continue;
    const half = input.footprintOf(n.id);
    _pos.set(n.x, n.y - DECK_DROP + Y_CONTACT, n.z);
    _scale.set(half[0] * CONTACT_SPREAD[0], 1, half[2] * CONTACT_SPREAD[1]);
    contacts.setMatrixAt(i, m4.identity().compose(_pos, ZERO_ROT, _scale));
  }
  contacts.count = nodes.length;
  contacts.instanceMatrix.needsUpdate = true;
  group.add(contacts);

  const set: GroundSet = {
    group,
    floor,
    decks,
    pads,
    padded: padded.map((n) => n.id),
    contacts,
    deckY,
    dispose(): void {
      floor.geometry.dispose();
      deckGeometry.dispose();
      padGeometry.dispose();
      pads.dispose();
      contactGeometry.dispose();
      decks.dispose();
      contacts.dispose();
      group.clear();
    },
  };
  return set;
}

/**
 * The deck's alpha at normalised radius r, mirroring the `radialFade` generator in materials.ts
 * ((1 − r)^2.2, zero at and beyond the edge midpoint). Duplicated rather than imported because the
 * generator writes a texture and exposes no function; the test that pins this pins the pair.
 */
export function deckFadeAlpha(r: number): number {
  return r >= 1 ? 0 : Math.pow(1 - Math.max(0, r), 2.2);
}

/** Below this deck alpha under its centre, a chassis has nothing under it to be grounded ON. */
export const MIN_SURFACE_UNDER_NODE = 0.3;

/**
 * A node pad's size as a multiple of the chassis half-extent. At 8 the silhouette falls at
 * normalised radius 0.25, where the fade still carries (0.75)^2.2 = 0.53 — a surface a contact
 * decal can darken — and the pad's own edge is four chassis widths out, soft enough to read as the
 * deck continuing rather than as a coaster.
 */
export const NODE_PAD_SPREAD = 8;

/**
 * The surface under each node once pads are laid: the deck's own alpha, or a pad's alpha at its
 * centre (1) where the deck fell short. Exported so a test asserts the doctrine per NODE rather
 * than per tier, which is the granularity it failed at.
 */
export function surfaceUnderNodes(
  tiers: readonly FabricTierBounds[],
  nodes: readonly { id: string; x: number; y: number; z: number }[],
): Map<string, number> {
  const support = deckSupport(tiers, nodes);
  const out = new Map<string, number>();
  for (const [id, a] of support) out.set(id, a < MIN_SURFACE_UNDER_NODE ? 1 : a);
  return out;
}

/**
 * THE SURFACE UNDER EVERY NODE, as a number.
 *
 * The header's doctrine — objects that do not sit on anything read as floating — was honoured for
 * the tier as a whole and not for each node on it. A deck is sized to its tier's extent and then
 * fades radially, so a node at the extreme of a wide or sparse tier sits where the deck has already
 * faded to almost nothing. MEASURED (render audit #5): `wan-edge-rtr1.lab` and `AP-floor3-01`
 * rendered as boxes on pure backdrop at both tiers, with their state rings floating beside them —
 * and the contact decal, being a DARKENING, cannot ground anything on a surface that is already the
 * backdrop's colour.
 *
 * Returns, per node, the strongest deck alpha under its centre across every deck on its plane.
 */
export function deckSupport(
  tiers: readonly FabricTierBounds[],
  nodes: readonly { id: string; x: number; y: number; z: number }[],
  padding: readonly number[] = deckPadding(tiers),
): Map<string, number> {
  const out = new Map<string, number>();
  for (const n of nodes) {
    let best = 0;
    for (let i = 0; i < tiers.length; i += 1) {
      const t = tiers[i];
      if (t === undefined || Math.abs(t.y - n.y) > 0.5) continue;
      const pad = padding[i] ?? 14;
      const w = t.maxX - t.minX + pad * 2;
      const d = t.maxZ - t.minZ + pad * 2;
      const r = Math.hypot((n.x - (t.minX + t.maxX) / 2) / w, (n.z - (t.minZ + t.maxZ) / 2) / d) * 2;
      best = Math.max(best, deckFadeAlpha(r));
    }
    out.set(n.id, best);
  }
  return out;
}

/**
 * Per-tier padding, reduced wherever two tiers share a Y plane and would otherwise meet.
 *
 * This snapshot lays access (tier 1) and distribution (tier 3) on the same plane, and likewise the
 * access point (tier 0) and the pod access switches (tier 4). Uniform padding would make those
 * pairs overlap, and two coplanar transparent decks overlapping is exactly the z-fight the brief
 * forbids — fixed at authoring time here rather than fought with polygonOffset later.
 */
export function deckPadding(tiers: readonly FabricTierBounds[]): number[] {
  // A generous floor matters most for a SMALL tier: the deck fades radially, so a two-node tier
  // padded like a seventeen-node one concentrates its brightest pixels into a tight blob that
  // reads as a spotlight rather than as a surface. Measured in the browser; 14 was too tight.
  const wanted = tiers.map((t) => Math.max(34, (t.maxX - t.minX + t.maxZ - t.minZ) * 0.06));
  for (let i = 0; i < tiers.length; i += 1) {
    for (let j = i + 1; j < tiers.length; j += 1) {
      const a = tiers[i];
      const b = tiers[j];
      if (a === undefined || b === undefined) continue;
      if (Math.abs(a.y - b.y) > 0.5) continue;
      const gapX = Math.max(a.minX - b.maxX, b.minX - a.maxX);
      const gapZ = Math.max(a.minZ - b.maxZ, b.minZ - a.maxZ);
      const gap = Math.max(gapX, gapZ);
      if (gap <= 0) continue; // already interleaved; the layout guarantees this does not happen
      const cap = Math.max(2, gap * 0.45);
      wanted[i] = Math.min(wanted[i] ?? cap, cap);
      wanted[j] = Math.min(wanted[j] ?? cap, cap);
    }
  }
  return wanted;
}

