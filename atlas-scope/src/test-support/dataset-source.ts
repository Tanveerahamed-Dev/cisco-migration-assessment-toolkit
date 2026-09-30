/* dataset-source.ts — where the snapshot the LOADED dataset was compiled from is, for tests that read it.
 *
 * The dataset under test is the file the compiled model names — found by the DIGEST the model binds, never by a
 * typed path (R7). The model names a repository file by its repository path, and a file outside the repository
 * (the rename leg's renamed snapshot, `sourceOrigin: "external-file"`) by its file name only; that one is looked
 * for where the phase legs write it (`.local-data/`, Git-ignored) or at ATLAS_DATASET_SOURCE. Every candidate must
 * carry the bound bytes (sourceExactSha256, or the LF-normalised sourceSha256 for a checkout that rewrote line
 * endings). None found THROWS: a join against the wrong bytes, or no join, is never a pass.
 *
 * The rule is src/core/compiler-fidelity.test.ts's `sourceSnapshotPath` (P3C-V2-3), shared here so a test that
 * reads the source of the dataset under test cannot resolve `meta.source` against the repository root alone —
 * the shape that failed the rename leg's whole EvidencePane.source.test.tsx at load time (phase 3.5 close).
 * Imported by tests only (it reads files with node:fs), never by the application.
 */
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

/** The binding keys the search reads. */
export interface BoundSource {
  source: string;
  sourceSha256: string;
  sourceExactSha256: string;
}

/** The path of the snapshot `meta` binds, or a thrown error naming every place that was searched. */
export function datasetSourcePath(meta: BoundSource): string {
  const sha = (b: Buffer): string => createHash("sha256").update(b).digest("hex");
  const exact = meta.sourceExactSha256.replace(/^sha256:/, "");
  const carries = (p: string): boolean => {
    if (!existsSync(p) || !statSync(p).isFile()) return false;
    const b = readFileSync(p);
    return sha(b) === exact || sha(Buffer.from(b.toString("latin1").split("\r\n").join("\n"), "latin1")) === meta.sourceSha256;
  };
  const named = basename(meta.source);
  const underLocal = (dir: string, depth: number): string[] => {
    if (depth < 0 || !existsSync(dir)) return [];
    return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory() ? underLocal(join(dir, e.name), depth - 1) : e.name === named ? [join(dir, e.name)] : [],
    );
  };
  const candidates = [
    resolve(PKG, "..", meta.source),
    resolve(PKG, meta.source),
    ...(process.env.ATLAS_DATASET_SOURCE ? [resolve(process.env.ATLAS_DATASET_SOURCE)] : []),
    ...underLocal(resolve(PKG, ".local-data"), 3),
  ];
  const hit = candidates.find(carries);
  if (hit === undefined) {
    throw new Error(
      `the snapshot the loaded model was compiled from (${meta.source}, sha256 ${meta.sourceSha256}) was not found ` +
        `at ${candidates.join(", ")}; set ATLAS_DATASET_SOURCE to it.`,
    );
  }
  return hit;
}
