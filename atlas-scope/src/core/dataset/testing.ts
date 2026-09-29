/**
 * dataset/testing.ts — test support for the dataset door: compile a snapshot file other than the tracked
 * sample with the ONE compiler, the way the runtime paths do. Imported by tests only (it reads files
 * with node:fs), never by the application.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compileAll } from "../../../tools/lib/compile-model.mjs";
import { assertValidSnapshot } from "../../../tools/lib/validate-snapshot.mjs";
import { bindSource } from "../../../tools/source-binding.mjs";
import type { CompiledDataset, InstalledDataset } from "./types";

/** The atlas-scope package root. */
export const PKG = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
/** The engine's golden snapshot (a real 7-device fleet that is NOT the tracked sample), in the parent repository. */
export const GOLDEN_SNAPSHOT = resolve(PKG, "..", "tests", "golden", "snapshot.json");
/** The tracked engine sample the bundled dataset is compiled from. */
export const SAMPLE_SNAPSHOT = resolve(PKG, "..", "webapp", "sample_data", "sample_fleet.snapshot.json");

/** Compile `bytes` as an external file named `name` (the label a file opened in the browser gets). */
export function compileBytes(bytes: Uint8Array, name: string): CompiledDataset {
  const { snap, schemaAssumed } = assertValidSnapshot(bytes);
  return compileAll(snap, bindSource(bytes, { source: name, sourceOrigin: "external-file" }), { schemaAssumed });
}

/** The golden snapshot, compiled. */
export function compileGolden(): CompiledDataset {
  return compileBytes(new Uint8Array(readFileSync(GOLDEN_SNAPSHOT)), "snapshot.json");
}

/** An installed-dataset record for `set`, as if the reader had opened it. */
export function asOpenedFile(set: CompiledDataset, fileName = "snapshot.json"): InstalledDataset {
  return { set, origin: { kind: "opened-file", fileName, fileBytes: set.fabric.meta.sourceBytes, warnings: [] } };
}
