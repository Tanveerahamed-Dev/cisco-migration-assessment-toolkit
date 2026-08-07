import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { gunzip } from "node:zlib";
import { promisify } from "node:util";
import { compressProjection } from "../../build/compress-projection.mjs";

const gunzipAsync = promisify(gunzip);
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const stableJson = (value) => {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
};

async function writeFixture(root, { orphan = false, missing = false, tampered = false } = {}) {
  const projection = join(root, "atlas-projection");
  const values = new Map([
    ["identity.mjs", Buffer.from("export const identity = 'Atlas';\n")],
    ["index.mjs", Buffer.from("export default 'index';\n")],
    ["source/chunk.mjs", Buffer.from("export const records = ['one', 'two'];\n")],
  ]);
  for (const [path, bytes] of values) {
    if (missing && path === "source/chunk.mjs") continue;
    const absolute = join(projection, ...path.split("/"));
    await mkdir(dirname(absolute), { recursive: true });
    await writeFile(absolute, bytes);
  }
  const descriptor = (path, sourcePath = null) => ({
    module: path,
    ...(sourcePath ? { path: sourcePath } : {}),
    bytes: values.get(path).byteLength,
    sha256: sha256(values.get(path)),
  });
  const pathDescriptor = (path) => ({
    path,
    bytes: values.get(path).byteLength,
    sha256: sha256(values.get(path)),
  });
  const manifest = {
    schemaVersion: "1.1.0",
    sourceCommit: "a".repeat(40),
    sourceTreeDigest: "b".repeat(64),
    identity: pathDescriptor("identity.mjs"),
    index: pathDescriptor("index.mjs"),
    sourceModules: [descriptor("source/chunk.mjs", "docs/authored-source.mjs")],
    repeatedDeclaration: descriptor("source/chunk.mjs"),
  };
  const manifestPath = join(projection, "projection-manifest.json");
  await writeFile(manifestPath, `${stableJson(manifest)}\n`);
  if (orphan) await writeFile(join(projection, "orphan.mjs"), "export default 'orphan';\n");
  if (tampered) await writeFile(join(projection, "index.mjs"), "export default 'tampered';\n");
  return { projection, manifestPath, values };
}

async function listCompressed(root) {
  const output = [];
  async function walk(directory, prefix = "") {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) await walk(join(directory, entry.name), relative);
      else if (relative.endsWith(".mjs.gz")) output.push(relative);
    }
  }
  await walk(root);
  return output.sort();
}

test("projection compression is deterministic, lossless, and preserves the projection manifest", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-compression-determinism-"));
  try {
    const first = await writeFixture(join(scratch, "first"));
    const second = await writeFixture(join(scratch, "second"));
    const firstManifest = await readFile(first.manifestPath);
    await compressProjection({ projectionDir: first.projection });
    await compressProjection({ projectionDir: second.projection });
    assert.deepEqual(await readFile(first.manifestPath), firstManifest);
    assert.deepEqual(
      await readFile(join(first.projection, "compression-manifest.json")),
      await readFile(join(second.projection, "compression-manifest.json")),
    );
    const compressed = await listCompressed(first.projection);
    assert.deepEqual(compressed, [...first.values.keys()].map((path) => `${path}.gz`).sort());
    for (const path of first.values.keys()) {
      await assert.rejects(readFile(join(first.projection, ...path.split("/"))), /ENOENT/);
      const firstGzip = await readFile(join(first.projection, ...`${path}.gz`.split("/")));
      const secondGzip = await readFile(join(second.projection, ...`${path}.gz`.split("/")));
      assert.deepEqual(firstGzip, secondGzip);
      assert.deepEqual(await gunzipAsync(firstGzip), first.values.get(path));
    }
    const receipt = JSON.parse(await readFile(join(first.projection, "compression-manifest.json"), "utf8"));
    assert.equal(receipt.moduleCount, first.values.size);
    assert.equal(receipt.declarationCount, first.values.size + 1);
    assert.equal(receipt.modules.length, first.values.size);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("projection compression requires exact equality between declared and actual modules", async (context) => {
  for (const [name, options, expected] of [
    ["undeclared module", { orphan: true }, /module census mismatch.*undeclared=orphan\.mjs/],
    ["missing module", { missing: true }, /module census mismatch.*missing=source\/chunk\.mjs/],
  ]) {
    await context.test(name, async () => {
      const scratch = await mkdtemp(join(os.tmpdir(), "atlas-compression-census-"));
      try {
        const fixture = await writeFixture(scratch, options);
        await assert.rejects(compressProjection({ projectionDir: fixture.projection }), expected);
        await assert.rejects(readFile(join(fixture.projection, "compression-manifest.json")), /ENOENT/);
        assert.deepEqual(await listCompressed(fixture.projection), []);
      } finally {
        await rm(scratch, { recursive: true, force: true });
      }
    });
  }
});

test("projection compression rejects module tampering before writing or removing anything", async () => {
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-compression-tamper-"));
  try {
    const fixture = await writeFixture(scratch, { tampered: true });
    await assert.rejects(
      compressProjection({ projectionDir: fixture.projection }),
      /projection module byte\/hash mismatch: index\.mjs/,
    );
    assert.match(await readFile(join(fixture.projection, "index.mjs"), "utf8"), /tampered/);
    assert.deepEqual(await listCompressed(fixture.projection), []);
    await assert.rejects(readFile(join(fixture.projection, "compression-manifest.json")), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});
