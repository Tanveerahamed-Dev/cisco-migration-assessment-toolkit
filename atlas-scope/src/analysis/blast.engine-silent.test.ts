/**
 * A half-null engine failure_impact record is engine-silence, never "no impact".
 *
 * `compareEngineImpact` used to read `(record.stranded ?? 0) > 0 || (record.hard ?? 0) > 0`, so a
 * record with `stranded: 0, hard: null` compared as "the engine says nothing breaks" — a null count
 * coerced to a measured zero. The shipped snapshot has no such record (all 23 carry both counts),
 * so this is pinned against a constructed one. Found by the 2026-09-21 auditor (B1).
 */
import { describe, expect, it } from "vitest";
import { compareEngineImpact } from "./blast";
import { fabric } from "../core/data";
import type { Device, FailureImpact } from "../core/types";

const withImpact = (stranded: number | null, hard: number | null): Device => {
  const base = fabric.devices.find((d) => d.impact !== null) ?? fabric.devices[0]!;
  const impact: FailureImpact = { severity: null, vlans: null, stranded, hard, backup: null, fhrp: null, detail: null, cite: "failure_impact[0]" };
  return { ...base, impact };
};

describe("compareEngineImpact never reads a null count as zero", () => {
  it.each([
    [0, null],
    [null, 0],
  ] as const)("stranded=%s hard=%s is engine-silent, not both-none", (stranded, hard) => {
    expect(compareEngineImpact(withImpact(stranded, hard), []).qualitative).toBe("engine-silent");
  });

  it("a single positive count is still an observed impact", () => {
    expect(compareEngineImpact(withImpact(3, null), []).qualitative).toBe("engine-impact-only");
  });

  it("both counts present and zero is the engine's own 'none'", () => {
    expect(compareEngineImpact(withImpact(0, 0), []).qualitative).toBe("both-none");
  });
});
