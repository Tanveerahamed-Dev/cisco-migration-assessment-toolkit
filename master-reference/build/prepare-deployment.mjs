#!/usr/bin/env node
/**
 * Remove only the prior generated outer receipt before Vinext replaces dist/.
 * The postbuild recreates and verifies it after every other deployable member
 * has reached its final bytes.
 */
import { lstat, unlink } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const MANIFEST_NAMES = Object.freeze([
  "deployment-manifest.json",
  "deployment-manifest.json.gz",
]);

async function prepareDeploymentInternal({ distDir = "dist" } = {}) {
  const root = resolve(distDir);
  const receipts = [];
  for (const name of MANIFEST_NAMES) {
    const manifestPath = join(root, name);
    let info;
    try {
      info = await lstat(manifestPath);
    } catch (error) {
      if (error?.code === "ENOENT") continue;
      throw error;
    }
    if (!info.isFile() || info.isSymbolicLink()) {
      throw new Error(`prior deployment receipt is not a regular file: ${manifestPath}`);
    }
    receipts.push(manifestPath);
  }
  for (const manifestPath of receipts) {
    await unlink(manifestPath);
  }
  return { path: join(root, MANIFEST_NAMES[1]), removed: receipts.length > 0 };
}

function snapshotPublicOptions(options) {
  if (
    options === undefined ||
    options === null ||
    typeof options !== "object" ||
    Object.getPrototypeOf(options) !== Object.prototype
  ) {
    throw new Error("invalid options");
  }
  const keys = Reflect.ownKeys(options);
  if (keys.some((key) => key !== "distDir")) throw new Error("invalid options");
  const descriptors = Object.getOwnPropertyDescriptors(options);
  if (
    Object.values(descriptors).some(
      (descriptor) => !("value" in descriptor) || descriptor.enumerable !== true,
    )
  ) {
    throw new Error("invalid options");
  }
  const distDir = descriptors.distDir?.value;
  if (distDir !== undefined && typeof distDir !== "string") throw new Error("invalid options");
  return distDir === undefined ? {} : { distDir };
}

export async function prepareDeployment(options = {}) {
  try {
    return await prepareDeploymentInternal(snapshotPublicOptions(options));
  } catch {
    throw new Error("deployment preparation failed");
  }
}

export const prepareDeploymentTestOnly = Object.freeze({
  prepareDeploymentInternal,
});

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
