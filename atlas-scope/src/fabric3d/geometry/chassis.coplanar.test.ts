/**
 * chassis.coplanar.test.ts — no two opaque faces of a chassis assembly tie in depth (C5 z-fighting).
 *
 * WHY. The C5 motion harness (`review/capture-motion.mjs`) reported flip-flopping pixel clusters on
 * chassis edges during slow orbits, at both tiers, and open-issues O16 attributed them to
 * near-coplanar faces ("the pixels cannot say which faces tie"). Pixels cannot; geometry can. A depth
 * tie needs two SAME-FACING faces lying in (nearly) one plane and overlapping — back-to-back faces
 * cannot tie with single-sided materials, and faces a finite distance apart are resolved by the depth
 * buffer (24 bits over a near plane fitted to the drawn bounds: ~1e-4 world units at the overview
 * pose, ~5e-5 dollied in; see camera.ts).
 *
 * WHAT IT CHECKS. Every triangle of every part of every chassis kind, at every quality tier the
 * scene can build, plus the role glyph placed on the lid exactly as scene.ts places it: any pair of
 * same-facing triangles whose planes are within TIE_EPS of each other and whose projections overlap
 * by more than a speck is a tie. The check is over the CLASS (all faces of everything the chassis
 * draws, discovered from the built geometry), not over a list of suspected features.
 *
 * WHAT IT DOES NOT CHECK. Transparent, non-depth-writing decals (contact shadow, halo, pads, decks)
 * never write depth, so they cannot z-fight; their stacking is ground.ts's Y_* ladder. Sub-pixel
 * geometry that aliases while the camera creeps is a coverage problem, not a depth tie; the ONE
 * instance measured to produce the harness's chassis-edge clusters (the frame's top bar, seen from
 * above) is pinned by the last block below, and the general case is not claimed here.
 *
 * WHAT THE MEASUREMENT FOUND (2026-09-22, review/capture-motion.mjs's orbit-keys-slow replayed with
 * the camera matrices recorded per frame, each cluster raycast): no cluster ray crossed two surfaces
 * within 0.02 units of each other on a chassis — the clusters were the silhouette of the faceplate
 * frame's top bar. The one true same-plane overlap in the chassis assembly is the distribution role
 * glyph's crossing arms, found by this test and separated.
 */
import { BufferGeometry, Matrix4, Quaternion, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import type { QualityTier } from "../contract";
import { profileFor } from "../quality";
import { ALL_CHASSIS_KINDS, buildChassis, buildRoleGlyph, buildStateRing, chassisSpec, ROLE_GLYPHS, type RoleGlyph, type StateRingShape } from "./chassis";

/** Two parallel same-facing planes closer than this (world units) are a tie: 20x the depth
 *  buffer's resolution at the overview pose, so "not a tie" means comfortably resolved. */
const TIE_EPS = 0.002;
/** Overlap below this area (world units^2) is a shared edge or a rounding speck, not a face. */
const AREA_EPS = 1e-4;

interface Tri {
  part: string;
  p: [Vector3, Vector3, Vector3];
  n: Vector3;
  d: number;
}

function trianglesOf(g: BufferGeometry, part: string, m?: Matrix4): Tri[] {
  const pos = g.getAttribute("position");
  if (pos === undefined) return []; // an empty part (the access point has no rack ears)
  const index = g.getIndex();
  const count = index === null ? pos.count : index.count;
  const out: Tri[] = [];
  const at = (i: number): Vector3 => {
    const k = index === null ? i : index.getX(i);
    const v = new Vector3(pos.getX(k), pos.getY(k), pos.getZ(k));
    return m === undefined ? v : v.applyMatrix4(m);
  };
  for (let i = 0; i + 2 < count; i += 3) {
    const a = at(i);
    const b = at(i + 1);
    const c = at(i + 2);
    const n = new Vector3().subVectors(b, a).cross(new Vector3().subVectors(c, a));
    const len = n.length();
    if (len < 1e-9) continue; // degenerate
    n.divideScalar(len);
    out.push({ part, p: [a, b, c], n, d: n.dot(a) });
  }
  return out;
}

/** Area of the overlap of two coplanar triangles (Sutherland-Hodgman in the plane's 2-D basis). */
function overlapArea(t: Tri, u: Tri): number {
  const n = t.n;
  const ax = Math.abs(n.x) < 0.9 ? new Vector3(1, 0, 0) : new Vector3(0, 1, 0);
  const e1 = new Vector3().crossVectors(n, ax).normalize();
  const e2 = new Vector3().crossVectors(n, e1);
  const to2 = (v: Vector3): [number, number] => [v.dot(e1), v.dot(e2)];
  const orient = (poly: [number, number][]): [number, number][] => {
    let s = 0;
    for (let i = 0; i < poly.length; i += 1) {
      const [x0, y0] = poly[i]!;
      const [x1, y1] = poly[(i + 1) % poly.length]!;
      s += x0 * y1 - x1 * y0;
    }
    return s < 0 ? [...poly].reverse() : poly;
  };
  let subject = orient(t.p.map(to2));
  const clip = orient(u.p.map(to2));
  for (let i = 0; i < clip.length && subject.length > 0; i += 1) {
    const [cx0, cy0] = clip[i]!;
    const [cx1, cy1] = clip[(i + 1) % clip.length]!;
    const inside = ([x, y]: [number, number]): boolean => (cx1 - cx0) * (y - cy0) - (cy1 - cy0) * (x - cx0) >= -1e-12;
    const cross = (a: [number, number], b: [number, number]): [number, number] => {
      const [x1, y1] = a;
      const [x2, y2] = b;
      const den = (x1 - x2) * (cy0 - cy1) - (y1 - y2) * (cx0 - cx1);
      const tt = ((x1 - cx0) * (cy0 - cy1) - (y1 - cy0) * (cx0 - cx1)) / den;
      return [x1 + tt * (x2 - x1), y1 + tt * (y2 - y1)];
    };
    const input = subject;
    subject = [];
    for (let k = 0; k < input.length; k += 1) {
      const cur = input[k]!;
      const prev = input[(k + input.length - 1) % input.length]!;
      if (inside(cur)) {
        if (!inside(prev)) subject.push(cross(prev, cur));
        subject.push(cur);
      } else if (inside(prev)) {
        subject.push(cross(prev, cur));
      }
    }
  }
  let area = 0;
  for (let i = 0; i < subject.length; i += 1) {
    const [x0, y0] = subject[i]!;
    const [x1, y1] = subject[(i + 1) % subject.length]!;
    area += x0 * y1 - x1 * y0;
  }
  return Math.abs(area) / 2;
}

/** Every depth tie among `tris`: same-facing, planes within TIE_EPS, overlapping by > AREA_EPS. */
export function depthTies(tris: readonly Tri[]): string[] {
  // Bucket by the normal (to 1e-3) so only near-parallel faces are ever compared.
  const buckets = new Map<string, Tri[]>();
  for (const t of tris) {
    const key = `${Math.round(t.n.x * 1000)},${Math.round(t.n.y * 1000)},${Math.round(t.n.z * 1000)}`;
    const list = buckets.get(key) ?? [];
    list.push(t);
    buckets.set(key, list);
  }
  const ties: string[] = [];
  for (const list of buckets.values()) {
    list.sort((a, b) => a.d - b.d);
    for (let i = 0; i < list.length; i += 1) {
      const t = list[i]!;
      for (let j = i + 1; j < list.length && list[j]!.d - t.d < TIE_EPS; j += 1) {
        const u = list[j]!;
        if (t.n.dot(u.n) < 0.99999) continue;
        const area = overlapArea(t, u);
        if (area > AREA_EPS) {
          const c = new Vector3().add(t.p[0]).add(t.p[1]).add(t.p[2]).divideScalar(3);
          ties.push(
            `${t.part} x ${u.part}: planes ${(u.d - t.d).toFixed(4)} apart, overlap ${area.toFixed(4)}, ` +
              `normal (${t.n.toArray().map((v) => v.toFixed(2)).join(",")}) near (${c.toArray().map((v) => v.toFixed(2)).join(",")})`,
          );
        }
      }
    }
  }
  return ties;
}

/** The role glyph on the lid, placed relative to the chassis centre exactly as scene.ts places it. */
function roleGlyphOnLid(kind: string, glyph: RoleGlyph, half: readonly [number, number, number]): Tri[] {
  const spec = chassisSpec(kind);
  const m = new Matrix4().compose(
    new Vector3(-half[0] * 0.58, spec.height / 2 + 0.05, half[2] * 0.3),
    new Quaternion().setFromAxisAngle(new Vector3(1, 0, 0), -Math.PI / 2),
    new Vector3(2.1, 2.1, 2.1),
  );
  const g = buildRoleGlyph(glyph);
  try {
    return trianglesOf(g, `role:${glyph}`, m);
  } finally {
    g.dispose();
  }
}

const TIERS: readonly QualityTier[] = ["high", "balanced", "low"];
/* Every glyph the owner can ask for (chassis.ts ROLE_GLYPHS, typed against core/roles.ts), not a hand-kept list:
   the "other" glyph (added phase 3) is checked on every lid the day it exists. */
const GLYPHS: readonly RoleGlyph[] = ROLE_GLYPHS;

describe("the detector is live", () => {
  it("flags two boxes whose faces share a plane, and not two boxes a millimetre-scale step apart", async () => {
    const { BoxGeometry } = await import("three");
    const a = new BoxGeometry(2, 1, 2).toNonIndexed();
    const b = new BoxGeometry(1, 1, 1).toNonIndexed().translate(0, 0, 0); // same top plane y = 0.5
    const tied = depthTies([...trianglesOf(a, "a"), ...trianglesOf(b, "b")]);
    expect(tied.some((s) => s.includes("normal (0.00,1.00,0.00)")), tied.join("\n")).toBe(true);
    const c = new BoxGeometry(1, 1.02, 1).toNonIndexed(); // top 0.01 proud: resolved by depth
    expect(depthTies([...trianglesOf(a, "a"), ...trianglesOf(c, "c")]).filter((s) => s.includes("(0.00,1.00,0.00)"))).toEqual([]);
    for (const g of [a, b, c]) g.dispose();
  });
});

describe("C5: no opaque face of a chassis ties in depth with another", () => {
  for (const tier of TIERS) {
    const profile = profileFor(tier);
    for (const kind of ALL_CHASSIS_KINDS) {
      it(`${kind} at ${tier}: every part and every role glyph on its lid`, () => {
        const parts = buildChassis(kind, { bevelSegments: profile.chassisBevelSegments, fineDetail: profile.chassisFineDetail });
        try {
          const tris = [
            ...trianglesOf(parts.body, "body"),
            ...trianglesOf(parts.bezel, "bezel"),
            ...trianglesOf(parts.dark, "dark"),
            ...trianglesOf(parts.rail, "rail"),
            ...trianglesOf(parts.led, "led"),
          ];
          expect(tris.length).toBeGreaterThan(20);
          const ties = depthTies(tris);
          expect(ties, `${ties.length} depth ties:\n${ties.slice(0, 12).join("\n")}`).toEqual([]);
          for (const glyph of GLYPHS) {
            const withGlyph = depthTies([...tris, ...roleGlyphOnLid(kind, glyph, parts.half)]).filter((s) => s.includes("role:"));
            expect(withGlyph, `${glyph} glyph:\n${withGlyph.slice(0, 8).join("\n")}`).toEqual([]);
          }
        } finally {
          parts.dispose();
        }
      });
    }
  }
});

describe("C5: the other opaque per-device meshes carry no depth tie of their own", () => {
  /* The state ring is opaque and depth-writing (materials.stateRim) and is the one per-device mesh
     outside the chassis parts built from several overlapping primitives (bands, curbs, stripes). */
  const SHAPES: readonly StateRingShape[] = ["solid", "dashed", "double"];
  for (const shape of SHAPES) {
    it(`state ring "${shape}"`, () => {
      const g = buildStateRing(shape);
      try {
        // The instance matrix scales X/Z by the footprint (scene.ts); a switch's is the widest.
        const m = new Matrix4().makeScale(7.6 * 1.42, 1, 4.9 * 1.62);
        const ties = depthTies(trianglesOf(g, `ring:${shape}`, m));
        expect(ties, ties.slice(0, 8).join("\n")).toEqual([]);
      } finally {
        g.dispose();
      }
    });
  }
});

/* ── C5 motion: no sub-pixel strip of bare metal at the front edge, seen from above ─────────────
 *
 * The flip-flop clusters the C5 motion harness reported on chassis edges were MEASURED to be the top
 * face of the faceplate frame's top bar: a 0.34-deep strip of bright metal standing proud of the
 * body's front edge, under a pixel wide from the orbit's elevations, crawling as the damped orbit
 * crept (per-cluster raycast + in-page isolation: removing that bar removed the clusters; changing
 * the bezel's roughness, normal map or anisotropy did not). The painted cover now runs over it (the
 * HOOD in buildRackMount). Pinned here as geometry: straight down onto every upward-facing bezel or
 * rail face that lies FORWARD of the lid's flat top, the first thing hit is paint. */
describe("C5 motion: from above, the front edge of a rack chassis is paint, not a strip of metal", () => {
  for (const tier of TIERS) {
    const profile = profileFor(tier);
    for (const kind of ["device", "router"] as const) {
      it(`${kind} at ${tier}`, async () => {
        const { Mesh, MeshBasicMaterial, Raycaster, DoubleSide } = await import("three");
        const parts = buildChassis(kind, { bevelSegments: profile.chassisBevelSegments, fineDetail: profile.chassisFineDetail });
        const spec = chassisSpec(kind);
        try {
          const mat = new MeshBasicMaterial({ side: DoubleSide });
          const meshes = { body: new Mesh(parts.body, mat), bezel: new Mesh(parts.bezel, mat), rail: new Mesh(parts.rail, mat) };
          const rc = new Raycaster();
          const lidFront = spec.depth / 2 - spec.bevel;
          const exposed: string[] = [];
          let checked = 0;
          /* The faceplate (bezel) only. The rack ears (rail) stand OUTSIDE the body by design — they
             break the rectangle — and their top faces are seen from above; hiding them in the same
             isolation run left every flip-flop cluster in place, so they are not this defect. */
          for (const name of ["bezel"] as const) {
            for (const t of trianglesOf(meshes[name].geometry, name)) {
              if (t.n.y < 0.5) continue; // not upward-facing
              const c = new Vector3().add(t.p[0]).add(t.p[1]).add(t.p[2]).divideScalar(3);
              if (c.z <= lidFront) continue; // on or behind the lid's flat top: detail by design
              checked += 1;
              rc.set(new Vector3(c.x, 50, c.z), new Vector3(0, -1, 0));
              const hits = rc.intersectObjects([meshes.body, meshes.bezel, meshes.rail], false);
              const first = hits[0];
              if (first !== undefined && first.object !== meshes.body) {
                exposed.push(`${name} face at (${c.x.toFixed(2)}, ${c.y.toFixed(2)}, ${c.z.toFixed(2)}) is the first thing seen from above`);
              }
            }
          }
          expect(checked, "the check found the front-edge metal it is meant to judge").toBeGreaterThan(0);
          expect([...new Set(exposed)].slice(0, 6), `${exposed.length} exposed`).toEqual([]);
          mat.dispose();
        } finally {
          parts.dispose();
        }
      });
    }
  }
});
