#!/usr/bin/env node
/**
 * Remove only the prior generated outer receipt before Vinext replaces dist/.
 * The postbuild recreates and verifies it after every other deployable member
 * has reached its final bytes.
 */
import { lstat, unlink } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const MANIFEST_NAME = "deployment-manifest.json";

export async function prepareDeployment({ distDir = "dist" } = {}) {
  const manifestPath = join(resolve(distDir), MANIFEST_NAME);
  let info;
  try {
    info = await lstat(manifestPath);
  } catch (error) {
    if (error?.code === "ENOENT") return { path: manifestPath, removed: false };
    throw error;
  }
  if (!info.isFile() || info.isSymbolicLink()) {
    throw new Error(`prior deployment receipt is not a regular file: ${manifestPath}`);
  }
  await unlink(manifestPath);
  return { path: manifestPath, removed: true };
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  try {
    const result = await prepareDeployment();
    process.stdout.write(`${JSON.stringify(result)}\n`);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
