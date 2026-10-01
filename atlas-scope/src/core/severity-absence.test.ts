/**
 * severity-absence.test.ts — a missing severity is never graded "Info".
 *
 * HISTORY. The compiler mapped a punchlist or cross_layer entry with no severity to "Info"
 * (`severity: val(p.severity) ?? "Info"`): the moment a producer emitted an ungraded entry it would render as a
 * GRADED Info finding — absence laundered into a low-risk grade (2026-09-21 auditor, B1). The compiler and the
 * `Finding.severity` type were frozen for that repair pass, so this file was only a RATCHET keeping the default
 * unreachable on the shipped snapshot, and it named the fix: emit `null` and render "not graded". That fix is now
 * made (2026-10-01): tools/lib/compile-model.mjs emits null for an absent severity, `Finding.severity` and
 * `CrossLayerFinding.severity` carry `| null`, and every surface renders it "severity not stated" (core/types.ts
 * SEVERITY_NOT_STATED) — grouped under Not observed, counted in a tally slot of its own, sorted after every graded
 * record. closed-vocabulary-accounting.test.tsx exercises that on a sample whose records state none.
 *
 * WHAT THIS FILE STILL PINS, joined against the REAL source bytes the loaded model was compiled from: every compiled
 * severity is the severity the source STATED (as the compiler reads it), or null where the source stated none —
 * never a value the source did not write. The ratchet is kept, not deleted: it is the one such check that runs
 * against whatever dataset the phase legs load, not against a fixture.
 */
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
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

/* The dataset UNDER TEST is the file the compiled model names — found by the DIGEST the model binds, never by a
   typed path (R7). The model names a repository file by its repository path, and a file outside the repository
   (the rename leg's renamed snapshot, `sourceOrigin: "external-file"`) by its file name only; that one is looked
   for where the phase legs write it (`.local-data/`, Git-ignored) or at ATLAS_DATASET_SOURCE. Every candidate must
   carry the bound bytes (sourceExactSha256, or the LF-normalised sourceSha256 for a checkout that rewrote line
   endings). None found fails the file loudly: a join against the wrong bytes, or no join, is never a pass
   (P3C-V2-3: the rename leg failed here on the file-name-only path). */
function sourceSnapshotPath(): string {
  const sha = (b: Buffer): string => createHash("sha256").update(b).digest("hex");
  const exact = fabric.meta.sourceExactSha256.replace(/^sha256:/, "");
  const carries = (p: string): boolean => {
    /* One read, no exists/stat check first (CodeQL js/file-system-race): nothing there, or a directory, carries nothing. */
    let b: Buffer;
    try {
      b = readFileSync(p);
    } catch (e) {
      if (["ENOENT", "ENOTDIR", "EISDIR"].includes((e as NodeJS.ErrnoException).code ?? "")) return false;
      throw e;
    }
    return sha(b) === exact || sha(Buffer.from(b.toString("utf8").replace(/\r\n/g, "\n"), "utf8")) === fabric.meta.sourceSha256;
  };
  const named = basename(fabric.meta.source);
  const underLocal = (dir: string, depth: number): string[] => {
    if (depth < 0 || !existsSync(dir)) return [];
    return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory() ? underLocal(join(dir, e.name), depth - 1) : e.name === named ? [join(dir, e.name)] : [],
    );
  };
  const candidates = [
    resolve(PKG, "..", fabric.meta.source),
    resolve(PKG, fabric.meta.source),
    ...(process.env.ATLAS_DATASET_SOURCE ? [resolve(process.env.ATLAS_DATASET_SOURCE)] : []),
    ...underLocal(resolve(PKG, ".local-data"), 3),
  ];
  const hit = candidates.find(carries);
  if (hit === undefined) {
    throw new Error(
      `the snapshot the loaded model was compiled from (${fabric.meta.source}, sha256 ${fabric.meta.sourceSha256}) was not found ` +
        `at ${candidates.join(", ")}; set ATLAS_DATASET_SOURCE to it.`,
    );
  }
  return hit;
}
const SNAPSHOT = sourceSnapshotPath();
const source = JSON.parse(readFileSync(SNAPSHOT, "utf8")) as SourceSnapshot;

/** The severity the compiler reads a source value as (tools/lib/compile-model.mjs `val` + `term`): trimmed text, or
 *  null for an absent, empty, "-", "N/A" or [NOT OBSERVED] value; a number or boolean as its text. */
const asCompiled = (v: unknown): string | null => {
  if (v === undefined || v === null) return null;
  if (typeof v === "number" && !Number.isFinite(v)) return null;
  const t = String(v).trim();
  return t === "" || t === "-" || t === "N/A" || /^\[NOT OBSERVED\]/i.test(t) ? null : t;
};

describe("no compiled severity is a default standing in for an absent grade", () => {
  it("has both sides to compare — an empty join is not a pass", () => {
    expect(source.punchlist?.length ?? 0).toBe(fabric.findings.length);
    expect(source.cross_layer?.length ?? 0).toBe(fabric.crossLayer.length);
    expect(fabric.findings.length).toBeGreaterThan(0);
  });

  it("every punchlist severity the model carries is the one the source stated, or null where it stated none", () => {
    const offenders = (source.punchlist ?? []).flatMap((p, i) =>
      asCompiled(p.severity) === fabric.findings[i]?.severity
        ? []
        : [`punchlist[${i}] severity=${JSON.stringify(p.severity)} compiled to ${JSON.stringify(fabric.findings[i]?.severity)}`],
    );
    expect(offenders, "a compiled severity the source did not state (an ungraded finding rendered as graded)").toEqual([]);
  });

  it("every cross_layer severity the model carries is the one the source stated, or null where it stated none", () => {
    const offenders = (source.cross_layer ?? []).flatMap((c, i) =>
      asCompiled(c.severity) === fabric.crossLayer[i]?.severity
        ? []
        : [`cross_layer[${i}] severity=${JSON.stringify(c.severity)} compiled to ${JSON.stringify(fabric.crossLayer[i]?.severity)}`],
    );
    expect(offenders, "a compiled cross-layer severity the source did not state").toEqual([]);
  });
});
