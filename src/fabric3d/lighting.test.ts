/**
 * lighting.test.ts — the shadow bias pair, which is the one lighting number a reader can be misled by.
 *
 * WHAT THESE TESTS PROVE
 *   - `bias` is the value design-brief.md publishes, read out of the brief rather than copied here.
 *   - `normalBias` is derived from the shadow map's TEXEL size instead of being a literal, and it
 *     tracks the map size: a tier that halves the map doubles the bias.
 *   - The derived value stays inside the band where a normal-offset bias is defensible. BOTH ends
 *     of that band are a measurement on this scene, not a rule of thumb, and both are failures that
 *     actually happened here:
 *
 *       below ~2 texels   the map contributes NOTHING BUT ACNE. At 1.5 texels, an A/B on a real
 *                         GPU (tier high, dark, one focused chassis) found shadows-on vs
 *                         shadows-off changed 1.32 % of the crop at mean delta 10.7, while raising
 *                         normalBias alone to 3.0 world units changed 1.29 % at mean 9.3 — i.e.
 *                         essentially the entire difference between "shadows on" and "shadows off"
 *                         was self-shadowing between the four interpenetrating meshes that make up
 *                         one chassis. A shadow map whose only visible output is an artefact is
 *                         worse than no shadow map.
 *       above ~5 texels   the shadow detaches from its caster — the peter-panning the brief pairs
 *                         the two values to avoid. Measured live at 1.075 world units (about 5.5
 *                         texels), the far projections read as hard dark rectangles sitting on
 *                         empty floor.
 *
 *     The band is therefore 2 to 5 texels and the shipped value is 4. The previous upper bound of
 *     3 was written when only the peter-panning end had been measured; it would have blocked the
 *     acne fix while the acne was the live defect.
 *
 * WHAT THEY DO NOT PROVE
 *   - Whether the result looks right, or that anything is GROUNDED. The cast shadow on this
 *     geometry is a thin crescent at the base by construction (a 52-degree key over a 3-unit-tall,
 *     16-unit-wide box), so grounding comes from the contact decals, not from here. See
 *     docs/render-decisions.md §5 and geometry/ground.test.ts.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createLighting } from "./lighting";
import { readTokens } from "./materials";
import { profileFor } from "./quality";

/** The real fabric's order of magnitude: ~360 across, ~60 tall. */
const BOUNDS = { min: [-180, -30, -180] as [number, number, number], max: [180, 30, 180] as [number, number, number] };

function texelWorld(mapSize: number): number {
  const size = Math.hypot(360, 60, 360);
  const radius = size / 2;
  const half = radius + radius * 0.06 + 8;
  return (2 * half) / mapSize;
}

describe("shadow bias", () => {
  it("uses the depth bias design-brief.md publishes", () => {
    const brief = readFileSync(resolve(__dirname, "../../docs/design-brief.md"), "utf8");
    const stated = brief.match(/key\.shadow\.bias\s*=\s*(-?[\d.]+);/);
    expect(stated, "design-brief.md no longer publishes key.shadow.bias").not.toBeNull();
    const rig = createLighting(readTokens("dark"), profileFor("high"));
    try {
      expect(rig.key.shadow.bias).toBe(Number(stated?.[1]));
    } finally {
      rig.dispose();
    }
  });

  it("derives normalBias from the shadow texel, and tracks the map size", () => {
    const rig = createLighting(readTokens("dark"), profileFor("high"));
    try {
      rig.fit(BOUNDS);
      const high = rig.key.shadow.normalBias;
      const highTexels = high / texelWorld(rig.key.shadow.mapSize.x);
      // Both bounds are measured failure modes on this scene — see the file header.
      expect(highTexels).toBeGreaterThan(2);
      expect(highTexels).toBeLessThan(5);

      // A smaller map means a bigger texel means a bigger offset, in the same proportion.
      const smallerMap = profileFor("balanced");
      expect(smallerMap.shadowMapSize).toBeLessThan(profileFor("high").shadowMapSize);
      rig.applyProfile(smallerMap);
      const balanced = rig.key.shadow.normalBias;
      expect(balanced / high).toBeCloseTo(
        profileFor("high").shadowMapSize / smallerMap.shadowMapSize,
        5,
      );
    } finally {
      rig.dispose();
    }
  });

  it("is not the brief's literal 0.022, and the deviation is a world-scale one", () => {
    // Recorded rather than silently deviated from: 0.022 is a WORLD distance written for a scene
    // about 140 units across. Here one 2048 texel is ~0.19 units, so 0.022 is about a ninth of a
    // texel — no acne protection at all. The brief's INTENT (a normal-offset paired with the depth
    // bias) is implemented; its literal is not transferable between scene scales.
    const rig = createLighting(readTokens("dark"), profileFor("high"));
    try {
      rig.fit(BOUNDS);
      expect(rig.key.shadow.normalBias).not.toBe(0.022);
      expect(rig.key.shadow.normalBias).toBeGreaterThan(0.022);
      expect(texelWorld(2048)).toBeGreaterThan(0.022 * 5);
    } finally {
      rig.dispose();
    }
  });
});
