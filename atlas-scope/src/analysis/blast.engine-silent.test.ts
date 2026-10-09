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

const withImpact = (stranded: number | null, hard: number | null, patch: Partial<FailureImpact> = {}): Device => {
  const base = fabric.devices.find((d) => d.impact !== null) ?? fabric.devices[0]!;
  const impact: FailureImpact = {
    severity: null, vlans: null, stranded, hard, backup: null, fhrp: null, detail: null,
    cite: "device_dossiers.per_device[0].impact_assessability",
    assessable: "published", why: "Owner admits this synthetic row.", unavailable: null,
    row: null,
    ...patch,
  };
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

  it("a zero lower bound never compares as a measured no-impact result", () => {
    const r = compareEngineImpact(withImpact(0, 0, { assessable: "lower_bound", why: "Only a floor is assessed." }), []);
    expect(r.qualitative).toBe("engine-silent");
    expect(r.note).toContain("zero floor cannot establish no impact");
    expect(r.note).toContain("Only a floor is assessed.");
  });

  it("a positive bound participates as qualified positive evidence, not an exact total", () => {
    const r = compareEngineImpact(withImpact(45, null, { assessable: "lower_bound", why: "One blind link is outside the count." }), []);
    expect(r.qualitative).toBe("engine-impact-only");
    expect(r.note).toContain("lower bounds, not exact totals");
    expect(r.note).toContain("One blind link is outside the count.");
  });

  it.each(["not_assessed", "ambiguous", null] as const)("%s holds even raw zero counts instead of declaring none", (assessable) => {
    const r = compareEngineImpact(withImpact(0, 0, { assessable, why: "The engine withholds this row." }), ["other-host"]);
    expect(r.qualitative).toBe("engine-silent");
    expect(r.note).toContain("The engine withholds this row.");
    expect(r.note).toContain("A held row is not a finding of no impact");
  });

  it("unreadable owner evidence holds a positive raw count too", () => {
    const r = compareEngineImpact(withImpact(45, 1, { assessable: null, unavailable: "Owner verdict is unreadable." }), []);
    expect(r.qualitative).toBe("engine-silent");
    expect(r.note).toContain("Owner verdict is unreadable.");
  });

  it("an unavailable result cannot bypass its hold through a published state", () => {
    expect(compareEngineImpact(withImpact(0, 0, { unavailable: "The owner row does not resolve." }), []).qualitative).toBe("engine-silent");
  });
});
