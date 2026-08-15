import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import ts from "typescript";

import imageSize, { imageSize as namedImageSize } from "image-size";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const value of bytes) {
    crc ^= value;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngHeader(width, height) {
  const bytes = Buffer.alloc(33);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(bytes, 0);
  bytes.writeUInt32BE(13, 8);
  bytes.write("IHDR", 12, "ascii");
  bytes.writeUInt32BE(width, 16);
  bytes.writeUInt32BE(height, 20);
  bytes[24] = 8;
  bytes[25] = 6;
  bytes[26] = 0;
  bytes[27] = 0;
  bytes[28] = 0;
  bytes.writeUInt32BE(crc32(bytes.subarray(12, 29)), 29);
  return bytes;
}

function rewritePngCrc(bytes) {
  bytes.writeUInt32BE(crc32(bytes.subarray(12, 29)), 29);
  return bytes;
}

test("the installed image-size binding is the bounded Atlas surface", async () => {
  const surface = await import("image-size");
  assert.deepEqual(Object.keys(surface).sort(), ["default", "imageSize"]);
  assert.equal(imageSize, namedImageSize);
  assert.equal(
    realpathSync(fileURLToPath(import.meta.resolve("image-size"))),
    realpathSync(path.join(projectRoot, "vendor/bounded-image-size/index.js")),
  );
  const vinextRequire = createRequire(path.join(projectRoot, "node_modules/vinext/dist/index.js"));
  assert.equal(
    realpathSync(vinextRequire.resolve("image-size")),
    realpathSync(path.join(projectRoot, "vendor/bounded-image-size/index.js")),
  );
});

test("the lock resolves the Vinext image-size edge only to the tracked local package", () => {
  const manifest = JSON.parse(readFileSync(path.join(projectRoot, "package.json"), "utf8"));
  const lock = JSON.parse(readFileSync(path.join(projectRoot, "package-lock.json"), "utf8"));

  assert.equal(manifest.overrides["image-size"], undefined);
  assert.deepEqual(manifest.overrides["vinext@0.0.50"], {
    "image-size": "file:vendor/bounded-image-size",
  });
  assert.deepEqual(lock.packages["node_modules/image-size"], {
    resolved: "vendor/bounded-image-size",
    link: true,
  });
  assert.deepEqual(lock.packages["vendor/bounded-image-size"], {
    name: "@atlas/bounded-image-size",
    version: "1.0.0",
    dev: true,
    license: "LicenseRef-Proprietary",
    engines: { node: ">=22.13.0" },
  });
  assert.deepEqual(
    Object.keys(lock.packages).filter(
      (key) => key === "node_modules/image-size" || key.endsWith("/node_modules/image-size"),
    ),
    ["node_modules/image-size"],
  );
  assert.equal(lock.packages["node_modules/vinext/vendor/bounded-image-size"], undefined);
});

test("valid PNG IHDR dimensions are returned", () => {
  assert.deepEqual(imageSize(pngHeader(1731, 909)), {
    width: 1731,
    height: 909,
    type: "png",
  });
  assert.deepEqual(imageSize(readFileSync(path.join(projectRoot, "public/atlas-social-card.png"))), {
    width: 1731,
    height: 909,
    type: "png",
  });
  assert.deepEqual(imageSize(readFileSync(path.join(projectRoot, "public/og.png"))), {
    width: 1730,
    height: 909,
    type: "png",
  });
  const padded = Buffer.concat([Buffer.from([1, 2, 3]), pngHeader(64, 32), Buffer.from([4])]);
  assert.deepEqual(imageSize(padded.subarray(3, 36)), { width: 64, height: 32, type: "png" });
});

test("SVG recognition is prefix-bounded and does not invent dimensions", () => {
  const svg = Buffer.from("\ufeff  <?xml version=\"1.0\"?><svg viewBox=\"0 0 10 20\"></svg>");
  assert.deepEqual(imageSize(svg), { type: "svg" });
  assert.throws(
    () => imageSize(Buffer.from("arbitrary binary prefix <svg></svg>")),
    /bounded image metadata rejected/,
  );
  for (const truncatedOrInvalid of [
    "<svg",
    "<svg/",
    "<SVG></SVG>",
    "<?XML?><svg></svg>",
    "<?xml a='?><svg>",
  ]) {
    assert.throws(
      () => imageSize(Buffer.from(truncatedOrInvalid)),
      /bounded image metadata rejected/,
    );
  }
  assert.deepEqual(imageSize(Buffer.concat([Buffer.alloc(507, 32), Buffer.from("<svg>")])), { type: "svg" });
  assert.throws(
    () => imageSize(Buffer.concat([Buffer.alloc(508, 32), Buffer.from("<svg>")])),
    /bounded image metadata rejected/,
  );
  assert.deepEqual(imageSize(readFileSync(path.join(projectRoot, "public/favicon.svg"))), { type: "svg" });
});

function moduleSpecifiers(source, filename) {
  const specifiers = [];
  const parsed = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true);
  const inspect = (node) => {
    let specifier;
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier) {
      specifier = node.moduleSpecifier;
    } else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference)) {
      specifier = node.moduleReference.expression;
    } else if (
      ts.isCallExpression(node)
      && node.arguments.length >= 1
      && node.expression.kind === ts.SyntaxKind.ImportKeyword
    ) {
      [specifier] = node.arguments;
    } else if (
      ts.isCallExpression(node)
      && node.arguments.length >= 1
      && ts.isIdentifier(node.expression)
      && node.expression.text === "require"
    ) {
      [specifier] = node.arguments;
    }
    if (specifier && ts.isStringLiteralLike(specifier)) specifiers.push(specifier.text);
    ts.forEachChild(node, inspect);
  };
  inspect(parsed);
  return specifiers;
}

test("application source contains no Vinext or Next image-parser entry points", () => {
  const imageExtension = /\.(?:avif|bmp|gif|ico|jpe?g|png|svg|tiff?|webp)(?:\?.*)?$/i;
  const metadataRoute = /^(?:favicon|(?:apple-icon|icon|opengraph-image|twitter-image)\d?)\.(?:avif|bmp|gif|ico|jpe?g|png|svg|tiff?|webp)$/i;
  const nextParserEntry = /^next\/(?:legacy\/)?image(?:\.js)?$|^next\/dist\/(?:(?:esm\/)?server\/image-optimizer|(?:esm\/)?build\/webpack\/loaders\/next-(?:image-loader(?:\/index)?|metadata-image-loader)|compiled\/(?:image-size(?:\/index)?|image-detector(?:\/detector)?))(?:\.js)?$/;
  const sourceExtensions = new Set([".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx"]);
  const excludedRootPrefixes = [".next/", "dist/", "node_modules/", "public/", "tmp/", "vendor/"];
  const isScannableSourcePath = (relative) => sourceExtensions.has(path.extname(relative))
    && !excludedRootPrefixes.some((prefix) => relative.startsWith(prefix));
  const isMetadataRoutePath = (relative) => (
    relative.startsWith("app/") || relative.startsWith("src/app/")
  ) && metadataRoute.test(path.posix.basename(relative));
  const findings = [];

  assert.deepEqual(
    moduleSpecifiers("import hero from './hostile.jpg'; import Image from 'next/image';", "fixture.ts"),
    ["./hostile.jpg", "next/image"],
  );
  assert.deepEqual(
    moduleSpecifiers('import("next/image", { with: { type: "javascript" } });', "fixture.ts"),
    ["next/image"],
  );
  assert.deepEqual(moduleSpecifiers('require("next/image", {});', "fixture.js"), ["next/image"]);
  assert.equal(isScannableSourcePath("app/vendor/component.tsx"), true);
  assert.equal(isScannableSourcePath("vendor/component.tsx"), false);
  assert.equal(metadataRoute.test("icon1.png"), true);
  assert.equal(isMetadataRoutePath("app/icon1.png"), true);
  assert.equal(isMetadataRoutePath("src/app/icon1.png"), true);
  assert.equal(isMetadataRoutePath("src/application/icon1.png"), false);
  for (const specifier of [
    "next/image.js",
    "next/legacy/image.js",
    "next/dist/compiled/image-size",
    "next/dist/compiled/image-size/index.js",
    "next/dist/compiled/image-detector/detector.js",
    "next/dist/server/image-optimizer",
    "next/dist/esm/server/image-optimizer.js",
    "next/dist/build/webpack/loaders/next-image-loader/index.js",
    "next/dist/esm/build/webpack/loaders/next-metadata-image-loader.js",
  ]) {
    assert.equal(nextParserEntry.test(specifier), true);
  }

  const repositoryPaths = execFileSync(
    "git",
    ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    { cwd: projectRoot, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], windowsHide: true },
  ).split("\0").filter(Boolean);
  const scannedPaths = repositoryPaths.filter(isScannableSourcePath).sort();
  for (const relative of repositoryPaths) {
    if (isMetadataRoutePath(relative)) {
      findings.push(`${relative}:metadata-route-file`);
    }
  }
  for (const relative of scannedPaths) {
    const current = path.join(projectRoot, ...relative.split("/"));
    const source = readFileSync(current, "utf8");
    for (const specifier of moduleSpecifiers(source, current)) {
      if (imageExtension.test(specifier) || nextParserEntry.test(specifier)) {
        findings.push(`${relative}:${specifier}`);
      }
    }
  }

  const pathSetDigest = createHash("sha256").update(`${JSON.stringify(scannedPaths)}\n`).digest("hex");
  assert.equal(scannedPaths.length, 63);
  assert.equal(pathSetDigest, "dbd98351588526099c650c841d05704ad6099b04d2c69eb90a911f541dd30f6d");
  assert.deepEqual(findings.sort(), []);
});

test("the separately bundled Next parser remains an explicit blocked residual", () => {
  const vectors = [
    [0x69, 0x63, 0x6e, 0x73, 0, 0, 0, 16, 0x69, 0x63, 0x70, 0x34, 0, 0, 0, 0],
    [
      0, 0, 0, 12, 0x4a, 0x58, 0x4c, 0x20, 0x0d, 0x0a, 0x87, 0x0a,
      0, 0, 0, 20, 0x66, 0x74, 0x79, 0x70, 0x6a, 0x78, 0x6c, 0x20,
      0, 0, 0, 0, 0, 0, 0, 0,
      0, 0, 0, 0, 0x6a, 0x78, 0x6c, 0x70,
    ],
  ];
  for (const vector of vectors) {
    const child = `const fs=require("node:fs");const imageSize=require("next/dist/compiled/image-size");fs.writeSync(1,"entered\\n");imageSize(Buffer.from(${JSON.stringify(vector)}));`;
    const result = spawnSync(process.execPath, ["--eval", child], {
      cwd: projectRoot,
      encoding: "utf8",
      timeout: 2_000,
      windowsHide: true,
    });
    assert.equal(result.stdout, "entered\n");
    assert.equal(result.error?.code, "ETIMEDOUT");
    assert.equal(result.status, null);
  }
});

test("malformed or over-broad inputs fail closed", () => {
  const badCrc = pngHeader(10, 20);
  badCrc[29] ^= 1;
  const zeroWidth = pngHeader(1, 1);
  zeroWidth.writeUInt32BE(0, 16);
  zeroWidth.writeUInt32BE(crc32(zeroWidth.subarray(12, 29)), 29);
  const tooWide = pngHeader(100_001, 1);
  const tooManyPixels = pngHeader(100_000, 1_001);
  const exactInputBound = Buffer.alloc(16 * 1024 * 1024);
  pngHeader(100_000, 1_000).copy(exactInputBound);

  const badLength = pngHeader(1, 1);
  badLength.writeUInt32BE(12, 8);
  const badType = pngHeader(1, 1);
  badType.write("JHDR", 12, "ascii");
  rewritePngCrc(badType);
  const badColorDepth = pngHeader(1, 1);
  badColorDepth[24] = 4;
  badColorDepth[25] = 2;
  rewritePngCrc(badColorDepth);
  const badCompression = pngHeader(1, 1);
  badCompression[26] = 1;
  rewritePngCrc(badCompression);
  const badFilter = pngHeader(1, 1);
  badFilter[27] = 1;
  rewritePngCrc(badFilter);
  const badInterlace = pngHeader(1, 1);
  badInterlace[28] = 2;
  rewritePngCrc(badInterlace);

  assert.deepEqual(imageSize(exactInputBound), { width: 100_000, height: 1_000, type: "png" });

  for (const input of [
    "not bytes",
    Buffer.alloc(0),
    Buffer.alloc(16 * 1024 * 1024 + 1),
    badCrc,
    zeroWidth,
    tooWide,
    tooManyPixels,
    badLength,
    badType,
    badColorDepth,
    badCompression,
    badFilter,
    badInterlace,
    Buffer.alloc(32),
    Buffer.from("plain text"),
    Buffer.from("<!doctype svg><svg></svg>"),
  ]) {
    assert.throws(() => imageSize(input), /bounded image metadata rejected/);
  }
});

test("historically risky image families terminate under a subprocess watchdog", () => {
  const child = String.raw`
    import { imageSize } from "image-size";
    const cases = [
      Buffer.from([0,0,0,0,0x66,0x74,0x79,0x70,0x68,0x65,0x69,0x63]),
      Buffer.from([0,0,0,0x0c,0x4a,0x58,0x4c,0x20,0x0d,0x0a,0x87,0x0a]),
      Buffer.from([
        0,0,0,12,0x4a,0x58,0x4c,0x20,0x0d,0x0a,0x87,0x0a,
        0,0,0,20,0x66,0x74,0x79,0x70,0x6a,0x78,0x6c,0x20,
        0,0,0,0,0,0,0,0,0,0,0,0,0x6a,0x78,0x6c,0x70,
      ]),
      Buffer.from([0,0,0,0,0x6a,0x70,0x32,0x68]),
      Buffer.from([0x69,0x63,0x6e,0x73,0,0,0,16,0x69,0x63,0x70,0x34,0,0,0,0]),
      Buffer.from([0xff,0xd8,0xff,0xe0,0,0]),
    ];
    for (const value of cases) {
      let rejected = false;
      try { imageSize(value); } catch { rejected = true; }
      if (!rejected) process.exit(2);
    }
    let state = 0x6d2b79f5;
    for (let sample = 0; sample < 2048; sample += 1) {
      state = (Math.imul(state ^ (state >>> 15), 1 | state) + sample) >>> 0;
      const value = Buffer.alloc(state % 1025);
      for (let index = 0; index < value.length; index += 1) {
        state = (Math.imul(state ^ (state >>> 15), 1 | state) + index) >>> 0;
        value[index] = state & 0xff;
      }
      try { imageSize(value); } catch {}
    }
  `;
  const result = spawnSync(process.execPath, ["--input-type=module", "--eval", child], {
    cwd: projectRoot,
    encoding: "utf8",
    timeout: 2_000,
    windowsHide: true,
  });
  assert.equal(result.error, undefined);
  assert.equal(result.signal, null);
  assert.equal(result.status, 0, `${result.stdout}${result.stderr}`);
});
