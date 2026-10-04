import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";
import { isDeepStrictEqual } from "node:util";

// GHSA-vfj7-8cjw-p6xm (CVE-2026-93687): every published braces release (<= 3.0.3) can exhaust the
// call stack on deeply nested patterns. The Vinext edge resolves braces to vendor/bounded-braces:
// released braces 3.0.3 plus the lib/ hunks of micromatch/braces#72, an OPEN, unmerged third-party
// pull request. This contract binds those bytes, the bound, the unchanged behaviour and the edge.

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(testDirectory, "../..");
const packageRoot = path.join(projectRoot, "vendor", "bounded-braces");
const OVERRIDE_SCOPE = "vinext@0.0.50";
const OVERRIDE_SPEC = "file:vendor/bounded-braces";
// fast-glob 3.3.3 out/utils/pattern.js expands every pattern with exactly these options.
const FAST_GLOB_BRACE_OPTIONS = Object.freeze({ expand: true, nodupes: true, keepEscaping: true });
const INPUT_DEPTH_REFUSAL = Object.freeze({
  name: "SyntaxError",
  message: "Input depth (101), exceeds max depth (100)",
});
const AST_DEPTH_REFUSAL = Object.freeze({
  name: "RangeError",
  message: "AST depth (101), exceeds max depth (100)",
});

// The published braces 3.0.3 tarball. Its sha512 is the integrity the lock recorded for
// node_modules/braces before the substitution; each member digest below was taken from that
// verified tarball.
const UPSTREAM_TARBALL_INTEGRITY =
  "sha512-yQbXgO/OSZVD2IsiLlro+7Hf6Q18EJrKSEsdoMzKePKXct3gvD8oLcOQdIzGupr5Fj+EDe8gO/lxc1BzfMpxvA==";
const UPSTREAM_MEMBER_SHA256 = Object.freeze({
  LICENSE: "35bdd8a44339719441900fb50fbefc5e2dca1ca662cbaed7a687de842c8b70f2",
  "README.md": "947b0fc3cc12eaaa070207126213fbdf9ab2bf8cd13dcc6e4007b36b79309866",
  "index.js": "332ea07c7b006361aad12aa994ca75dc1db8e8382b884909e2f38f10b85c88a4",
  "lib/compile.js": "dc98f22eee3d511785d92a00758d5f0d48efed5f5813bdecc2de430c529b5c9f",
  "lib/constants.js": "c18ac5adb57308f1ce42a28552da3a31f5d83709743ebd9a636336813a744d4b",
  "lib/expand.js": "41ccc196ebfa7b7781a634e721eb744e4e7bcb54cba427a7e3d6806a1b9e58f7",
  "lib/parse.js": "e572166565f15fa6ad9865ae49d678218e32aabfd1b3720f6d0d43d39800d310",
  "lib/stringify.js": "379f22d77bfa1478341ccd49c5e4267464aabcbba03558bab332aac23fc6f23a",
  "lib/utils.js": "b5a7596aa67730412b3c029ef09e84e6b67b8e445cffd35d1d295549c89066c7",
  "package.json": "56f08b888a4f30dc7cf8a7dbb36ffe92b737912ba36abe9d069d32167c957ac7",
});
// Published documentation and manifest replaced by the Atlas README.md and package.json.
const UPSTREAM_MEMBERS_REPLACED = Object.freeze(["README.md", "package.json"]);

// The pull request is third-party code under review, not a braces release.
const PATCH_PROVENANCE = Object.freeze({
  pullRequest: "micromatch/braces#72",
  headSha: "d0d575e55e74a4e0218e5248fafb79efc3e54ebb",
  author: "FSDevelop",
  state: "OPEN and unmerged",
  retrievedUtc: "2026-10-03T03:19:55Z",
  // sha256 of the exact lib/ portion of the pull request's diff (GitHub diff media type, LF).
  libDiffSha256: "0b1df17466e51e0fc867a1cdce4054441e656d115fc646a91318f801db0a5dd1",
});

const PR_72_LIB_DIFF_LINES = Object.freeze([
  "diff --git a/lib/compile.js b/lib/compile.js",
  "index dce69be..945a78b 100644",
  "--- a/lib/compile.js",
  "+++ b/lib/compile.js",
  "@@ -2,9 +2,15 @@",
  " ",
  " const fill = require('fill-range');",
  " const utils = require('./utils');",
  "+const { MAX_DEPTH } = require('./constants');",
  " ",
  " const compile = (ast, options = {}) => {",
  "-  const walk = (node, parent = {}) => {",
  "+  const maxDepth = Number.isFinite(options.maxDepth) ? Math.min(MAX_DEPTH, options.maxDepth) : MAX_DEPTH;",
  "+",
  "+  const walk = (node, parent = {}, depth = 0) => {",
  "+    if (node.nodes && depth > maxDepth) {",
  "+      throw new RangeError(`AST depth (${depth}), exceeds max depth (${maxDepth})`);",
  "+    }",
  "     const invalidBlock = utils.isInvalidBrace(parent);",
  "     const invalidNode = node.invalid === true && options.escapeInvalid === true;",
  "     const invalid = invalidBlock === true || invalidNode === true;",
  "@@ -47,14 +53,14 @@ const compile = (ast, options = {}) => {",
  " ",
  "     if (node.nodes) {",
  "       for (const child of node.nodes) {",
  "-        output += walk(child, node);",
  "+        output += walk(child, node, child.nodes ? depth + 1 : depth);",
  "       }",
  "     }",
  " ",
  "     return output;",
  "   };",
  " ",
  "-  return walk(ast);",
  "+  return walk(ast, {}, ast.type === 'root' ? 0 : 1);",
  " };",
  " ",
  " module.exports = compile;",
  "diff --git a/lib/constants.js b/lib/constants.js",
  "index 2bb3b88..c237099 100644",
  "--- a/lib/constants.js",
  "+++ b/lib/constants.js",
  "@@ -1,6 +1,7 @@",
  " 'use strict';",
  " ",
  " module.exports = {",
  "+  MAX_DEPTH: 100,",
  "   MAX_LENGTH: 10000,",
  " ",
  "   // Digits",
  "diff --git a/lib/expand.js b/lib/expand.js",
  "index 35b2c41..80ea368 100644",
  "--- a/lib/expand.js",
  "+++ b/lib/expand.js",
  "@@ -3,6 +3,7 @@",
  " const fill = require('fill-range');",
  " const stringify = require('./stringify');",
  " const utils = require('./utils');",
  "+const { MAX_DEPTH } = require('./constants');",
  " ",
  " const append = (queue = '', stash = '', enclose = false) => {",
  "   const result = [];",
  "@@ -32,8 +33,12 @@ const append = (queue = '', stash = '', enclose = false) => {",
  " ",
  " const expand = (ast, options = {}) => {",
  "   const rangeLimit = options.rangeLimit === undefined ? 1000 : options.rangeLimit;",
  "+  const maxDepth = Number.isFinite(options.maxDepth) ? Math.min(MAX_DEPTH, options.maxDepth) : MAX_DEPTH;",
  " ",
  "-  const walk = (node, parent = {}) => {",
  "+  const walk = (node, parent = {}, depth = 0) => {",
  "+    if (node.nodes && depth > maxDepth) {",
  "+      throw new RangeError(`AST depth (${depth}), exceeds max depth (${maxDepth})`);",
  "+    }",
  "     node.queue = [];",
  " ",
  "     let p = parent;",
  "@@ -100,14 +105,14 @@ const expand = (ast, options = {}) => {",
  "       }",
  " ",
  "       if (child.nodes) {",
  "-        walk(child, node);",
  "+        walk(child, node, child.nodes ? depth + 1 : depth);",
  "       }",
  "     }",
  " ",
  "     return queue;",
  "   };",
  " ",
  "-  return utils.flatten(walk(ast));",
  "+  return utils.flatten(walk(ast, {}, ast.type === 'root' ? 0 : 1));",
  " };",
  " ",
  " module.exports = expand;",
  "diff --git a/lib/parse.js b/lib/parse.js",
  "index 4e57de6..b8183b6 100644",
  "--- a/lib/parse.js",
  "+++ b/lib/parse.js",
  "@@ -7,6 +7,7 @@ const stringify = require('./stringify');",
  "  */",
  " ",
  " const {",
  "+  MAX_DEPTH,",
  "   MAX_LENGTH,",
  "   CHAR_BACKSLASH, /* \\ */",
  "   CHAR_BACKTICK, /* ` */",
  "@@ -35,6 +36,7 @@ const parse = (input, options = {}) => {",
  " ",
  "   const opts = options || {};",
  "   const max = typeof opts.maxLength === 'number' ? Math.min(MAX_LENGTH, opts.maxLength) : MAX_LENGTH;",
  "+  const maxDepth = Number.isFinite(opts.maxDepth) ? Math.min(MAX_DEPTH, opts.maxDepth) : MAX_DEPTH;",
  "   if (input.length > max) {",
  "     throw new SyntaxError(`Input length (${input.length}), exceeds max characters (${max})`);",
  "   }",
  "@@ -47,6 +49,7 @@ const parse = (input, options = {}) => {",
  "   const length = input.length;",
  "   let index = 0;",
  "   let depth = 0;",
  "+  let nesting = 0;",
  "   let value;",
  " ",
  "   /**",
  "@@ -143,6 +146,10 @@ const parse = (input, options = {}) => {",
  "      */",
  " ",
  "     if (value === CHAR_LEFT_PARENTHESES) {",
  "+      if (nesting >= maxDepth) {",
  "+        throw new SyntaxError(`Input depth (${nesting + 1}), exceeds max depth (${maxDepth})`);",
  "+      }",
  "+      nesting++;",
  "       block = push({ type: 'paren', nodes: [] });",
  "       stack.push(block);",
  "       push({ type: 'text', value });",
  "@@ -156,6 +163,7 @@ const parse = (input, options = {}) => {",
  "       }",
  "       block = stack.pop();",
  "       push({ type: 'text', value });",
  "+      nesting--;",
  "       block = stack[stack.length - 1];",
  "       continue;",
  "     }",
  "@@ -203,6 +211,10 @@ const parse = (input, options = {}) => {",
  "      */",
  " ",
  "     if (value === CHAR_LEFT_CURLY_BRACE) {",
  "+      if (nesting >= maxDepth) {",
  "+        throw new SyntaxError(`Input depth (${nesting + 1}), exceeds max depth (${maxDepth})`);",
  "+      }",
  "+      nesting++;",
  "       depth++;",
  " ",
  "       const dollar = prev.value && prev.value.slice(-1) === '$' || block.dollar === true;",
  "@@ -239,6 +251,7 @@ const parse = (input, options = {}) => {",
  " ",
  "       push({ type, value });",
  "       depth--;",
  "+      nesting--;",
  " ",
  "       block = stack[stack.length - 1];",
  "       continue;",
  "diff --git a/lib/stringify.js b/lib/stringify.js",
  "index 8bcf872..4d8b196 100644",
  "--- a/lib/stringify.js",
  "+++ b/lib/stringify.js",
  "@@ -1,9 +1,15 @@",
  " 'use strict';",
  " ",
  " const utils = require('./utils');",
  "+const { MAX_DEPTH } = require('./constants');",
  " ",
  " module.exports = (ast, options = {}) => {",
  "-  const stringify = (node, parent = {}) => {",
  "+  const maxDepth = Number.isFinite(options.maxDepth) ? Math.min(MAX_DEPTH, options.maxDepth) : MAX_DEPTH;",
  "+",
  "+  const stringify = (node, parent = {}, depth = 0) => {",
  "+    if (node.nodes && depth > maxDepth) {",
  "+      throw new RangeError(`AST depth (${depth}), exceeds max depth (${maxDepth})`);",
  "+    }",
  "     const invalidBlock = options.escapeInvalid && utils.isInvalidBrace(parent);",
  "     const invalidNode = node.invalid === true && options.escapeInvalid === true;",
  "     let output = '';",
  "@@ -21,12 +27,11 @@ module.exports = (ast, options = {}) => {",
  " ",
  "     if (node.nodes) {",
  "       for (const child of node.nodes) {",
  "-        output += stringify(child);",
  "+        output += stringify(child, node, child.nodes ? depth + 1 : depth);",
  "       }",
  "     }",
  "     return output;",
  "   };",
  " ",
  "-  return stringify(ast);",
  "+  return stringify(ast, {}, ast.type === 'root' ? 0 : 1);",
  " };",
  "-",
]);

// Every vendored file. Code members are the published bytes or published bytes plus the patch,
// which the reconstruction test below proves; README.md and package.json are Atlas-authored.
const VENDORED_SHA256 = Object.freeze({
  LICENSE: "35bdd8a44339719441900fb50fbefc5e2dca1ca662cbaed7a687de842c8b70f2",
  "README.md": "e1bc416ea24f0964c292d05f86c024d0b26a3144bebce65b2e01b2396f30ed0e",
  "index.js": "332ea07c7b006361aad12aa994ca75dc1db8e8382b884909e2f38f10b85c88a4",
  "lib/compile.js": "b651f7715e6db8942ce61d3394357b4d81c8ece88240aa31a458ea1165edd195",
  "lib/constants.js": "f9fb688959232eee3e6ad7906a5b0e3234815db49ee857ef86983d65b917dc7c",
  "lib/expand.js": "2974d5b8763a358d81dfa5b4b804329f525239f34429c396b93a540219504809",
  "lib/parse.js": "ef9b3851f848460daaf91ff248222a43e266f97c4f2df7010cb7858e1e39a107",
  "lib/stringify.js": "645f13c68af685148e9fe8eca449ee2ebb88eee0f27de7b2125fbfc175b1584d",
  "lib/utils.js": "b5a7596aa67730412b3c029ef09e84e6b67b8e445cffd35d1d295549c89066c7",
  "package.json": "7b034e186488f3ad856880bdd35acc533fb91700d144df65dd764bd113ed0b6f",
});

const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const load = createRequire(import.meta.url);

function listFiles(root, { skipNodeModules = false } = {}) {
  const files = [];
  const walk = (directory, prefix) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        if (!(skipNodeModules && entry.name === "node_modules")) walk(path.join(directory, entry.name), relative);
      } else {
        assert.ok(entry.isFile(), `${relative} must be a regular file`);
        files.push(relative);
      }
    }
  };
  walk(root, "");
  return files.sort();
}

function readVendoredFiles() {
  return new Map(
    listFiles(packageRoot).map((relative) => [relative, readFileSync(path.join(packageRoot, ...relative.split("/")))]),
  );
}

function parseUnifiedDiff(text) {
  const lines = text.split("\n");
  assert.equal(lines.pop(), "", "the recorded diff ends with a newline");
  const files = [];
  let file;
  let hunk;
  let metadata = [];
  for (const line of lines) {
    if (line.startsWith("diff --git ")) {
      const match = /^diff --git a\/(\S+) b\/(\S+)$/.exec(line);
      assert.ok(match && match[1] === match[2], `unsupported diff header: ${line}`);
      file = { path: match[1], hunks: [] };
      files.push(file);
      hunk = undefined;
      metadata = [];
    } else if (file && !hunk && !line.startsWith("@@ ")) {
      metadata.push(line);
      assert.ok(metadata.length <= 3, `unexpected diff metadata: ${line}`);
      const expected = [/^index [0-9a-f]{7}\.\.[0-9a-f]{7} 100644$/, `--- a/${file.path}`, `+++ b/${file.path}`][
        metadata.length - 1
      ];
      if (typeof expected === "string") assert.equal(line, expected);
      else assert.match(line, expected);
    } else if (file && line.startsWith("@@ ")) {
      assert.equal(metadata.length === 3 || file.hunks.length > 0, true, `hunk before metadata: ${line}`);
      const match = /^@@ -(\d+),(\d+) \+(\d+),(\d+) @@/.exec(line);
      assert.ok(match, `unsupported hunk header: ${line}`);
      hunk = { oldCount: Number(match[2]), newCount: Number(match[4]), before: [], after: [] };
      file.hunks.push(hunk);
    } else if (hunk && line.startsWith(" ")) {
      hunk.before.push(line.slice(1));
      hunk.after.push(line.slice(1));
    } else if (hunk && line.startsWith("-")) {
      hunk.before.push(line.slice(1));
    } else if (hunk && line.startsWith("+")) {
      hunk.after.push(line.slice(1));
    } else {
      assert.fail(`unsupported diff line: ${JSON.stringify(line)}`);
    }
  }
  for (const { path: filePath, hunks } of files) {
    assert.ok(hunks.length > 0, `${filePath} has no hunks`);
    for (const { oldCount, newCount, before, after } of hunks) {
      assert.equal(before.length, oldCount, `${filePath} hunk old-side count`);
      assert.equal(after.length, newCount, `${filePath} hunk new-side count`);
    }
  }
  return files;
}

// Applies hunks as exact whole-line block replacements. Each source block must occur exactly once,
// so a changed byte inside or around a hunk makes the reconstruction fail instead of drifting.
function applyHunks(text, hunks, direction, label) {
  let lines = text.split("\n");
  hunks.forEach((hunk, index) => {
    const [from, to] = direction === "forward" ? [hunk.before, hunk.after] : [hunk.after, hunk.before];
    const positions = [];
    for (let start = 0; start + from.length <= lines.length; start += 1) {
      if (from.every((line, offset) => lines[start + offset] === line)) positions.push(start);
    }
    assert.equal(positions.length, 1, `${label} hunk ${index + 1} must match exactly once (${direction})`);
    lines = [...lines.slice(0, positions[0]), ...to, ...lines.slice(positions[0] + from.length)];
  });
  return lines.join("\n");
}

const patchText = () => `${PR_72_LIB_DIFF_LINES.join("\n")}\n`;

function reconstructUpstream(vendored) {
  const reconstructed = new Map();
  for (const relative of ["LICENSE", "index.js", "lib/utils.js"]) {
    reconstructed.set(relative, vendored.get(relative));
  }
  for (const filePatch of parseUnifiedDiff(patchText())) {
    const current = vendored.get(filePatch.path);
    assert.ok(current, `${filePatch.path} is vendored`);
    reconstructed.set(
      filePatch.path,
      Buffer.from(applyHunks(current.toString("utf8"), filePatch.hunks, "reverse", filePatch.path), "utf8"),
    );
  }
  return reconstructed;
}

let upstreamFixture;
function upstreamBraces() {
  if (upstreamFixture) return upstreamFixture;
  const reconstructed = reconstructUpstream(readVendoredFiles());
  for (const [relative, bytes] of reconstructed) {
    assert.equal(sha256(bytes), UPSTREAM_MEMBER_SHA256[relative], `reconstructed ${relative}`);
  }
  const root = mkdtempSync(path.join(tmpdir(), "atlas-braces-3.0.3-"));
  const moduleRoot = path.join(root, "node_modules", "braces");
  for (const [relative, bytes] of reconstructed) {
    const target = path.join(moduleRoot, ...relative.split("/"));
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, bytes);
  }
  writeFileSync(path.join(moduleRoot, "package.json"), '{"name":"braces","version":"3.0.3","main":"index.js"}\n');
  // The released copy resolves the same installed fill-range closure as the vendored copy.
  let from = path.join(packageRoot, "index.js");
  for (const dependency of ["fill-range", "to-regex-range", "is-number"]) {
    const manifest = createRequire(from).resolve(`${dependency}/package.json`);
    cpSync(path.dirname(manifest), path.join(root, "node_modules", dependency), { recursive: true });
    from = manifest;
  }
  const modulePath = path.join(moduleRoot, "index.js");
  upstreamFixture = { root, modulePath, braces: createRequire(path.join(root, "probe.js"))("braces") };
  return upstreamFixture;
}

after(() => {
  if (upstreamFixture) rmSync(upstreamFixture.root, { recursive: true, force: true });
});

function nearestManifest(file) {
  let directory = path.dirname(file);
  for (;;) {
    const candidate = path.join(directory, "package.json");
    try {
      return { path: candidate, value: JSON.parse(readFileSync(candidate, "utf8")) };
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
    const parent = path.dirname(directory);
    assert.notEqual(parent, directory, `no package.json above ${file}`);
    directory = parent;
  }
}

// Vinext -> vite-plugin-commonjs -> vite-plugin-dynamic-import -> fast-glob -> micromatch -> braces,
// each hop resolved from the previous package's own location, as Node resolves it at build time.
function consumerChain() {
  const hops = [
    ["vite-plugin-commonjs", "0.10.4"],
    ["vite-plugin-dynamic-import", "1.6.0"],
    ["fast-glob", "3.3.3"],
    ["micromatch", "4.0.8"],
    ["braces", undefined],
  ];
  let from = path.join(projectRoot, "node_modules", "vinext", "package.json");
  let declaring = JSON.parse(readFileSync(from, "utf8"));
  assert.equal(declaring.version, "0.0.50");
  const resolved = {};
  for (const [name, version] of hops) {
    assert.ok(declaring.dependencies?.[name], `${declaring.name} declares ${name}`);
    const file = createRequire(from).resolve(name);
    resolved[name] = file;
    if (version === undefined) break;
    const manifest = nearestManifest(file);
    assert.equal(manifest.value.name, name);
    assert.equal(manifest.value.version, version);
    declaring = manifest.value;
    from = file;
  }
  return resolved;
}

test("the vendored package is braces 3.0.3 plus exactly the lib hunks of unmerged micromatch/braces#72", () => {
  const vendored = readVendoredFiles();
  assert.deepEqual([...vendored.keys()], Object.keys(VENDORED_SHA256).sort());
  for (const [relative, bytes] of vendored) {
    assert.equal(sha256(bytes), VENDORED_SHA256[relative], `vendored ${relative}`);
    assert.equal(bytes.includes(13), false, `${relative} is LF-only`);
  }

  assert.equal(sha256(patchText()), PATCH_PROVENANCE.libDiffSha256);
  const filePatches = parseUnifiedDiff(patchText());
  assert.deepEqual(
    filePatches.map((filePatch) => [filePatch.path, filePatch.hunks.length]),
    [
      ["lib/compile.js", 2],
      ["lib/constants.js", 1],
      ["lib/expand.js", 3],
      ["lib/parse.js", 7],
      ["lib/stringify.js", 2],
    ],
  );

  // Reverse the patch: the result must be the published 3.0.3 members, byte for byte.
  const reconstructed = reconstructUpstream(vendored);
  assert.deepEqual(
    [...reconstructed.keys()].sort(),
    Object.keys(UPSTREAM_MEMBER_SHA256)
      .filter((relative) => !UPSTREAM_MEMBERS_REPLACED.includes(relative))
      .sort(),
  );
  for (const [relative, bytes] of reconstructed) {
    assert.equal(sha256(bytes), UPSTREAM_MEMBER_SHA256[relative], `published ${relative}`);
  }
  // Re-apply it: the result must be the vendored bytes, so nothing outside the patch differs.
  for (const filePatch of filePatches) {
    const forward = applyHunks(
      reconstructed.get(filePatch.path).toString("utf8"),
      filePatch.hunks,
      "forward",
      filePatch.path,
    );
    assert.equal(forward, vendored.get(filePatch.path).toString("utf8"), `patched ${filePatch.path}`);
  }
});

test("the Atlas manifest and README keep braces' CommonJS surface and the patch provenance", () => {
  const manifest = JSON.parse(readFileSync(path.join(packageRoot, "package.json"), "utf8"));
  assert.deepEqual(manifest, {
    name: "@atlas/bounded-braces",
    version: "3.0.3",
    description:
      "Released braces 3.0.3 plus the unmerged third-party nesting-depth patch from micromatch/braces#72, for the Atlas Vinext build edge only",
    private: true,
    type: "commonjs",
    main: "index.js",
    engines: { node: ">=22.13.0" },
    dependencies: { "fill-range": "^7.1.1" },
    license: "MIT",
  });
  const readme = readFileSync(path.join(packageRoot, "README.md"), "utf8").replace(/\s+/g, " ");
  for (const fact of [
    UPSTREAM_TARBALL_INTEGRITY,
    PATCH_PROVENANCE.pullRequest,
    PATCH_PROVENANCE.headSha,
    `\`${PATCH_PROVENANCE.author}\``,
    PATCH_PROVENANCE.retrievedUtc,
    "OPEN and unmerged",
    "not a braces release",
    "MAX_DEPTH: 100",
    "capped at 100",
    "GHSA-vfj7-8cjw-p6xm",
    "escapeInvalid",
  ]) {
    assert.ok(readme.includes(fact), `README records ${fact}`);
  }
  const license = readFileSync(path.join(packageRoot, "LICENSE"), "utf8");
  assert.match(license, /^The MIT License \(MIT\)\n\nCopyright \(c\) 2014-present, Jon Schlinkert\.\n/);
});

function overrideEntries(value, prefix = []) {
  return Object.entries(value).flatMap(([key, child]) =>
    typeof child === "string" ? [[[...prefix, key], child]] : overrideEntries(child, [...prefix, key]),
  );
}

function lockResolve(packages, fromPath, name) {
  let base = fromPath;
  for (;;) {
    const candidate = base ? `${base}/node_modules/${name}` : `node_modules/${name}`;
    if (packages[candidate]) return candidate;
    if (!base) return undefined;
    const cut = base.lastIndexOf("/node_modules/");
    base = cut === -1 ? "" : base.slice(0, cut);
  }
}

test("the lock substitutes braces only on the exact Vinext edge", () => {
  const manifest = JSON.parse(readFileSync(path.join(projectRoot, "package.json"), "utf8"));
  const lock = JSON.parse(readFileSync(path.join(projectRoot, "package-lock.json"), "utf8"));
  const { packages } = lock;

  assert.equal(manifest.overrides[OVERRIDE_SCOPE].braces, OVERRIDE_SPEC);
  assert.deepEqual(
    overrideEntries(manifest.overrides).filter(
      ([keys, spec]) =>
        keys.some((key) => key === "braces" || key.startsWith("braces@")) || spec.includes("bounded-braces"),
    ),
    [[[OVERRIDE_SCOPE, "braces"], OVERRIDE_SPEC]],
  );
  assert.deepEqual(packages["node_modules/braces"], { resolved: "vendor/bounded-braces", link: true });
  assert.deepEqual(packages["vendor/bounded-braces"], {
    name: "@atlas/bounded-braces",
    version: "3.0.3",
    dev: true,
    license: "MIT",
    dependencies: { "fill-range": "^7.1.1" },
    engines: { node: ">=22.13.0" },
  });
  assert.deepEqual(
    Object.keys(packages).filter((key) => key === "node_modules/braces" || key.endsWith("/node_modules/braces")),
    ["node_modules/braces"],
  );
  assert.deepEqual(
    Object.entries(packages)
      .filter(([, record]) => /\/braces\/-\/braces-/.test(String(record.resolved ?? "")) || record.name === "braces")
      .map(([key]) => key),
    [],
  );
  for (const dependency of ["fill-range", "to-regex-range", "is-number"]) {
    assert.equal(packages[`node_modules/${dependency}`].dev, true, `${dependency} stays a locked dev record`);
  }

  // Only micromatch 4.0.8 declares braces, and every lock path from the root to braces passes
  // through Vinext 0.0.50: with Vinext removed, braces is unreachable.
  const dependents = Object.entries(packages)
    .filter(([key, record]) => key && record.dependencies?.braces)
    .map(([key, record]) => [key, record.version, record.dependencies.braces]);
  assert.deepEqual(dependents, [["node_modules/micromatch", "4.0.8", "^3.0.3"]]);
  const reach = (blocked) => {
    const seen = new Set([""]);
    const queue = [""];
    while (queue.length > 0) {
      const current = queue.shift();
      const record = packages[current];
      const declared = {
        ...record.dependencies,
        ...record.optionalDependencies,
        ...record.peerDependencies,
        ...(current === "" ? record.devDependencies : {}),
      };
      for (const name of Object.keys(declared)) {
        const target = lockResolve(packages, current, name);
        if (!target || target === blocked || seen.has(target)) continue;
        seen.add(target);
        queue.push(target);
      }
    }
    return seen;
  };
  assert.equal(reach(undefined).has("node_modules/braces"), true);
  assert.equal(reach("node_modules/vinext").has("node_modules/braces"), false);
  assert.equal(reach("node_modules/vinext").has("node_modules/micromatch"), false);
});

test("the installed Vinext consumer chain loads the vendored package", () => {
  const chain = consumerChain();
  const vendoredEntry = realpathSync(path.join(packageRoot, "index.js"));
  assert.equal(realpathSync(chain.braces), vendoredEntry);
  assert.equal(realpathSync(createRequire(path.join(projectRoot, "package.json")).resolve("braces")), vendoredEntry);
  assert.match(chain["fast-glob"].replaceAll("\\", "/"), /node_modules\/vite-plugin-dynamic-import\/node_modules\/fast-glob\//);
  assert.equal(createRequire(chain.braces)("./lib/constants").MAX_DEPTH, 100);
  assert.equal(typeof load(chain.braces), "function");
});

// Runs the hostile matrix in a child process so a regression can only fail the test, never hang or
// crash the runner. The matrix is defined once here and handed to the child.
const HOSTILE_MATRIX = Object.freeze({
  depths: [100, 101, 3500, 4999],
  consumerShapes: ["brace", "mixed"],
  bracesShapes: ["brace", "paren", "mixed"],
  astTypes: ["brace", "paren"],
  pluginDepths: [100, 101, 3500, 4990],
});

const HOSTILE_CHILD = String.raw`
"use strict";
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { createRequire } = require("node:module");
const matrix = JSON.parse(process.env.ATLAS_BRACES_MATRIX);
const hop = (from, request) => createRequire(from).resolve(request);
const commonjsPath = hop(path.join(process.env.ATLAS_BRACES_PROJECT_ROOT, "node_modules", "vinext", "package.json"), "vite-plugin-commonjs");
const dynamicImportPath = hop(commonjsPath, "vite-plugin-dynamic-import");
const fastGlobPath = hop(dynamicImportPath, "fast-glob");
const micromatchPath = hop(fastGlobPath, "micromatch");
const plugin = require(dynamicImportPath);
const acorn = createRequire(dynamicImportPath)("acorn");
const fastGlob = require(fastGlobPath);
const micromatch = require(micromatchPath);
const braces = require(hop(micromatchPath, "braces"));
const FAST_GLOB_OPTIONS = { expand: true, nodupes: true, keepEscaping: true };
const emptyDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "atlas-braces-empty-"));
const records = [];
const describe = (error) => ({ name: error && error.name, message: String(error && error.message) });
function attempt(record, run) {
  try { run(); record.outcome = "ok"; } catch (error) { record.outcome = describe(error); }
  records.push(record);
}
function nested(shape, depth) {
  const core = 2 * depth + 3 < 10000 ? "a,b" : "a";
  let left = "";
  let right = "";
  for (let index = 0; index < depth; index += 1) {
    const brace = shape === "brace" || (shape === "mixed" && index % 2 === 0);
    left += brace ? "{" : "(";
    right = (brace ? "}" : ")") + right;
  }
  const pattern = left + core + right;
  if (pattern.length >= 10000) throw new Error("pattern exceeds the 10,000-character input limit");
  return pattern;
}
function chain(type, depth, rooted) {
  let node = { type: "text", value: "a" };
  for (let index = 0; index < depth; index += 1) node = { type, nodes: [node] };
  return rooted ? { type: "root", nodes: [node] } : node;
}
const consumerEntries = {
  "fast-glob generateTasks": (pattern) => fastGlob.generateTasks([pattern]),
  "fast-glob sync": (pattern) => fastGlob.sync([pattern], { cwd: emptyDirectory }),
  "micromatch.braces": (pattern) => micromatch.braces(pattern),
  "micromatch.braces fast-glob options": (pattern) => micromatch.braces(pattern, FAST_GLOB_OPTIONS),
  "micromatch.braceExpand": (pattern) => micromatch.braceExpand(pattern),
  "micromatch.parse": (pattern) => micromatch.parse(pattern),
};
const bracesEntries = {
  "braces": (pattern) => braces(pattern),
  "braces expand option": (pattern) => braces(pattern, { expand: true }),
  "braces.expand": (pattern) => braces.expand(pattern),
  "braces.compile": (pattern) => braces.compile(pattern),
  "braces.parse": (pattern) => braces.parse(pattern),
  "braces.stringify": (pattern) => braces.stringify(pattern),
  "braces.parse maxDepth 100000": (pattern) => braces.parse(pattern, { maxDepth: 100000 }),
};
const walkers = { compile: braces.compile, expand: braces.expand, stringify: braces.stringify };
(async () => {
  for (const depth of matrix.depths) {
    for (const shape of matrix.consumerShapes) {
      const pattern = nested(shape, depth);
      for (const [entry, run] of Object.entries(consumerEntries)) {
        attempt({ kind: "pattern", entry, shape, depth }, () => run(pattern));
      }
    }
    for (const shape of matrix.bracesShapes) {
      const pattern = nested(shape, depth);
      for (const [entry, run] of Object.entries(bracesEntries)) {
        attempt({ kind: "pattern", entry, shape, depth }, () => run(pattern));
      }
    }
    for (const type of matrix.astTypes) {
      for (const rooted of [true, false]) {
        for (const [entry, walk] of Object.entries(walkers)) {
          attempt({ kind: "ast", entry, shape: type + (rooted ? " rooted" : ""), depth }, () => walk(chain(type, depth, rooted)));
        }
      }
    }
  }
  for (const [entry, walk] of Object.entries(walkers)) {
    const cycle = { type: "brace", nodes: [] };
    cycle.nodes.push(cycle);
    attempt({ kind: "ast", entry, shape: "cycle", depth: "cycle" }, () => walk({ type: "root", nodes: [cycle] }));
  }
  const tick = String.fromCharCode(96);
  for (const depth of matrix.pluginDepths) {
    const expression = "import(" + tick + "./views/" + "$" + "{name}" + "{".repeat(depth) + "a,b" + "}".repeat(depth) + ".js" + tick + ")";
    const importeeNode = acorn.parse(expression, { sourceType: "module", ecmaVersion: 2020 }).body[0].expression.source;
    const record = { kind: "plugin", entry: "vite-plugin-dynamic-import globFiles", shape: "template literal", depth };
    try {
      await plugin.globFiles({
        importeeNode,
        importExpression: expression,
        importer: path.join(emptyDirectory, "main.js"),
        resolve: { tryResolve: async () => undefined },
        extensions: [".js"],
        loose: true,
      });
      record.outcome = "ok";
    } catch (error) {
      record.outcome = describe(error);
    }
    records.push(record);
  }
  fs.rmSync(emptyDirectory, { recursive: true, force: true });
  process.stdout.write(JSON.stringify(records));
})().catch((error) => {
  process.stderr.write(String(error && error.stack));
  process.exit(3);
});
`;

function expectedHostileRecords() {
  const consumerEntryCount = 6;
  const bracesEntryCount = 7;
  const perDepth =
    HOSTILE_MATRIX.consumerShapes.length * consumerEntryCount +
    HOSTILE_MATRIX.bracesShapes.length * bracesEntryCount +
    HOSTILE_MATRIX.astTypes.length * 2 * 3;
  return HOSTILE_MATRIX.depths.length * perDepth + 3 + HOSTILE_MATRIX.pluginDepths.length;
}

function runHostileMatrix(stackSize) {
  const result = spawnSync(
    process.execPath,
    [...(stackSize ? [`--stack-size=${stackSize}`] : []), "--eval", HOSTILE_CHILD],
    {
      cwd: projectRoot,
      encoding: "utf8",
      env: {
        ...process.env,
        ATLAS_BRACES_PROJECT_ROOT: projectRoot,
        ATLAS_BRACES_MATRIX: JSON.stringify(HOSTILE_MATRIX),
      },
      maxBuffer: 64 * 1024 * 1024,
      timeout: 120_000,
      windowsHide: true,
    },
  );
  assert.equal(result.error, undefined);
  assert.equal(result.signal, null);
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

for (const stackSize of [undefined, 128]) {
  const label = stackSize ? `a ${stackSize} KB stack` : "the default stack";
  test(`deep nesting through the real consumer chain is refused with a controlled error on ${label}`, () => {
    const records = runHostileMatrix(stackSize);
    assert.equal(records.length, expectedHostileRecords());
    for (const record of records) {
      const where = `${record.kind} ${record.entry} ${record.shape} depth ${record.depth}`;
      if (record.outcome !== "ok") {
        assert.doesNotMatch(record.outcome.message, /Maximum call stack size exceeded/, where);
      }
      if (typeof record.depth === "number" && record.depth <= 100) {
        assert.equal(record.outcome, "ok", where);
      } else {
        assert.deepEqual(record.outcome, record.kind === "ast" ? AST_DEPTH_REFUSAL : INPUT_DEPTH_REFUSAL, where);
      }
    }
  });
}

test("released braces 3.0.3 exhausts a 128 KB stack on the same deep patterns (control)", () => {
  const { modulePath } = upstreamBraces();
  const child = String.raw`
    "use strict";
    const braces = require(process.env.ATLAS_BRACES_UPSTREAM_MODULE);
    const results = [];
    for (const depth of [3500, 4999]) {
      const pattern = "{".repeat(depth) + "a" + "}".repeat(depth);
      for (const [entry, run] of [
        ["braces.compile", () => braces.compile(pattern)],
        ["braces.expand", () => braces.expand(pattern)],
        ["braces.stringify", () => braces.stringify(pattern)],
      ]) {
        try { run(); results.push([entry, depth, "ok"]); }
        catch (error) { results.push([entry, depth, error.name + ": " + error.message]); }
      }
    }
    process.stdout.write(JSON.stringify(results));
  `;
  const result = spawnSync(process.execPath, ["--stack-size=128", "--eval", child], {
    encoding: "utf8",
    env: { ...process.env, ATLAS_BRACES_UPSTREAM_MODULE: modulePath },
    timeout: 120_000,
    windowsHide: true,
  });
  assert.equal(result.status, 0, result.stderr);
  const results = JSON.parse(result.stdout);
  assert.equal(results.length, 6);
  for (const [entry, depth, outcome] of results) {
    assert.equal(outcome, "RangeError: Maximum call stack size exceeded", `${entry} depth ${depth}`);
  }
});

function canonical(value, seen = new Set()) {
  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return "[cycle]";
  seen.add(value);
  const result = Array.isArray(value)
    ? value.map((item) => canonical(item, seen))
    : Object.fromEntries(
        Object.keys(value)
          .filter((key) => key !== "parent" && key !== "prev")
          .sort()
          .map((key) => [key, canonical(value[key], seen)]),
      );
  seen.delete(value);
  return result;
}

function observe(run) {
  const logs = [];
  const log = console.log;
  console.log = (...items) => {
    logs.push(items.map(String).join(" "));
  };
  try {
    return { value: canonical(run()), logs };
  } catch (error) {
    return { error: `${error?.name}: ${error?.message}`, logs };
  } finally {
    console.log = log;
  }
}

const ENTRY_POINTS = Object.freeze([
  ["braces()", (braces, input, options) => braces(input, options)],
  ["braces.create", (braces, input, options) => braces.create(input, options)],
  ["braces.expand", (braces, input, options) => braces.expand(input, options)],
  ["braces.compile", (braces, input, options) => braces.compile(input, options)],
  ["braces.parse", (braces, input, options) => braces.parse(input, options)],
  ["braces.stringify", (braces, input, options) => braces.stringify(input, options)],
]);
// escapeInvalid is excluded here on purpose: the patch changes it (pinned in its own test below).
const OPTION_SETS = Object.freeze([
  undefined,
  {},
  { expand: true },
  FAST_GLOB_BRACE_OPTIONS,
  { nodupes: true },
  { keepQuotes: true },
  { keepEscaping: true },
  { optimize: false },
  { bash: false },
  { minimatch: false, optimize: false },
  { expand: true, rangeLimit: 5 },
  { maxLength: 24 },
]);

function nestedSet(depth, open, close, core) {
  return open.repeat(depth) + core + close.repeat(depth);
}

function mixedSet(depth, core) {
  let left = "";
  let right = "";
  for (let index = 0; index < depth; index += 1) {
    const brace = index % 2 === 0;
    left += brace ? "{" : "(";
    right = (brace ? "}" : ")") + right;
  }
  return left + core + right;
}

const ADDITIONAL_INPUTS = Object.freeze([
  "{a,b}",
  "a/{b,c}/d",
  "{1..10}",
  "{a..e}",
  "x{01..10..2}y",
  "{-5..5}",
  "{1..3}{a..c}",
  "\\{a,b}",
  "{a,b\\}",
  "{a\\,b,c}",
  "a\\,b",
  "'{a,b}'",
  '"{a,b}"',
  "{a,'b,c'}",
  "./src/**/*.{js,ts}",
  "./locales/*.{mjs,js,mts,ts,jsx,tsx,json}",
  "./views/**/*.{mjs,js,mts,ts,jsx,tsx,json}",
  "./views/**/*/index.{mjs,js,mts,ts,jsx,tsx,json}",
  "./pages/**/*/index.{mjs,js,mts,ts,jsx,tsx,json}",
  "{src,test}/**/*.{js,jsx}",
  "@(a|b){c,d}",
  "*(a|{b|c,d})",
  ...[1, 2, 5, 50, 99, 100].flatMap((depth) => [
    nestedSet(depth, "{", "}", "a,b"),
    nestedSet(depth, "(", ")", "a|b"),
    "{a,".repeat(depth) + "b" + "}".repeat(depth),
    mixedSet(depth, "a,b"),
  ]),
]);

test("ordinary patterns produce exactly the released braces 3.0.3 results", () => {
  const vendored = load(consumerChain().braces);
  const { braces: released } = upstreamBraces();
  const corpus = JSON.parse(readFileSync(path.join(testDirectory, "bounded-braces.upstream-inputs.json"), "utf8"));
  assert.ok(corpus.inputs.length >= 400, "the upstream test-input corpus is present");
  const inputs = [...corpus.inputs, ...ADDITIONAL_INPUTS];
  const mismatches = [];
  let compared = 0;
  for (const input of inputs) {
    for (const options of OPTION_SETS) {
      for (const [entry, run] of ENTRY_POINTS) {
        const expected = observe(() => run(released, input, options));
        const actual = observe(() => run(vendored, input, options));
        compared += 1;
        if (!isDeepStrictEqual(actual, expected)) mismatches.push({ entry, input, options, expected, actual });
      }
    }
  }
  assert.deepEqual(mismatches.slice(0, 3), []);
  assert.equal(compared, inputs.length * OPTION_SETS.length * ENTRY_POINTS.length);
  assert.deepEqual(observe(() => vendored(["a/{b,c}", "{1..3}"])), observe(() => released(["a/{b,c}", "{1..3}"])));
  // 3.0.3's stray console.log in compile is kept byte for byte. Parsed patterns never mark a node
  // isClose, so only a hand-built AST reaches it; both copies log the same line.
  const closeMarked = () => ({ type: "root", nodes: [{ type: "text", value: "}", isClose: true }] });
  const releasedLog = observe(() => released.compile(closeMarked()));
  assert.deepEqual(releasedLog, { value: "}", logs: ["node.isClose  }"] });
  assert.deepEqual(observe(() => vendored.compile(closeMarked())), releasedLog);
});

test("vite-plugin-dynamic-import builds and expands its real globs through the bounded package", async () => {
  const chain = consumerChain();
  const plugin = load(chain["vite-plugin-dynamic-import"]);
  const acorn = createRequire(chain["vite-plugin-dynamic-import"])("acorn");
  // The very module object the plugin calls fastGlob.sync on.
  const fastGlob = load(chain["fast-glob"]);
  const vendored = load(chain.braces);
  const { braces: released } = upstreamBraces();
  // vite-plugin-dynamic-import 1.6.0 DEFAULT_EXTENSIONS
  const extensions = [".mjs", ".js", ".mts", ".ts", ".jsx", ".tsx", ".json"];
  const fixture = mkdtempSync(path.join(tmpdir(), "atlas-braces-globs-"));
  const files = [
    "main.js",
    "locales/en.json",
    "locales/fr.json",
    "views/home.js",
    "views/notes.md",
    "views/about/index.ts",
    "views/about/team.tsx",
    "pages/blog/index.jsx",
    "pages/blog/post.js",
    "pages/shop/index.mts",
  ];
  for (const relative of files) {
    mkdirSync(path.dirname(path.join(fixture, relative)), { recursive: true });
    writeFileSync(path.join(fixture, relative), "export default 1;\n");
  }
  const tick = String.fromCharCode(96);
  const expressions = {
    [`import(${tick}./locales/\${lang}.json${tick})`]: ["./locales/en.json", "./locales/fr.json"],
    [`import(${tick}./views/\${name}${tick})`]: ["./views/about/index.ts", "./views/about/team.tsx", "./views/home.js"],
    "import('./pages/' + section + '/index')": ["./pages/blog/index.jsx", "./pages/shop/index.mts"],
  };
  const globFiles = (expression) =>
    plugin.globFiles({
      importeeNode: acorn.parse(expression, { sourceType: "module", ecmaVersion: 2020 }).body[0].expression.source,
      importExpression: expression,
      importer: path.join(fixture, "main.js"),
      resolve: { tryResolve: async () => undefined },
      extensions,
      loose: true,
    });
  const captured = [];
  const sync = fastGlob.sync;
  try {
    fastGlob.sync = (patterns, options) => {
      captured.push(...[].concat(patterns));
      return sync(patterns, options);
    };
    for (const [expression, expected] of Object.entries(expressions)) {
      const result = await globFiles(expression);
      assert.deepEqual([...result.files].sort(), expected, expression);
    }
    fastGlob.sync = sync;
    const hostile = `import(${tick}./views/\${name}${"{".repeat(101)}a,b${"}".repeat(101)}.js${tick})`;
    await assert.rejects(globFiles(hostile), INPUT_DEPTH_REFUSAL);
  } finally {
    fastGlob.sync = sync;
    rmSync(fixture, { recursive: true, force: true });
  }
  const braceGlobs = captured.filter((glob) => glob.includes("{"));
  assert.ok(braceGlobs.length >= 4, `the plugin built brace globs: ${JSON.stringify(captured)}`);
  for (const glob of captured) {
    assert.deepEqual(
      observe(() => vendored(glob, FAST_GLOB_BRACE_OPTIONS)),
      observe(() => released(glob, FAST_GLOB_BRACE_OPTIONS)),
      glob,
    );
  }
});

test("the patch's behaviour beyond the depth bound is pinned and unreachable from the installed edge", () => {
  const chain = consumerChain();
  const vendored = load(chain.braces);
  const { braces: released } = upstreamBraces();

  // 1. stringify now passes the real parent, which changes escapeInvalid output.
  for (const [input, releasedOutput, patchedOutput] of [
    ["{{a}}", "{{a}}", "\\{\\{a\\}\\}"],
    ["{a}", "{a}", "\\{a\\}"],
    ["a{b}c", "a{b}c", "a\\{b\\}c"],
    ["{1..8}", "{1..8}", "\\{1..8\\}"],
    ["{a,{b}}", "{a,{b}}", "{a,\\{b\\}}"],
  ]) {
    assert.equal(released.stringify(input, { escapeInvalid: true }), releasedOutput, input);
    assert.equal(vendored.stringify(input, { escapeInvalid: true }), patchedOutput, input);
  }
  // 2. A fractional maxDepth is admitted by parse but refused by the walkers.
  assert.equal(vendored.parse("{{a,b},c}", { maxDepth: 1.5 }).type, "root");
  assert.throws(() => vendored.compile("{{a,b},c}", { maxDepth: 1.5 }), {
    name: "RangeError",
    message: "AST depth (2), exceeds max depth (1.5)",
  });
  assert.throws(() => vendored.parse("{{a,b},c}", { maxDepth: 1 }), {
    name: "SyntaxError",
    message: "Input depth (2), exceeds max depth (1)",
  });
  assert.equal(vendored.compile("{{a,b},c}", { maxDepth: 2 }), "((a|b)|c)");
  // 3. A missing AST fails with a different TypeError message.
  assert.throws(() => released.compile(), { name: "TypeError", message: /reading 'invalid'/ });
  assert.throws(() => vendored.compile(), { name: "TypeError", message: /reading 'type'/ });

  // None of it is reachable here: no package between Vinext and braces names either option, and
  // fast-glob calls micromatch.braces with one fixed option set.
  const sources = [];
  for (const name of ["vite-plugin-commonjs", "vite-plugin-dynamic-import", "fast-glob", "micromatch"]) {
    const root = path.dirname(nearestManifest(chain[name]).path);
    for (const relative of listFiles(root, { skipNodeModules: true })) {
      if (!/\.[cm]?js$/.test(relative)) continue;
      sources.push([`${name}/${relative}`, readFileSync(path.join(root, ...relative.split("/")), "utf8")]);
    }
  }
  assert.ok(sources.length > 10);
  assert.deepEqual(
    sources.filter(([, text]) => /escapeInvalid|maxDepth/.test(text)).map(([name]) => name),
    [],
  );
  const callers = sources.filter(([, text]) => /\bbraces\(|micromatch\.braces\(|micromatch\.braceExpand\(/.test(text));
  assert.deepEqual(callers.map(([name]) => name).sort(), ["fast-glob/out/utils/pattern.js", "micromatch/index.js"]);
  const fastGlobPattern = callers.find(([name]) => name === "fast-glob/out/utils/pattern.js")[1];
  assert.deepEqual(fastGlobPattern.match(/micromatch\.braces\([^)]*\)/g), [
    "micromatch.braces(pattern, { expand: true, nodupes: true, keepEscaping: true })",
  ]);
});

test("Vite's compiled bundle carries its own unbounded braces 3.0.3 copy outside npm resolution", () => {
  // npm overrides and npm audit act on packages, not on code compiled into another package's dist.
  // The release gate models this copy separately; this pins the installed fact it relies on.
  const viteManifest = path.join(projectRoot, "node_modules", "vite", "package.json");
  const vite = JSON.parse(readFileSync(viteManifest, "utf8"));
  assert.equal(vite.version, "8.2.0");
  const bundle = readFileSync(path.join(path.dirname(viteManifest), "dist", "node", "chunks", "node.js"), "utf8");
  assert.ok(bundle.includes("//#region ../../node_modules/.pnpm/braces@3.0.3/node_modules/braces/lib/parse.js"));
  assert.ok(bundle.includes("node_modules/.pnpm/chokidar@3.6.0"));
  assert.ok(bundle.includes("exceeds max characters"));
  assert.equal(bundle.includes("exceeds max depth"), false, "the compiled copy has no depth guard");
  // Vite's dev server watcher disables chokidar globbing, the only bundled caller of braces.expand.
  assert.ok(bundle.includes("disableGlobbing: true,\n\t\t...serverConfig.watch"));
  assert.ok(bundle.includes("(path.includes(BRACE_START) ? braces.expand(path) : [path])"));
});
