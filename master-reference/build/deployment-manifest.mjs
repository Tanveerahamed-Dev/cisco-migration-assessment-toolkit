#!/usr/bin/env node
/**
 * Produce and verify the outer, exact-member receipt for a Sites deployment.
 * Its raw canonical JSON is deliberately not self-hashed: the physical
 * deterministic-gzip representation is excluded from the member census, and
 * verification reconstructs and recomputes the conceptual receipt in memory.
 */
import { createHash, randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import {
  link,
  lstat,
  open,
  readdir,
  unlink,
} from "node:fs/promises";
import { basename, dirname, join, relative, resolve, sep } from "node:path";
import { promisify, TextDecoder } from "node:util";
import { pathToFileURL } from "node:url";

import { deterministicGzip, expandReceiptBoundGzip } from "./deterministic-gzip.mjs";

const execFileAsync = promisify(execFile);
const MANIFEST_SOURCE_NAME = "deployment-manifest.json";
const MANIFEST_NAME = `${MANIFEST_SOURCE_NAME}.gz`;
const SCHEMA_VERSION = "1.1.0";
const RECORD_TYPE = "atlas_deployment_bundle";
const IO_CONCURRENCY = 16;
const PRIVACY_SCAN_CONCURRENCY = 4;
const MAX_JSON_RECEIPT_BYTES = 32 * 1024 * 1024;
const MAX_GZIP_RECEIPT_BYTES = 32 * 1024 * 1024;
const MAX_JSON_STRUCTURE_DEPTH = 64;
const MAX_JSON_STRUCTURE_VALUES = 5_000_000;
const MAX_COMPRESSED_MODULE_BYTES = 8 * 1024 * 1024;
const MAX_EXPANDED_MODULE_BYTES = 8 * 1024 * 1024;
const MAX_COMPRESSED_PROJECTION_BYTES = 512 * 1024 * 1024;
const MAX_EXPANDED_PROJECTION_BYTES = 2 * 1024 * 1024 * 1024;
const MAX_DEPLOYMENT_MEMBER_BYTES = 248 * 1024 * 1024;
const MAX_DEPLOYMENT_BYTES = 248 * 1024 * 1024;
const MAX_RUNTIME_VERSION_BYTES = 64;
const PUBLIC_OPTIONS_KEYS = new Set(["distDir", "repoRoot"]);
const GENERIC_AUTOMATION_USERS = new Set([
  "actions",
  "agent",
  "build",
  "builder",
  "codex",
  "github",
  "root",
  "runner",
]);
const GENERIC_WINDOWS_USER_HOME = /(?:^|[^a-z0-9])(?:[a-z]:|[\\/]{2,}[^\\/\r\n]+)[\\/]+users[\\/]+[^\\/\p{Cc}<>:"|?*']{1,128}(?=[\\/]|$|["'])/u;
const GENERIC_POSIX_USER_HOME = /(?:^|[^a-z0-9])\/(?:home|users)\/[^/\p{Cc}"']{1,128}(?=\/|$|["'])/u;
const GENERIC_COLLAPSED_USER_HOME = /(?:^|_)(?:[a-z]_users|home|users)_[a-z0-9][a-z0-9_]{0,127}_(?:appdata|build|cache|checkout|checkouts|code|config|desktop|documents|downloads|git|onedrive|project|projects|repo|repos|source|src|work|workspace)(?:_|$)/;
const STRICT_UTF8 = new TextDecoder("utf-8", { fatal: true });
const MANIFEST_RULE = Object.freeze({
  path: MANIFEST_SOURCE_NAME,
  representationPath: MANIFEST_NAME,
  contentEncoding: "gzip",
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

function hasExactKeys(value, keys) {
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    stableJson(Object.keys(value).sort(compareText)) === stableJson([...keys].sort(compareText))
  );
}

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

function assertBoundedJsonStructure(value, label) {
  const pending = [{ value, depth: 0 }];
  let visited = 0;
  while (pending.length) {
    const current = pending.pop();
    visited += 1;
    if (
      visited > MAX_JSON_STRUCTURE_VALUES ||
      current.depth > MAX_JSON_STRUCTURE_DEPTH
    ) {
      throw new Error(`${label} exceeds bounded JSON structure limits`);
    }
    if (Array.isArray(current.value)) {
      for (const child of current.value) {
        pending.push({ value: child, depth: current.depth + 1 });
      }
    } else if (current.value && typeof current.value === "object") {
      for (const child of Object.values(current.value)) {
        pending.push({ value: child, depth: current.depth + 1 });
      }
    }
  }
}

async function mapBounded(values, operation, concurrency = IO_CONCURRENCY) {
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
  await Promise.all(Array.from({ length: Math.min(concurrency, values.length) }, worker));
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
    throw new Error(`${label} path is unsafe`);
  }
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error(`${label} path is unsafe`);
  }
  return value;
}

function relativePosix(root, path) {
  return relative(root, path).split(sep).join("/");
}

async function assertDirectory(path, label) {
  let info;
  try {
    info = await lstat(path);
  } catch {
    throw new Error(`${label} is unavailable`);
  }
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new Error(`${label} is not a regular directory`);
  }
}

async function assertRegularFile(path, label) {
  let info;
  try {
    info = await lstat(path);
  } catch {
    throw new Error(`${label} is unavailable`);
  }
  if (!info.isFile() || info.isSymbolicLink()) {
    throw new Error(`${label} is not a regular file`);
  }
  return info;
}

function sameFileIdentity(left, right) {
  return left.dev === right.dev && left.ino === right.ino;
}

function sameFileSnapshot(left, right) {
  return (
    sameFileIdentity(left, right) &&
    left.size === right.size &&
    left.mtimeMs === right.mtimeMs &&
    left.ctimeMs === right.ctimeMs
  );
}

async function readStableBoundedBytes(
  path,
  label,
  maximumBytes,
  hooks = {},
) {
  let handle;
  try {
    if (!Number.isSafeInteger(maximumBytes) || maximumBytes < 0) {
      throw new Error(`${label} has an invalid bounded byte limit`);
    }
    const pathBefore = await assertRegularFile(path, label);
    if (pathBefore.size > maximumBytes) {
      throw new Error(`${label} exceeds the bounded byte limit`);
    }
    await hooks.afterPathStat?.({ path, label });
    handle = await open(path, "r");
    const handleBefore = await handle.stat();
    if (!handleBefore.isFile() || !sameFileSnapshot(pathBefore, handleBefore)) {
      throw new Error(`${label} changed during its bounded read`);
    }
    await hooks.afterHandleStat?.({ path, label });

    const chunks = [];
    let totalBytes = 0;
    let position = 0;
    while (totalBytes <= maximumBytes) {
      const requestedBytes = Math.min(64 * 1024, maximumBytes - totalBytes + 1);
      const buffer = Buffer.allocUnsafe(requestedBytes);
      const { bytesRead } = await handle.read(
        buffer,
        0,
        requestedBytes,
        position,
      );
      if (bytesRead === 0) break;
      chunks.push(buffer.subarray(0, bytesRead));
      totalBytes += bytesRead;
      position += bytesRead;
    }
    if (totalBytes > maximumBytes) {
      throw new Error(`${label} exceeds the bounded byte limit`);
    }
    const bytes = Buffer.concat(chunks, totalBytes);
    const handleAfter = await handle.stat();
    if (
      !sameFileSnapshot(handleBefore, handleAfter) ||
      bytes.byteLength !== handleAfter.size
    ) {
      throw new Error(`${label} changed during its bounded read`);
    }
    await handle.close();
    handle = null;
    const pathAfter = await assertRegularFile(path, label);
    if (!sameFileSnapshot(handleAfter, pathAfter)) {
      throw new Error(`${label} changed during its bounded read`);
    }
    return bytes;
  } catch {
    if (handle) {
      try {
        await handle.close();
      } catch {
        // The public fixed error below is the only disclosure boundary.
      }
    }
    throw new Error(`${label} bounded read failed`);
  }
}

async function walkRegularFiles(root) {
  await assertDirectory(root, "deployment root");
  const files = [];
  async function walk(directory) {
    let entries;
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch {
      throw new Error("deployment directory cannot be enumerated");
    }
    entries.sort((left, right) => compareText(left.name, right.name));
    for (const entry of entries) {
      const path = join(directory, entry.name);
      if (entry.isSymbolicLink()) throw new Error("symlink refused in deployment bundle");
      if (entry.isDirectory()) await walk(path);
      else if (entry.isFile()) files.push(path);
      else throw new Error("non-regular deployment entry refused");
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
  } catch {
    throw new Error(`Git source-binding command failed: git ${args.join(" ")}`);
  }
}

async function readCleanGitSource(repoRoot) {
  const requestedRoot = resolve(repoRoot);
  const observedRoot = resolve((await runGit(requestedRoot, ["rev-parse", "--show-toplevel"])).trim());
  if (requestedRoot !== observedRoot) {
    throw new Error("repository root mismatch");
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

async function readJsonObject(
  path,
  label,
  maximumBytes = MAX_JSON_RECEIPT_BYTES,
  hooks = {},
) {
  const bytes = await readStableBoundedBytes(path, label, maximumBytes, hooks);
  let value;
  try {
    value = JSON.parse(STRICT_UTF8.decode(bytes));
  } catch {
    throw new Error(`${label} is not valid UTF-8 JSON`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} is not a JSON object`);
  }
  assertBoundedJsonStructure(value, label);
  return { bytes, value };
}

async function readGzipJsonObject(
  path,
  label,
  maximumExpandedBytes = MAX_JSON_RECEIPT_BYTES,
  hooks = {},
) {
  const representationBytes = await readStableBoundedBytes(
    path,
    label,
    MAX_GZIP_RECEIPT_BYTES,
    hooks,
  );
  const bytes = await expandReceiptBoundGzip(representationBytes, {
    label,
    maximumCompressedBytes: MAX_GZIP_RECEIPT_BYTES,
    maximumExpandedBytes,
  });
  let value;
  try {
    value = JSON.parse(STRICT_UTF8.decode(bytes));
  } catch {
    throw new Error(`${label} is not valid UTF-8 JSON`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} is not a JSON object`);
  }
  assertBoundedJsonStructure(value, label);
  return { bytes, representationBytes, value };
}

function safeProjectionModulePath(value, label = "projection module") {
  const path = safeMemberPath(value, label);
  if (!path.endsWith(".mjs")) {
    throw new Error(`${label} does not name an .mjs module`);
  }
  return path;
}

function collectDeclaredProjectionModules(manifest) {
  const modules = new Map();
  let declarationCount = 0;
  function visit(value) {
    if (Array.isArray(value)) {
      value.forEach((entry) => visit(entry));
      return;
    }
    if (!value || typeof value !== "object") return;
    const entries = Object.entries(value);
    const moduleEntry = entries.find(
      ([key, child]) => key === "module" && typeof child === "string" && child.endsWith(".mjs"),
    );
    const candidates = moduleEntry
      ? [moduleEntry]
      : entries.filter(([, child]) => typeof child === "string" && child.endsWith(".mjs"));
    for (const [, child] of candidates) {
      const declarationIndex = declarationCount;
      const path = safeProjectionModulePath(child, `projection module declaration ${declarationIndex}`);
      if (
        !Number.isSafeInteger(value.bytes) ||
        value.bytes < 0 ||
        value.bytes > MAX_EXPANDED_MODULE_BYTES ||
        !/^[0-9a-f]{64}$/.test(String(value.sha256 ?? ""))
      ) {
        throw new Error(`projection module declaration lacks a bounded byte/hash receipt: index=${declarationIndex}`);
      }
      const descriptor = { path, bytes: value.bytes, sha256: value.sha256 };
      const prior = modules.get(path);
      if (prior && (prior.bytes !== descriptor.bytes || prior.sha256 !== descriptor.sha256)) {
        throw new Error(`conflicting projection module declarations: ${path}`);
      }
      modules.set(path, descriptor);
      declarationCount += 1;
    }
    for (const [, child] of entries) visit(child);
  }
  visit(manifest);
  if (!modules.size) throw new Error("projection manifest declares no .mjs modules");
  return { modules, declarationCount };
}

function collapsedAsciiIdentity(value) {
  return value
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function localIdentityContract(repoRoot) {
  const nativeRoot = resolve(repoRoot);
  const slashRoot = nativeRoot.replaceAll("\\", "/");
  const parts = slashRoot.split("/").filter(Boolean);
  const homeIndex = parts.findIndex((part) => ["home", "users"].includes(part.toLowerCase()));
  const homePath = homeIndex >= 0 && homeIndex + 1 < parts.length
    ? parts.slice(0, homeIndex + 2).join("/")
    : "";
  const user = homePath ? parts[homeIndex + 1].normalize("NFKC").toLowerCase() : "";
  const exactVariants = (value) => value
    ? [...new Set([
        value.normalize("NFKC").toLowerCase(),
        value.normalize("NFKC").toLowerCase().replaceAll("\\", "/"),
        value.normalize("NFKC").toLowerCase().replaceAll("/", "\\"),
      ])]
    : [];
  const collapsedVariants = (value) => {
    const collapsed = collapsedAsciiIdentity(value);
    return collapsed.length >= 8 ? [collapsed] : [];
  };
  return {
    repositoryExact: exactVariants(nativeRoot),
    repositoryCollapsed: collapsedVariants(nativeRoot),
    homeExact: exactVariants(homePath),
    homeCollapsed: collapsedVariants(homePath),
    users:
      user.length >= 3 && !GENERIC_AUTOMATION_USERS.has(user)
        ? [user]
        : [],
  };
}

function localIdentityRule(value, contract) {
  const folded = value.normalize("NFKC").toLowerCase();
  if (contract.repositoryExact.some((marker) => folded.includes(marker))) {
    return "local_repository_path";
  }
  if (contract.homeExact.some((marker) => folded.includes(marker))) {
    return "local_home_path";
  }
  const collapsed = collapsedAsciiIdentity(folded);
  if (contract.repositoryCollapsed.some((marker) => collapsed.includes(marker))) {
    return "local_repository_collapsed_path";
  }
  if (contract.homeCollapsed.some((marker) => collapsed.includes(marker))) {
    return "local_home_collapsed_path";
  }
  for (const user of contract.users) {
    let offset = folded.indexOf(user);
    while (offset >= 0) {
      const before = offset === 0 ? "" : folded[offset - 1];
      const after = offset + user.length >= folded.length ? "" : folded[offset + user.length];
      if (!/[a-z0-9]/i.test(before) && !/[a-z0-9]/i.test(after)) {
        return "local_user_identity_component";
      }
      offset = folded.indexOf(user, offset + 1);
    }
  }
  return null;
}

function genericHomeIdentityRule(value) {
  const folded = value.normalize("NFKC").toLowerCase();
  if (GENERIC_WINDOWS_USER_HOME.test(folded)) {
    return "generic_windows_user_home_path";
  }
  if (GENERIC_POSIX_USER_HOME.test(folded)) {
    return "generic_posix_user_home_path";
  }
  if (GENERIC_COLLAPSED_USER_HOME.test(collapsedAsciiIdentity(folded))) {
    return "generic_collapsed_user_home_path";
  }
  return null;
}

function generatedPathIdentityRule(value, contract) {
  if (typeof value !== "string") return null;
  return localIdentityRule(value, contract) ?? genericHomeIdentityRule(value);
}

function assertGeneratedPathPrivacy(value, contract, category, index) {
  const rule = generatedPathIdentityRule(value, contract);
  if (rule !== null) {
    throw new Error(
      `deployment path privacy scan failed: rule=${rule}; category=${category}; index=${index}`,
    );
  }
}

function preflightProjectionPaths(projection, compression, contract) {
  let declarationIndex = 0;
  function visit(value) {
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (!value || typeof value !== "object") return;
    const entries = Object.entries(value);
    const moduleEntry = entries.find(
      ([key, child]) => key === "module" && typeof child === "string" && child.endsWith(".mjs"),
    );
    const candidates = moduleEntry
      ? [moduleEntry]
      : entries.filter(([, child]) => typeof child === "string" && child.endsWith(".mjs"));
    for (const [, child] of candidates) {
      assertGeneratedPathPrivacy(child, contract, "projection-declaration", declarationIndex);
      declarationIndex += 1;
    }
    for (const [, child] of entries) visit(child);
  }
  visit(projection);
  if (!Array.isArray(compression?.modules)) return;
  compression.modules.forEach((record, index) => {
    assertGeneratedPathPrivacy(record?.path, contract, "compression-original", index);
    assertGeneratedPathPrivacy(record?.compressedPath, contract, "compression-member", index);
  });
}

function assertGeneratedReceiptPrivacy(bytes, contract, category) {
  const text = STRICT_UTF8.decode(bytes);
  const rule = localIdentityRule(text, contract) ?? genericHomeIdentityRule(text);
  if (rule !== null) {
    throw new Error(
      `deployment generated-metadata privacy scan failed: rule=${rule}; category=${category}`,
    );
  }
}

function graphPrivacyModulePaths(projection) {
  const paths = new Set();
  const add = (value) => {
    if (typeof value === "string") paths.add(safeProjectionModulePath(value, "graph privacy module"));
  };
  add(projection?.index?.path);
  add(projection?.graph?.index?.module);
  add(projection?.graph?.summary?.module);
  for (const descriptor of projection?.graph?.shards ?? []) add(descriptor?.module);
  for (const descriptor of projection?.metadataModules ?? []) {
    if (["graph_nodes", "graph_edges"].includes(descriptor?.group)) add(descriptor?.module);
  }
  return paths;
}

async function validateCompressedProjection({
  projectionRoot,
  projection,
  compression,
  repoRoot,
  readHooks = {},
}) {
  if (!projection.bytes.equals(canonicalBytes(projection.value))) {
    throw new Error("projection manifest is not stable canonical JSON with one trailing LF");
  }
  if (!compression.bytes.equals(canonicalBytes(compression.value))) {
    throw new Error("compression manifest is not stable canonical JSON with one trailing LF");
  }
  const privacyContract = localIdentityContract(repoRoot);
  preflightProjectionPaths(projection.value, compression.value, privacyContract);
  assertGeneratedReceiptPrivacy(
    projection.bytes,
    privacyContract,
    "projection-manifest",
  );
  assertGeneratedReceiptPrivacy(
    compression.bytes,
    privacyContract,
    "compression-manifest",
  );
  const { modules: declared, declarationCount } = collectDeclaredProjectionModules(
    projection.value,
  );
  const genericPrivacyModules = graphPrivacyModulePaths(projection.value);
  const receipt = compression.value;
  const records = receipt.modules;
  if (
    !hasExactKeys(receipt, [
      "algorithm",
      "compressedBytes",
      "declarationCount",
      "moduleCount",
      "modules",
      "originalBytes",
      "producerRuntime",
      "projectionManifest",
      "projectionSchemaVersion",
      "schemaVersion",
      "sourceCommit",
      "sourceTreeDigest",
    ]) ||
    !hasExactKeys(receipt.producerRuntime, ["node", "zlib"]) ||
    !hasExactKeys(receipt.projectionManifest, [
      "bytes",
      "contentEncoding",
      "path",
      "representationBytes",
      "representationPath",
      "representationSha256",
      "sha256",
    ]) ||
    receipt.schemaVersion !== "1.1.0" ||
    !/^gzip:deflate-raw:level-[0-9]:fixed-header:receipt-bound$/.test(
      String(receipt.algorithm ?? ""),
    ) ||
    !Array.isArray(records) ||
    receipt.declarationCount !== declarationCount ||
    receipt.moduleCount !== declared.size ||
    receipt.moduleCount !== records?.length ||
    !Number.isSafeInteger(receipt.originalBytes) ||
    receipt.originalBytes < 0 ||
    receipt.originalBytes > MAX_EXPANDED_PROJECTION_BYTES ||
    !Number.isSafeInteger(receipt.compressedBytes) ||
    receipt.compressedBytes < 0 ||
    receipt.compressedBytes > MAX_COMPRESSED_PROJECTION_BYTES
  ) {
    throw new Error("compression module receipt is absent or inconsistent");
  }
  const paths = [];
  const compressedPaths = [];
  let originalBytes = 0;
  let compressedBytes = 0;
  for (const record of records) {
    if (!hasExactKeys(record, [
      "compressedBytes",
      "compressedPath",
      "compressedSha256",
      "originalBytes",
      "originalSha256",
      "path",
    ])) {
      throw new Error("compressed projection module receipt has an unexpected shape");
    }
    const path = safeProjectionModulePath(record?.path, "compression module");
    const compressedPath = safeMemberPath(
      record?.compressedPath,
      "compressed projection module",
    );
    const declaredModule = declared.get(path);
    if (
      compressedPath !== `${path}.gz` ||
      !declaredModule ||
      !Number.isSafeInteger(record.originalBytes) ||
      record.originalBytes < 0 ||
      record.originalBytes > MAX_EXPANDED_MODULE_BYTES ||
      !Number.isSafeInteger(record.compressedBytes) ||
      record.compressedBytes < 0 ||
      record.compressedBytes > MAX_COMPRESSED_MODULE_BYTES ||
      !/^[0-9a-f]{64}$/.test(String(record.originalSha256 ?? "")) ||
      !/^[0-9a-f]{64}$/.test(String(record.compressedSha256 ?? "")) ||
      record.originalBytes !== declaredModule.bytes ||
      record.originalSha256 !== declaredModule.sha256
    ) {
      throw new Error(`compressed projection module receipt is malformed: ${path}`);
    }
    paths.push(path);
    compressedPaths.push(compressedPath);
    originalBytes += record.originalBytes;
    compressedBytes += record.compressedBytes;
    if (
      !Number.isSafeInteger(originalBytes) ||
      originalBytes > MAX_EXPANDED_PROJECTION_BYTES ||
      !Number.isSafeInteger(compressedBytes) ||
      compressedBytes > MAX_COMPRESSED_PROJECTION_BYTES
    ) {
      throw new Error("compressed projection aggregate exceeds its bounded receipt limits");
    }
  }
  if (
    new Set(paths).size !== paths.length ||
    new Set(compressedPaths).size !== compressedPaths.length ||
    stableJson(paths) !== stableJson([...paths].sort(compareText)) ||
    originalBytes !== receipt.originalBytes ||
    compressedBytes !== receipt.compressedBytes
  ) {
    throw new Error("compression module census or aggregate receipt is inconsistent");
  }
  const actualProjectionFiles = await walkRegularFiles(projectionRoot);
  const actualProjectionPaths = actualProjectionFiles.map((path) =>
    relativePosix(projectionRoot, path));
  actualProjectionPaths.forEach((path, index) => {
    assertGeneratedPathPrivacy(path, privacyContract, "projection-member", index);
  });
  const actualOriginalModules = actualProjectionPaths
    .filter((path) => path.endsWith(".mjs"));
  if (actualOriginalModules.length) {
    throw new Error(`uncompressed projection module remains: ${actualOriginalModules[0]}`);
  }
  if (
    actualProjectionPaths.includes("projection-manifest.json") ||
    actualProjectionPaths.includes("compression-manifest.json")
  ) {
    throw new Error("raw projection receipt duplicate is forbidden");
  }
  const actualCompressed = new Set(
    actualProjectionPaths
      .filter((path) => path.endsWith(".mjs.gz")),
  );
  const compressedCensusError = describeCensusDifference(
    new Set(compressedPaths),
    actualCompressed,
  );
  if (compressedCensusError) {
    throw new Error(`compressed projection ${compressedCensusError}`);
  }

  await mapBounded(
    records,
    async (record, index) => {
      const memberPath = join(projectionRoot, ...record.compressedPath.split("/"));
      const bytes = await readStableBoundedBytes(
        memberPath,
        "compressed projection module",
        Math.min(record.compressedBytes, MAX_COMPRESSED_MODULE_BYTES),
        readHooks.module,
      );
      if (bytes.byteLength !== record.compressedBytes || sha256(bytes) !== record.compressedSha256) {
        throw new Error(`compressed projection module byte/hash mismatch: ${record.compressedPath}`);
      }
      let expanded;
      try {
        expanded = await expandReceiptBoundGzip(bytes, {
          label: "compressed projection module",
          maximumCompressedBytes: MAX_COMPRESSED_MODULE_BYTES,
          maximumExpandedBytes: MAX_EXPANDED_MODULE_BYTES,
        });
      } catch {
        throw new Error(`compressed projection module cannot be bounded-gunzipped: ${record.compressedPath}`);
      }
      if (
        expanded.byteLength !== record.originalBytes ||
        sha256(expanded) !== record.originalSha256
      ) {
        throw new Error(`expanded projection module byte/hash mismatch: ${record.compressedPath}`);
      }
      let text;
      try {
        text = STRICT_UTF8.decode(expanded);
      } catch {
        throw new Error(`expanded projection module is not strict UTF-8: ${record.compressedPath}`);
      }
      const rule = localIdentityRule(text, privacyContract);
      const genericRule = (
        genericPrivacyModules.has(record.path) ||
        record.path === "index.mjs" ||
        record.path.startsWith("graph/") ||
        record.path.startsWith("metadata/graph_nodes/") ||
        record.path.startsWith("metadata/graph_edges/")
      )
        ? genericHomeIdentityRule(text)
        : null;
      if (rule !== null || genericRule !== null) {
        throw new Error(
          `deployment projection privacy scan failed: rule=${rule ?? genericRule}; category=compressed-projection-module; index=${index}`,
        );
      }
    },
    PRIVACY_SCAN_CONCURRENCY,
  );
}

async function readReferenceSource(distRoot, repoRoot, expectedSourceCommit, readHooks = {}) {
  const projectionRoot = join(distRoot, "client", "atlas-projection");
  const projectionPath = join(projectionRoot, "projection-manifest.json.gz");
  const compressionPath = join(projectionRoot, "compression-manifest.json.gz");
  const projection = await readGzipJsonObject(
    projectionPath,
    "projection manifest",
    MAX_JSON_RECEIPT_BYTES,
    readHooks.projection,
  );
  const compression = await readGzipJsonObject(
    compressionPath,
    "compression manifest",
    MAX_JSON_RECEIPT_BYTES,
    readHooks.compression,
  );
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
  const runtime = compression.value.producerRuntime;
  if (
    !runtime ||
    Object.keys(runtime).sort(compareText).join("\0") !== "node\0zlib" ||
    typeof runtime.node !== "string" ||
    runtime.node.length < 1 ||
    Buffer.byteLength(runtime.node, "utf8") > MAX_RUNTIME_VERSION_BYTES ||
    typeof runtime.zlib !== "string" ||
    runtime.zlib.length < 1 ||
    Buffer.byteLength(runtime.zlib, "utf8") > MAX_RUNTIME_VERSION_BYTES ||
    !/^(?:0|[1-9]\d{0,2})\.(?:0|[1-9]\d{0,2})\.(?:0|[1-9]\d{0,3})(?:[-+][0-9A-Za-z.-]{1,32})?$/.test(runtime.node) ||
    !/^(?:0|[1-9]\d{0,2})\.(?:0|[1-9]\d{0,2})\.(?:0|[1-9]\d{0,3})(?:[-+][0-9A-Za-z.-]{1,32})?$/.test(runtime.zlib)
  ) {
    throw new Error("compression receipt producer runtime is malformed");
  }
  const projectionReceipt = compression.value.projectionManifest;
  if (
    projectionReceipt?.path !== "projection-manifest.json" ||
    projectionReceipt.representationPath !== "projection-manifest.json.gz" ||
    projectionReceipt.contentEncoding !== "gzip" ||
    projectionReceipt.bytes !== projection.bytes.byteLength ||
    projectionReceipt.sha256 !== sha256(projection.bytes) ||
    projectionReceipt.representationBytes !== projection.representationBytes.byteLength ||
    projectionReceipt.representationSha256 !== sha256(projection.representationBytes)
  ) {
    throw new Error("compression receipt does not bind the exact projection manifest");
  }
  if (projection.value.sourceCommit !== expectedSourceCommit) {
    throw new Error("reference projection commit does not equal clean build commit");
  }
  await validateCompressedProjection({
    projectionRoot,
    projection,
    compression,
    repoRoot,
    readHooks,
  });
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

async function censusMembers(distRoot, repoRoot, readHooks = {}) {
  const files = await walkRegularFiles(distRoot);
  const paths = files
    .map((path) => relativePosix(distRoot, path))
    .filter((path) => path !== MANIFEST_NAME)
    .sort(compareText);
  const privacyContract = localIdentityContract(repoRoot);
  paths.forEach((path, index) => {
    assertGeneratedPathPrivacy(path, privacyContract, "deployment-member", index);
  });
  if (new Set(paths).size !== paths.length) {
    throw new Error("deployment member census contains duplicate relative paths");
  }
  const members = await mapBounded(paths, async (path) => {
    safeMemberPath(path);
    const bytes = await readStableBoundedBytes(
      join(distRoot, ...path.split("/")),
      "deployment member",
      MAX_DEPLOYMENT_MEMBER_BYTES,
      readHooks.member,
    );
    return { path, bytes: bytes.byteLength, sha256: sha256(bytes) };
  });
  const totalBytes = members.reduce((total, member) => total + member.bytes, 0);
  if (!Number.isSafeInteger(totalBytes) || totalBytes > MAX_DEPLOYMENT_BYTES) {
    throw new Error("deployment member aggregate exceeds the Sites expanded limit");
  }
  return members;
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

async function verifyDeploymentManifestReceipt(
  { distDir = "dist", repoRoot = ".." } = {},
  readHooks = {},
) {
  const distRoot = resolve(distDir);
  const manifestPath = join(distRoot, MANIFEST_NAME);
  const manifestReceipt = await readGzipJsonObject(
    manifestPath,
    "deployment manifest",
    MAX_JSON_RECEIPT_BYTES,
    readHooks.manifest,
  );
  if (!manifestReceipt.bytes.equals(canonicalBytes(manifestReceipt.value))) {
    throw new Error("deployment manifest is not stable canonical JSON with one trailing LF");
  }
  const receipt = manifestReceipt.value;
  if (!Array.isArray(receipt.members)) throw new Error("deployment manifest members are malformed");
  const privacyContract = localIdentityContract(repoRoot);
  assertGeneratedReceiptPrivacy(
    manifestReceipt.bytes,
    privacyContract,
    "deployment-manifest",
  );
  let declaredTotalBytes = 0;
  for (const member of receipt.members) {
    if (
      !hasExactKeys(member, ["bytes", "path", "sha256"]) ||
      typeof member.path !== "string" ||
      !Number.isSafeInteger(member?.bytes) ||
      member.bytes < 0 ||
      member.bytes > MAX_DEPLOYMENT_MEMBER_BYTES ||
      typeof member.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(member.sha256)
    ) {
      throw new Error("deployment manifest members are malformed");
    }
    declaredTotalBytes += member.bytes;
    if (!Number.isSafeInteger(declaredTotalBytes) || declaredTotalBytes > MAX_DEPLOYMENT_BYTES) {
      throw new Error("deployment member aggregate exceeds the Sites expanded limit");
    }
  }
  if (
    receipt.memberCount !== receipt.members.length ||
    receipt.totalBytes !== declaredTotalBytes ||
    declaredTotalBytes + manifestReceipt.representationBytes.byteLength > MAX_DEPLOYMENT_BYTES
  ) {
    throw new Error("deployment manifest member aggregate is inconsistent");
  }
  receipt.members.forEach((member, index) => {
    assertGeneratedPathPrivacy(member?.path, privacyContract, "deployment-member", index);
  });
  const declaredPaths = receipt.members.map((member) => safeMemberPath(member?.path));
  if (
    declaredPaths.includes(MANIFEST_NAME) ||
    declaredPaths.includes(MANIFEST_SOURCE_NAME) ||
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
  if (
    actualPaths.has("client/atlas-projection/projection-manifest.json") ||
    actualPaths.has("client/atlas-projection/compression-manifest.json")
  ) {
    throw new Error("raw projection receipt duplicate is forbidden");
  }
  [...actualPaths].sort(compareText).forEach((path, index) => {
    assertGeneratedPathPrivacy(path, privacyContract, "deployment-member", index);
  });
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
    if (member.bytes > MAX_DEPLOYMENT_MEMBER_BYTES) {
      throw new Error(`deployment member receipt is malformed: ${member.path}`);
    }
    const bytes = await readStableBoundedBytes(
      join(distRoot, ...member.path.split("/")),
      "deployment member",
      Math.min(member.bytes, MAX_DEPLOYMENT_MEMBER_BYTES),
      readHooks.member,
    );
    if (bytes.byteLength !== member.bytes || sha256(bytes) !== member.sha256) {
      throw new Error(`deployment member byte/hash mismatch: ${member.path}`);
    }
  });
  const source = await readCleanGitSource(repoRoot);
  const referenceSource = await readReferenceSource(
    distRoot,
    repoRoot,
    source.commit,
    readHooks,
  );
  assertExactSourceJoin(source, referenceSource);
  const expected = createManifest({ source, referenceSource, members: receipt.members });
  if (!canonicalBytes(receipt).equals(canonicalBytes(expected))) {
    throw new Error("deployment manifest does not match its recomputed source-bound receipt");
  }
  return receipt;
}

function isMissingFileError(error) {
  return Boolean(error && typeof error === "object" && error.code === "ENOENT");
}

async function createOwnedPublication(path, bytes, hooks = {}) {
  let handle;
  let identity;
  let failure;
  try {
    handle = await open(path, "wx");
    const before = await handle.stat();
    if (!before.isFile()) {
      throw new Error("deployment manifest temporary publication is inconsistent");
    }
    identity = { dev: before.dev, ino: before.ino };
    await handle.writeFile(bytes);
    await handle.sync();
    const info = await handle.stat();
    if (
      !info.isFile() ||
      !sameFileIdentity(info, identity) ||
      info.size !== bytes.byteLength
    ) {
      throw new Error("deployment manifest temporary publication is inconsistent");
    }
  } catch (error) {
    failure =
      error instanceof Error &&
      error.message === "deployment manifest temporary publication is inconsistent"
        ? error
        : new Error("deployment manifest temporary publication could not be created");
  }
  if (handle) {
    try {
      await handle.close();
    } catch {
      failure ??= new Error("deployment manifest temporary publication could not be created");
    }
  }
  if (failure) {
    if (identity && !await removeOwnedPathByIdentity(path, identity, hooks)) {
      throw new Error("deployment manifest temporary publication cleanup refused");
    }
    throw failure;
  }
  return { bytes, identity, path };
}

async function removeOwnedPathByIdentity(path, identity, hooks = {}) {
  let info;
  try {
    info = await (hooks.statOwnedPath ?? lstat)(path);
  } catch (error) {
    return isMissingFileError(error);
  }
  if (
    !info.isFile() ||
    info.isSymbolicLink() ||
    !sameFileIdentity(info, identity)
  ) {
    return false;
  }
  try {
    await unlink(path);
    return true;
  } catch {
    return false;
  }
}

async function removeOwnedPublication(publication, label, hooks = {}) {
  if (!publication) return true;
  let before;
  try {
    before = await (hooks.statOwnedPath ?? lstat)(publication.path);
  } catch (error) {
    return isMissingFileError(error);
  }
  if (
    !before.isFile() ||
    before.isSymbolicLink() ||
    !sameFileIdentity(before, publication.identity) ||
    before.size !== publication.bytes.byteLength
  ) {
    return false;
  }
  let observed;
  try {
    observed = await readStableBoundedBytes(
      publication.path,
      label,
      publication.bytes.byteLength,
    );
  } catch {
    return false;
  }
  if (!observed.equals(publication.bytes)) return false;
  let after;
  try {
    after = await (hooks.statOwnedPath ?? lstat)(publication.path);
  } catch (error) {
    return isMissingFileError(error);
  }
  if (
    !after.isFile() ||
    after.isSymbolicLink() ||
    !sameFileIdentity(after, publication.identity) ||
    after.size !== publication.bytes.byteLength
  ) {
    return false;
  }
  try {
    await unlink(publication.path);
    return true;
  } catch {
    return false;
  }
}

async function publishManifestNoClobber(temporary, manifestPath) {
  try {
    await link(temporary.path, manifestPath);
  } catch (error) {
    if (error && typeof error === "object" && error.code === "EEXIST") {
      throw new Error(
        "deployment manifest publication lost a concurrent no-clobber race",
      );
    }
    throw new Error("deployment manifest could not be atomically published");
  }
  return { ...temporary, path: manifestPath };
}

async function buildDeploymentManifestInternal(
  { distDir = "dist", repoRoot = ".." } = {},
  hooks = {},
) {
  const distRoot = resolve(distDir);
  const manifestPath = join(distRoot, MANIFEST_NAME);
  await assertDirectory(distRoot, "deployment root");
  const initialFiles = await walkRegularFiles(distRoot);
  if (initialFiles.some((path) => [MANIFEST_NAME, MANIFEST_SOURCE_NAME].includes(relativePosix(distRoot, path)))) {
    throw new Error(`${MANIFEST_NAME} already exists; refusing to overwrite a prior outer receipt`);
  }
  const source = await readCleanGitSource(repoRoot);
  const referenceSource = await readReferenceSource(
    distRoot,
    repoRoot,
    source.commit,
    hooks.readHooks,
  );
  assertExactSourceJoin(source, referenceSource);
  const members = await censusMembers(distRoot, repoRoot, hooks.readHooks);
  const finalSource = await readCleanGitSource(repoRoot);
  if (stableJson(source) !== stableJson(finalSource)) {
    throw new Error("tracked Git source changed while deployment members were being hashed");
  }
  const receipt = createManifest({ source, referenceSource, members });
  const receiptBytes = canonicalBytes(receipt);
  const receiptRepresentation = await deterministicGzip(receiptBytes);
  await expandReceiptBoundGzip(receiptRepresentation, {
    label: "deployment manifest",
    maximumCompressedBytes: MAX_GZIP_RECEIPT_BYTES,
    maximumExpandedBytes: MAX_JSON_RECEIPT_BYTES,
  });
  if (receipt.totalBytes + receiptRepresentation.byteLength > MAX_DEPLOYMENT_BYTES) {
    throw new Error("deployment bundle exceeds the Sites expanded limit");
  }
  const temporaryPath = join(
    dirname(distRoot),
    `.${basename(distRoot)}.${MANIFEST_NAME}.${randomUUID()}.tmp`,
  );
  let temporary;
  let published;
  try {
    temporary = await createOwnedPublication(temporaryPath, receiptRepresentation, hooks);
    await hooks.beforePublish?.();
    published = await publishManifestNoClobber(temporary, manifestPath);
    if (!await removeOwnedPublication(temporary, "deployment manifest temporary publication", hooks)) {
      throw new Error("deployment manifest temporary publication cleanup refused");
    }
    temporary = null;
    await verifyDeploymentManifestReceipt(
      { distDir: distRoot, repoRoot },
      hooks.readHooks,
    );
    return receipt;
  } catch (error) {
    let cleanupFailure = false;
    if (
      published &&
      !await removeOwnedPublication(published, "deployment manifest owned publication", hooks)
    ) {
      cleanupFailure = true;
    }
    if (
      temporary &&
      !await removeOwnedPublication(temporary, "deployment manifest temporary publication", hooks)
    ) {
      cleanupFailure = true;
    }
    if (cleanupFailure) {
      throw new Error("deployment manifest failure could not remove only its owned publication");
    }
    throw error;
  }
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
  if (keys.some((key) => typeof key !== "string" || !PUBLIC_OPTIONS_KEYS.has(key))) {
    throw new Error("invalid options");
  }
  const descriptors = Object.getOwnPropertyDescriptors(options);
  if (
    Object.values(descriptors).some(
      (descriptor) => !("value" in descriptor) || descriptor.enumerable !== true,
    )
  ) {
    throw new Error("invalid options");
  }
  const result = {};
  for (const key of PUBLIC_OPTIONS_KEYS) {
    const value = descriptors[key]?.value;
    if (value !== undefined && typeof value !== "string") throw new Error("invalid options");
    if (value !== undefined) result[key] = value;
  }
  return result;
}

export async function verifyDeploymentManifest(options = {}) {
  try {
    return await verifyDeploymentManifestReceipt(snapshotPublicOptions(options));
  } catch {
    throw new Error("deployment manifest verification failed");
  }
}

export async function buildDeploymentManifest(options = {}) {
  try {
    return await buildDeploymentManifestInternal(snapshotPublicOptions(options));
  } catch {
    throw new Error("deployment manifest build failed");
  }
}

export const deploymentManifestTestOnly = Object.freeze({
  buildDeploymentManifestWithHooks: buildDeploymentManifestInternal,
  verifyDeploymentManifestWithHooks: verifyDeploymentManifestReceipt,
  readJsonObject,
  readGzipJsonObject,
});

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
