/**
 * layout.test.ts — the 3-D layout engine verified against the REAL compiled fabric.
 *
 * Every assertion runs over `src/data/fabric.json` as compiled from the engine snapshot. No
 * hand-built fixture: a fixture shaped the way the layout expects would simply agree with a layout
 * bug. Where an assertion depends on a fact of THIS fabric (core1/core2 being the hub tier, no
 * cable needing a detour at the shipped tier pitch) the test states that fact explicitly, so a
 * data refresh fails loudly instead of silently weakening the test.
 *
 * The geometric claims — crossings, clearance, frustum containment — are re-derived here with the
 * test's own arithmetic rather than by calling the engine's helpers. A verifier that reuses the
 * proposer's maths proves only that the maths is self-consistent.
 *
 * Three route-hint branches exist and all three are exercised below against real device records:
 * two by adding one link between REAL hosts (a link record cloned from a real one, so its shape
 * comes from the real producer), and one by flattening the tier pitch until real cables genuinely
 * graze real chassis. None of them fires on the shipped fabric at the shipped pitch — which is a
 * claim, not an assumption, and the "absent hint" test below proves it.
 */
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { fabric } from "../core/data";
import { describeGolden } from "../test-support/golden-sample";
import type { Link } from "../core/types";
import {
  CHASSIS_EXTENT,
  INTRA_TIER_BOW,
  JITTER_AMPLITUDE,
  MIN_NODE_SEPARATION,
  ROUTE_CLEARANCE,
  ROUTE_CURVE_SAMPLES,
  ROUTE_DETOUR_STEPS,
  ROUTE_T_MARGIN,
  computeLayout,
  focusFraming,
  layoutJob,
  type FabricLayout,
  type LayoutNode,
  type LayoutOptions,
  type RouteHint,
  type Vec3,
} from "./layout";

const OPTS = { devices: fabric.devices, links: fabric.links, tiers: fabric.tiers } as const;
const layout = computeLayout(OPTS);

/** A link record cloned from a real one, re-pointed at two real hosts. Shape from the producer. */
const linkTemplate = fabric.links.find((l) => l.id === "L18")!;
const relinked = (id: string, a: string, b: string): Link => ({ ...linkTemplate, id, a, b });

/**
 * A STAR of extra links from `hub` to every other device in `to`, each id `${prefix}:${host}`.
 *
 * Why a star and not one extra link: since the tiers wrap column-major into a near-square block,
 * the crossing sweeps place any ONE added pair rank-adjacent — measured, all 210 single extra
 * layer-1 pairs came out with a clear straight cable — so a single pair no longer reaches the
 * detour branches. A hub linked to its whole tier cannot be adjacent to all of them, which is the
 * obstruction the detour code exists for.
 */
const star = (prefix: string, hub: string, to: readonly string[]): Link[] =>
  to.filter((h) => h !== hub).map((h) => relinked(`${prefix}:${h}`, hub, h));
const TIER1 = fabric.devices.filter((d) => d.tier === 1).map((d) => d.host);

/* ── test-local geometry, deliberately independent of layout.ts ────────────── */

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Vec3, b: Vec3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const norm = (a: Vec3): Vec3 => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};
const at = (n: LayoutNode): Vec3 => [n.x, n.y, n.z];
const distance = (a: Vec3, b: Vec3): number => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

/**
 * The layout's work, counted instead of timed: every call made while `fn` runs into a function-valued
 * own property of Array.prototype, Map.prototype, Set.prototype or Math. The class is derived by
 * reflection, not listed, so a primitive the layout starts using is counted without anyone adding it
 * here. Each is wrapped for the duration of the synchronous call and restored in `finally`.
 *
 * What it cannot see, stated: a loop whose body calls none of them (bare index arithmetic), and the
 * relative cost of each call — it counts operations, it does not weigh them. Every loop in layout.ts
 * that does work touches a Map, an array method or Math at least once per iteration, which is what
 * makes the count track the ORDER of the work.
 *
 * `runaway` is a hang guard, not a budget: once the count passes it, the next counted call throws
 * RunawayWork, so a regression that loops forever (a non-finite sweep count) ends as a readable
 * failure instead of a test timeout. Every caller that states a budget leaves it at Infinity.
 */
class RunawayWork extends Error {
  constructor(readonly ops: number) {
    super(`still running after ${ops} primitive operations`);
  }
}
function primitiveOps(fn: () => void, runaway = Infinity): number {
  let n = 0;
  const saved: [object, PropertyKey, PropertyDescriptor][] = [];
  try {
    for (const o of [Array.prototype, Map.prototype, Set.prototype, Math] as object[]) {
      for (const key of Reflect.ownKeys(o)) {
        const d = Object.getOwnPropertyDescriptor(o, key);
        if (key === "constructor" || d === undefined || typeof d.value !== "function") continue;
        const f = d.value as (...a: unknown[]) => unknown;
        saved.push([o, key, d]);
        Object.defineProperty(o, key, {
          ...d,
          value: function counted(this: unknown, ...args: unknown[]): unknown {
            n += 1;
            /* Once, on crossing: the restore loop in `finally` below iterates through these same
               wrapped primitives, and must not throw on the way out. */
            if (n === runaway + 1) throw new RunawayWork(n);
            return f.apply(this, args);
          },
        });
      }
    }
    /* The wrapping above is itself made of array calls; only what `fn` does is counted. */
    n = 0;
    fn();
    return n;
  } finally {
    for (const [o, key, d] of saved) Object.defineProperty(o, key, d);
  }
}

/** Distance from `p` to segment ab, plus the clamped parameter along the segment. */
function pointSegment(p: Vec3, a: Vec3, b: Vec3): { d: number; t: number } {
  const ab = sub(b, a);
  const len2 = dot(ab, ab);
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, dot(sub(p, a), ab) / len2));
  const c: Vec3 = [a[0] + ab[0] * t, a[1] + ab[1] * t, a[2] + ab[2] * t];
  return { d: distance(p, c), t };
}

/** A point on the quadratic Bezier the RouteHint's `mid` is the control point of. */
function bezier(a: Vec3, c: Vec3, b: Vec3, t: number): Vec3 {
  const u = 1 - t;
  return [
    u * u * a[0] + 2 * u * t * c[0] + t * t * b[0],
    u * u * a[1] + 2 * u * t * c[1] + t * t * b[1],
    u * u * a[2] + 2 * u * t * c[2] + t * t * b[2],
  ];
}

/**
 * Clearance of the SUGGESTED curve, by dense point sampling — deliberately a different method from
 * the engine's polyline measure, so agreement between them is evidence rather than tautology.
 * 400 samples over a curve a few hundred units long puts the sampling gap far below the 12-unit
 * threshold being tested, and point sampling can only OVERSTATE clearance, so a violation it finds
 * is real.
 */
function curveClearance(
  l: FabricLayout,
  h: RouteHint,
  a: LayoutNode,
  b: LayoutNode,
): { min: number; worst: string } {
  let min = Infinity;
  let worst = "";
  /* The same closed domain the engine measures, [ROUTE_T_MARGIN, 1 − ROUTE_T_MARGIN], endpoints
     included. This used to start one step INSIDE it (t > margin), which was invisible while every
     detour was short; a hub-star detour (see `star`) sweeps wide enough that one 1/400 step near
     the end is ~2 units of cable, and the two measures then disagreed by more than the tolerance
     with the ENGINE the conservative one (14.78 vs 16.66 from access1). */
  for (let i = 0; i <= 400; i += 1) {
    const t = ROUTE_T_MARGIN + ((1 - 2 * ROUTE_T_MARGIN) * i) / 400;
    const p = bezier(at(a), h.mid, at(b), t);
    for (const n of l.nodes) {
      if (n.id === a.id || n.id === b.id) continue;
      const d = distance(p, at(n));
      if (d < min) {
        min = d;
        worst = n.id;
      }
    }
  }
  return { min, worst };
}

/**
 * Every hint in a layout, checked against the test's own curve maths. The engine may report a hint
 * as unresolved — that is honest and allowed — but it may never report "cleared" for a curve that
 * this independent measurement finds still inside ROUTE_CLEARANCE.
 */
function auditHints(l: FabricLayout, links: readonly Link[], label: string): string[] {
  const byLink = new Map(links.map((k) => [k.id, k]));
  const lies: string[] = [];
  for (const h of l.routeHints) {
    const link = byLink.get(h.linkId)!;
    const a = l.byId.get(link.a)!;
    const b = l.byId.get(link.b)!;
    const { min, worst } = curveClearance(l, h, a, b);
    if (typeof h.routedClearance !== "number" || !Number.isFinite(h.routedClearance)) {
      lies.push(`${label}/${h.linkId}: emitted a hint with no measured curve clearance`);
      continue;
    }
    if (h.resolution !== "cleared" && h.resolution !== "unresolved") {
      lies.push(`${label}/${h.linkId}: emitted a hint with no resolution (${String(h.resolution)})`);
      continue;
    }
    if (Math.abs(h.routedClearance - min) > 1.5) {
      lies.push(
        `${label}/${h.linkId}: engine says curve clears ${h.routedClearance.toFixed(2)}, ` +
          `independent measure ${min.toFixed(2)} (${worst})`,
      );
    }
    if (h.resolution === "cleared" && min < ROUTE_CLEARANCE) {
      lies.push(
        `${label}/${h.linkId}: claims "cleared" but the suggested curve passes ${min.toFixed(2)} ` +
          `from ${worst} (limit ${ROUTE_CLEARANCE})`,
      );
    }
    if (h.resolution === "cleared" && h.routedBlockedBy.length > 0) {
      lies.push(`${label}/${h.linkId}: claims "cleared" while naming residual blockers`);
    }
    if (h.resolution === "unresolved" && h.routedBlockedBy.length === 0) {
      lies.push(`${label}/${h.linkId}: claims "unresolved" but names nothing still in the way`);
    }
    // `apexOffset` must describe the curve that was actually published, not the control point that
    // produced it. This is the arithmetic the whole defect turned on: a constant applied to the
    // control point delivers half of what it names, and only measuring the drawn apex catches it.
    const chordMid: Vec3 = [(a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2];
    const drawnApex = distance(bezier(at(a), h.mid, at(b), 0.5), chordMid);
    if (Math.abs(drawnApex - h.apexOffset) > 1e-6) {
      lies.push(
        `${label}/${h.linkId}: reports apexOffset ${h.apexOffset.toFixed(2)} but the published ` +
          `curve rises only ${drawnApex.toFixed(2)} off the chord`,
      );
    }
  }
  return lies;
}

/**
 * Crossings between adjacent layers, counted on the ordering the engine published: two edges
 * cross iff their endpoint ranks are inverted. This is the Sugiyama measure the sweeps claim to
 * reduce, computed here so the engine's own diagnostic can be checked against it.
 */
function countCrossings(l: FabricLayout, links: readonly Link[]): number {
  const edges: { layer: number; u: number; v: number }[] = [];
  for (const link of links) {
    const a = l.byId.get(link.a);
    const b = l.byId.get(link.b);
    if (!a || !b || Math.abs(a.layer - b.layer) !== 1) continue;
    const upper = a.layer < b.layer ? a : b;
    const lower = a.layer < b.layer ? b : a;
    edges.push({ layer: upper.layer, u: upper.rank, v: lower.rank });
  }
  let crossings = 0;
  for (let i = 0; i < edges.length; i += 1) {
    for (let j = i + 1; j < edges.length; j += 1) {
      const e = edges[i]!;
      const f = edges[j]!;
      if (e.layer !== f.layer) continue;
      if ((e.u - f.u) * (e.v - f.v) < 0) crossings += 1;
    }
  }
  return crossings;
}

/* ── placement completeness ────────────────────────────────────────────────── */

describe("computeLayout — placement", () => {
  it("places every device in the fabric, dropping none", () => {
    expect(layout.nodes).toHaveLength(fabric.devices.length);
    expect(layout.byId.size).toBe(fabric.devices.length);
    const placed = new Set(layout.nodes.map((n) => n.id));
    const missing = fabric.devices.filter((d) => !placed.has(d.id)).map((d) => d.id);
    expect(missing).toEqual([]);
  });

  it("carries each device's citation onto its node", () => {
    for (const d of fabric.devices) {
      const n = layout.byId.get(d.id)!;
      expect(n.cite).toBe(d.cite);
      expect(n.cite.length).toBeGreaterThan(0);
      expect(n.collected).toBe(d.collected);
    }
  });

  it("gives every coordinate a finite value", () => {
    const bad = layout.nodes.filter(
      (n) => !Number.isFinite(n.x) || !Number.isFinite(n.y) || !Number.isFinite(n.z),
    );
    expect(bad).toEqual([]);
  });

  it("keeps every pair of nodes at least MIN_NODE_SEPARATION apart", () => {
    let min = Infinity;
    let worst = "";
    for (let i = 0; i < layout.nodes.length; i += 1) {
      for (let j = i + 1; j < layout.nodes.length; j += 1) {
        const a = layout.nodes[i]!;
        const b = layout.nodes[j]!;
        const d = distance(at(a), at(b));
        if (d < min) {
          min = d;
          worst = `${a.id}↔${b.id}`;
        }
      }
    }
    expect(min, `closest pair ${worst} at ${min.toFixed(3)}`).toBeGreaterThanOrEqual(
      MIN_NODE_SEPARATION - 1e-9,
    );
    // The constant must stay a real floor, not a number so slack it can never bite.
    expect(min).toBeLessThan(MIN_NODE_SEPARATION * 2);
  });

  it("never lets two chassis volumes intersect", () => {
    const overlaps: string[] = [];
    for (let i = 0; i < layout.nodes.length; i += 1) {
      for (let j = i + 1; j < layout.nodes.length; j += 1) {
        const a = layout.nodes[i]!;
        const b = layout.nodes[j]!;
        if (
          Math.abs(a.x - b.x) < CHASSIS_EXTENT.width &&
          Math.abs(a.y - b.y) < CHASSIS_EXTENT.height &&
          Math.abs(a.z - b.z) < CHASSIS_EXTENT.depth
        ) {
          overlaps.push(`${a.id}↔${b.id}`);
        }
      }
    }
    expect(overlaps).toEqual([]);
  });
});

/* ── tier structure ────────────────────────────────────────────────────────── */

describe("computeLayout — tier structure", () => {
  it("puts every node of a tier on exactly one Y plane", () => {
    const yByTier = new Map<number, number>();
    const offenders: string[] = [];
    for (const n of layout.nodes) {
      const seen = yByTier.get(n.tier);
      if (seen === undefined) yByTier.set(n.tier, n.y);
      else if (seen !== n.y) offenders.push(`${n.id} y=${n.y} ≠ ${seen}`);
    }
    expect(offenders).toEqual([]);
    expect(yByTier.size).toBe(fabric.tiers.length);
  });

  it("puts the hub tier at the top — core1/core2 are the highest plane", () => {
    const maxY = Math.max(...layout.nodes.map((n) => n.y));
    const top = layout.nodes.filter((n) => n.y === maxY).map((n) => n.id).sort();
    expect(top).toEqual(["core1", "core2"]);
    const y = (id: string): number => layout.byId.get(id)!.y;
    expect(y("access1")).toBeLessThan(y("core1"));
    expect(y("dist1")).toBeLessThan(y("core1"));
    expect(y("AP-floor1")).toBeLessThan(y("access1"));
    expect(y("podacc1")).toBeLessThan(y("dist1"));
  });

  it("derives the hub tier from the engine's own centrality, not from a hostname", () => {
    const { rootTier } = layout.diagnostics;
    expect(rootTier.tier).toBe(2);
    expect(rootTier.basis).toBe("link-betweenness");
    // L27 core1↔core2 carries betweenness 99.5, the highest in the snapshot.
    expect(rootTier.maxBetweenness).toBe(99.5);
    const observed = fabric.links.filter((l) => l.betweenness !== null);
    expect(rootTier.maxBetweenness).toBe(Math.max(...observed.map((l) => l.betweenness!)));
  });

  it("reports tier bounds that actually contain their nodes", () => {
    expect(layout.tierBounds).toHaveLength(fabric.tiers.length);
    for (const b of layout.tierBounds) {
      const members = layout.nodes.filter((n) => n.tier === b.tier);
      expect(members.length).toBe(b.count);
      expect(members.map((n) => n.id).sort()).toEqual([...b.nodeIds].sort());
      for (const n of members) {
        expect(n.y).toBe(b.y);
        expect(n.x).toBeGreaterThanOrEqual(b.minX - 1e-9);
        expect(n.x).toBeLessThanOrEqual(b.maxX + 1e-9);
        expect(n.z).toBeGreaterThanOrEqual(b.minZ - 1e-9);
        expect(n.z).toBeLessThanOrEqual(b.maxZ + 1e-9);
      }
    }
  });

  it("spreads a wide tier over X and Z instead of a single flat line", () => {
    const access = layout.nodes.filter((n) => n.tier === 1);
    expect(access).toHaveLength(17);
    expect(new Set(access.map((n) => Math.round(n.z))).size).toBeGreaterThan(1);
    const spanX = Math.max(...access.map((n) => n.x)) - Math.min(...access.map((n) => n.x));
    const spanZ = Math.max(...access.map((n) => n.z)) - Math.min(...access.map((n) => n.z));
    expect(spanZ).toBeGreaterThan(CHASSIS_EXTENT.depth);
    // Near-square, not a 3:1 strip. The strip put six chassis per row at the stage's full width,
    // which left each label ~60 px for an ~80 px name: the blind panel measured 11 of 26 labels
    // dropped and four more sitting on other devices' chassis. The camera now looks down steeply
    // (VIEW_DIRECTION), so a deeper block no longer hides its back rows behind the front ones.
    expect(spanX / spanZ).toBeLessThan(1.5);
    expect(spanZ / spanX).toBeLessThan(1.5);
  });

  it("steps each layer toward the camera so no tier hangs over the one beneath it", () => {
    // Every node of layer k+1 is in front of (larger Z than) every node of layer k, with at least
    // a chassis depth of clear air — the property that keeps the tiers in separate screen bands.
    const maxLayer = Math.max(...layout.nodes.map((n) => n.layer));
    for (let k = 0; k < maxLayer; k += 1) {
      const upper = layout.nodes.filter((n) => n.layer === k);
      const lower = layout.nodes.filter((n) => n.layer === k + 1);
      const upperFront = Math.max(...upper.map((n) => n.z));
      const lowerBack = Math.min(...lower.map((n) => n.z));
      expect(lowerBack - upperFront, `layer ${k + 1} overlaps layer ${k} in Z`).toBeGreaterThan(
        CHASSIS_EXTENT.depth,
      );
    }
  });

  it("clusters topology-only nodes under the devices that reported them", () => {
    const access = layout.nodes.filter((n) => n.tier === 1);
    const ap = layout.byId.get("AP-floor1")!;
    expect(ap.collected).toBe(false);
    expect(ap.degree).toBe(17);
    expect(ap.x).toBeGreaterThanOrEqual(Math.min(...access.map((n) => n.x)));
    expect(ap.x).toBeLessThanOrEqual(Math.max(...access.map((n) => n.x)));

    // podacc1/2 hang off dist1/dist2 only, so their block must sit beneath that pod, not beside it.
    const mean = (ids: string[]): number =>
      ids.reduce((s, id) => s + layout.byId.get(id)!.x, 0) / ids.length;
    expect(Math.abs(mean(["podacc1", "podacc2"]) - mean(["dist1", "dist2"]))).toBeLessThan(
      CHASSIS_EXTENT.width,
    );
  });

  it("keeps each tier contiguous in rank and monotonic in X", () => {
    const byLayer = new Map<number, LayoutNode[]>();
    for (const n of layout.nodes) byLayer.set(n.layer, [...(byLayer.get(n.layer) ?? []), n]);
    for (const [, members] of byLayer) {
      const ordered = [...members].sort((a, b) => a.rank - b.rank);
      expect(ordered.map((n) => n.rank)).toEqual(ordered.map((_, i) => i));
      // A tier occupies one unbroken run of ranks: a WAN router must not be interleaved into a
      // row of access switches, however few crossings that would shave.
      const runs: number[] = [];
      for (const n of ordered) if (runs[runs.length - 1] !== n.tier) runs.push(n.tier);
      expect(runs).toEqual([...new Set(runs)]);
      // X is non-decreasing in rank (within jitter), which is what makes the crossing count above
      // describe what the viewer actually sees from the default camera.
      for (let i = 1; i < ordered.length; i += 1) {
        expect(ordered[i]!.x).toBeGreaterThanOrEqual(ordered[i - 1]!.x - 2 * JITTER_AMPLITUDE);
      }
    }
  });
});

/* ── determinism ───────────────────────────────────────────────────────────── */

describe("computeLayout — determinism", () => {
  it("returns a deeply equal result for the same input", () => {
    expect(computeLayout(OPTS)).toEqual(computeLayout(OPTS));
  });

  it("is independent of the order devices and links arrive in", () => {
    const reversed = computeLayout({
      devices: [...fabric.devices].reverse(),
      links: [...fabric.links].reverse(),
      tiers: fabric.tiers,
    });
    for (const n of layout.nodes) {
      const other = reversed.byId.get(n.id)!;
      expect([other.x, other.y, other.z, other.rank]).toEqual([n.x, n.y, n.z, n.rank]);
    }
  });

  it("derives jitter from the seed alone, and never from the structure", () => {
    const a = computeLayout({ ...OPTS, seed: 7 });
    const b = computeLayout({ ...OPTS, seed: 7 });
    expect(a.nodes.map((n) => n.x)).toEqual(b.nodes.map((n) => n.x));
    const c = computeLayout({ ...OPTS, seed: 8 });
    expect(c.nodes.map((n) => n.rank)).toEqual(a.nodes.map((n) => n.rank));
    expect(c.nodes.map((n) => n.x)).not.toEqual(a.nodes.map((n) => n.x));
  });
});

/* ── golden geometry (tracked reference sample only) ───────────────────────────
   SCALE (2026-09-28). The route stage now measures each cable only against the chassis a spatial
   index returns near it, crossings are counted as inversions, and the pipeline can be run in slices
   (layoutJob). None of that may move a chassis: the index is a pruning of the same arithmetic, never
   a different measure. These digests were taken from the PRE-index layout.ts on this very input, for
   every configuration known to exercise a distinct branch (the defaults, a seed, no sweeps, five
   flattened pitches that make the detour ladder run, and the CROSS / INTRA / TIGHT links that reach
   the cross-plane, intra-tier and unresolved branches), and the post-index layout reproduces every
   one bit for bit. They pin geometry and diagnostics — every coordinate, rank, tier, bound, framing
   figure, hint and count — and leave out only the per-node `cite`, which is the compiler's wording.

   Two pins, so a failure says which half moved: INPUT is the layout-relevant part of the compiled
   sample (device id/host/order/tier/role/collected, link id/ends/betweenness, the tier partition). A
   changed INPUT means the data was recompiled and every digest below must be re-derived from the
   regenerated data, with the reason recorded; a changed digest under an unchanged INPUT is the layout
   itself moving, which is a regression unless the change was meant and re-baselined with evidence. */

const sha256 = (v: unknown): string => createHash("sha256").update(JSON.stringify(v)).digest("hex");
const byKey = <V,>(a: readonly [string, V], b: readonly [string, V]): number => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);
const geometryOf = (l: FabricLayout) => ({
  nodes: l.nodes.map((n) => [n.id, n.host, n.x, n.y, n.z, n.tier, n.observedTier, n.layer, n.rank, n.groupKey, n.collected, n.degree, n.droppedAdjacency]),
  tierBounds: l.tierBounds,
  bounds: l.bounds,
  framing: l.framing,
  layerY: l.layerY,
  routeHints: l.routeHints,
  diagnostics: l.diagnostics,
  linkMidpoints: [...l.linkMidpoints].sort(byKey),
  adjacency: [...l.adjacency].sort(byKey),
});
const GOLDEN_LAYOUT_INPUT = "543c58bc24c2d393e52eda85cf5af8fde78ccb0c6a3d1a9507063cf0ffd448f7";
const GOLDEN_LAYOUT: readonly (readonly [string, Partial<LayoutOptions>, string, number])[] = [
  ["default", {}, "97fa8831bb9ab3a97be98a45987a1dbd688337d966316d3815aae3e3f6f92cf6", 0],
  ["seed 101", { seed: 101 }, "5786dbc10db8aad6ede6ed8587a500967351b55aba020b549eecca9324de64c7", 0],
  ["sweeps 0", { sweeps: 0 }, "b9c9837f082b8967741b445228169c6ecaeec8b8156ddd04e0a5cdeaa96df147", 0],
  ["pitch MIN_NODE_SEPARATION", { tierYPitch: MIN_NODE_SEPARATION }, "0055e7abc052dd7a8093332eedf7daf6e9946658acf6b36bf0c403140c07ea6a", 21],
  ["pitch 26", { tierYPitch: 26 }, "971bcab0eda6656d97d268eab4ed356f3a96b62ba6f5b358ba7b8434b468c2f7", 20],
  ["pitch 28", { tierYPitch: 28 }, "4116e1223007f6edd466ad4b8f61456d16fc0812767f6c085e29027a626c283f", 20],
  ["pitch 32", { tierYPitch: 32 }, "9712d10b078ffc5601e1a91496ee70caa22555dc20c13b04a0ebc2934de6bcd7", 18],
  ["pitch 36", { tierYPitch: 36 }, "645a4e5ab84b2ba0ce9a6b69647c4f68ab6b029f3e83f548e2b37db207d2640f", 17],
  ["CROSS", { links: [...fabric.links, relinked("CROSS", "access1", "dist1")] }, "a7aa289733e3fcf6bda853cc8adad540e73f058efe3bc548dbd133cc9bb38a8f", 1],
  ["INTRA", { links: [...fabric.links, ...star("INTRA", "access1", TIER1)] }, "09fa93c8097c18f78e602a515ce64c3f76b19c810b8bd6a35ed385fce13dcb52", 12],
  [
    "TIGHT",
    { links: [...fabric.links, ...star("TIGHT", "dist1", TIER1)], tierYPitch: MIN_NODE_SEPARATION },
    "b49f1fbba27fccc37a1cf733a2d53d53f3642daeeed88b483beb21c6e45b700e",
    34,
  ],
];

describeGolden("computeLayout — the reference sample's geometry is the pre-index geometry, bit for bit", () => {
  it("is fed the input the digests were taken from", () => {
    const input = {
      devices: fabric.devices.map((d) => [d.id, d.host, d.order, d.tier, d.role, d.collected]),
      links: fabric.links.map((k) => [k.id, k.a, k.b, k.betweenness]),
      tiers: fabric.tiers,
    };
    expect(sha256(input), "the compiled sample's layout inputs changed: re-derive every GOLDEN_LAYOUT digest").toBe(
      GOLDEN_LAYOUT_INPUT,
    );
  });

  for (const [name, extra, digest, hints] of GOLDEN_LAYOUT) {
    it(`${name}: every coordinate, hint and diagnostic is unchanged`, () => {
      const l = computeLayout({ ...OPTS, ...extra });
      // The hint count first: it names the branch that moved when the digest does.
      expect(l.routeHints.length).toBe(hints);
      expect(sha256(geometryOf(l))).toBe(digest);
    });
  }
});

describe("computeLayout — a sliced run is the same layout", () => {
  it("gives a deeply equal result however small the slices, on every hint-bearing configuration", () => {
    for (const [name, extra] of GOLDEN_LAYOUT) {
      const whole = computeLayout({ ...OPTS, ...extra });
      const job = layoutJob({ ...OPTS, ...extra });
      let slices = 0;
      let out: FabricLayout | null = null;
      while (out === null) {
        out = job.step(1);
        slices += 1;
      }
      // A budget of one stops at every yield, so this is the most finely divided run there is.
      expect(slices, `${name}: the run never yielded`).toBeGreaterThan(fabric.links.length);
      expect(job.done).toBe(true);
      expect(job.result).toBe(out);
      expect(out, name).toEqual(whole);
    }
  });

  it("a job whose step threw stays failed: every later step rethrows the same error, and it never reads as done", () => {
    /* A generator that throws is closed, and a closed generator's next() answers { done: true, value:
       undefined }. Without a latch, the step AFTER a failure therefore "finished" the layout with
       `undefined`: `done` true, `result` undefined — a failure read back as a finished layout. The stage
       re-reads a job it has already stepped (StrictMode, a retry), so the latch is on the job itself. */
    const job = layoutJob({ ...OPTS, seed: Number.NaN });
    const caught = (): unknown => {
      try {
        job.step(1);
      } catch (e) {
        return e;
      }
      return "no throw";
    };
    const first = caught();
    expect(first, "precondition: a non-finite seed is refused").toBeInstanceOf(Error);
    expect(caught(), "the second step did not rethrow the job's failure").toBe(first);
    expect(caught()).toBe(first);
    expect(job.done, "a failed layout reads as done").toBe(false);
    expect(job.result, "a failed layout has a result").toBeNull();
    expect(job.failure).toEqual({ error: first });
  });
});

/* ── crossing reduction ────────────────────────────────────────────────────── */

describe("computeLayout — crossing reduction", () => {
  it("produces measurably fewer crossings than the naive snapshot ordering", () => {
    const naive = computeLayout({ ...OPTS, sweeps: 0 });
    const naiveCrossings = countCrossings(naive, fabric.links);
    const sweptCrossings = countCrossings(layout, fabric.links);
    expect(naiveCrossings).toBeGreaterThan(0);
    expect(
      sweptCrossings,
      `barycentre sweeps: ${naiveCrossings} → ${sweptCrossings} crossings`,
    ).toBeLessThan(naiveCrossings);
    // Not a rounding win: the sweeps must remove most of them, or the ordering step is decoration.
    expect(sweptCrossings).toBeLessThanOrEqual(naiveCrossings / 2);
    // The engine's own counters must agree with this independent count, or its diagnostics lie.
    expect(layout.diagnostics.crossingsFinal).toBe(sweptCrossings);
    expect(naive.diagnostics.crossingsInitial).toBe(naiveCrossings);
    expect(naive.diagnostics.crossingsFinal).toBe(naiveCrossings);
  });

  it("never returns an ordering worse than the one it started from", () => {
    expect(layout.diagnostics.crossingsFinal).toBeLessThanOrEqual(
      layout.diagnostics.crossingsInitial,
    );
    expect(layout.diagnostics.sweeps).toBeGreaterThan(0);
  });
});

/* ── camera framing ────────────────────────────────────────────────────────── */

describe("computeLayout — camera framing", () => {
  it("returns a bounding sphere that contains every node", () => {
    const { center, radius } = layout.framing.boundingSphere;
    expect(radius).toBeGreaterThan(0);
    const outside = layout.nodes
      .filter((n) => distance(at(n), center) > radius + 1e-9)
      .map((n) => n.id);
    expect(outside).toEqual([]);
  });

  it("frames the whole fabric inside the declared frustum", () => {
    const { position, target, fovDeg, aspect, near, far } = layout.framing;
    const forward = norm(sub(target, position));
    const right = norm(cross(forward, [0, 1, 0]));
    const up = cross(right, forward);
    const tanV = Math.tan((fovDeg * Math.PI) / 360);
    const tanH = tanV * aspect;
    for (const n of layout.nodes) {
      const d = sub(at(n), position);
      const depth = dot(d, forward);
      expect(depth).toBeGreaterThan(near);
      expect(depth).toBeLessThan(far);
      expect(Math.abs(dot(d, up))).toBeLessThanOrEqual(depth * tanV);
      expect(Math.abs(dot(d, right))).toBeLessThanOrEqual(depth * tanH);
    }
  });

  it("frames a device and its neighbours on focus, and refuses an unknown host", () => {
    const f = focusFraming(layout, "dist1");
    expect(f).not.toBeNull();
    const neighbourhood = ["dist1", ...(layout.adjacency.get("dist1") ?? [])];
    expect(neighbourhood.length).toBeGreaterThan(1);
    const outside = neighbourhood.filter(
      (id) => distance(at(layout.byId.get(id)!), f!.boundingSphere.center) > f!.boundingSphere.radius + 1e-9,
    );
    expect(outside).toEqual([]);
    // Drilling in must actually narrow the view, and a wider hop radius must widen it again.
    expect(f!.boundingSphere.radius).toBeLessThan(layout.framing.boundingSphere.radius);
    expect(focusFraming(layout, "dist1", 0)!.boundingSphere.radius).toBeLessThan(
      f!.boundingSphere.radius,
    );
    // Absence is not a default view: an unknown host yields null, never the overview framing.
    expect(focusFraming(layout, "no-such-host")).toBeNull();
  });
});

/* ── cable routing hints ───────────────────────────────────────────────────── */

describe("computeLayout — route hints", () => {
  it("only hints links that exist, with finite midpoints", () => {
    // The shipped fabric produces NO hints, so running this over `layout` would assert nothing at
    // all — a green test proving only that a loop body never executed. It runs instead over the
    // flattest pitch that makes real cables graze real chassis, and the count is asserted first so
    // a data or constant change that empties the list fails here instead of passing vacuously.
    const flat = computeLayout({ ...OPTS, tierYPitch: 26 });
    expect(flat.routeHints.length).toBeGreaterThan(0);
    const ids = new Set(fabric.links.map((l) => l.id));
    for (const h of flat.routeHints) {
      expect(ids.has(h.linkId)).toBe(true);
      expect(h.mid.every((v) => Number.isFinite(v))).toBe(true);
      expect(h.reason.length).toBeGreaterThan(0);
      expect(h.blockedBy.length).toBeGreaterThan(0);
    }
    expect(flat.linkMidpoints.size).toBe(flat.routeHints.length);
    for (const h of flat.routeHints) expect(flat.linkMidpoints.get(h.linkId)).toEqual(h.mid);
    // And the shipped fabric's empty list is still a checked fact, not an untested assumption.
    expect(layout.linkMidpoints.size).toBe(layout.routeHints.length);
  });

  it("proves the claim behind an ABSENT hint: the straight route really is clear", () => {
    const hinted = new Set(layout.routeHints.map((h) => h.linkId));
    const violations: string[] = [];
    for (const link of fabric.links) {
      if (hinted.has(link.id)) continue;
      const a = layout.byId.get(link.a);
      const b = layout.byId.get(link.b);
      if (!a || !b) continue;
      for (const n of layout.nodes) {
        if (n.id === a.id || n.id === b.id) continue;
        const { d, t } = pointSegment(at(n), at(a), at(b));
        if (t <= ROUTE_T_MARGIN || t >= 1 - ROUTE_T_MARGIN) continue;
        if (d < ROUTE_CLEARANCE) violations.push(`${link.id} grazes ${n.id} at ${d.toFixed(1)}`);
      }
    }
    expect(violations).toEqual([]);
    // On the shipped fabric at the shipped pitch every cable is clear — stated, not assumed.
    expect(layout.routeHints).toEqual([]);
  });

  it("holds the layering invariant that makes an inter-tier detour unnecessary", () => {
    // Layers are BFS depths over the tier graph and every link is an edge of it, so no link can
    // span non-adjacent layers. Published as data so the invariant is checked, not asserted.
    expect(layout.diagnostics.linksSpanningNonAdjacentLayers).toEqual([]);
    const spans = fabric.links.filter((l) => {
      const a = layout.byId.get(l.a);
      const b = layout.byId.get(l.b);
      return a && b && Math.abs(a.layer - b.layer) >= 2;
    });
    expect(spans.map((l) => l.id)).toEqual([]);
  });

  it("bows a cable that runs inside one tier past other chassis", () => {
    // access1 linked to its whole tier (see `star`); access1↔access16 are both real tier-1
    // switches and the link record is cloned from a real one.
    const l = computeLayout({ ...OPTS, links: [...fabric.links, ...star("INTRA", "access1", TIER1)] });
    const hint = l.routeHints.find((h) => h.linkId === "INTRA:access16");
    expect(hint?.kind).toBe("intra-tier");
    expect(hint!.blockedBy.length).toBeGreaterThan(0);
    expect(hint!.clearance).toBeLessThan(ROUTE_CLEARANCE);
    const plane = l.byId.get("access1")!.y;
    expect(l.byId.get("access16")!.y).toBe(plane);
    expect(hint!.mid[1]).toBeGreaterThan(plane);
  });

  it("routes a cable between two blocks on one plane behind the fabric", () => {
    // access1 (tier 1) and dist1 (tier 3) are hop-equal, so they share a Y plane: the contract's
    // "non-adjacent tiers" case, reachable exactly here.
    const l = computeLayout({ ...OPTS, links: [...fabric.links, relinked("CROSS", "access1", "dist1")] });
    const hint = l.routeHints.find((h) => h.linkId === "CROSS");
    expect(hint?.kind).toBe("cross-tier-plane");
    expect(l.byId.get("access1")!.y).toBe(l.byId.get("dist1")!.y);
    expect(l.byId.get("access1")!.tier).not.toBe(l.byId.get("dist1")!.tier);
    // Behind the fabric, never across its face.
    expect(hint!.mid[2]).toBeLessThan(l.bounds.min[2]);
  });

  it("detours a real cable that a flatter tier pitch would push into a chassis", () => {
    // Same fabric, same links: at a 36-unit pitch core1↔access2 (L19) runs down its column over
    // access4 within ROUTE_CLEARANCE, and the engine says so instead of drawing the cable through it.
    const flat = computeLayout({ ...OPTS, tierYPitch: 36 });
    const link = fabric.links.find((l) => l.id === "L19")!;
    expect([link.a, link.b].sort()).toEqual(["access2", "core1"]);
    const hint = flat.routeHints.find((h) => h.linkId === "L19");
    expect(hint?.kind).toBe("adjacent-obstructed");
    expect(hint!.clearance).toBeLessThan(ROUTE_CLEARANCE);
    const a = flat.byId.get("core1")!;
    const b = flat.byId.get("access2")!;
    expect(Math.abs(a.layer - b.layer)).toBe(1);
    // The detour has to move the cable off the straight line it was failing on.
    const straightMid: Vec3 = [(a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2];
    expect(Math.abs(hint!.mid[2] - straightMid[2])).toBeGreaterThan(ROUTE_CLEARANCE);
  });

  it("never lets a flattened pitch break the separation guarantee it promised", () => {
    const flat = computeLayout({ ...OPTS, tierYPitch: 1 });
    let min = Infinity;
    for (let i = 0; i < flat.nodes.length; i += 1) {
      for (let j = i + 1; j < flat.nodes.length; j += 1) {
        min = Math.min(min, distance(at(flat.nodes[i]!), at(flat.nodes[j]!)));
      }
    }
    expect(min).toBeGreaterThanOrEqual(MIN_NODE_SEPARATION - 1e-9);
  });
});

/* ── refuter regressions ───────────────────────────────────────────────────────
   Each test below reproduces a confirmed defect found by an adversarial read of this module. They
   are grouped so the shape of each failure stays legible: a claim the code did not compute, a
   positional artifact published as evidence, an unvalidated input, and missing evidence rendered
   as a structural fact. */

describe("computeLayout — the suggested detour is measured, not assumed", () => {
  /** Every configuration in this repo known to produce a hint, with the link table each needs. */
  const hintingCases = (): { label: string; layout: FabricLayout; links: readonly Link[] }[] => {
    const cases: { label: string; layout: FabricLayout; links: readonly Link[] }[] = [];
    // MIN_NODE_SEPARATION is the flattest fabric the engine will build, and the one where a detour
    // has least room to work — the configuration most likely to expose a false claim of clearance.
    for (const pitch of [MIN_NODE_SEPARATION, 26, 28, 32, 36]) {
      cases.push({
        label: `pitch${pitch}`,
        layout: computeLayout({ ...OPTS, tierYPitch: pitch }),
        links: fabric.links,
      });
    }
    for (const [id, extra, pitch] of [
      ["CROSS", [relinked("CROSS", "access1", "dist1")], undefined],
      ["INTRA", star("INTRA", "access1", TIER1), undefined],
      // Reaches the branch where no detour in the ladder clears; see the "could not clear" test.
      ["TIGHT", star("TIGHT", "dist1", TIER1), MIN_NODE_SEPARATION],
    ] as const) {
      const links = [...fabric.links, ...extra];
      cases.push({
        label: id,
        layout: computeLayout({ ...OPTS, links, ...(pitch === undefined ? {} : { tierYPitch: pitch }) }),
        links,
      });
    }
    return cases;
  };

  it("never claims a detour clears a chassis it still passes through", () => {
    const cases = hintingCases();
    const hinted = cases.reduce((s, c) => s + c.layout.routeHints.length, 0);
    // Guard against the vacuous-green shape: this suite must actually exercise hint branches.
    expect(hinted, "no configuration produced a hint — the audit below proves nothing").toBeGreaterThan(8);
    const lies = cases.flatMap((c) => auditHints(c.layout, c.links, c.label));
    expect(lies).toEqual([]);
  });

  it("clears the case the CROSS detour was written for, and says by how much", () => {
    // Regression: the control point was pushed SPAN_CLEARANCE behind the fabric, but a quadratic's
    // apex reaches only half its control offset, so the drawn curve still passed 10.54 from
    // access17 — inside the very ROUTE_CLEARANCE that declared the straight route obstructed.
    const links = [...fabric.links, relinked("CROSS", "access1", "dist1")];
    const l = computeLayout({ ...OPTS, links });
    const h = l.routeHints.find((x) => x.linkId === "CROSS")!;
    expect(h.kind).toBe("cross-tier-plane");
    expect(h.clearance!).toBeLessThan(ROUTE_CLEARANCE); // the straight route really was blocked
    const measured = curveClearance(l, h, l.byId.get("access1")!, l.byId.get("dist1")!);
    expect(
      measured.min,
      `suggested curve passes ${measured.min.toFixed(2)} from ${measured.worst}`,
    ).toBeGreaterThanOrEqual(ROUTE_CLEARANCE);
    expect(h.resolution).toBe("cleared");
    expect(h.routedBlockedBy).toEqual([]);
    expect(h.mid[2]).toBeLessThan(l.bounds.min[2]);
  });

  it("makes INTRA_TIER_BOW describe the drawn cable, not the control point", () => {
    // The constant names an APEX. access1↔access16 clears on the first candidate, so the published
    // curve must rise exactly INTRA_TIER_BOW above the chord — the figure the comment promises.
    const links = [...fabric.links, ...star("INTRA", "access1", TIER1)];
    const l = computeLayout({ ...OPTS, links });
    const h = l.routeHints.find((x) => x.linkId === "INTRA:access16")!;
    expect(h.kind).toBe("intra-tier");
    expect(h.resolution).toBe("cleared");
    expect(h.apexOffset).toBe(INTRA_TIER_BOW);
    const a = l.byId.get("access1")!;
    const b = l.byId.get("access16")!;
    const apex = bezier(at(a), h.mid, at(b), 0.5);
    // Same plane, so the whole apex is vertical: the bow's height IS the documented constant.
    expect(apex[1] - a.y).toBeCloseTo(INTRA_TIER_BOW, 9);
    expect(h.mid[1] - a.y).toBeCloseTo(2 * INTRA_TIER_BOW, 9);
  });

  it("clears the intra-tier bow across every real tier-1 pair that needs one", () => {
    // Regression: 8 of the 72 hinted tier-1 pairs bowed to an apex of 13.00 against a 12-unit
    // threshold and still grazed access8. The sweep is over every real pair, not the ones that
    // happened to fail, because a fix scoped to the failing names is not a fix. Every tier-1 switch
    // is made a hub of its whole tier in turn (see `star` for why a lone pair no longer obstructs).
    const lies: string[] = [];
    let hinted = 0;
    for (const hub of TIER1) {
      const links = [...fabric.links, ...star("PAIR", hub, TIER1)];
      const l = computeLayout({ ...OPTS, links });
      for (const h of l.routeHints) {
        if (!h.linkId.startsWith("PAIR:")) continue;
        const other = h.linkId.slice("PAIR:".length);
        hinted += 1;
        const m = curveClearance(l, h, l.byId.get(hub)!, l.byId.get(other)!);
        if (h.resolution === "cleared" && m.min < ROUTE_CLEARANCE) {
          lies.push(`${hub}-${other}: "cleared" at ${m.min.toFixed(2)} from ${m.worst}`);
        }
      }
    }
    expect(hinted).toBeGreaterThan(50);
    expect(lies).toEqual([]);
  });

  it("reports a detour it could not clear instead of publishing it as clean", () => {
    // The escalation ladder is bounded, so "cleared" must be a computed outcome and not a
    // guaranteed one. Whatever the outcome, the hint carries the measurement that decided it.
    let unresolved = 0;
    for (const c of hintingCases()) {
      for (const h of c.layout.routeHints) {
        expect(h.routedClearance).not.toBeNull();
        expect(Number.isFinite(h.routedClearance!)).toBe(true);
        expect(["cleared", "unresolved"]).toContain(h.resolution);
        if (h.resolution === "unresolved") {
          unresolved += 1;
          expect(h.routedBlockedBy.length).toBeGreaterThan(0);
          expect(h.routedClearance!).toBeLessThan(ROUTE_CLEARANCE);
          // The prose must carry the failure too: a renderer that shows only `reason` still says so.
          expect(h.reason).toContain("still within");
        }
      }
    }
    // The honest branch is not dead code, and this suite is not passing it by: at the flattest
    // fabric the engine will build, a real cable exists that no detour in the ladder clears.
    expect(unresolved, "the unresolved branch never fired — this test proves nothing about it")
      .toBeGreaterThan(0);
  });

  it("names what is still in the way when it gives up, rather than going quiet", () => {
    // dist1↔access2 at the flattest pitch, with dist1 linked to the whole access tier: the detour
    // swings SPAN_CLEARANCE behind the fabric and still cannot get the cable's shoulders past the
    // access block, because the obstruction is near the endpoints where a mid-point control has
    // least leverage. That is a real limit of a quadratic route, and the correct output is to say
    // so — not to publish the curve as solved.
    const links = [...fabric.links, ...star("TIGHT", "dist1", TIER1)];
    const l = computeLayout({ ...OPTS, links, tierYPitch: MIN_NODE_SEPARATION });
    const h = l.routeHints.find((x) => x.linkId === "TIGHT:access2")!;
    expect(h.resolution).toBe("unresolved");
    expect(h.routedBlockedBy.length).toBeGreaterThan(0);
    // It is still the BEST curve found, not a giving-up-in-place: it must beat the straight route.
    expect(h.routedClearance!).toBeGreaterThan(h.clearance!);
    expect(h.routedClearance!).toBeLessThan(ROUTE_CLEARANCE);
    const measured = curveClearance(l, h, l.byId.get("dist1")!, l.byId.get("access2")!);
    expect(Math.abs(measured.min - h.routedClearance!)).toBeLessThan(1.5);
    expect(h.routedBlockedBy).toContain(measured.worst);
  });
});

describe("computeLayout — the cable map is a partition, not a tier numbering", () => {
  /** The snapshot's own device records with one device's tier field cleared. */
  const devicesMinusWanTier = fabric.devices.map((d) =>
    d.id === "wan-edge-rtr1.lab" ? { ...d, tier: null } : d,
  );

  it("does not let the partition's array order become a device's observed tier", () => {
    // Regression: `tiers.forEach((hosts, index) => ...index)` published the ARRAY POSITION as the
    // tier of a device whose record had none — and since there was no record value to disagree
    // with, no diagnostic named it. Reordering the same partition moved the device's Y plane.
    const full = computeLayout({ devices: devicesMinusWanTier, links: fabric.links, tiers: fabric.tiers });
    const withoutAp = computeLayout({
      devices: devicesMinusWanTier,
      links: fabric.links,
      // Same partition, same evidence — one group the wan router is not a member of removed.
      tiers: fabric.tiers.filter((t) => !t.includes("AP-floor1")),
    });
    const permuted = computeLayout({
      devices: devicesMinusWanTier,
      links: fabric.links,
      tiers: [...fabric.tiers].reverse(),
    });
    for (const other of [withoutAp, permuted]) {
      expect(other.diagnostics.tierDisagreements).toEqual([]);
      for (const n of full.nodes) {
        const o = other.byId.get(n.id)!;
        expect(
          [o.observedTier, o.tier, o.x, o.y, o.z],
          `${n.id} moved when the cable map's list order changed`,
        ).toEqual([n.observedTier, n.tier, n.x, n.y, n.z]);
      }
    }
    // The tier it takes is the one its own group's members are recorded at — evidence, not index.
    expect(full.byId.get("wan-edge-rtr1.lab")!.observedTier).toBe(3);
  });

  it("refuses to invent a tier for a group whose members have no recorded tier", () => {
    // podacc1/podacc2 are a whole cable-map group; clear both records and the group can no longer
    // vouch for a number. Absence must stay absence rather than collapsing to a list index.
    const devices = fabric.devices.map((d) =>
      d.id === "podacc1" || d.id === "podacc2" ? { ...d, tier: null } : d,
    );
    const l = computeLayout({ devices, links: fabric.links, tiers: fabric.tiers });
    expect(l.diagnostics.devicesWithoutObservedTier).toEqual(["podacc1", "podacc2"]);
    expect(l.byId.get("podacc1")!.observedTier).toBeNull();
    expect(l.byId.get("podacc2")!.observedTier).toBeNull();
    expect(l.diagnostics.syntheticTier).not.toBeNull();
    const bucket = l.tierBounds.find((b) => b.tier === l.diagnostics.syntheticTier)!;
    expect(bucket.observedTier).toBeNull();
  });

  it("publishes how each cable-map group was reconciled, including the ones it could not be", () => {
    const l = computeLayout(OPTS);
    expect(l.diagnostics.cableMapGroups).toHaveLength(fabric.tiers.length);
    for (const g of l.diagnostics.cableMapGroups) {
      expect(g.members).toBe(fabric.tiers[g.index]!.length);
      expect(g.basis).toBe("device-consensus");
      expect(g.tier).not.toBeNull();
    }
    // Every group on this fabric resolves; a group that cannot must say so rather than take a number.
    const split = [...fabric.tiers, ["core1", "podacc1"]];
    const conflicted = computeLayout({ ...OPTS, tiers: split });
    const last = conflicted.diagnostics.cableMapGroups[split.length - 1]!;
    expect(last.basis).toBe("no-consensus");
    expect(last.tier).toBeNull();
  });
});

describe("computeLayout — option validation", () => {
  /* Every numeric option, derived from LayoutOptions by type rather than listed from memory: a
     numeric option added to LayoutOptions and missing here, or a key here that is not one, fails
     `tsc` (`satisfies` checks both directions on an object literal). */
  type NumericOption = {
    [K in keyof LayoutOptions]-?: NonNullable<LayoutOptions[K]> extends number ? K : never;
  }[keyof LayoutOptions];
  const NUMERIC_OPTIONS = {
    seed: true,
    sweeps: true,
    tierYPitch: true,
    fovDeg: true,
    aspect: true,
    margin: true,
  } as const satisfies Record<NumericOption, true>;

  it("refuses every non-finite numeric option before laying anything out: no fabric comes back, and no layout work runs first", () => {
    /* The BEHAVIOUR the input guard exists for, judged without reading any error message (repair
       wave 7: the message test below was the only thing that noticed the guard's removal, because
       the output post-condition then threw instead, with other wording). A refusal counts only if
       nothing is returned AND it came before the layout did any work — fewer counted primitive
       operations than there are devices to place. A NaN that reaches the post-condition has already
       been laid out, and one the post-condition cannot see (a NaN seed is `>>> 0`, a NaN sweep count
       runs no sweeps) comes back as a plausible fabric. The runaway guard turns an infinite sweep
       count into a failure here rather than a timeout. */
    const upFront = fabric.devices.length;
    const failures: string[] = [];
    let judged = 0;
    for (const name of Object.keys(NUMERIC_OPTIONS) as NumericOption[]) {
      for (const bad of [NaN, Infinity, -Infinity]) {
        let returned: FabricLayout | undefined;
        let thrown: unknown;
        const ops = primitiveOps(() => {
          try {
            returned = computeLayout({ ...OPTS, [name]: bad });
          } catch (e) {
            thrown = e;
          }
        }, 1_000_000);
        judged += 1;
        const at = `${name}=${bad}`;
        if (returned !== undefined) failures.push(`${at}: returned a fabric after ${ops} primitive operations`);
        else if (thrown instanceof RunawayWork) failures.push(`${at}: never refused — ${thrown.message}`);
        else if (!(thrown instanceof Error)) failures.push(`${at}: neither returned nor threw an Error`);
        else if (ops >= upFront) failures.push(`${at}: refused only after ${ops} primitive operations of layout work`);
      }
    }
    expect(judged, "every numeric option was tried with every non-finite value").toBe(Object.keys(NUMERIC_OPTIONS).length * 3);
    expect(failures, "a non-finite option was not refused before layout work began").toEqual([]);
  });

  it("names the offending option in each refusal, and range-checks aspect, fovDeg and margin", () => {
    // Regression: Math.max(MIN_NODE_SEPARATION, NaN) is NaN, so every Y, the bounding sphere and
    // the camera came back NaN with no throw and no diagnostic. The refusal itself is judged by
    // behaviour in the test above; this one pins that the refusal says WHICH option was wrong.
    for (const bad of [NaN, Infinity, -Infinity]) {
      expect(() => computeLayout({ ...OPTS, tierYPitch: bad })).toThrow(/tierYPitch/);
      expect(() => computeLayout({ ...OPTS, margin: bad })).toThrow(/margin/);
      expect(() => computeLayout({ ...OPTS, seed: bad })).toThrow(/seed/);
      expect(() => computeLayout({ ...OPTS, sweeps: bad })).toThrow(/sweeps/);
    }
    // aspect 0 produced an Infinity camera distance; fov outside (0,180) has no frustum at all.
    expect(() => computeLayout({ ...OPTS, aspect: 0 })).toThrow(/aspect/);
    expect(() => computeLayout({ ...OPTS, aspect: -1 })).toThrow(/aspect/);
    expect(() => computeLayout({ ...OPTS, fovDeg: 0 })).toThrow(/fovDeg/);
    expect(() => computeLayout({ ...OPTS, fovDeg: 180 })).toThrow(/fovDeg/);
    expect(() => computeLayout({ ...OPTS, margin: 0 })).toThrow(/margin/);
  });

  it("still clamps a finite pitch that would let two chassis touch across planes", () => {
    const flat = computeLayout({ ...OPTS, tierYPitch: -1000 });
    expect(flat.layerY.every((y) => Number.isFinite(y))).toBe(true);
    const planes = [...new Set(flat.layerY)].sort((a, b) => a - b);
    for (let i = 1; i < planes.length; i += 1) {
      expect(planes[i]! - planes[i - 1]!).toBeGreaterThanOrEqual(MIN_NODE_SEPARATION - 1e-9);
    }
  });

  it("checks the finiteness of its own output, not just of its inputs", () => {
    const l = computeLayout(OPTS);
    const bad = l.nodes.filter(
      (n) => !Number.isFinite(n.x) || !Number.isFinite(n.y) || !Number.isFinite(n.z),
    );
    expect(bad).toEqual([]);
    expect(Number.isFinite(l.framing.boundingSphere.radius)).toBe(true);
    expect(l.framing.position.every((v) => Number.isFinite(v))).toBe(true);
    expect(Number.isFinite(l.framing.near) && Number.isFinite(l.framing.far)).toBe(true);
  });
});

describe("computeLayout — a dropped link is not an absence of neighbours", () => {
  /**
   * core1's 11 links still NAME core1, but each far end now names a host with no device record.
   * That is the shape the defect lives in: the evidence of core1's adjacency is present and
   * unusable, which is not the same fact as core1 having no neighbours.
   */
  const ghosted = computeLayout({
    devices: fabric.devices,
    links: fabric.links.map((l) =>
      l.a === "core1" ? { ...l, b: "ghost-x" } : l.b === "core1" ? { ...l, a: "ghost-x" } : l,
    ),
    tiers: fabric.tiers,
  });

  it("never reports a device whose links were dropped as structurally isolated", () => {
    // Regression: core1 — the most connected device in the fabric — came back degree 0 and named
    // in isolatedHosts, identical in shape to a device that genuinely has no neighbours.
    expect(ghosted.diagnostics.linksWithUnplacedEndpoint).toHaveLength(11);
    expect(ghosted.diagnostics.isolatedHosts).not.toContain("core1");
    const dropped = ghosted.diagnostics.hostsWithDroppedAdjacency.find((h) => h.host === "core1")!;
    expect(dropped.droppedLinks).toHaveLength(11);
    expect(ghosted.byId.get("core1")!.droppedAdjacency).toBe(11);
    expect(ghosted.byId.get("core1")!.degree).toBe(0);
  });

  it("still reports a genuinely disconnected device as isolated", () => {
    // The distinguishing evidence must actually distinguish: same shape, opposite cause.
    const cut = computeLayout({
      devices: fabric.devices,
      links: fabric.links.filter((l) => l.a !== "podacc1" && l.b !== "podacc1"),
      tiers: fabric.tiers,
    });
    expect(cut.diagnostics.isolatedHosts).toContain("podacc1");
    expect(cut.diagnostics.linksWithUnplacedEndpoint).toEqual([]);
    expect(cut.diagnostics.hostsWithDroppedAdjacency).toEqual([]);
    expect(cut.byId.get("podacc1")!.droppedAdjacency).toBe(0);
  });

  it("carries the dropped-link denominator onto the hub-tier evidence computed without them", () => {
    // rootTier's betweenness statistics are computed on the surviving graph; a reader cannot judge
    // that basis without knowing how much of the graph never reached it.
    expect(ghosted.diagnostics.rootTier.droppedLinks).toBe(11);
    expect(ghosted.diagnostics.rootTier.detail).toContain("11");
    expect(layout.diagnostics.rootTier.droppedLinks).toBe(0);
    expect(layout.diagnostics.hostsWithDroppedAdjacency).toEqual([]);
    for (const n of layout.nodes) expect(n.droppedAdjacency).toBe(0);
  });
});

/* ── diagnostics + budget ──────────────────────────────────────────────────── */

describe("computeLayout — honesty and budget", () => {
  it("reports no synthetic tier for this fabric, because every device has an observed one", () => {
    const d = layout.diagnostics;
    expect(d.devicesWithoutObservedTier).toEqual([]);
    expect(d.syntheticTier).toBeNull();
    expect(d.tierDisagreements).toEqual([]);
    expect(d.cableMapHostsWithoutDevice).toEqual([]);
    expect(d.linksWithUnplacedEndpoint).toEqual([]);
    expect(d.tiersUnreachableFromRoot).toEqual([]);
    expect(d.isolatedHosts).toEqual([]);
    for (const n of layout.nodes) expect(n.observedTier).toBe(n.tier);
  });

  it("places a device with no observed tier instead of dropping it, and says so", () => {
    // Real device records with the tier field cleared: the snapshot's own shape, minus one field.
    const devices = fabric.devices.map((d) => (d.id === "wan-edge-rtr1.lab" ? { ...d, tier: null } : d));
    const l = computeLayout({ devices, links: fabric.links, tiers: [] });
    expect(l.byId.has("wan-edge-rtr1.lab")).toBe(true);
    expect(l.diagnostics.devicesWithoutObservedTier).toEqual(["wan-edge-rtr1.lab"]);
    expect(l.diagnostics.syntheticTier).not.toBeNull();
    // The bucket it was drawn in must never read back as an observed tier.
    expect(l.byId.get("wan-edge-rtr1.lab")!.observedTier).toBeNull();
    expect(l.tierBounds.find((b) => b.tier === l.diagnostics.syntheticTier)!.observedTier).toBeNull();
  });

  /* WORK, NOT TIME (O26; acceptance F2, 2026-09-24). This was a median of seven wall-clock runs
     under 50 ms, and its comment called it the only timing assertion that had never flaked and said
     "the other two were rewritten to match it". By wave 4 both halves were false: R64 replaced the
     engine's and the palette's timings with COUNTS, not with this shape, and vitest.config.ts's rule
     is that a unit test asserts no wall-clock time at all. A median absorbs one scheduler stall; it
     does not absorb a host that is 85 % busy for the whole run, and it cannot tell an algorithmic
     blow-up from that host.

     The count is deterministic — the same number on every run and every seed (the layout reads no
     clock, and the seed moves only the jitter) — so it is held to a budget with no margin for noise. The budget is stated in the fabric's own size, so a larger fabric earns a
     larger one and only a change in the ORDER of the work goes red:
       - 12·E·N — the straight-route clearance scan at its exhaustive size: every placed link against
         every other chassis (3 counted calls a pair), and everything else outside the sweeps linear
         in N + E. Since the chassis index (2026-09-28) a link is measured only against the chassis the
         index returns near it, so on a fabric this small the term is a loose ceiling; scale.test.ts
         holds the index to its own near-linear budget on 300- and 1 000-node fleets, where the
         difference is the point. Measured on this fabric with sweeps 0: 7 035 before the index,
         9 969 after (the index is built even where a fabric this small gains nothing), against 13 728.
       - 20·(N + E) per barycentre sweep — one reorder pass per layer and one crossing count.
         Measured: 764 a sweep, against 1 400.
       - per route hint, 2 directions × ROUTE_DETOUR_STEPS candidates, each measured against every
         chassis along ROUTE_CURVE_SAMPLES segments at 5 counted calls: the detour ladder at its
         longest. Measured with the pitch flattened to 26: 20 hints, 33 558 a hint, against 74 880.
     In all, 16 206 at the defaults (20 184 since the index) against 30 528: about 2x headroom on each term over what the
     layout does today (1.3x on a detour that exhausts its whole ladder), and the known answer below
     proves the sweep term is not decorative — a sweep loop run N times over is red. */
  const workBudget = (n: number, e: number, sweeps: number, hints: number): number =>
    12 * e * n + 20 * sweeps * (n + e) + hints * 2 * ROUTE_DETOUR_STEPS * n * ROUTE_CURVE_SAMPLES * 5;
  const N = fabric.devices.length;
  const E = fabric.links.length;

  it("lays out the full fabric within a counted work budget stated in its own size, on every seed", () => {
    for (let i = 0; i < 7; i += 1) {
      let l: FabricLayout | undefined;
      const ops = primitiveOps(() => {
        l = computeLayout({ ...OPTS, seed: 100 + i });
      });
      // Stated, not assumed: no route hint fires on the shipped fabric (see the "absent hint" test).
      expect(l!.routeHints, "precondition: the shipped fabric needs no detour").toHaveLength(0);
      // The instrument is live. This floor was derived as "the clearance scan alone makes 3 counted
      // calls per (link, chassis)"; the index broke that derivation, not the floor (20 184 counted
      // calls against 3 168), so it stays as a floor and is no longer explained as the scan's work.
      expect(ops, "the counter saw less than 3·E·(N−2) operations").toBeGreaterThanOrEqual(3 * E * (N - 2));
      expect(ops, `seed ${100 + i}: ${ops} primitive operations`).toBeLessThanOrEqual(workBudget(N, E, l!.diagnostics.sweeps, 0));
    }
  });

  it("holds each term of the budget on its own: no sweeps, and a pitch flat enough that the detour ladder runs", () => {
    let still: FabricLayout | undefined;
    const noSweeps = primitiveOps(() => {
      still = computeLayout({ ...OPTS, sweeps: 0 });
    });
    expect(still!.diagnostics.sweeps).toBe(0);
    expect(noSweeps).toBeLessThanOrEqual(workBudget(N, E, 0, 0));

    let flat: FabricLayout | undefined;
    const detours = primitiveOps(() => {
      flat = computeLayout({ ...OPTS, tierYPitch: 26 });
    });
    expect(flat!.routeHints.length, "precondition: the flattened pitch makes the detour ladder run").toBeGreaterThan(0);
    expect(detours).toBeLessThanOrEqual(workBudget(N, E, flat!.diagnostics.sweeps, flat!.routeHints.length));
  });

  it("known answer: a sweep loop run N times over its bound is over budget", () => {
    // The blow-up, reproduced through the public option: the default sweeps × N, judged against the
    // budget for the default sweeps. A budget that could not see this could not see the bug.
    const defaultSweeps = layout.diagnostics.sweeps;
    expect(defaultSweeps, "precondition: the layout sweeps by default").toBeGreaterThan(0);
    const blown = primitiveOps(() => {
      computeLayout({ ...OPTS, sweeps: defaultSweeps * N });
    });
    expect(blown).toBeGreaterThan(workBudget(N, E, defaultSweeps, 0));
  });

  it("the counter counts what runs inside it, and puts every primitive back", () => {
    const push = Array.prototype.push;
    const max = Math.max;
    const arr: number[] = [];
    const n = primitiveOps(() => {
      for (let i = 0; i < 10; i += 1) arr.push(Math.max(i, 0));
    });
    expect(n).toBe(20);
    expect(Array.prototype.push).toBe(push);
    expect(Math.max).toBe(max);
    expect(primitiveOps(() => {})).toBe(0);
  });
});
