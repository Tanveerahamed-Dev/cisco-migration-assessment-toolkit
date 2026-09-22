/**
 * chassis.test.ts — the curved kind, which is the only silhouette in this scene with no straight
 * edge to hide a facet behind.
 *
 * WHAT THESE TESTS PROVE
 *   - The access point's radial resolution responds to the quality tier at all. It did not: the
 *     builder took `bevelSegments` for the rack-mount kinds and ignored it for the AP, which was
 *     fixed at 48 segments — 7.5 degrees per facet, countable at 4x DPR.
 *   - At `high` the facet angle is under 4 degrees, and the extra triangles are a rounding error
 *     against the frame (two access points in this snapshot, geometry shared per kind).
 *
 * WHAT THEY DO NOT PROVE
 *   - How it looks. A 4x-DPR capture of the AP after the change shows a continuous rim; before it,
 *     the same crop showed straight chords.
 */
import { describe, expect, it } from "vitest";
import { buildChassis } from "./chassis";

/** LatheGeometry over an 8-point profile: (points - 1) * segments * 2 triangles, 3 vertices each. */
const PROFILE_POINTS = 8;
function radialSegmentsFrom(bodyVertexCount: number): number {
  return bodyVertexCount / ((PROFILE_POINTS - 1) * 2 * 3);
}

describe("the access point's curved body", () => {
  it("gets more radial segments at a higher tier", () => {
    const tiers = [1, 2, 3].map((bevelSegments) => {
      const parts = buildChassis("ap", { bevelSegments, fineDetail: bevelSegments > 1 });
      const count = parts.body.getAttribute("position").count;
      parts.dispose();
      return radialSegmentsFrom(count);
    });
    expect(tiers[0]).toBeLessThan(tiers[1] as number);
    expect(tiers[1]).toBeLessThan(tiers[2] as number);
  });

  it("puts the high tier's facet angle under 4 degrees", () => {
    const parts = buildChassis("ap", { bevelSegments: 3, fineDetail: true });
    try {
      const segments = radialSegmentsFrom(parts.body.getAttribute("position").count);
      expect(segments).toBeGreaterThanOrEqual(96);
      expect(360 / segments).toBeLessThan(4);
    } finally {
      parts.dispose();
    }
  });

  it("costs a few thousand triangles at most, against a frame that draws ~240,000", () => {
    const high = buildChassis("ap", { bevelSegments: 3, fineDetail: true });
    const low = buildChassis("ap", { bevelSegments: 1, fineDetail: false });
    try {
      const tris = (p: typeof high): number =>
        (p.body.getAttribute("position").count +
          p.bezel.getAttribute("position").count +
          p.dark.getAttribute("position").count) /
        3;
      expect(tris(high) - tris(low)).toBeLessThan(6000);
    } finally {
      high.dispose();
      low.dispose();
    }
  });

  it("leaves the rack-mount kinds' own bevel knob working", () => {
    const coarse = buildChassis("device", { bevelSegments: 1, fineDetail: false });
    const fine = buildChassis("device", { bevelSegments: 3, fineDetail: true });
    try {
      expect(fine.body.getAttribute("position").count).toBeGreaterThan(
        coarse.body.getAttribute("position").count,
      );
    } finally {
      coarse.dispose();
      fine.dispose();
    }
  });
});

describe("uncollected silhouette is tier-independent", () => {
  it("keeps every box edge for rack kinds, whatever bevel the tier would tessellate", async () => {
    const { chassisSilhouette } = await import("./chassis");
    for (const kind of ["router", "switch"]) {
      // 144 vertices = the reference body's full outline. The high tier's own body gave 72: the
      // twelve corner edges fell under the 24-degree threshold and the ghost read as opaque.
      expect(chassisSilhouette(kind).getAttribute("position").count).toBeGreaterThanOrEqual(144);
    }
  });
});
