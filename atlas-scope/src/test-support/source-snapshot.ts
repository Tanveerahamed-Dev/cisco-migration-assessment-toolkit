/**
 * source-snapshot.ts — the SOURCE snapshot a compiled dataset was read from, for the tests that check a
 * compiled record against the bytes it came from.
 *
 * TEST SUPPORT ONLY (imported by `*.test.ts(x)` files in this directory, never by the product).
 *
 * Why it exists (phase 3 rename leg, 2026-09-28). DevicePane.cite.test.tsx and producer-emission.test.ts
 * read `meta.source` as a repository-relative path and opened it while the file was being collected. A
 * dataset compiled from a file OUTSIDE the tree (`sourceOrigin: "external-file"` — the rename leg's renamed
 * snapshot) names only that file's basename, so both files crashed at collection ("ENOENT … sample_fleet.
 * renamed.snapshot.json") and every test in them was lost, not just the source-reading ones.
 *
 * FOUND BY ITS DIGEST, NOT SKIPPED (phase 3.5 close, 2026-09-30). The first repair opened the source only for a
 * repository file and skipped the source-reading blocks BY NAME otherwise — so on the rename leg 30 INVARIANT tests
 * (B6's identity/health citations, the emission sidecar's binding) were named skips on the one leg that exists to
 * run them on other names. The source is now located the way src/core/compiler-fidelity.test.ts locates it
 * (src/test-support/dataset-source.ts): by the digest the compiled model binds, at its repository path, under the
 * legs' `.local-data/`, or at ATLAS_DATASET_SOURCE. Not found is a FAILURE, on every dataset — never a skip.
 */
import { readFileSync } from "node:fs";
import { describe } from "vitest";
import { fabric } from "../core/data";
import { datasetSourcePath } from "./dataset-source";

let path: string | null = null;
/** The source snapshot's absolute path (found once, by digest); throws when no file carries the bound bytes. */
export function sourcePath(): string {
  path ??= datasetSourcePath(fabric.meta);
  return path;
}

let bytes: Buffer | null = null;
/** The source snapshot's bytes (read once). */
export function sourceBytes(): Buffer {
  bytes ??= readFileSync(sourcePath());
  return bytes;
}

let parsed: unknown = undefined;
/** The source snapshot, parsed (read once). */
export function sourceDocument(): unknown {
  parsed ??= JSON.parse(sourceBytes().toString("utf8"));
  return parsed;
}

/** A describe block that needs the source snapshot's bytes. It always runs: a source it cannot find fails it. */
export function describeWithSource(name: string, fn: () => void): void {
  describe(name, fn);
}
