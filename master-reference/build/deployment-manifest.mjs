#!/usr/bin/env node
/**
 * Produce and verify the outer, exact-member receipt for a Sites deployment.
 * The receipt is deliberately not self-hashed: its member census is every
 * other regular file under dist/, and verification recomputes that closed set.
 */
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import {
  lstat,
  readFile,
  readdir,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { join, relative, resolve, sep } from "node:path";
import { promisify } from "node:util";
import { pathToFileURL } from "node:url";

const execFileAsync = promisify(execFile);
const MANIFEST_NAME = "deployment-manifest.json";
const SCHEMA_VERSION = "1.0.0";
const RECORD_TYPE = "atlas_deployment_bundle";
const IO_CONCURRENCY = 16;
const MANIFEST_RULE = Object.freeze({
  path: MANIFEST_NAME,
  selfHash: false,
  memberCensus: "every_regular_file_under_dist_except_this_manifest",
  verification: "manifest_must_exist_once_but_must_not_appear_in_members",
});
const HASH_RULE = Object.freeze({
  member: "sha256(raw_file_bytes)",
  membersDigest: "sha256(utf8(stable_json(members)+LF))",
  bundleDigest:
    "sha256(utf8(stable_json({schemaVersion,recordType,source,referenceSource,memberCount,totalBytes,members})+LF))",
  ordering: "ascending_utf16_code_unit_relative_posix_path",
  filesystem: "regular_files_only;symlinks_and_special_entries_forbidden",
});
const SOURCE_RULE = Object.freeze({
  commitJoin: "source.commit_must_equal_referenceSource.commit",
  gitTree: "source.treeOid_is_the_clean_HEAD_git_tree_object",
  referenceTree:
    "referenceSource.compilerTreeDigest_is_the_compiler_file_census_digest_not_a_git_tree_oid",
});

const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const compareText = (left, right) => (left < right ? -1 : left > right ? 1 : 0);

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort(compareText)
      .map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function canonicalBytes(value) {
  return Buffer.from(`${stableJson(value)}\n`, "utf8");
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
  await Promise.all(Array.from({ length: Math.min(IO_CONCURRENCY, values.length) }, worker));
  if (firstError) throw firstError;
  return results;
}

function safeMemberPath(value, label = "deployment member") {
  if (
    typeof value !== "string" ||
    !value ||
    value.includes("\\") ||
    value.startsWith("/") ||
    /^[A-Za-z]:/.test(value)
  ) {
    throw new Error(`${label} path is unsafe: ${String(value)}`);
  }
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error(`${label} path is unsafe: ${value}`);
  }
  return value;
}

function relativePosix(root, path) {
  return relative(root, path).split(sep).join("/");
}

async function assertDirectory(path, label) {
  const info = await lstat(path);
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new Error(`${label} is not a regular directory: ${path}`);
  }
}

async function assertRegularFile(path, label) {
  const info = await lstat(path);
  if (!info.isFile() || info.isSymbolicLink()) {
    throw new Error(`${label} is not a regular file: ${path}`);
  }
}

async function walkRegularFiles(root) {
  await assertDirectory(root, "deployment root");
  const files = [];
  async function walk(directory) {
    const entries = await readdir(directory, { withFileTypes: true });
    entries.sort((left, right) => compareText(left.name, right.name));
    for (const entry of entries) {
      const path = join(directory, entry.name);
      if (entry.isSymbolicLink()) throw new Error(`symlink refused in deployment bundle: ${path}`);
      if (entry.isDirectory()) await walk(path);
      else if (entry.isFile()) files.push(path);
      else throw new Error(`non-regular deployment entry refused: ${path}`);
    }
  }
  await walk(root);
  return files;
}

async function runGit(repoRoot, args) {
  try {
    const { stdout } = await execFileAsync("git", args, {
      cwd: repoRoot,
      encoding: "utf8",
      windowsHide: true,
      maxBuffer: 4 * 1024 * 1024,
    });
    return stdout;
  } catch (error) {
    throw new Error(`Git source-binding command failed: git ${args.join(" ")}`, { cause: error });
  }
}

async function readCleanGitSource(repoRoot) {
  const requestedRoot = resolve(repoRoot);
  const observedRoot = resolve((await runGit(requestedRoot, ["rev-parse", "--show-toplevel"])).trim());
  if (requestedRoot !== observedRoot) {
    throw new Error(`repository root mismatch: requested=${requestedRoot}; observed=${observedRoot}`);
  }
  const status = await runGit(requestedRoot, [
    "status",
    "--porcelain=v1",
    "--untracked-files=no",
  ]);
  if (status.length !== 0) {
    throw new Error("tracked Git tree is not clean; deployment receipt refused");
  }
  const commit = (await runGit(requestedRoot, ["rev-parse", "--verify", "HEAD"])).trim();
  const treeOid = (await runGit(requestedRoot, ["rev-parse", "--verify", "HEAD^{tree}"])).trim();
  const oidPattern = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;
  if (!oidPattern.test(commit) || !oidPattern.test(treeOid)) {
    throw new Error("Git source binding returned a malformed commit or tree object ID");
  }
  return {
    commit,
    treeOid,
    trackedTreeState: "clean",
    untrackedFilesDisposition: "not_part_of_cleanliness_gate;files_under_dist_are_still_censused",
  };
}

async function readJsonObject(path, label) {
  await assertRegularFile(path, label);
  const bytes = await readFile(path);
  let value;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch (error) {
    throw new Error(`${label} is not valid UTF-8 JSON`, { cause: error });
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} is not a JSON object`);
  }
  return { bytes, value };
}

async function readReferenceSource(distRoot) {
  const projectionRoot = join(distRoot, "client", "atlas-projection");
  const projectionPath = join(projectionRoot, "projection-manifest.json");
  const compressionPath = join(projectionRoot, "compression-manifest.json");
  const projection = await readJsonObject(projectionPath, "projection manifest");
  const compression = await readJsonObject(compressionPath, "compression manifest");
  const commitPattern = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;
  const digestPattern = /^[0-9a-f]{64}$/;
  if (
    !commitPattern.test(String(projection.value.sourceCommit ?? "")) ||
    !digestPattern.test(String(projection.value.sourceTreeDigest ?? "")) ||
    compression.value.sourceCommit !== projection.value.sourceCommit ||
    compression.value.sourceTreeDigest !== projection.value.sourceTreeDigest ||
    compression.value.projectionSchemaVersion !== projection.value.schemaVersion
  ) {
    throw new Error("projection/compression source binding mismatch");
  }
  const projectionReceipt = compression.value.projectionManifest;
  if (
    projectionReceipt?.path !== "projection-manifest.json" ||
    projectionReceipt.bytes !== projection.bytes.byteLength ||
    projectionReceipt.sha256 !== sha256(projection.bytes)
  ) {
    throw new Error("compression receipt does not bind the exact projection manifest");
  }
  return {
    commit: projection.value.sourceCommit,
    compilerTreeDigest: projection.value.sourceTreeDigest,
    projectionSchemaVersion: projection.value.schemaVersion,
    compressionSchemaVersion: compression.value.schemaVersion,
    projectionManifestSha256: sha256(projection.bytes),
    compressionManifestSha256: sha256(compression.bytes),
  };
}

function assertExactSourceJoin(source, referenceSource) {
  if (source.commit !== referenceSource.commit) {
    throw new Error(
      `reference projection commit does not equal clean build commit: reference=${referenceSource.commit}; build=${source.commit}`,
    );
  }
}

async function censusMembers(distRoot) {
  const files = await walkRegularFiles(distRoot);
  const paths = files
    .map((path) => relativePosix(distRoot, path))
    .filter((path) => path !== MANIFEST_NAME)
    .sort(compareText);
  if (new Set(paths).size !== paths.length) {
    throw new Error("deployment member census contains duplicate relative paths");
  }
  return mapBounded(paths, async (path) => {
    safeMemberPath(path);
    const bytes = await readFile(join(distRoot, ...path.split("/")));
    return { path, bytes: bytes.byteLength, sha256: sha256(bytes) };
  });
}

function digestPayload({ source, referenceSource, members }) {
  return {
    schemaVersion: SCHEMA_VERSION,
    recordType: RECORD_TYPE,
    source,
    referenceSource,
    memberCount: members.length,
    totalBytes: members.reduce((total, member) => total + member.bytes, 0),
    members,
  };
}

function createManifest({ source, referenceSource, members }) {
  const payload = digestPayload({ source, referenceSource, members });
  return {
    ...payload,
    manifestRule: MANIFEST_RULE,
    hashRule: HASH_RULE,
    sourceRule: SOURCE_RULE,
    membersDigest: sha256(canonicalBytes(members)),
    bundleDigest: sha256(canonicalBytes(payload)),
  };
}

function describeCensusDifference(declared, actual) {
  const missing = [...declared].filter((path) => !actual.has(path)).sort(compareText);
  const extra = [...actual].filter((path) => !declared.has(path)).sort(compareText);
  if (!missing.length && !extra.length) return null;
  const sample = (values) => values.slice(0, 5).join(", ") || "none";
  return `deployment member census mismatch; missing=${sample(missing)}; extra=${sample(extra)}`;
}

export async function verifyDeploymentManifest({ distDir = "dist", repoRoot = ".." } = {}) {
  const distRoot = resolve(distDir);
  const manifestPath = join(distRoot, MANIFEST_NAME);
  const manifestReceipt = await readJsonObject(manifestPath, "deployment manifest");
  if (!manifestReceipt.bytes.equals(canonicalBytes(manifestReceipt.value))) {
    throw new Error("deployment manifest is not stable canonical JSON with one trailing LF");
  }
  const receipt = manifestReceipt.value;
  if (!Array.isArray(receipt.members)) throw new Error("deployment manifest members are malformed");
  const declaredPaths = receipt.members.map((member) => safeMemberPath(member?.path));
  if (
    declaredPaths.includes(MANIFEST_NAME) ||
    new Set(declaredPaths).size !== declaredPaths.length ||
    stableJson(declaredPaths) !== stableJson([...declaredPaths].sort(compareText))
  ) {
    throw new Error("deployment manifest member paths violate the non-self-hashed sorted census rule");
  }
  const actualFiles = await walkRegularFiles(distRoot);
  const actualPaths = new Set(
    actualFiles
      .map((path) => relativePosix(distRoot, path))
      .filter((path) => path !== MANIFEST_NAME),
  );
  const censusError = describeCensusDifference(new Set(declaredPaths), actualPaths);
  if (censusError) throw new Error(censusError);
  await mapBounded(receipt.members, async (member) => {
    if (
      !Number.isSafeInteger(member.bytes) ||
      member.bytes < 0 ||
      !/^[0-9a-f]{64}$/.test(String(member.sha256 ?? ""))
    ) {
      throw new Error(`deployment member receipt is malformed: ${member.path}`);
    }
    const bytes = await readFile(join(distRoot, ...member.path.split("/")));
    if (bytes.byteLength !== member.bytes || sha256(bytes) !== member.sha256) {
      throw new Error(`deployment member byte/hash mismatch: ${member.path}`);
    }
  });
  const source = await readCleanGitSource(repoRoot);
  const referenceSource = await readReferenceSource(distRoot);
  assertExactSourceJoin(source, referenceSource);
  const expected = createManifest({ source, referenceSource, members: receipt.members });
  if (!canonicalBytes(receipt).equals(canonicalBytes(expected))) {
    throw new Error("deployment manifest does not match its recomputed source-bound receipt");
  }
  return receipt;
}

export async function buildDeploymentManifest({ distDir = "dist", repoRoot = ".." } = {}) {
  const distRoot = resolve(distDir);
  const manifestPath = join(distRoot, MANIFEST_NAME);
  await assertDirectory(distRoot, "deployment root");
  const initialFiles = await walkRegularFiles(distRoot);
  if (initialFiles.some((path) => relativePosix(distRoot, path) === MANIFEST_NAME)) {
    throw new Error(`${MANIFEST_NAME} already exists; refusing to overwrite a prior outer receipt`);
  }
  const source = await readCleanGitSource(repoRoot);
  const referenceSource = await readReferenceSource(distRoot);
  assertExactSourceJoin(source, referenceSource);
  const members = await censusMembers(distRoot);
  const finalSource = await readCleanGitSource(repoRoot);
  if (stableJson(source) !== stableJson(finalSource)) {
    throw new Error("tracked Git source changed while deployment members were being hashed");
  }
  const receipt = createManifest({ source, referenceSource, members });
  const temporaryPath = `${distRoot}.deployment-manifest-${process.pid}.tmp`;
  await rm(temporaryPath, { force: true });
  try {
    await writeFile(temporaryPath, canonicalBytes(receipt), { flag: "wx" });
    await rename(temporaryPath, manifestPath);
    await verifyDeploymentManifest({ distDir: distRoot, repoRoot });
    return receipt;
  } catch (error) {
    await rm(manifestPath, { force: true });
    throw error;
  } finally {
    await rm(temporaryPath, { force: true });
  }
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  try {
    const receipt = await buildDeploymentManifest();
    process.stdout.write(
      `${JSON.stringify({
        output: resolve("dist", MANIFEST_NAME),
        members: receipt.memberCount,
        totalBytes: receipt.totalBytes,
        bundleDigest: receipt.bundleDigest,
      })}\n`,
    );
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  }
}
