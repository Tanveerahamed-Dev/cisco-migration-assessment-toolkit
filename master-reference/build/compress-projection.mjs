#!/usr/bin/env node
/**
 * Losslessly replace the generated Atlas projection modules with deterministic
 * gzip members for Sites packaging. The worker maps virtual `.mjs` requests to
 * these `.mjs.gz` assets; this build step never changes the projection manifest.
 */
import { createHash } from "node:crypto";
import {
  lstat,
  mkdir,
  readFile,
  readdir,
  rename,
  rm,
  unlink,
  writeFile,
} from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";
import { promisify } from "node:util";
import { constants, crc32, deflateRaw, gunzip } from "node:zlib";
import { pathToFileURL } from "node:url";

import { CANONICAL_GZIP_HEADER_BYTES } from "./gzip-contract.js";

const RECEIPT_NAME = "compression-manifest.json";
const PROJECTION_MANIFEST_NAME = "projection-manifest.json";
const CONCURRENCY = 4;
const deflateRawAsync = promisify(deflateRaw);
const gunzipAsync = promisify(gunzip);

const sha256 = (value) => createHash("sha256").update(value).digest("hex");

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function safeModulePath(value, location) {
  if (
    typeof value !== "string" ||
    !value.endsWith(".mjs") ||
    value.includes("\\") ||
    value.startsWith("/") ||
    /^[A-Za-z]:/.test(value)
  ) {
    throw new Error(`unsafe projection module declaration at ${location}: ${String(value)}`);
  }
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error(`unsafe projection module declaration at ${location}: ${value}`);
  }
  return value;
}

function collectDeclaredModules(manifest) {
  const modules = new Map();
  let declarationCount = 0;
  function visit(value, location = "$") {
    if (Array.isArray(value)) {
      value.forEach((entry, index) => visit(entry, `${location}[${index}]`));
      return;
    }
    if (!value || typeof value !== "object") return;
    const entries = Object.entries(value);
    // A projection descriptor's `module` is authoritative. Its sibling `path`
    // can be the authored source path and can itself end in .mjs; that is not a
    // generated projection module. Descriptors without `module` (identity and
    // root index) declare their module through `path`.
    const moduleEntry = entries.find(
      ([key, child]) => key === "module" && typeof child === "string" && child.endsWith(".mjs"),
    );
    const candidates = moduleEntry
      ? [moduleEntry]
      : entries.filter(([, child]) => typeof child === "string" && child.endsWith(".mjs"));
    for (const [key, child] of candidates) {
      const childLocation = `${location}.${key}`;
      const path = safeModulePath(child, childLocation);
      if (
        !Number.isSafeInteger(value.bytes) ||
        value.bytes < 0 ||
        !/^[0-9a-f]{64}$/.test(String(value.sha256 ?? ""))
      ) {
        throw new Error(`projection module declaration lacks a byte/hash receipt at ${childLocation}`);
      }
      const descriptor = { path, bytes: value.bytes, sha256: value.sha256 };
      const prior = modules.get(path);
      if (prior && (prior.bytes !== descriptor.bytes || prior.sha256 !== descriptor.sha256)) {
        throw new Error(`conflicting projection module declarations: ${path}`);
      }
      modules.set(path, descriptor);
      declarationCount += 1;
    }
    for (const [key, child] of entries) {
      const childLocation = `${location}.${key}`;
      visit(child, childLocation);
    }
  }
  visit(manifest);
  if (modules.size === 0) throw new Error("projection manifest declares no .mjs modules");
  return { modules, declarationCount };
}

async function walkFiles(root) {
  const files = [];
  async function walk(directory) {
    const entries = await readdir(directory, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const path = join(directory, entry.name);
      if (entry.isSymbolicLink()) throw new Error(`symlink refused in projection: ${path}`);
      if (entry.isDirectory()) await walk(path);
      else if (entry.isFile()) files.push(path);
      else throw new Error(`non-regular projection entry refused: ${path}`);
    }
  }
  await walk(root);
  return files;
}

function relativePosix(root, path) {
  return relative(root, path).split(sep).join("/");
}

function describeDifference(expected, actual) {
  const missing = [...expected].filter((path) => !actual.has(path)).sort();
  const undeclared = [...actual].filter((path) => !expected.has(path)).sort();
  if (!missing.length && !undeclared.length) return null;
  const sample = (values) => values.slice(0, 5).join(", ") || "none";
  return `projection module census mismatch; missing=${sample(missing)}; undeclared=${sample(undeclared)}`;
}

async function mapBounded(values, operation) {
  const results = Array.from({ length: values.length });
  let cursor = 0;
  let firstError = null;
  async function worker() {
    while (!firstError) {
      const index = cursor;
      cursor += 1;
      if (index >= values.length) return;
      try {
        results[index] = await operation(values[index], index);
      } catch (error) {
        firstError ??= error;
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, values.length) }, worker));
  if (firstError) throw firstError;
  return results;
}

async function deterministicGzip(original) {
  const deflated = await deflateRawAsync(original, { level: constants.Z_BEST_COMPRESSION });
  // RFC 1952 header: no optional fields, zero mtime, best-compression XFL,
  // and OS=unknown. This prevents host metadata from entering the artifact.
  const header = Buffer.from(CANONICAL_GZIP_HEADER_BYTES);
  const trailer = Buffer.alloc(8);
  trailer.writeUInt32LE(crc32(original) >>> 0, 0);
  trailer.writeUInt32LE(original.byteLength >>> 0, 4);
  return Buffer.concat([header, deflated, trailer]);
}

async function verifyCompressed(bytes, record, label) {
  if (bytes.byteLength !== record.compressedBytes || sha256(bytes) !== record.compressedSha256) {
    throw new Error(`compressed byte/hash verification failed: ${label}`);
  }
  let expanded;
  try {
    expanded = await gunzipAsync(bytes);
  } catch (error) {
    throw new Error(`compressed module cannot be gunzipped: ${label}`, { cause: error });
  }
  if (
    expanded.byteLength !== record.originalBytes ||
    sha256(expanded) !== record.originalSha256
  ) {
    throw new Error(`gunzip does not reproduce the declared module: ${label}`);
  }
}

async function assertRegularFile(path, label) {
  const info = await lstat(path);
  if (!info.isFile() || info.isSymbolicLink()) throw new Error(`${label} is not a regular file`);
}

export async function compressProjection({ projectionDir = "dist/client/atlas-projection" } = {}) {
  const root = resolve(projectionDir);
  const rootInfo = await lstat(root);
  if (!rootInfo.isDirectory() || rootInfo.isSymbolicLink()) {
    throw new Error(`projection root is not a regular directory: ${root}`);
  }
  const manifestPath = join(root, PROJECTION_MANIFEST_NAME);
  await assertRegularFile(manifestPath, "projection manifest");
  const manifestBytes = await readFile(manifestPath);
  let manifest;
  try {
    manifest = JSON.parse(manifestBytes.toString("utf8"));
  } catch (error) {
    throw new Error("projection manifest is not valid UTF-8 JSON", { cause: error });
  }
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    throw new Error("projection manifest is not a JSON object");
  }
  const { modules: declared, declarationCount } = collectDeclaredModules(manifest);
  const existingFiles = await walkFiles(root);
  const receiptPath = join(root, RECEIPT_NAME);
  if (existingFiles.some((path) => path === receiptPath)) {
    throw new Error(`${RECEIPT_NAME} already exists; refusing to overwrite a prior receipt`);
  }
  const precompressed = existingFiles
    .map((path) => relativePosix(root, path))
    .filter((path) => path.endsWith(".mjs.gz"));
  if (precompressed.length) {
    throw new Error(`pre-existing compressed projection module refused: ${precompressed[0]}`);
  }
  const actualModules = new Set(
    existingFiles
      .map((path) => relativePosix(root, path))
      .filter((path) => path.endsWith(".mjs")),
  );
  const censusError = describeDifference(new Set(declared.keys()), actualModules);
  if (censusError) throw new Error(censusError);

  const descriptors = [...declared.values()].sort((left, right) => left.path.localeCompare(right.path));
  // Verify every source against the projection compiler receipt before writing
  // any compressed output.
  await mapBounded(descriptors, async (descriptor) => {
    const path = join(root, ...descriptor.path.split("/"));
    await assertRegularFile(path, `projection module ${descriptor.path}`);
    const bytes = await readFile(path);
    if (bytes.byteLength !== descriptor.bytes || sha256(bytes) !== descriptor.sha256) {
      throw new Error(`projection module byte/hash mismatch: ${descriptor.path}`);
    }
  });

  const stagingRoot = `${root}.compression-staging-${process.pid}`;
  await rm(stagingRoot, { recursive: true, force: true });
  await mkdir(stagingRoot, { recursive: false });
  try {
    const records = await mapBounded(descriptors, async (descriptor) => {
      const original = await readFile(join(root, ...descriptor.path.split("/")));
      const compressed = await deterministicGzip(original);
      const compressedPath = `${descriptor.path}.gz`;
      const stagePath = join(stagingRoot, ...compressedPath.split("/"));
      await mkdir(dirname(stagePath), { recursive: true });
      await writeFile(stagePath, compressed, { flag: "wx" });
      const record = {
        path: descriptor.path,
        compressedPath,
        originalBytes: original.byteLength,
        originalSha256: descriptor.sha256,
        compressedBytes: compressed.byteLength,
        compressedSha256: sha256(compressed),
      };
      await verifyCompressed(await readFile(stagePath), record, compressedPath);
      return record;
    });

    const stagedFiles = new Set(
      (await walkFiles(stagingRoot)).map((path) => relativePosix(stagingRoot, path)),
    );
    const stagedError = describeDifference(new Set(records.map((record) => record.compressedPath)), stagedFiles);
    if (stagedError) throw new Error(`staged ${stagedError}`);

    for (const record of records) {
      const destination = join(root, ...record.compressedPath.split("/"));
      await rename(join(stagingRoot, ...record.compressedPath.split("/")), destination);
    }
    await rm(stagingRoot, { recursive: true, force: true });

    // All final compressed members must independently reproduce their source
    // before even one original is removed.
    await mapBounded(records, async (record) => {
      const compressedPath = join(root, ...record.compressedPath.split("/"));
      await assertRegularFile(compressedPath, `compressed projection module ${record.compressedPath}`);
      await verifyCompressed(await readFile(compressedPath), record, record.compressedPath);
    });
    await mapBounded(descriptors, async (descriptor) => {
      const original = await readFile(join(root, ...descriptor.path.split("/")));
      if (original.byteLength !== descriptor.bytes || sha256(original) !== descriptor.sha256) {
        throw new Error(`projection module changed during compression: ${descriptor.path}`);
      }
    });

    for (const descriptor of descriptors) {
      await unlink(join(root, ...descriptor.path.split("/")));
    }
    const finalFiles = await walkFiles(root);
    const remainingOriginals = finalFiles
      .map((path) => relativePosix(root, path))
      .filter((path) => path.endsWith(".mjs"));
    if (remainingOriginals.length) {
      throw new Error(`uncompressed projection module remains: ${remainingOriginals[0]}`);
    }
    const finalCompressed = new Set(
      finalFiles
        .map((path) => relativePosix(root, path))
        .filter((path) => path.endsWith(".mjs.gz")),
    );
    const finalError = describeDifference(
      new Set(records.map((record) => record.compressedPath)),
      finalCompressed,
    );
    if (finalError) throw new Error(`final compressed ${finalError}`);
    const finalManifestBytes = await readFile(manifestPath);
    if (!finalManifestBytes.equals(manifestBytes)) {
      throw new Error("projection-manifest.json changed during compression");
    }

    const receipt = {
      schemaVersion: "1.0.0",
      algorithm: "gzip:deflate-raw:level-9:mtime-0:os-255",
      sourceCommit: manifest.sourceCommit ?? null,
      sourceTreeDigest: manifest.sourceTreeDigest ?? null,
      projectionSchemaVersion: manifest.schemaVersion ?? null,
      projectionManifest: {
        path: PROJECTION_MANIFEST_NAME,
        bytes: manifestBytes.byteLength,
        sha256: sha256(manifestBytes),
      },
      declarationCount,
      moduleCount: records.length,
      originalBytes: records.reduce((total, record) => total + record.originalBytes, 0),
      compressedBytes: records.reduce((total, record) => total + record.compressedBytes, 0),
      modules: records,
    };
    const receiptBytes = Buffer.from(`${stableJson(receipt)}\n`, "utf8");
    const temporaryReceipt = `${receiptPath}.tmp-${process.pid}`;
    await writeFile(temporaryReceipt, receiptBytes, { flag: "wx" });
    await rename(temporaryReceipt, receiptPath);
    return receipt;
  } finally {
    await rm(stagingRoot, { recursive: true, force: true });
    await rm(`${receiptPath}.tmp-${process.pid}`, { force: true });
  }
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  try {
    const projectionDir = process.argv[2] ?? "dist/client/atlas-projection";
    const receipt = await compressProjection({ projectionDir });
    process.stdout.write(
      `${JSON.stringify({
        output: resolve(projectionDir),
        modules: receipt.moduleCount,
        originalBytes: receipt.originalBytes,
        compressedBytes: receipt.compressedBytes,
      })}\n`,
    );
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
