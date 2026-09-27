/**
 * severity-absence.test.ts — a missing severity must never be graded "Info".
 *
 * `tools/compile-snapshot.mjs` maps a punchlist or cross_layer entry with no severity to "Info"
 * (`severity: val(p.severity) ?? "Info"`). The shipped snapshot never reaches that default — every
 * entry carries a severity — so no screen shows it today. But the moment a producer emits an
 * ungraded entry it would render as a GRADED Info finding: absence laundered into a low-risk grade.
 *
 * The compiler and the `Finding.severity: Severity` type are frozen for this repair pass (another
 * cluster owns them), so the default cannot be removed here. This is the ratchet that keeps it
 * unreachable: joined against the REAL source bytes, it fails the first time any compiled severity
 * was not stated by the source. The fix, when it fires, is to emit `null` and render "not graded".
 * Found by the 2026-09-21 auditor (B1).
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { fabric } from "./data";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

interface Graded {
  severity?: unknown;
}
interface SourceSnapshot {
  punchlist?: Graded[];
  cross_layer?: Graded[];
}

/* The dataset under test: the file the compiled model names (`meta.source`), not a typed path (R7). */
const SNAPSHOT = resolve(PKG, "..", fabric.meta.source);
const source = JSON.parse(readFileSync(SNAPSHOT, "utf8")) as SourceSnapshot;

const stated = (v: unknown): boolean => typeof v === "string" && v.trim() !== "" && !/^\s*(N\/A|unknown|\[NOT OBSERVED\]|-)\s*$/i.test(v);

describe("no compiled severity is a default standing in for an absent grade", () => {
  it("has both sides to compare — an empty join is not a pass", () => {
    expect(source.punchlist?.length ?? 0).toBe(fabric.findings.length);
    expect(source.cross_layer?.length ?? 0).toBe(fabric.crossLayer.length);
    expect(fabric.findings.length).toBeGreaterThan(0);
  });

  it("every punchlist severity the model carries was stated by the source", () => {
    const offenders = (source.punchlist ?? []).flatMap((p, i) =>
      stated(p.severity) ? [] : [`punchlist[${i}] severity=${JSON.stringify(p.severity)} compiled to ${JSON.stringify(fabric.findings[i]?.severity)}`],
    );
    expect(offenders, "an ungraded finding would render as a graded Info finding").toEqual([]);
  });

  it("every cross_layer severity the model carries was stated by the source", () => {
    const offenders = (source.cross_layer ?? []).flatMap((c, i) =>
      stated(c.severity) ? [] : [`cross_layer[${i}] severity=${JSON.stringify(c.severity)} compiled to ${JSON.stringify(fabric.crossLayer[i]?.severity)}`],
    );
    expect(offenders, "an ungraded cross-layer finding would render as a graded Info finding").toEqual([]);
  });
});
