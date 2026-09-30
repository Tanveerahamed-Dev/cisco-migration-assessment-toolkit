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
