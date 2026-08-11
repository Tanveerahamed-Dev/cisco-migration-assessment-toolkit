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
import { constants, crc32, deflateRawSync } from "node:zlib";
import test from "node:test";
import { CANONICAL_GZIP_HEADER_BYTES } from "../../build/gzip-contract.js";
import {
  buildDeploymentManifest,
  deploymentManifestTestOnly,
  verifyDeploymentManifest,
} from "../../build/deployment-manifest.mjs";
import { prepareDeployment } from "../../build/prepare-deployment.mjs";

const execFileAsync = promisify(execFile);
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const compareText = (left, right) => (left < right ? -1 : left > right ? 1 : 0);
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

function deterministicGzip(original) {
  const deflated = deflateRawSync(original, { level: constants.Z_BEST_COMPRESSION });
  const trailer = Buffer.alloc(8);
  trailer.writeUInt32LE(crc32(original) >>> 0, 0);
  trailer.writeUInt32LE(original.byteLength >>> 0, 4);
  return Buffer.concat([Buffer.from(CANONICAL_GZIP_HEADER_BYTES), deflated, trailer]);
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
    schemaVersion: "1.0.0",
    algorithm: "gzip:deflate-raw:level-9:mtime-0:os-255",
    sourceCommit,
    sourceTreeDigest,
    projectionSchemaVersion: projection.schemaVersion,
    projectionManifest: {
      path: "projection-manifest.json",
      bytes: projectionBytes.byteLength,
      sha256: sha256(projectionBytes),
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
  const members = new Map([
    ["index.html", Buffer.from("<!doctype html><title>Atlas</title>\n")],
    ["client/app.js", Buffer.from("export const atlas = true;\n")],
    ["client/app.css", Buffer.from(":root{color-scheme:dark}\n")],
    ["client/atlas-projection/projection-manifest.json", projectionBytes],
    ["client/atlas-projection/compression-manifest.json", Buffer.from(`${stableJson(compression)}\n`)],
    [`client/atlas-projection/${compressedPath}`, compressedModule],
  ]);
  for (const [path, bytes] of members) {
    await writeBytes(join(dist, ...path.split("/")), bytes);
  }
  return { dist, members, projectionRoot };
}

async function replaceReceiptedProjectionModule(dist, projectionModule) {
  const projectionRoot = join(dist, "client", "atlas-projection");
  const projectionPath = join(projectionRoot, "projection-manifest.json");
  const compressionPath = join(projectionRoot, "compression-manifest.json");
  const compressedPath = join(projectionRoot, "identity.mjs.gz");
  const projection = JSON.parse(await readFile(projectionPath, "utf8"));
  projection.identity.bytes = projectionModule.byteLength;
  projection.identity.sha256 = sha256(projectionModule);
  const projectionBytes = Buffer.from(`${stableJson(projection)}\n`);
  const compressedModule = deterministicGzip(projectionModule);
  const compression = JSON.parse(await readFile(compressionPath, "utf8"));
  compression.projectionManifest.bytes = projectionBytes.byteLength;
  compression.projectionManifest.sha256 = sha256(projectionBytes);
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
  await writeFile(projectionPath, projectionBytes);
  await writeFile(compressedPath, compressedModule);
  await writeFile(compressionPath, `${stableJson(compression)}\n`);
}

async function addReceiptedProjectionMetadata(dist, key, value) {
  const projectionRoot = join(dist, "client", "atlas-projection");
  const projectionPath = join(projectionRoot, "projection-manifest.json");
  const compressionPath = join(projectionRoot, "compression-manifest.json");
  const projection = JSON.parse(await readFile(projectionPath, "utf8"));
  projection[key] = value;
  const projectionBytes = Buffer.from(`${stableJson(projection)}\n`);
  const compression = JSON.parse(await readFile(compressionPath, "utf8"));
  compression.projectionManifest.bytes = projectionBytes.byteLength;
  compression.projectionManifest.sha256 = sha256(projectionBytes);
  await writeFile(projectionPath, projectionBytes);
  await writeFile(compressionPath, `${stableJson(compression)}\n`);
}

async function replaceReceiptedProjectionModulePath(dist, modulePath) {
  const projectionRoot = join(dist, "client", "atlas-projection");
  const projectionPath = join(projectionRoot, "projection-manifest.json");
  const compressionPath = join(projectionRoot, "compression-manifest.json");
  const oldCompressedPath = "identity.mjs.gz";
  const newCompressedPath = `${modulePath}.gz`;
  const projection = JSON.parse(await readFile(projectionPath, "utf8"));
  projection.identity.path = modulePath;
  const projectionBytes = Buffer.from(`${stableJson(projection)}\n`);
  const compression = JSON.parse(await readFile(compressionPath, "utf8"));
  compression.projectionManifest.bytes = projectionBytes.byteLength;
  compression.projectionManifest.sha256 = sha256(projectionBytes);
  compression.modules[0].path = modulePath;
  compression.modules[0].compressedPath = newCompressedPath;
  await mkdir(dirname(join(projectionRoot, ...newCompressedPath.split("/"))), { recursive: true });
  await rename(
    join(projectionRoot, oldCompressedPath),
    join(projectionRoot, ...newCompressedPath.split("/")),
  );
  await writeFile(projectionPath, projectionBytes);
  await writeFile(compressionPath, `${stableJson(compression)}\n`);

  const manifestPath = join(dist, "deployment-manifest.json");
  const receipt = JSON.parse(await readFile(manifestPath, "utf8"));
  const member = receipt.members.find(
    (entry) => entry.path === `client/atlas-projection/${oldCompressedPath}`,
  );
  assert.ok(member);
  member.path = `client/atlas-projection/${newCompressedPath}`;
  receipt.members.sort((left, right) => compareText(left.path, right.path));
  await writeFile(manifestPath, `${stableJson(receipt)}\n`);
  return refreshOuterDeploymentReceipt(dist);
}

async function refreshOuterDeploymentReceipt(dist) {
  const manifestPath = join(dist, "deployment-manifest.json");
  const receipt = JSON.parse(await readFile(manifestPath, "utf8"));
  for (const member of receipt.members) {
    const bytes = await readFile(join(dist, ...member.path.split("/")));
    member.bytes = bytes.byteLength;
    member.sha256 = sha256(bytes);
  }
  receipt.memberCount = receipt.members.length;
  receipt.totalBytes = receipt.members.reduce((total, member) => total + member.bytes, 0);
  const projectionBytes = await readFile(
    join(dist, "client", "atlas-projection", "projection-manifest.json"),
  );
  const compressionBytes = await readFile(
    join(dist, "client", "atlas-projection", "compression-manifest.json"),
  );
  receipt.referenceSource.projectionManifestSha256 = sha256(projectionBytes);
  receipt.referenceSource.compressionManifestSha256 = sha256(compressionBytes);
  receipt.membersDigest = sha256(Buffer.from(`${stableJson(receipt.members)}\n`));
  const payload = {
    schemaVersion: receipt.schemaVersion,
    recordType: receipt.recordType,
    source: receipt.source,
    referenceSource: receipt.referenceSource,
    memberCount: receipt.memberCount,
    totalBytes: receipt.totalBytes,
    members: receipt.members,
  };
  receipt.bundleDigest = sha256(Buffer.from(`${stableJson(payload)}\n`));
  const manifestBytes = Buffer.from(`${stableJson(receipt)}\n`);
  await writeFile(manifestPath, manifestBytes);
  return manifestBytes;
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

test("outer deployment receipt is deterministic, exact-source bound, and covers every other file", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-deployment-manifest-"));
  try {
    const fixture = await initializeFixture(scratch);
    const first = await writeDist(fixture.repo, "dist-first");
    const second = await writeDist(fixture.repo, "dist-second");
    const receiptA = await buildDeploymentManifest({ distDir: first.dist, repoRoot: fixture.repo });
    const receiptB = await buildDeploymentManifest({ distDir: second.dist, repoRoot: fixture.repo });
    assert.deepEqual(
      await readFile(join(first.dist, "deployment-manifest.json")),
      await readFile(join(second.dist, "deployment-manifest.json")),
    );
    assert.equal(receiptA.schemaVersion, "1.0.0");
    assert.equal(receiptA.recordType, "atlas_deployment_bundle");
    assert.equal(receiptA.source.commit, fixture.commit);
    assert.equal(receiptA.source.treeOid, fixture.treeOid);
    assert.equal(receiptA.source.trackedTreeState, "clean");
    assert.equal(receiptA.referenceSource.commit, fixture.commit);
    assert.equal(receiptA.manifestRule.path, "deployment-manifest.json");
    assert.equal(receiptA.manifestRule.selfHash, false);
    assert.ok(!receiptA.members.some((member) => member.path === "deployment-manifest.json"));
    const actualMembers = (await listRegularFiles(first.dist))
      .filter((path) => path !== "deployment-manifest.json");
    assert.deepEqual(receiptA.members.map((member) => member.path), actualMembers);
    assert.equal(receiptA.memberCount, actualMembers.length);
    assert.deepEqual(receiptB, receiptA);
    assert.deepEqual(
      await verifyDeploymentManifest({ distDir: first.dist, repoRoot: fixture.repo }),
      receiptA,
    );
  } finally {
    await rm(scratch, { recursive: true, force: true });
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
      assert.equal(failure.message, "test receipt changed during its bounded read");
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
        "test receipt exceeds the bounded JSON receipt limit",
      );
      assert.equal(failure.stack.includes(marker), false);
      assert.equal(failure.cause, undefined);
    } finally {
      await rm(scratch, { recursive: true, force: true });
    }
  });
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
        (name) => name.startsWith(".dist.deployment-manifest.json.") && name.endsWith(".tmp"),
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
      readFile(join(deployment.dist, "deployment-manifest.json")),
      /ENOENT/,
    );
    const siblingNames = await readdir(dirname(deployment.dist));
    assert.equal(
      siblingNames.some(
        (name) => name.startsWith(".dist.deployment-manifest.json.") && name.endsWith(".tmp"),
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
        await readFile(join(deployment.dist, "deployment-manifest.json"));
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
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
    await assert.rejects(readFile(join(deployment.dist, "deployment-manifest.json")), /ENOENT/);
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
        await assert.rejects(readFile(join(deployment.dist, "deployment-manifest.json")), /ENOENT/);
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
    await assert.rejects(readFile(join(deployment.dist, "deployment-manifest.json")), /ENOENT/);
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
      /^deployment path privacy scan failed: rule=generic_collapsed_user_home_path; category=deployment-member; index=\d+$/,
    );
    assert.equal(failure.stack.includes(marker), false);
    assert.deepEqual(await readFile(join(deployment.dist, "deployment-manifest.json")), manifestBytes);
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
    await assert.rejects(readFile(join(deployment.dist, "deployment-manifest.json")), /ENOENT/);
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
    assert.deepEqual(await readFile(join(deployment.dist, "deployment-manifest.json")), manifestBytes);
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
    await assert.rejects(readFile(join(deployment.dist, "deployment-manifest.json")), /ENOENT/);
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
    const projectionPath = join(deployment.projectionRoot, "projection-manifest.json");
    const compressionPath = join(deployment.projectionRoot, "compression-manifest.json");
    const projectionBytes = Buffer.from(
      `{"deep":${"[".repeat(80)}${JSON.stringify(marker)}${"]".repeat(80)}}\n`,
    );
    const compression = JSON.parse(await readFile(compressionPath, "utf8"));
    compression.projectionManifest.bytes = projectionBytes.byteLength;
    compression.projectionManifest.sha256 = sha256(projectionBytes);
    await writeFile(projectionPath, projectionBytes);
    await writeFile(compressionPath, `${stableJson(compression)}\n`);
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
    await assert.rejects(readFile(join(deployment.dist, "deployment-manifest.json")), /ENOENT/);
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
    assert.deepEqual(await readFile(join(deployment.dist, "deployment-manifest.json")), manifestBytes);
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
    await assert.rejects(readFile(join(deployment.dist, "deployment-manifest.json")), /ENOENT/);
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
      "compression-manifest.json",
    );
    const compression = JSON.parse(await readFile(compressionPath, "utf8"));
    compression.compressedBytes = 600 * 1024 * 1024;
    await writeFile(compressionPath, `${stableJson(compression)}\n`);
    await assert.rejects(
      buildDeploymentManifest({ distDir: deployment.dist, repoRoot: fixture.repo }),
      /compression module receipt is absent or inconsistent/,
    );
    await assert.rejects(readFile(join(deployment.dist, "deployment-manifest.json")), /ENOENT/);
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
    await assert.rejects(readFile(join(deployment.dist, "deployment-manifest.json")), /ENOENT/);
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
      path: join(dist, "deployment-manifest.json"),
      removed: false,
    });
    await writeFile(join(dist, "deployment-manifest.json"), "generated\n");
    assert.deepEqual(await prepareDeployment({ distDir: dist }), {
      path: join(dist, "deployment-manifest.json"),
      removed: true,
    });
    await assert.rejects(readFile(join(dist, "deployment-manifest.json")), /ENOENT/);
    await mkdir(join(dist, "deployment-manifest.json"));
    await assert.rejects(
      prepareDeployment({ distDir: dist }),
      /prior deployment receipt is not a regular file/,
    );
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
    await assert.rejects(readFile(join(deployment.dist, "deployment-manifest.json")), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});
