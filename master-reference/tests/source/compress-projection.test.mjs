import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import { dirname, join } from "node:path";
import { promisify } from "node:util";
import { gunzip } from "node:zlib";
import test from "node:test";

import { CANONICAL_GZIP_HEADER_BYTES } from "../../build/gzip-contract.js";
import {
  compressProjection as compressProjectionPublic,
  compressionTestOnly,
} from "../../build/compress-projection.mjs";

const compressProjection = compressionTestOnly.compressProjectionInternal;

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

test("projection compression is deterministic, lossless, and preserves canonical receipt bytes", async () => {
  assert.deepEqual(CANONICAL_GZIP_HEADER_BYTES, [
    0x1f,
    0x8b,
    0x08,
    0x00,
    0x00,
    0x00,
    0x00,
    0x00,
    0x02,
    0xff,
  ]);
  const scratch = await mkdtemp(join(os.tmpdir(), "atlas-compression-determinism-"));
  try {
    const first = await writeFixture(join(scratch, "first"));
    const second = await writeFixture(join(scratch, "second"));
    const firstManifest = await readFile(first.manifestPath);
    await compressProjectionPublic({ projectionDir: first.projection });
    await compressProjection({ projectionDir: second.projection });
    await assert.rejects(readFile(first.manifestPath), /ENOENT/);
    const firstProjectionReceipt = await readFile(`${first.manifestPath}.gz`);
    const secondProjectionReceipt = await readFile(`${second.manifestPath}.gz`);
    assert.deepEqual(firstProjectionReceipt, secondProjectionReceipt);
    assert.deepEqual(await gunzipAsync(firstProjectionReceipt), firstManifest);
    assert.deepEqual(
      [...firstProjectionReceipt.subarray(0, CANONICAL_GZIP_HEADER_BYTES.length)],
      CANONICAL_GZIP_HEADER_BYTES,
    );
    assert.deepEqual(
      await readFile(join(first.projection, "compression-manifest.json.gz")),
      await readFile(join(second.projection, "compression-manifest.json.gz")),
    );
    const compressed = await listCompressed(first.projection);
    assert.deepEqual(compressed, [...first.values.keys()].map((path) => `${path}.gz`).sort());
    for (const path of first.values.keys()) {
      await assert.rejects(readFile(join(first.projection, ...path.split("/"))), /ENOENT/);
      const firstGzip = await readFile(join(first.projection, ...`${path}.gz`.split("/")));
      const secondGzip = await readFile(join(second.projection, ...`${path}.gz`.split("/")));
      assert.deepEqual(firstGzip, secondGzip);
      assert.deepEqual(
        [...firstGzip.subarray(0, CANONICAL_GZIP_HEADER_BYTES.length)],
        CANONICAL_GZIP_HEADER_BYTES,
      );
      assert.deepEqual(await gunzipAsync(firstGzip), first.values.get(path));
    }
    const receiptRepresentation = await readFile(join(first.projection, "compression-manifest.json.gz"));
    assert.deepEqual(
      [...receiptRepresentation.subarray(0, CANONICAL_GZIP_HEADER_BYTES.length)],
      CANONICAL_GZIP_HEADER_BYTES,
    );
    const receipt = JSON.parse(await gunzipAsync(receiptRepresentation));
    assert.equal(receipt.schemaVersion, "1.1.0");
    assert.equal(
      receipt.algorithm,
      "gzip:deflate-raw:level-9:memlevel-8:strategy-filtered:mtime-0:os-255",
    );
    assert.deepEqual(receipt.producerRuntime, {
      node: process.versions.node,
      zlib: process.versions.zlib,
    });
    assert.deepEqual(receipt.projectionManifest, {
      path: "projection-manifest.json",
      representationPath: "projection-manifest.json.gz",
      contentEncoding: "gzip",
      bytes: firstManifest.byteLength,
      sha256: sha256(firstManifest),
      representationBytes: firstProjectionReceipt.byteLength,
      representationSha256: sha256(firstProjectionReceipt),
    });
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
        await assert.rejects(readFile(join(fixture.projection, "compression-manifest.json.gz")), /ENOENT/);
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
    await assert.rejects(readFile(join(fixture.projection, "compression-manifest.json.gz")), /ENOENT/);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
});

test("public projection compression rejects hostile options without disclosure", async (context) => {
  const marker = "private-compression-options-sentinel";
  const accessor = {};
  Object.defineProperty(accessor, "projectionDir", {
    enumerable: true,
    get() {
      throw new Error(marker);
    },
  });
  const nonenumerable = {};
  Object.defineProperty(nonenumerable, "projectionDir", {
    enumerable: false,
    value: marker,
  });
  const cases = [
    ["null", null],
    ["scalar", 7],
    ["string scalar", marker],
    ["accessor", accessor],
    ["string wrapper", { projectionDir: new String(marker) }],
    ["custom prototype", Object.assign(Object.create({ marker }), { projectionDir: marker })],
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
  for (const [name, options] of cases) {
    await context.test(name, async () => {
      let failure;
      try {
        await compressProjectionPublic(options);
      } catch (error) {
        failure = error;
      }
      assert.ok(failure instanceof Error);
      assert.equal(failure.message, "projection compression failed");
      assert.equal(failure.stack.includes(marker), false);
      assert.equal(failure.cause, undefined);
    });
  }
});
