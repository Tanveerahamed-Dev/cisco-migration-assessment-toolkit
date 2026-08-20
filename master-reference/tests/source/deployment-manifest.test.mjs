import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import {
  appendFile,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rename,
  rm,
  unlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import { dirname, join } from "node:path";
import { promisify } from "node:util";
import { constants, crc32, deflateRawSync, gunzipSync } from "node:zlib";
import test from "node:test";
import { CANONICAL_GZIP_HEADER_BYTES } from "../../build/gzip-contract.js";
import {
  buildDeploymentManifest as buildDeploymentManifestPublic,
  deploymentManifestTestOnly,
  verifyDeploymentManifest as verifyDeploymentManifestPublic,
} from "../../build/deployment-manifest.mjs";
import {
  prepareDeployment as prepareDeploymentPublic,
  prepareDeploymentTestOnly,
} from "../../build/prepare-deployment.mjs";
import {
  deterministicGzip as deterministicGzipPublic,
  expandReceiptBoundGzip,
  RECEIPT_BOUND_GZIP_ALGORITHM,
} from "../../build/deterministic-gzip.mjs";

const execFileAsync = promisify(execFile);
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const compareText = (left, right) => (left < right ? -1 : left > right ? 1 : 0);
const PROJECTION_MANIFEST_NAME = "projection-manifest.json.gz";
const COMPRESSION_MANIFEST_NAME = "compression-manifest.json.gz";
const DEPLOYMENT_MANIFEST_NAME = "deployment-manifest.json.gz";
const PROJECTION_DIRECTORY = "client/atlas-projection";
const PROJECTION_MANIFEST_REPRESENTATION = `${PROJECTION_DIRECTORY}/${PROJECTION_MANIFEST_NAME}`;
const PROJECTION_MEMBER_AUTHORITY = `${PROJECTION_DIRECTORY}/${COMPRESSION_MANIFEST_NAME}`;
const buildDeploymentManifest = (options) =>
  deploymentManifestTestOnly.buildDeploymentManifestWithHooks(options);
const verifyDeploymentManifest = (options) =>
  deploymentManifestTestOnly.verifyDeploymentManifestWithHooks(options);
const prepareDeployment = (options) =>
  prepareDeploymentTestOnly.prepareDeploymentInternal(options);
const collapsedAsciiIdentity = (value) => value
  .normalize("NFKC")
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, "_")
  .replace(/^_+|_+$/g, "");
const stableJson = (value) => {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort(compareText).map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
};

function deterministicGzip(
  original,
  level = constants.Z_BEST_COMPRESSION,
  { memLevel = 8, strategy = constants.Z_FILTERED } = {},
) {
  const deflated = deflateRawSync(original, {
    level,
    memLevel,
    strategy,
  });
  const trailer = Buffer.alloc(8);
  trailer.writeUInt32LE(crc32(original) >>> 0, 0);
  trailer.writeUInt32LE(original.byteLength >>> 0, 4);
  return Buffer.concat([Buffer.from(CANONICAL_GZIP_HEADER_BYTES), deflated, trailer]);
}

const canonicalJsonBytes = (value) => Buffer.from(`${stableJson(value)}\n`);
const readGzipJson = async (path) => JSON.parse(gunzipSync(await readFile(path)));

async function writeGzipJson(path, value) {
  const raw = canonicalJsonBytes(value);
  const representation = deterministicGzip(raw);
  await writeFile(path, representation);
  return { raw, representation };
}

async function writeInnerReceipts(projectionRoot, projection, compression) {
  const projectionResult = await writeGzipJson(
    join(projectionRoot, PROJECTION_MANIFEST_NAME),
    projection,
  );
  compression.projectionManifest = {
    path: "projection-manifest.json",
    representationPath: PROJECTION_MANIFEST_NAME,
    contentEncoding: "gzip",
    bytes: projectionResult.raw.byteLength,
    sha256: sha256(projectionResult.raw),
    representationBytes: projectionResult.representation.byteLength,
    representationSha256: sha256(projectionResult.representation),
  };
  const compressionResult = await writeGzipJson(
    join(projectionRoot, COMPRESSION_MANIFEST_NAME),
    compression,
  );
  return { compressionResult, projectionResult };
}

async function git(repo, ...args) {
  const { stdout } = await execFileAsync("git", args, { cwd: repo, encoding: "utf8" });
  return stdout.trim();
}

async function writeBytes(path, bytes) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, bytes);
}

async function initializeFixture(root) {
  const repo = join(root, "repo");
  await mkdir(repo, { recursive: true });
  await git(repo, "init", "--quiet");
  await git(repo, "config", "user.email", "atlas-tests@example.invalid");
  await git(repo, "config", "user.name", "Atlas Tests");
  await writeFile(join(repo, "tracked.txt"), "tracked source\n");
  await git(repo, "add", "tracked.txt");
  await git(repo, "commit", "--quiet", "-m", "fixture source");
  const commit = await git(repo, "rev-parse", "HEAD");
  const treeOid = await git(repo, "rev-parse", "HEAD^{tree}");
  return { repo, commit, treeOid };
}

async function writeDist(
  repo,
  name,
  {
    projectionModule = Buffer.from("export const identity = 'Atlas';\n"),
    projectionModulePath = "identity.mjs",
    graphSensitive = false,
    graphModuleKind = "shard",
  } = {},
) {
  const dist = join(repo, name);
  const projectionRoot = join(dist, "client", "atlas-projection");
  const sourceCommit = await git(repo, "rev-parse", "HEAD");
  const sourceTreeDigest = "c".repeat(64);
  const modulePath = projectionModulePath;
  const compressedPath = `${modulePath}.gz`;
  const compressedModule = deterministicGzip(projectionModule);
  const projection = {
    schemaVersion: "1.1.0",
    sourceCommit,
    sourceTreeDigest,
  };
  const descriptor = {
    bytes: projectionModule.byteLength,
    sha256: sha256(projectionModule),
  };
  if (graphSensitive) {
    projection.graph = graphModuleKind === "summary"
      ? { summary: { ...descriptor, module: modulePath } }
      : { shards: [{ ...descriptor, module: modulePath }] };
  } else {
    projection.identity = { ...descriptor, path: modulePath };
  }
  const projectionBytes = Buffer.from(`${stableJson(projection)}\n`);
  const compression = {
    schemaVersion: "1.1.0",
    algorithm: RECEIPT_BOUND_GZIP_ALGORITHM,
    producerRuntime: {
      node: process.versions.node,
      zlib: process.versions.zlib,
    },
    sourceCommit,
    sourceTreeDigest,
    projectionSchemaVersion: projection.schemaVersion,
    projectionManifest: {
      path: "projection-manifest.json",
      representationPath: PROJECTION_MANIFEST_NAME,
      contentEncoding: "gzip",
      bytes: 0,
      sha256: "0".repeat(64),
      representationBytes: 0,
      representationSha256: "0".repeat(64),
    },
    declarationCount: 1,
    moduleCount: 1,
    originalBytes: projectionModule.byteLength,
    compressedBytes: compressedModule.byteLength,
    modules: [
      {
        path: modulePath,
        compressedPath,
        originalBytes: projectionModule.byteLength,
        originalSha256: sha256(projectionModule),
        compressedBytes: compressedModule.byteLength,
        compressedSha256: sha256(compressedModule),
      },
    ],
  };
  const projectionResult = {
    raw: projectionBytes,
    representation: deterministicGzip(projectionBytes),
  };
  compression.projectionManifest = {
    path: "projection-manifest.json",
    representationPath: PROJECTION_MANIFEST_NAME,
    contentEncoding: "gzip",
    bytes: projectionResult.raw.byteLength,
    sha256: sha256(projectionResult.raw),
    representationBytes: projectionResult.representation.byteLength,
    representationSha256: sha256(projectionResult.representation),
  };
  const compressionBytes = canonicalJsonBytes(compression);
  const compressionRepresentation = deterministicGzip(compressionBytes);
  const members = new Map([
    ["index.html", Buffer.from("<!doctype html><title>Atlas</title>\n")],
    ["client/app.js", Buffer.from("export const atlas = true;\n")],
    ["client/app.css", Buffer.from(":root{color-scheme:dark}\n")],
    [`client/atlas-projection/${PROJECTION_MANIFEST_NAME}`, projectionResult.representation],
    [`client/atlas-projection/${COMPRESSION_MANIFEST_NAME}`, compressionRepresentation],
    [`client/atlas-projection/${compressedPath}`, compressedModule],
  ]);
  for (const [path, bytes] of members) {
    await writeBytes(join(dist, ...path.split("/")), bytes);
  }
  return { dist, members, projectionRoot };
}

async function replaceReceiptedProjectionModule(dist, projectionModule) {
  const projectionRoot = join(dist, "client", "atlas-projection");
  const projectionPath = join(projectionRoot, PROJECTION_MANIFEST_NAME);
  const compressionPath = join(projectionRoot, COMPRESSION_MANIFEST_NAME);
  const compressedPath = join(projectionRoot, "identity.mjs.gz");
  const projection = await readGzipJson(projectionPath);
  projection.identity.bytes = projectionModule.byteLength;
  projection.identity.sha256 = sha256(projectionModule);
  const compressedModule = deterministicGzip(projectionModule);
  const compression = await readGzipJson(compressionPath);
  compression.originalBytes = projectionModule.byteLength;
  compression.compressedBytes = compressedModule.byteLength;
  compression.modules[0] = {
    path: "identity.mjs",
    compressedPath: "identity.mjs.gz",
    originalBytes: projectionModule.byteLength,
    originalSha256: sha256(projectionModule),
    compressedBytes: compressedModule.byteLength,
    compressedSha256: sha256(compressedModule),
  };
  await writeFile(compressedPath, compressedModule);
  await writeInnerReceipts(projectionRoot, projection, compression);
}

async function addReceiptedProjectionMetadata(dist, key, value) {
  const projectionRoot = join(dist, "client", "atlas-projection");
  const projectionPath = join(projectionRoot, PROJECTION_MANIFEST_NAME);
  const compressionPath = join(projectionRoot, COMPRESSION_MANIFEST_NAME);
  const projection = await readGzipJson(projectionPath);
  projection[key] = value;
  const compression = await readGzipJson(compressionPath);
  await writeInnerReceipts(projectionRoot, projection, compression);
}

async function addReceiptedProjectionModule(
  dist,
  modulePath = "alpha.mjs",
  moduleBytes = Buffer.from("export const alpha = true;\n"),
) {
  const projectionRoot = join(dist, "client", "atlas-projection");
  const projection = await readGzipJson(
    join(projectionRoot, PROJECTION_MANIFEST_NAME),
  );
  const compression = await readGzipJson(
    join(projectionRoot, COMPRESSION_MANIFEST_NAME),
  );
  const compressedPath = `${modulePath}.gz`;
  const compressedBytes = deterministicGzip(moduleBytes);
  projection.secondary = {
    path: modulePath,
    bytes: moduleBytes.byteLength,
    sha256: sha256(moduleBytes),
  };
  compression.modules.push({
    path: modulePath,
    compressedPath,
    originalBytes: moduleBytes.byteLength,
    originalSha256: sha256(moduleBytes),
    compressedBytes: compressedBytes.byteLength,
    compressedSha256: sha256(compressedBytes),
  });
  compression.modules.sort((left, right) => compareText(left.path, right.path));
  compression.declarationCount += 1;
  compression.moduleCount += 1;
  compression.originalBytes += moduleBytes.byteLength;
  compression.compressedBytes += compressedBytes.byteLength;
  await writeBytes(join(projectionRoot, ...compressedPath.split("/")), compressedBytes);
  await writeInnerReceipts(projectionRoot, projection, compression);
}

async function replaceReceiptedProjectionModulePath(dist, modulePath) {
  const projectionRoot = join(dist, "client", "atlas-projection");
  const projectionPath = join(projectionRoot, PROJECTION_MANIFEST_NAME);
  const compressionPath = join(projectionRoot, COMPRESSION_MANIFEST_NAME);
  const oldCompressedPath = "identity.mjs.gz";
  const newCompressedPath = `${modulePath}.gz`;
  const projection = await readGzipJson(projectionPath);
  projection.identity.path = modulePath;
  const compression = await readGzipJson(compressionPath);
  compression.modules[0].path = modulePath;
  compression.modules[0].compressedPath = newCompressedPath;
  await mkdir(dirname(join(projectionRoot, ...newCompressedPath.split("/"))), { recursive: true });
  await rename(
    join(projectionRoot, oldCompressedPath),
    join(projectionRoot, ...newCompressedPath.split("/")),
  );
  await writeInnerReceipts(projectionRoot, projection, compression);
  return refreshOuterDeploymentReceipt(dist);
}

function projectionMemberLedger(compression) {
  return compression.modules.map((record) => ({
    path: `${PROJECTION_DIRECTORY}/${record.compressedPath}`,
    bytes: record.compressedBytes,
    sha256: record.compressedSha256,
  }));
}

function projectionMembersSummary(ledger) {
  return {
    authorityRepresentationPath: PROJECTION_MEMBER_AUTHORITY,
    memberCount: ledger.length,
    totalBytes: ledger.reduce((total, member) => total + member.bytes, 0),
    membersDigest: sha256(canonicalJsonBytes(ledger)),
  };
}

function rechainOuterBundleDigest(receipt) {
  const payload = {
    schemaVersion: receipt.schemaVersion,
    recordType: receipt.recordType,
    source: receipt.source,
    referenceSource: receipt.referenceSource,
    memberCount: receipt.memberCount,
    totalBytes: receipt.totalBytes,
    members: receipt.members,
    membersDigest: receipt.membersDigest,
    projectionMembers: receipt.projectionMembers,
  };
  receipt.bundleDigest = sha256(canonicalJsonBytes(payload));
}

async function refreshOuterDeploymentReceipt(dist) {
  const manifestPath = join(dist, DEPLOYMENT_MANIFEST_NAME);
  const receipt = await readGzipJson(manifestPath);
  for (const member of receipt.members) {
    const bytes = await readFile(join(dist, ...member.path.split("/")));
    member.bytes = bytes.byteLength;
    member.sha256 = sha256(bytes);
  }
  const projectionBytes = await readFile(
    join(dist, "client", "atlas-projection", PROJECTION_MANIFEST_NAME),
  );
  const compressionBytes = await readFile(
    join(dist, "client", "atlas-projection", COMPRESSION_MANIFEST_NAME),
  );
  const compression = JSON.parse(gunzipSync(compressionBytes));
  const projectionLedger = projectionMemberLedger(compression);
  const reconstructedMembers = [...receipt.members, ...projectionLedger]
    .sort((left, right) => compareText(left.path, right.path));
  receipt.referenceSource.projectionManifestSha256 = sha256(gunzipSync(projectionBytes));
  receipt.referenceSource.compressionManifestSha256 = sha256(gunzipSync(compressionBytes));
  receipt.projectionMembers = projectionMembersSummary(projectionLedger);
  receipt.memberCount = reconstructedMembers.length;
  receipt.totalBytes = reconstructedMembers.reduce(
    (total, member) => total + member.bytes,
    0,
  );
  receipt.membersDigest = sha256(canonicalJsonBytes(reconstructedMembers));
  rechainOuterBundleDigest(receipt);
  const manifestBytes = deterministicGzip(canonicalJsonBytes(receipt));
  await writeFile(manifestPath, manifestBytes);
  return manifestBytes;
}

async function addOuterReceiptMembers(dist, paths) {
  const manifestPath = join(dist, DEPLOYMENT_MANIFEST_NAME);
  const receipt = await readGzipJson(manifestPath);
  for (const path of paths) {
    const bytes = await readFile(join(dist, ...path.split("/")));
    receipt.members.push({ path, bytes: bytes.byteLength, sha256: sha256(bytes) });
  }
  receipt.members.sort((left, right) => compareText(left.path, right.path));
  await writeFile(manifestPath, deterministicGzip(canonicalJsonBytes(receipt)));
  return refreshOuterDeploymentReceipt(dist);
}

async function listRegularFiles(root, prefix = "") {
  const files = [];
  const entries = await readdir(root, { withFileTypes: true });
  for (const entry of entries) {
    const path = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) files.push(...await listRegularFiles(join(root, entry.name), path));
    else if (entry.isFile()) files.push(path);
  }
  return files.sort(compareText);
}

test("outer deployment receipt is deterministic, exact-source bound, and compactly covers every other file", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-manifest-"));
  try {
    const fixture = await initializeFixture(scratch);
    const first = await writeDist(fixture.repo, "dist-first");
    const second = await writeDist(fixture.repo, "dist-second");
    const receiptA = await buildDeploymentManifestPublic({
      distDir: first.dist,
      repoRoot: fixture.repo,
    });
    const receiptB = await buildDeploymentManifest({ distDir: second.dist, repoRoot: fixture.repo });
    assert.deepEqual(
      await readFile(join(first.dist, DEPLOYMENT_MANIFEST_NAME)),
      await readFile(join(second.dist, DEPLOYMENT_MANIFEST_NAME)),
    );
    assert.equal(receiptA.schemaVersion, "1.2.0");
    assert.equal(receiptA.recordType, "atlas_deployment_bundle");
    assert.equal(receiptA.source.commit, fixture.commit);
    assert.equal(receiptA.source.treeOid, fixture.treeOid);
    assert.equal(receiptA.source.trackedTreeState, "clean");
    assert.equal(receiptA.referenceSource.commit, fixture.commit);
    assert.equal(receiptA.manifestRule.path, "deployment-manifest.json");
    assert.equal(receiptA.manifestRule.representationPath, DEPLOYMENT_MANIFEST_NAME);
    assert.equal(receiptA.manifestRule.contentEncoding, "gzip");
    assert.equal(receiptA.manifestRule.selfHash, false);
    assert.ok(!receiptA.members.some((member) => ["deployment-manifest.json", DEPLOYMENT_MANIFEST_NAME].includes(member.path)));
    assert.deepEqual(
      [...(await readFile(join(first.dist, DEPLOYMENT_MANIFEST_NAME))).subarray(
        0,
        CANONICAL_GZIP_HEADER_BYTES.length,
      )],
      CANONICAL_GZIP_HEADER_BYTES,
    );
    await assert.rejects(readFile(join(first.dist, "deployment-manifest.json")), /ENOENT/);
    await assert.rejects(
      readFile(join(first.projectionRoot, "projection-manifest.json")),
      /ENOENT/,
    );
    await assert.rejects(
      readFile(join(first.projectionRoot, "compression-manifest.json")),
      /ENOENT/,
    );
    const actualMembers = (await listRegularFiles(first.dist))
      .filter((path) => path !== DEPLOYMENT_MANIFEST_NAME);
    const compression = await readGzipJson(
      join(first.projectionRoot, COMPRESSION_MANIFEST_NAME),
    );
    const projectionLedger = projectionMemberLedger(compression);
    const projectionPaths = new Set(projectionLedger.map((member) => member.path));
    assert.deepEqual(
      receiptA.members.map((member) => member.path),
      actualMembers.filter((path) => !projectionPaths.has(path)),
    );
    assert.deepEqual(receiptA.projectionMembers, projectionMembersSummary(projectionLedger));
    assert.equal(receiptA.members.some((member) => member.path.endsWith(".mjs.gz")), false);
    assert.ok(receiptA.members.some((member) => member.path === PROJECTION_MEMBER_AUTHORITY));
    assert.ok(receiptA.members.some(
      (member) => member.path === PROJECTION_MANIFEST_REPRESENTATION,
    ));
    assert.deepEqual(
      [...receiptA.members, ...projectionLedger]
        .sort((left, right) => compareText(left.path, right.path))
        .map((member) => member.path),
      actualMembers,
    );
    assert.equal(receiptA.memberCount, actualMembers.length);
    assert.deepEqual(receiptB, receiptA);
    assert.deepEqual(
      await verifyDeploymentManifestPublic({ distDir: first.dist, repoRoot: fixture.repo }),
      receiptA,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("projection member summary rejects hostile shape and a fully rechained forged ledger", async (context) => {
  const marker = "private-projection-summary-sentinel";
  for (const [name, mutate, expected] of [
    [
      "extra summary key",
      async (receipt) => {
        receipt.projectionMembers.EvilKey = marker;
        rechainOuterBundleDigest(receipt);
      },
      "deployment projection member summary is malformed",
    ],
    [
      "forged projection ledger",
      async (receipt, deployment) => {
        const compression = await readGzipJson(
          join(deployment.projectionRoot, COMPRESSION_MANIFEST_NAME),
        );
        const forgedLedger = projectionMemberLedger(compression).map((member, index) => ({
          ...member,
          sha256: index === 0
            ? `${member.sha256.startsWith("0") ? "1" : "0"}${member.sha256.slice(1)}`
            : member.sha256,
        }));
        receipt.projectionMembers = projectionMembersSummary(forgedLedger);
        const forgedUnion = [...receipt.members, ...forgedLedger]
          .sort((left, right) => compareText(left.path, right.path));
        receipt.memberCount = forgedUnion.length;
        receipt.totalBytes = forgedUnion.reduce((total, member) => total + member.bytes, 0);
        receipt.membersDigest = sha256(canonicalJsonBytes(forgedUnion));
        rechainOuterBundleDigest(receipt);
      },
      "deployment projection member summary does not match the fully validated compression manifest",
    ],
  ]) {
    await context.test(name, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-summary-hostile-"));
      try {
        const fixture = await initializeFixture(scratch);
        const deployment = await writeDist(fixture.repo, "dist");
        await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
        const manifestPath = join(deployment.dist, DEPLOYMENT_MANIFEST_NAME);
        const receipt = await readGzipJson(manifestPath);
        await mutate(receipt, deployment);
        const manifestBytes = deterministicGzip(canonicalJsonBytes(receipt));
        await writeFile(manifestPath, manifestBytes);
        let failure;
        try {
          await verifyDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
        } catch (error) {
          failure = error;
        }
        assert.ok(failure instanceof Error);
        assert.equal(failure.message, expected);
        assert.equal(failure.stack.includes(marker), false);
        assert.deepEqual(await readFile(manifestPath), manifestBytes);
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});

test("compact member ledgers reject projection overlap, order, and authority aliases", async (context) => {
  for (const [name, mutate, expected] of [
    [
      "projection overlap",
      async (receipt, deployment) => {
        const compression = await readGzipJson(
          join(deployment.projectionRoot, COMPRESSION_MANIFEST_NAME),
        );
        const ledger = projectionMemberLedger(compression);
        receipt.members.push({ ...ledger[0] });
        receipt.members.sort((left, right) => compareText(left.path, right.path));
        const overlappingUnion = [...receipt.members, ...ledger]
          .sort((left, right) => compareText(left.path, right.path));
        receipt.memberCount = overlappingUnion.length;
        receipt.totalBytes = overlappingUnion.reduce(
          (total, member) => total + member.bytes,
          0,
        );
        receipt.membersDigest = sha256(canonicalJsonBytes(overlappingUnion));
        rechainOuterBundleDigest(receipt);
      },
      "deployment direct and projection member ledgers overlap",
    ],
    [
      "direct order",
      async (receipt) => {
        receipt.members.reverse();
        rechainOuterBundleDigest(receipt);
      },
      "deployment manifest direct member paths violate the compact sorted census rule",
    ],
    [
      "authority path case alias",
      async (receipt, deployment) => {
        const compression = await readGzipJson(
          join(deployment.projectionRoot, COMPRESSION_MANIFEST_NAME),
        );
        const ledger = projectionMemberLedger(compression);
        const aliasedPath = `${PROJECTION_DIRECTORY}/Compression-Manifest.json.gz`;
        const member = receipt.members.find(
          (candidate) => candidate.path === PROJECTION_MEMBER_AUTHORITY,
        );
        assert.ok(member);
        const temporaryPath = join(deployment.projectionRoot, "compression-authority.tmp");
        await rename(
          join(deployment.projectionRoot, COMPRESSION_MANIFEST_NAME),
          temporaryPath,
        );
        await rename(
          temporaryPath,
          join(deployment.dist, ...aliasedPath.split("/")),
        );
        member.path = aliasedPath;
        receipt.members.sort((left, right) => compareText(left.path, right.path));
        const aliasedUnion = [...receipt.members, ...ledger]
          .sort((left, right) => compareText(left.path, right.path));
        receipt.membersDigest = sha256(canonicalJsonBytes(aliasedUnion));
        rechainOuterBundleDigest(receipt);
      },
      "deployment manifest direct member paths violate the compact sorted census rule",
    ],
  ]) {
    await context.test(name, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-ledger-hostile-"));
      try {
        const fixture = await initializeFixture(scratch);
        const deployment = await writeDist(fixture.repo, "dist");
        await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
        const manifestPath = join(deployment.dist, DEPLOYMENT_MANIFEST_NAME);
        const receipt = await readGzipJson(manifestPath);
        await mutate(receipt, deployment);
        const manifestBytes = deterministicGzip(canonicalJsonBytes(receipt));
        await writeFile(manifestPath, manifestBytes);
        await assert.rejects(
          verifyDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo }),
          (error) => error instanceof Error && error.message === expected,
        );
        assert.deepEqual(await readFile(manifestPath), manifestBytes);
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});

test("compression authority rejects missing, extra, and noncanonical projection members", async (context) => {
  for (const [name, prepare, mutate, expected] of [
    [
      "missing",
      async () => {},
      async (deployment) => unlink(join(deployment.projectionRoot, "identity.mjs.gz")),
      /compressed projection deployment member census mismatch; missing=identity\.mjs\.gz; extra=none/,
    ],
    [
      "extra",
      async () => {},
      async (deployment) => writeFile(
        join(deployment.projectionRoot, "rogue.mjs.gz"),
        deterministicGzip(Buffer.from("export const rogue = true;\n")),
      ),
      /compressed projection deployment member census mismatch; missing=none; extra=rogue\.mjs\.gz/,
    ],
    [
      "order",
      async (deployment) => addReceiptedProjectionModule(deployment.dist),
      async (deployment) => {
        const projection = await readGzipJson(
          join(deployment.projectionRoot, PROJECTION_MANIFEST_NAME),
        );
        const compression = await readGzipJson(
          join(deployment.projectionRoot, COMPRESSION_MANIFEST_NAME),
        );
        compression.modules.reverse();
        await writeInnerReceipts(deployment.projectionRoot, projection, compression);
        await refreshOuterDeploymentReceipt(deployment.dist);
      },
      /compression module census or aggregate receipt is inconsistent/,
    ],
  ]) {
    await context.test(name, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-authority-hostile-"));
      try {
        const fixture = await initializeFixture(scratch);
        const deployment = await writeDist(fixture.repo, "dist");
        await prepare(deployment);
        await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
        await mutate(deployment);
        await assert.rejects(
          verifyDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo }),
          expected,
        );
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});

test("bounded JSON receipt reads reject deterministic replacement and growth races without disclosure", async (context) => {
  await context.test("replacement after path stat", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-json-swap-"));
    const receiptPath = join(scratch, "receipt.json");
    const displacedPath = join(scratch, "displaced.json");
    const marker = "private-swap-sentinel";
    const originalValue = "publicx-swap-sentinel";
    try {
      assert.equal(Buffer.byteLength(originalValue), Buffer.byteLength(marker));
      await writeFile(receiptPath, `{"value":${JSON.stringify(originalValue)}}\n`);
      let failure;
      try {
        await deploymentManifestTestOnly.readJsonObject(
          receiptPath,
          "test receipt",
          1024,
          {
            afterPathStat: async () => {
              await rename(receiptPath, displacedPath);
              await writeFile(receiptPath, `{"value":${JSON.stringify(marker)}}\n`);
            },
          },
        );
      } catch (error) {
        failure = error;
      }
      assert.ok(failure instanceof Error);
      assert.equal(failure.message, "test receipt bounded read failed");
      assert.equal(failure.stack.includes(marker), false);
      assert.equal(failure.cause, undefined);
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });

  await context.test("growth after handle stat", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-json-grow-"));
    const receiptPath = join(scratch, "receipt.json");
    const original = Buffer.from("{}\n");
    const marker = "private-growth-sentinel";
    try {
      await writeFile(receiptPath, original);
      let failure;
      try {
        await deploymentManifestTestOnly.readJsonObject(
          receiptPath,
          "test receipt",
          original.byteLength,
          {
            afterHandleStat: async () => appendFile(receiptPath, marker),
          },
        );
      } catch (error) {
        failure = error;
      }
      assert.ok(failure instanceof Error);
      assert.equal(
        failure.message,
        "test receipt bounded read failed",
      );
      assert.equal(failure.stack.includes(marker), false);
      assert.equal(failure.cause, undefined);
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });
});

test("receipt-bound gzip reads reject lossy, oversized, malformed, and unsafe representations", async (context) => {
  const marker = "private-gzip-receipt-sentinel";
  const cases = [
    {
      name: "noncanonical header",
      bytes: () => {
        const bytes = deterministicGzip(canonicalJsonBytes({ value: "public" }));
        bytes[4] = 1;
        return bytes;
      },
      maximumExpandedBytes: 1024,
      expected: "receipt-bound gzip verification failed",
    },
    {
      name: "concatenated canonical member",
      bytes: () => {
        const first = deterministicGzip(canonicalJsonBytes({ value: "public" }));
        return Buffer.concat([first, deterministicGzip(Buffer.from("second\n"))]);
      },
      maximumExpandedBytes: 1024,
      expected: "receipt-bound gzip verification failed",
    },
    {
      name: "second member with optional filename metadata",
      bytes: () => {
        const first = deterministicGzip(canonicalJsonBytes({ value: "public" }));
        const second = deterministicGzip(Buffer.from("second\n"));
        const namedHeader = Buffer.concat([
          Buffer.from([0x1f, 0x8b, 0x08, 0x08, 0, 0, 0, 0, 0x02, 0xff]),
          Buffer.from("private-name-sentinel\0"),
        ]);
        return Buffer.concat([first, namedHeader, second.subarray(10)]);
      },
      maximumExpandedBytes: 1024,
      expected: "receipt-bound gzip verification failed",
    },
    {
      name: "trailing bytes",
      bytes: () => Buffer.concat([
        deterministicGzip(canonicalJsonBytes({ value: "public" })),
        Buffer.from("private-trailing-sentinel"),
      ]),
      maximumExpandedBytes: 1024,
      expected: "receipt-bound gzip verification failed",
    },
    {
      name: "bad CRC trailer",
      bytes: () => {
        const bytes = deterministicGzip(canonicalJsonBytes({ value: "public" }));
        bytes[bytes.byteLength - 8] ^= 0xff;
        return bytes;
      },
      maximumExpandedBytes: 1024,
      expected: "receipt-bound gzip verification failed",
    },
    {
      name: "truncated member",
      bytes: () => {
        const bytes = deterministicGzip(canonicalJsonBytes({ value: marker }));
        return bytes.subarray(0, bytes.byteLength - 4);
      },
      maximumExpandedBytes: 1024,
      expected: "receipt-bound gzip verification failed",
    },
    {
      name: "expanded limit",
      bytes: () => deterministicGzip(canonicalJsonBytes({ value: marker.repeat(64) })),
      maximumExpandedBytes: 32,
      expected: "receipt-bound gzip verification failed",
    },
    {
      name: "malformed JSON",
      bytes: () => deterministicGzip(Buffer.from(`{${marker}\n`)),
      maximumExpandedBytes: 1024,
      expected: "test gzip receipt is not valid UTF-8 JSON",
    },
  ];
  for (const hostile of cases) {
    await context.test(hostile.name, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-gzip-receipt-"));
      const receiptPath = join(scratch, "receipt.json.gz");
      try {
        await writeFile(receiptPath, hostile.bytes());
        let failure;
        try {
          await deploymentManifestTestOnly.readGzipJsonObject(
            receiptPath,
            "test gzip receipt",
            hostile.maximumExpandedBytes,
          );
        } catch (error) {
          failure = error;
        }
        assert.ok(failure instanceof Error);
        assert.equal(failure.message, hostile.expected);
        assert.equal(failure.stack.includes(marker), false);
        assert.equal(failure.cause, undefined);
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});

test("public receipt-bound gzip verifier rejects hostile API values without disclosure", async (context) => {
  const raw = canonicalJsonBytes({ value: "public" });
  const representation = deterministicGzip(raw);
  const validOptions = {
    label: "test gzip receipt",
    maximumCompressedBytes: 1024,
    maximumExpandedBytes: 1024,
  };
  assert.deepEqual(await expandReceiptBoundGzip(representation, validOptions), raw);

  const marker = "private-options-sentinel";
  const accessorOptions = {};
  Object.defineProperties(accessorOptions, {
    label: {
      enumerable: true,
      get() {
        throw new Error(marker);
      },
    },
    maximumCompressedBytes: { enumerable: true, value: 1024 },
    maximumExpandedBytes: { enumerable: true, value: 1024 },
  });
  const cases = [
    ["null", null],
    ["scalar", 7],
    ["string scalar", marker],
    ["accessor", accessorOptions],
    ["string wrapper label", { ...validOptions, label: new String(marker) }],
    ["custom prototype", Object.assign(Object.create({ marker }), validOptions)],
    ["symbol key", { ...validOptions, [Symbol(marker)]: true }],
    [
      "prototype proxy trap",
      new Proxy({}, {
        getPrototypeOf() {
          throw new Error(marker);
        },
      }),
    ],
    [
      "descriptor proxy trap",
      new Proxy(validOptions, {
        getOwnPropertyDescriptor() {
          throw new Error(marker);
        },
      }),
    ],
  ];
  for (const [name, options] of cases) {
    await context.test(name, async () => {
      let failure;
      try {
        await expandReceiptBoundGzip(representation, options);
      } catch (error) {
        failure = error;
      }
      assert.ok(failure instanceof Error);
      assert.equal(failure.message, "receipt-bound gzip verification failed");
      assert.equal(failure.stack.includes(marker), false);
      assert.equal(failure.cause, undefined);
    });
  }
});

test("gzip helpers pin the filtered producer profile, snapshot bytes, and accept alternate deflate", async () => {
  assert.equal(
    RECEIPT_BOUND_GZIP_ALGORITHM,
    "gzip:deflate-raw:level-9:memlevel-8:strategy-filtered:mtime-0:os-255",
  );
  const original = Buffer.from("public immutable gzip input\n".repeat(128));
  const expected = Buffer.from(original);
  const compression = deterministicGzipPublic(original);
  original.fill(0x78);
  const productionRepresentation = await compression;
  assert.deepEqual(productionRepresentation, deterministicGzip(expected));
  assert.deepEqual(gunzipSync(productionRepresentation), expected);

  const profileInput = Buffer.from(
    `${Array.from({ length: 1000 }, (_, index) => JSON.stringify({
      path: `metadata/symbols/${String(index).padStart(5, "0")}-${(index * 2654435761 >>> 0).toString(16)}.mjs`,
      bytes: 1000 + (index % 997),
      sha256: index.toString(16).padStart(8, "0").repeat(8),
      tags: ["atlas", "projection", `group-${index % 37}`],
      value: "alpha beta gamma delta ".repeat(1 + (index % 7)),
    })).join("\n")}\n`,
  );
  const profileRepresentation = await deterministicGzipPublic(profileInput);
  assert.deepEqual(profileRepresentation, deterministicGzip(profileInput));
  assert.notDeepEqual(profileRepresentation, deterministicGzip(profileInput, 8));
  assert.notDeepEqual(
    profileRepresentation,
    deterministicGzip(profileInput, constants.Z_BEST_COMPRESSION, { memLevel: 9 }),
  );
  assert.notDeepEqual(
    profileRepresentation,
    deterministicGzip(profileInput, constants.Z_BEST_COMPRESSION, {
      strategy: constants.Z_DEFAULT_STRATEGY,
    }),
  );

  const alternateRepresentation = deterministicGzip(expected, constants.Z_BEST_SPEED);
  const representationSnapshot = Buffer.from(alternateRepresentation);
  const expansion = expandReceiptBoundGzip(alternateRepresentation, {
    label: "alternate deflate",
    maximumCompressedBytes: 64 * 1024,
    maximumExpandedBytes: 64 * 1024,
  });
  alternateRepresentation.fill(0x78);
  assert.deepEqual(await expansion, expected);
  assert.notDeepEqual(alternateRepresentation, representationSnapshot);
});

test("public deployment APIs reject hostile options without disclosure", async (context) => {
  const marker = "private-deployment-options-sentinel";
  const apis = [
    ["build", buildDeploymentManifestPublic, "deployment manifest build failed", ["distDir", "repoRoot"]],
    ["verify", verifyDeploymentManifestPublic, "deployment manifest verification failed", ["distDir", "repoRoot"]],
    ["prepare", prepareDeploymentPublic, "deployment preparation failed", ["distDir"]],
  ];
  for (const [apiName, api, expected, allowedKeys] of apis) {
    await context.test(apiName, async (apiContext) => {
      const accessor = {};
      Object.defineProperty(accessor, allowedKeys[0], {
        enumerable: true,
        get() {
          throw new Error(marker);
        },
      });
      const nonenumerable = {};
      Object.defineProperty(nonenumerable, allowedKeys[0], {
        enumerable: false,
        value: marker,
      });
      const cases = [
        ["null", null],
        ["scalar", 7],
        ["string scalar", marker],
        ["accessor", accessor],
        ["string wrapper", { [allowedKeys[0]]: new String(marker) }],
        ["custom prototype", Object.assign(Object.create({ marker }), { [allowedKeys[0]]: marker })],
        ["symbol key", { [Symbol(marker)]: true }],
        ["unknown key", { EvilKey: marker }],
        ["non-enumerable key", nonenumerable],
        [
          "prototype proxy trap",
          new Proxy({}, {
            getPrototypeOf() {
              throw new Error(marker);
            },
          }),
        ],
      ];
      for (const [caseName, options] of cases) {
        await apiContext.test(caseName, async () => {
          let failure;
          try {
            await api(options);
          } catch (error) {
            failure = error;
          }
          assert.ok(failure instanceof Error);
          assert.equal(failure.message, expected);
          assert.equal(failure.stack.includes(marker), false);
          assert.equal(failure.cause, undefined);
        });
      }
    });
  }
});

test("standalone verification remains portable across fully receipt-bound alternate deflate bytes", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-alt-deflate-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    const projectionPath = join(deployment.projectionRoot, PROJECTION_MANIFEST_NAME);
    const compressionPath = join(deployment.projectionRoot, COMPRESSION_MANIFEST_NAME);
    const modulePath = join(deployment.projectionRoot, "identity.mjs.gz");
    const projection = await readGzipJson(projectionPath);
    const compression = await readGzipJson(compressionPath);
    const original = gunzipSync(await readFile(modulePath));
    const alternate = deterministicGzip(original, constants.Z_BEST_SPEED);
    compression.producerRuntime = { node: "22.13.0", zlib: "1.2.13" };
    compression.modules[0].compressedBytes = alternate.byteLength;
    compression.modules[0].compressedSha256 = sha256(alternate);
    compression.compressedBytes = alternate.byteLength;
    await writeFile(modulePath, alternate);
    await writeInnerReceipts(deployment.projectionRoot, projection, compression);
    await refreshOuterDeploymentReceipt(deployment.dist);
    const receipt = await verifyDeploymentManifest({
      distDir: deployment.dist,
      repoRoot: fixture.repo,
    });
    assert.equal(receipt.memberCount, deployment.members.size);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("compression receipt exact shapes and algorithm reject self-receipted drift", async (context) => {
  for (const [name, mutate, expected] of [
    [
      "legacy generic algorithm",
      (compression) => {
        compression.algorithm = "gzip:deflate-raw:level-9:fixed-header:receipt-bound";
      },
      /compression module receipt is absent or inconsistent/,
    ],
    [
      "wrong memory level",
      (compression) => {
        compression.algorithm =
          "gzip:deflate-raw:level-9:memlevel-9:strategy-filtered:mtime-0:os-255";
      },
      /compression module receipt is absent or inconsistent/,
    ],
    [
      "wrong compression level",
      (compression) => {
        compression.algorithm =
          "gzip:deflate-raw:level-8:memlevel-8:strategy-filtered:mtime-0:os-255";
      },
      /compression module receipt is absent or inconsistent/,
    ],
    [
      "wrong strategy",
      (compression) => {
        compression.algorithm =
          "gzip:deflate-raw:level-9:memlevel-8:strategy-default:mtime-0:os-255";
      },
      /compression module receipt is absent or inconsistent/,
    ],
    [
      "algorithm scalar",
      (compression) => { compression.algorithm = 9; },
      /compression module receipt is absent or inconsistent/,
    ],
    [
      "wrong modification time",
      (compression) => {
        compression.algorithm =
          "gzip:deflate-raw:level-9:memlevel-8:strategy-filtered:mtime-1:os-255";
      },
      /compression module receipt is absent or inconsistent/,
    ],
    [
      "wrong operating system",
      (compression) => {
        compression.algorithm =
          "gzip:deflate-raw:level-9:memlevel-8:strategy-filtered:mtime-0:os-3";
      },
      /compression module receipt is absent or inconsistent/,
    ],
    [
      "algorithm suffix",
      (compression) => { compression.algorithm = `${RECEIPT_BOUND_GZIP_ALGORITHM}:EvilKey`; },
      /compression module receipt is absent or inconsistent/,
    ],
    [
      "top-level extra",
      (compression) => { compression.EvilKey = "private-shape-sentinel"; },
      /compression module receipt is absent or inconsistent/,
    ],
    [
      "runtime extra",
      (compression) => { compression.producerRuntime.EvilKey = "private-shape-sentinel"; },
      /compression receipt producer runtime is malformed/,
    ],
    [
      "projection receipt extra",
      (compression) => { compression.projectionManifest.EvilKey = "private-shape-sentinel"; },
      /compression module receipt is absent or inconsistent/,
    ],
    [
      "module record extra",
      (compression) => { compression.modules[0].EvilKey = "private-shape-sentinel"; },
      /compressed projection module receipt has an unexpected shape/,
    ],
  ]) {
    await context.test(name, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-shape-"));
      try {
        const fixture = await initializeFixture(scratch);
        const deployment = await writeDist(fixture.repo, "dist");
        await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
        const projection = await readGzipJson(
          join(deployment.projectionRoot, PROJECTION_MANIFEST_NAME),
        );
        const compression = await readGzipJson(
          join(deployment.projectionRoot, COMPRESSION_MANIFEST_NAME),
        );
        await writeInnerReceipts(deployment.projectionRoot, projection, compression);
        mutate(compression);
        await writeGzipJson(
          join(deployment.projectionRoot, COMPRESSION_MANIFEST_NAME),
          compression,
        );
        await refreshOuterDeploymentReceipt(deployment.dist);
        await assert.rejects(
          verifyDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo }),
          expected,
        );
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});

test("standalone verification forbids self-receipted raw inner receipt duplicates", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-raw-duplicates-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    const rawPaths = [
      "client/atlas-projection/projection-manifest.json",
      "client/atlas-projection/compression-manifest.json",
    ];
    for (const path of rawPaths) {
      const representation = await readFile(`${join(deployment.dist, ...path.split("/"))}.gz`);
      await writeFile(join(deployment.dist, ...path.split("/")), gunzipSync(representation));
    }
    await addOuterReceiptMembers(deployment.dist, rawPaths);
    await assert.rejects(
      verifyDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo }),
      /raw projection receipt duplicate is forbidden/,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("module and outer member reads reject same-handle replacement, growth, and hook failures", async (context) => {
  const cases = [
    {
      name: "module same-size replacement after path stat",
      hookKind: "module",
      hookName: "afterPathStat",
      target: (deployment) => join(deployment.projectionRoot, "identity.mjs.gz"),
      mutate: async (path, marker) => {
        const displaced = `${path}.displaced`;
        const original = await readFile(path);
        await rename(path, displaced);
        const replacement = Buffer.alloc(original.byteLength, 0x61);
        Buffer.from(marker).copy(replacement);
        await writeFile(path, replacement);
      },
      expected: "compressed projection module bounded read failed",
    },
    {
      name: "module growth after handle stat",
      hookKind: "module",
      hookName: "afterHandleStat",
      target: (deployment) => join(deployment.projectionRoot, "identity.mjs.gz"),
      mutate: (path, marker) => appendFile(path, marker),
      expected: "compressed projection module bounded read failed",
    },
    {
      name: "outer member same-size replacement after path stat",
      hookKind: "member",
      hookName: "afterPathStat",
      target: (deployment) => join(deployment.dist, "client", "app.js"),
      mutate: async (path, marker) => {
        const displaced = `${path}.displaced`;
        const original = await readFile(path);
        await rename(path, displaced);
        const replacement = Buffer.alloc(original.byteLength, 0x61);
        Buffer.from(marker).copy(replacement);
        await writeFile(path, replacement);
      },
      expected: "deployment member bounded read failed",
    },
    {
      name: "outer member hook exception",
      hookKind: "member",
      hookName: "afterPathStat",
      target: (deployment) => join(deployment.dist, "client", "app.js"),
      mutate: async (_path, marker) => { throw new Error(marker); },
      expected: "deployment member bounded read failed",
    },
  ];
  for (const race of cases) {
    await context.test(race.name, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-member-race-"));
      const marker = "private-member-race-sentinel";
      try {
        const fixture = await initializeFixture(scratch);
        const deployment = await writeDist(fixture.repo, "dist");
        await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
        const targetPath = race.target(deployment);
        let injected = false;
        let failure;
        try {
          await deploymentManifestTestOnly.verifyDeploymentManifestWithHooks(
            { distDir: deployment.dist, repoRoot: fixture.repo },
            {
              [race.hookKind]: {
                [race.hookName]: async ({ path }) => {
                  if (!injected && path === targetPath) {
                    injected = true;
                    await race.mutate(path, marker);
                  }
                },
              },
            },
          );
        } catch (error) {
          failure = error;
        }
        assert.equal(injected, true);
        assert.ok(failure instanceof Error);
        assert.equal(failure.message, race.expected);
        assert.equal(failure.stack.includes(marker), false);
        assert.equal(failure.cause, undefined);
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});

test("full-tree snapshots reject inter-phase projection and earlier-direct mutations", async (context) => {
  const cases = [
    {
      name: "projection module mutation during direct reads",
      createHooks: (deployment, marker, markInjected) => ({
        member: {
          afterPathStat: async ({ path }) => {
            if (path === join(deployment.dist, "client", "app.js")) {
              markInjected();
              await appendFile(
                join(deployment.projectionRoot, "identity.mjs.gz"),
                marker,
              );
            }
          },
        },
      }),
    },
    {
      name: "earlier direct member mutation during a later direct read",
      createHooks: (deployment, marker, markInjected) => {
        const earlierPath = join(deployment.dist, "client", "app.css");
        const laterPath = join(deployment.dist, "index.html");
        let releaseEarlierRead;
        const earlierRead = new Promise((resolveRead) => {
          releaseEarlierRead = resolveRead;
        });
        return {
          member: {
            afterPathStat: async ({ path }) => {
              if (path === laterPath) {
                await earlierRead;
                markInjected();
                await appendFile(earlierPath, marker);
              }
            },
            afterRead: async ({ path }) => {
              if (path === earlierPath) releaseEarlierRead();
            },
          },
        };
      },
    },
  ];
  for (const hostile of cases) {
    await context.test(hostile.name, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-inter-phase-"));
      const marker = "private-inter-phase-sentinel";
      try {
        const fixture = await initializeFixture(scratch);
        const deployment = await writeDist(fixture.repo, "dist");
        await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
        const manifestPath = join(deployment.dist, DEPLOYMENT_MANIFEST_NAME);
        const manifestBytes = await readFile(manifestPath);
        let injected = false;
        let failure;
        try {
          await deploymentManifestTestOnly.verifyDeploymentManifestWithHooks(
            { distDir: deployment.dist, repoRoot: fixture.repo },
            hostile.createHooks(deployment, marker, () => { injected = true; }),
          );
        } catch (error) {
          failure = error;
        }
        assert.equal(injected, true);
        assert.ok(failure instanceof Error);
        assert.equal(
          failure.message,
          "deployment physical tree changed during verification",
        );
        assert.equal(failure.stack.includes(marker), false);
        assert.equal(failure.cause, undefined);
        assert.deepEqual(await readFile(manifestPath), manifestBytes);
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});

test("concurrent builders publish exactly one no-clobber receipt and preserve the winner", { timeout: 15_000 }, async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-publish-race-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    let arrivals = 0;
    let releaseBarrier;
    let barrierTimer;
    const barrier = new Promise((resolveBarrier, rejectBarrier) => {
      releaseBarrier = () => {
        clearTimeout(barrierTimer);
        resolveBarrier();
      };
      barrierTimer = setTimeout(
        () => rejectBarrier(new Error("concurrent publication test barrier timed out")),
        10_000,
      );
      barrierTimer.unref();
    });
    const hooks = {
      beforePublish: async () => {
        arrivals += 1;
        if (arrivals === 2) releaseBarrier();
        await barrier;
      },
    };
    const options = { distDir: deployment.dist, repoRoot: fixture.repo };
    const results = await Promise.allSettled([
      deploymentManifestTestOnly.buildDeploymentManifestWithHooks(options, hooks),
      deploymentManifestTestOnly.buildDeploymentManifestWithHooks(options, hooks),
    ]);
    const fulfilled = results.filter((result) => result.status === "fulfilled");
    const rejected = results.filter((result) => result.status === "rejected");
    assert.equal(fulfilled.length, 1);
    assert.equal(rejected.length, 1);
    assert.ok(rejected[0].reason instanceof Error);
    assert.equal(
      rejected[0].reason.message,
      "deployment manifest publication lost a concurrent no-clobber race",
    );
    assert.equal(rejected[0].reason.cause, undefined);
    assert.deepEqual(
      await verifyDeploymentManifest(options),
      fulfilled[0].value,
    );
    const siblingNames = await readdir(dirname(deployment.dist));
    assert.equal(
      siblingNames.some(
        (name) => name.startsWith(".dist.deployment-manifest.json.gz.") && name.endsWith(".tmp"),
      ),
      false,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("owned publication cleanup refuses non-missing stat failures without disclosure", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-cleanup-stat-"));
  const marker = "private-cleanup-stat-sentinel";
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    let injected = false;
    let failure;
    try {
      await deploymentManifestTestOnly.buildDeploymentManifestWithHooks(
        { distDir: deployment.dist, repoRoot: fixture.repo },
        {
          statOwnedPath: async (path) => {
            if (!injected) {
              injected = true;
              const error = new Error(marker);
              error.code = "EACCES";
              throw error;
            }
            return lstat(path);
          },
        },
      );
    } catch (error) {
      failure = error;
    }
    assert.ok(failure instanceof Error);
    assert.equal(
      failure.message,
      "deployment manifest temporary publication cleanup refused",
    );
    assert.equal(failure.stack.includes(marker), false);
    assert.equal(failure.cause, undefined);
    await assert.rejects(
      readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)),
      /ENOENT/,
    );
    const siblingNames = await readdir(dirname(deployment.dist));
    assert.equal(
      siblingNames.some(
        (name) => name.startsWith(".dist.deployment-manifest.json.gz.") && name.endsWith(".tmp"),
      ),
      false,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("outer deployment verification detects extra, missing, and tampered members", async (context) => {
  for (const [name, mutate, expected] of [
    [
      "extra",
      async ({ dist }) => writeFile(join(dist, "extra.txt"), "not declared\n"),
      /deployment member census mismatch; missing=none; extra=extra\.txt/,
    ],
    [
      "missing",
      async ({ dist }) => unlink(join(dist, "client", "app.js")),
      /deployment member census mismatch; missing=client\/app\.js; extra=none/,
    ],
    [
      "tampered",
      async ({ dist }) => writeFile(join(dist, "client", "app.js"), "tampered\n"),
      /deployment member byte\/hash mismatch: client\/app\.js/,
    ],
  ]) {
    await context.test(name, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), `atlas-deployment-${name}-`));
      try {
        const fixture = await initializeFixture(scratch);
        const deployment = await writeDist(fixture.repo, "dist");
        await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
        await mutate(deployment);
        await assert.rejects(
          verifyDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo }),
          expected,
        );
        await readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME));
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});

test("outer deployment rejects self-receipted member extras and private raw metadata", async (context) => {
  await context.test("member extra key", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-member-shape-"));
    const marker = "private-outer-member-sentinel";
    try {
      const fixture = await initializeFixture(scratch);
      const deployment = await writeDist(fixture.repo, "dist");
      await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
      const manifestPath = join(deployment.dist, DEPLOYMENT_MANIFEST_NAME);
      const receipt = await readGzipJson(manifestPath);
      receipt.members[0].EvilKey = marker;
      await writeFile(manifestPath, deterministicGzip(canonicalJsonBytes(receipt)));
      await refreshOuterDeploymentReceipt(deployment.dist);
      let failure;
      try {
        await verifyDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
      } catch (error) {
        failure = error;
      }
      assert.ok(failure instanceof Error);
      assert.equal(failure.message, "deployment manifest members are malformed");
      assert.equal(failure.stack.includes(marker), false);
      assert.equal(failure.cause, undefined);
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });

  await context.test("private outer metadata", async () => {
    const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-outer-privacy-"));
    try {
      const fixture = await initializeFixture(scratch);
      const deployment = await writeDist(fixture.repo, "dist");
      await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
      const marker = collapsedAsciiIdentity(fixture.repo);
      const manifestPath = join(deployment.dist, DEPLOYMENT_MANIFEST_NAME);
      const receipt = await readGzipJson(manifestPath);
      receipt.EvilKey = marker;
      await writeFile(manifestPath, deterministicGzip(canonicalJsonBytes(receipt)));
      let failure;
      try {
        await verifyDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
      } catch (error) {
        failure = error;
      }
      assert.ok(failure instanceof Error);
      assert.match(
        failure.message,
        /^deployment generated-metadata privacy scan failed: rule=local_repository_collapsed_path; category=deployment-manifest$/,
      );
      assert.equal(failure.stack.includes(marker), false);
      assert.equal(failure.cause, undefined);
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });
});

test("outer deployment refuses a local identity inside a receipted gzip before manifest creation", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-nested-privacy-"));
  try {
    const fixture = await initializeFixture(scratch);
    const localMarker = collapsedAsciiIdentity(fixture.repo);
    const deployment = await writeDist(fixture.repo, "dist", {
      projectionModule: Buffer.from(`export const generated = ${JSON.stringify(`${localMarker}_graph_node`)};\n`),
    });
    let failure;
    try {
      await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    } catch (error) {
      failure = error;
    }
    assert.ok(failure instanceof Error);
    assert.match(
      failure.message,
      /^deployment projection privacy scan failed: rule=local_repository_collapsed_path; category=compressed-projection-module; index=0$/,
    );
    assert.equal(failure.message.includes(localMarker), false);
    await assert.rejects(readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("outer deployment rejects foreign user-home identities in graph-only modules", async (context) => {
  for (const [name, marker, rule, graphModuleKind] of [
    [
      "windows",
      String.raw`D:\Users\Foreign.Person\Desktop\Atlas\graph.json`,
      "generic_windows_user_home_path",
      "shard",
    ],
    [
      "posix",
      "/home/foreign.person/work/atlas/graph.json",
      "generic_posix_user_home_path",
      "summary",
    ],
    [
      "collapsed",
      "home_foreign_owner_checkout_atlas_graph_json",
      "generic_collapsed_user_home_path",
      "shard",
    ],
  ]) {
    await context.test(name, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), `atlas-deployment-foreign-${name}-`));
      try {
        const fixture = await initializeFixture(scratch);
        const modulePath = graphModuleKind === "summary"
          ? "graph/summary-test.mjs"
          : "graph/shards/foreign-nodes-00000-test.mjs";
        const deployment = await writeDist(fixture.repo, "dist", {
          projectionModule: Buffer.from(
            `export const generated = ${JSON.stringify(`${marker}_graph_node`)};\n`,
          ),
          projectionModulePath: modulePath,
          graphSensitive: true,
          graphModuleKind,
        });
        let failure;
        try {
          await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
        } catch (error) {
          failure = error;
        }
        assert.ok(failure instanceof Error);
        assert.match(
          failure.message,
          new RegExp(`^deployment projection privacy scan failed: rule=${rule}; category=compressed-projection-module; index=0$`),
        );
        assert.equal(failure.message.includes(marker), false);
        await assert.rejects(readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), /ENOENT/);
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});

test("outer deployment rejects a foreign identity in a self-consistent module path before manifest creation", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-path-privacy-build-"));
  try {
    const fixture = await initializeFixture(scratch);
    const marker = "home_foreign_owner_checkout_atlas";
    const modulePath = `graph/shards/${marker}-nodes.mjs`;
    const deployment = await writeDist(fixture.repo, "dist", {
      projectionModulePath: modulePath,
      graphSensitive: true,
    });
    let failure;
    try {
      await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    } catch (error) {
      failure = error;
    }
    assert.ok(failure instanceof Error);
    assert.match(
      failure.message,
      /^deployment path privacy scan failed: rule=generic_collapsed_user_home_path; category=projection-declaration; index=0$/,
    );
    assert.equal(failure.stack.includes(marker), false);
    await assert.rejects(readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("standalone verifier rejects a self-consistent private module path and remains read-only", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-path-privacy-verify-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    const marker = "home_foreign_owner_checkout_atlas";
    const manifestBytes = await replaceReceiptedProjectionModulePath(
      deployment.dist,
      `graph/shards/${marker}-nodes.mjs`,
    );
    let failure;
    try {
      await verifyDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    } catch (error) {
      failure = error;
    }
    assert.ok(failure instanceof Error);
    assert.match(
      failure.message,
      /^deployment path privacy scan failed: rule=generic_collapsed_user_home_path; category=projection-declaration; index=0$/,
    );
    assert.equal(failure.stack.includes(marker), false);
    assert.deepEqual(await readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), manifestBytes);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("outer deployment rejects a self-receipted foreign identity in generated projection metadata", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-metadata-privacy-build-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    const marker = "home_foreign_owner_checkout_atlas";
    await addReceiptedProjectionMetadata(deployment.dist, "producer_note", marker);
    let failure;
    try {
      await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    } catch (error) {
      failure = error;
    }
    assert.ok(failure instanceof Error);
    assert.match(
      failure.message,
      /^deployment generated-metadata privacy scan failed: rule=generic_collapsed_user_home_path; category=projection-manifest$/,
    );
    assert.equal(failure.stack.includes(marker), false);
    await assert.rejects(readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("standalone verifier rejects self-receipted local projection metadata and remains read-only", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-metadata-privacy-verify-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    const marker = collapsedAsciiIdentity(fixture.repo);
    await addReceiptedProjectionMetadata(deployment.dist, "producer_note", marker);
    const manifestBytes = await refreshOuterDeploymentReceipt(deployment.dist);
    let failure;
    try {
      await verifyDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    } catch (error) {
      failure = error;
    }
    assert.ok(failure instanceof Error);
    assert.match(
      failure.message,
      /^deployment generated-metadata privacy scan failed: rule=local_repository_collapsed_path; category=projection-manifest$/,
    );
    assert.equal(failure.stack.includes(marker), false);
    assert.deepEqual(await readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), manifestBytes);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("deployment filesystem failures do not expose host paths in exception chains", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-host-path-errors-"));
  try {
    const marker = "home_foreign_owner_checkout_private";
    const missingDist = join(scratch, marker, "dist");
    let failure;
    try {
      await buildDeploymentManifest({ distDir: missingDist, repoRoot: scratch });
    } catch (error) {
      failure = error;
    }
    assert.ok(failure instanceof Error);
    assert.equal(failure.message, "deployment root is unavailable");
    assert.equal(failure.stack.includes(marker), false);
    assert.equal(failure.cause, undefined);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("projection census preflights unexpected member paths before reporting them", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-projection-census-privacy-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    const marker = "home_foreign_owner_checkout_atlas";
    const extraPath = join(
      deployment.projectionRoot,
      "graph",
      `${marker}.mjs`,
    );
    await mkdir(dirname(extraPath), { recursive: true });
    await writeFile(extraPath, "export const unexpected = true;\n");
    let failure;
    try {
      await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    } catch (error) {
      failure = error;
    }
    assert.ok(failure instanceof Error);
    assert.match(
      failure.message,
      /^deployment path privacy scan failed: rule=generic_collapsed_user_home_path; category=projection-member; index=\d+$/,
    );
    assert.equal(failure.stack.includes(marker), false);
    await assert.rejects(readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("deployment rejects deeply nested generated metadata with a fixed non-echoing error", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-deep-metadata-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    const marker = "home_foreign_owner_checkout_private";
    const projectionPath = join(deployment.projectionRoot, PROJECTION_MANIFEST_NAME);
    const compressionPath = join(deployment.projectionRoot, COMPRESSION_MANIFEST_NAME);
    const projectionBytes = Buffer.from(
      `{"deep":${"[".repeat(80)}${JSON.stringify(marker)}${"]".repeat(80)}}\n`,
    );
    const compression = await readGzipJson(compressionPath);
    const projectionRepresentation = deterministicGzip(projectionBytes);
    compression.projectionManifest = {
      path: "projection-manifest.json",
      representationPath: PROJECTION_MANIFEST_NAME,
      contentEncoding: "gzip",
      bytes: projectionBytes.byteLength,
      sha256: sha256(projectionBytes),
      representationBytes: projectionRepresentation.byteLength,
      representationSha256: sha256(projectionRepresentation),
    };
    await writeFile(projectionPath, projectionRepresentation);
    await writeGzipJson(compressionPath, compression);
    let failure;
    try {
      await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    } catch (error) {
      failure = error;
    }
    assert.ok(failure instanceof Error);
    assert.equal(
      failure.message,
      "projection manifest exceeds bounded JSON structure limits",
    );
    assert.equal(failure.stack.includes(marker), false);
    assert.equal(failure.cause, undefined);
    await assert.rejects(readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("standalone verifier scans self-consistent nested gzip privacy and remains read-only", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-verify-privacy-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    await buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    const localMarker = collapsedAsciiIdentity(fixture.repo);
    await replaceReceiptedProjectionModule(
      deployment.dist,
      Buffer.from(`export const generated = ${JSON.stringify(`${localMarker}_graph_node`)};\n`),
    );
    const manifestBytes = await refreshOuterDeploymentReceipt(deployment.dist);
    let failure;
    try {
      await verifyDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo });
    } catch (error) {
      failure = error;
    }
    assert.ok(failure instanceof Error);
    assert.match(
      failure.message,
      /^deployment projection privacy scan failed: rule=local_repository_collapsed_path; category=compressed-projection-module; index=0$/,
    );
    assert.equal(failure.message.includes(localMarker), false);
    assert.deepEqual(await readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), manifestBytes);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("outer deployment bounds expanded projection members before manifest creation", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-gzip-budget-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist", {
      projectionModule: Buffer.alloc(8 * 1024 * 1024 + 1, 0x61),
    });
    await assert.rejects(
      buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo }),
      /projection module declaration lacks a bounded byte\/hash receipt/,
    );
    await assert.rejects(readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("outer deployment rejects an oversized aggregate compression receipt without large I/O", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-gzip-aggregate-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    const compressionPath = join(
      deployment.projectionRoot,
      COMPRESSION_MANIFEST_NAME,
    );
    const compression = await readGzipJson(compressionPath);
    compression.compressedBytes = 600 * 1024 * 1024;
    await writeGzipJson(compressionPath, compression);
    await assert.rejects(
      buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo }),
      /compression module receipt is absent or inconsistent/,
    );
    await assert.rejects(readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("outer deployment receipt refuses a dirty tracked Git tree", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-dirty-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    await writeFile(join(fixture.repo, "tracked.txt"), "dirty tracked source\n");
    await assert.rejects(
      buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo }),
      /tracked Git tree is not clean; deployment receipt refused/,
    );
    await assert.rejects(readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("prebuild removes only a prior regular deployment receipt", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-prepare-"));
  try {
    const dist = join(scratch, "dist");
    await mkdir(dist, { recursive: true });
    assert.deepEqual(await prepareDeployment({ distDir: dist }), {
      path: join(dist, DEPLOYMENT_MANIFEST_NAME),
      removed: false,
    });
    await writeFile(join(dist, DEPLOYMENT_MANIFEST_NAME), "generated\n");
    assert.deepEqual(await prepareDeployment({ distDir: dist }), {
      path: join(dist, DEPLOYMENT_MANIFEST_NAME),
      removed: true,
    });
    await assert.rejects(readFile(join(dist, DEPLOYMENT_MANIFEST_NAME)), /ENOENT/);
    await mkdir(join(dist, DEPLOYMENT_MANIFEST_NAME));
    await writeFile(join(dist, "deployment-manifest.json"), "legacy generated\n");
    await assert.rejects(
      prepareDeployment({ distDir: dist }),
      /prior deployment receipt is not a regular file/,
    );
    assert.equal(await readFile(join(dist, "deployment-manifest.json"), "utf8"), "legacy generated\n");
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("outer deployment receipt refuses a stale reference on a clean newer commit", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-stale-reference-"));
  try {
    const fixture = await initializeFixture(scratch);
    const deployment = await writeDist(fixture.repo, "dist");
    await writeFile(join(fixture.repo, "tracked.txt"), "new committed source\n");
    await git(fixture.repo, "add", "tracked.txt");
    await git(fixture.repo, "commit", "--quiet", "-m", "newer clean source");
    await assert.rejects(
      buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo }),
      /reference projection commit does not equal clean build commit/,
    );
    await assert.rejects(readFile(join(deployment.dist, DEPLOYMENT_MANIFEST_NAME)), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});
