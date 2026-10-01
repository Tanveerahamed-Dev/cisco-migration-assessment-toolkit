/**
 * chassis.prepared.test.ts — the cold-load pre-build (E5) changes WHEN chassis geometry is built,
 * never WHAT is built, and never lets two callers share a buffer.
 *
 * WHAT THESE TESTS PROVE
 *   - Parts handed out after `prepareChassis` are vertex-for-vertex the parts built in place.
 *   - Every call returns its OWN geometry: disposing or mutating one caller's parts cannot reach
 *     another's (a rebuilt graph must never draw a disposed graph's buffers).
 *   - Readiness is per (kind, tessellation): preparing one tessellation does not claim another.
 *
 * WHAT THEY DO NOT PROVE
 *   - The cold-load timing itself; that is review/audit-e5-coldload.mjs against a real browser.
 */
import { describe, expect, it } from "vitest";
import type { BufferGeometry } from "three";
import { ALL_CHASSIS_KINDS, buildChassis, chassisPrepared, prepareChassis } from "./chassis";

const OPTS = { bevelSegments: 3, fineDetail: true };
/** An empty part (an access point has no rack ears) carries no position attribute at all. */
const positions = (g: BufferGeometry): number[] => {
  const attr = g.getAttribute("position");
  return attr === undefined ? [] : Array.from(attr.array as ArrayLike<number>);
};

describe("prepareChassis — the same geometry, built earlier", () => {
  it("hands out parts identical to an in-place build, for every kind", async () => {
    const fresh = ALL_CHASSIS_KINDS.map((k) => buildChassis(k, OPTS));
    expect(chassisPrepared(ALL_CHASSIS_KINDS, OPTS)).toBe(false);
    await prepareChassis(ALL_CHASSIS_KINDS, OPTS);
    expect(chassisPrepared(ALL_CHASSIS_KINDS, OPTS)).toBe(true);
    ALL_CHASSIS_KINDS.forEach((k, i) => {
      const a = fresh[i]!;
      const b = buildChassis(k, OPTS);
      for (const part of ["body", "bezel", "dark", "rail", "led"] as const) {
        expect(positions(b[part])).toEqual(positions(a[part]));
        expect(b[part].index?.count ?? 0).toBe(a[part].index?.count ?? 0);
      }
      expect(b.half).toEqual(a.half);
      expect(b.topY).toBe(a.topY);
      a.dispose();
      b.dispose();
    });
  });

  it("gives every caller its own buffers", async () => {
    await prepareChassis(["router"], OPTS);
    const a = buildChassis("router", OPTS);
    const b = buildChassis("router", OPTS);
    expect(a.body).not.toBe(b.body);
    expect(a.body.getAttribute("position").array).not.toBe(b.body.getAttribute("position").array);
    const before = positions(b.body)[0];
    (a.body.getAttribute("position").array as Float32Array)[0] = 12345;
    a.dispose();
    expect(positions(b.body)[0]).toBe(before);
    expect(positions(buildChassis("router", OPTS).body)[0]).toBe(before);
    a.half[0] = -1;
    expect(b.half[0]).not.toBe(-1);
  });

  it("does not claim a tessellation it did not prepare", async () => {
    await prepareChassis(ALL_CHASSIS_KINDS, OPTS);
    expect(chassisPrepared(ALL_CHASSIS_KINDS, { bevelSegments: 1, fineDetail: false })).toBe(false);
  });
});
