import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  unlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import { dirname, join } from "node:path";
import { promisify } from "node:util";
import test from "node:test";
import {
  buildDeploymentManifest,
  verifyDeploymentManifest,
} from "../../build/deployment-manifest.mjs";
import { prepareDeployment } from "../../build/prepare-deployment.mjs";

const execFileAsync = promisify(execFile);
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const compareText = (left, right) => (left < right ? -1 : left > right ? 1 : 0);
const stableJson = (value) => {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort(compareText).map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
};

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

async function writeDist(repo, name) {
  const dist = join(repo, name);
  const projectionRoot = join(dist, "client", "atlas-projection");
  const sourceCommit = await git(repo, "rev-parse", "HEAD");
  const sourceTreeDigest = "c".repeat(64);
  const projection = {
    schemaVersion: "1.1.0",
    sourceCommit,
    sourceTreeDigest,
  };
  const projectionBytes = Buffer.from(`${stableJson(projection)}\n`);
  const compression = {
    schemaVersion: "1.0.0",
    sourceCommit,
    sourceTreeDigest,
    projectionSchemaVersion: projection.schemaVersion,
    projectionManifest: {
      path: "projection-manifest.json",
      bytes: projectionBytes.byteLength,
      sha256: sha256(projectionBytes),
    },
  };
  const members = new Map([
    ["index.html", Buffer.from("<!doctype html><title>Atlas</title>\n")],
    ["client/app.js", Buffer.from("export const atlas = true;\n")],
    ["client/app.css", Buffer.from(":root{color-scheme:dark}\n")],
    ["client/atlas-projection/projection-manifest.json", projectionBytes],
    ["client/atlas-projection/compression-manifest.json", Buffer.from(`${stableJson(compression)}\n`)],
  ]);
  for (const [path, bytes] of members) {
    await writeBytes(join(dist, ...path.split("/")), bytes);
  }
  return { dist, members, projectionRoot };
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
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
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
