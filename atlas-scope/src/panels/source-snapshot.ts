/**
 * source-snapshot.ts — the SOURCE snapshot a compiled dataset was read from, for the tests that check a
 * compiled record against the bytes it came from.
 *
 * TEST SUPPORT ONLY (imported by `*.test.ts(x)` files in this directory, never by the product).
 *
 * Why it exists (phase 3 rename leg, 2026-09-28). DevicePane.cite.test.tsx and producer-emission.test.ts
 * read `meta.source` as a repository-relative path and opened it while the file was being collected. A
 * dataset compiled from a file OUTSIDE the tree (`sourceOrigin: "external-file"` — the rename and golden
 * legs) names only that file's basename, so both files crashed at collection ("ENOENT … sample_fleet.
 * renamed.snapshot.json") and every test in them was lost, not just the source-reading ones. The source
 * is now opened only when the dataset says it is a repository file; otherwise the blocks that need it are
 * skipped BY NAME. On the reference sample the source is always a repository file, and anything else is a
 * failure, never a skip.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe } from "vitest";
import { fabric } from "../core/data";
import { isGoldenSample } from "../test-support/golden-sample";

/** The package's parent — the repository root `meta.source` is relative to for a repository file. */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

/** The source snapshot's absolute path, or null when the dataset was compiled from a file outside the tree. */
export function repositorySourcePath(): string | null {
  if (fabric.meta.sourceOrigin !== "repository-file") {
    if (isGoldenSample()) throw new Error(`source-snapshot: the reference sample must be a repository file, not ${fabric.meta.sourceOrigin}`);
    return null;
  }
  return resolve(REPO_ROOT, fabric.meta.source);
}

let bytes: Buffer | null = null;
/** The source snapshot's bytes (read once). Only call inside a block `describeWithSource` runs. */
export function sourceBytes(): Buffer {
  const p = repositorySourcePath();
  if (p === null) throw new Error("source-snapshot: this dataset's source is not in the repository");
  bytes ??= readFileSync(p);
  return bytes;
}

let parsed: unknown = undefined;
/** The source snapshot, parsed (read once). Only call inside a block `describeWithSource` runs. */
export function sourceDocument(): unknown {
  parsed ??= JSON.parse(sourceBytes().toString("utf8"));
  return parsed;
}

/** A describe block that needs the source snapshot's bytes; skipped BY NAME when they are not in the tree. */
export function describeWithSource(name: string, fn: () => void): void {
  if (repositorySourcePath() !== null) describe(name, fn);
  else describe.skip(`[source snapshot not in the repository: ${fabric.meta.source}] ${name}`, fn);
}
