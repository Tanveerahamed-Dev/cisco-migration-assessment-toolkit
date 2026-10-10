/** Hosted, scratch-only dependency resolution. Outputs require review and are never qualification.
 * No package scripts, installs, builds or tests are run by this helper. npm's resolver is NOT a
 * complete transport-origin sandbox: fixed registry/config and source admission do not prove that.
 * Run on the existing pinned frontend job: node .github/scripts/frontend_dependency_prepare.mjs
 */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { closeSync, constants, existsSync, fstatSync, ftruncateSync, mkdirSync, mkdtempSync,
  openSync, readSync, realpathSync, writeSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const PLAN = ".github/frontend-dependency-plan.json";
const PACKAGE = "webapp/frontend/package.json";
const LOCK = "webapp/frontend/package-lock.json";
const INPUTS = [PLAN, PACKAGE, LOCK, ".github/scripts/frontend_dependency_prepare.mjs",
  ".github/scripts/frontend_dependency_prepare.test.mjs", ".github/workflows/webapp-ci.yml"];
const REGISTRY = "https://registry.npmjs.org/";
const MAX_FILE = 16 * 1024 * 1024;
const MAX_REGISTRY = 2 * 1024 * 1024;
const MAX_CHANGES = 32;
// The closed member set main() may write under its fresh output directory. It mirrors the receiver's census
// (frontend_artifact_receive.py :: candidate); any other name is refused before a byte is written.
const FIXED_MEMBERS = new Set(["preparation.json", "npm-version.stdout.log", "npm-version.stderr.log",
  "npm-lock-only.stdout.log", "npm-lock-only.stderr.log", "selected-metadata.json", "dependency-diff.json",
  "candidate.patch", "patch.stderr.log", "candidate/package.json", "candidate/package-lock.json"]);
const METADATA_MEMBER = /^metadata\/(?:0[1-9]|[12][0-9]|3[0-2])\.json$/;
const NAME = /^(?:@[a-z0-9][a-z0-9._-]*\/)?[a-z0-9][a-z0-9._-]*$/;
const VERSION = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;
const GROUPS = ["dependencies", "devDependencies"];
// npm recomputes these booleans from graph reachability/edge kinds, even when the
// same distribution is reached through a newly changed dependency. They do not
// identify package bytes or declared package metadata. Every other key, including
// unknown future keys, is immutable for an unplanned direct dependency.
const GRAPH_FLAGS = ["dev", "optional", "devOptional", "peer"];
const need = (ok, message) => { if (!ok) throw new Error(message); };
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const same = (a, b) => canonical(a) === canonical(b);
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (object(value)) return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  return JSON.stringify(value);
}
function closed(value, keys, label) {
  need(object(value) && same(Object.keys(value).sort(), [...keys].sort()), `${label} has missing or unexpected keys`);
}

/** Bounded JSON with duplicate-key refusal, including escaped duplicate keys. */
export function strictJson(bytes) {
  need(bytes.length <= MAX_FILE, "JSON exceeds its size bound");
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  let at = 0; let nodes = 0;
  const ws = () => { while (/[\t\n\r ]/.test(text[at] ?? "x")) at += 1; };
  const string = () => {
    const start = at++;
    while (at < text.length) {
      if (text[at] === "\\") { at += 2; continue; }
      if (text[at++] === '"') return JSON.parse(text.slice(start, at));
    }
    throw new Error("Unterminated JSON string");
  };
  const value = (depth) => {
    need(depth <= 64 && ++nodes <= 200000, "JSON exceeds its structural bound"); ws();
    if (text[at] === '"') return string();
    if (text[at] === "{") {
      at += 1; ws(); const result = Object.create(null);
      if (text[at] === "}") { at += 1; return result; }
      while (true) {
        need(text[at] === '"', "Invalid JSON object key"); const key = string(); ws();
        need(!Object.hasOwn(result, key), "Duplicate JSON key");
        need(text[at++] === ":", "Invalid JSON object separator"); result[key] = value(depth + 1); ws();
        const end = text[at++]; if (end === "}") return result;
        need(end === ",", "Invalid JSON object delimiter"); ws();
      }
    }
    if (text[at] === "[") {
      at += 1; ws(); const result = [];
      if (text[at] === "]") { at += 1; return result; }
      while (true) {
        result.push(value(depth + 1)); ws(); const end = text[at++];
        if (end === "]") return result;
        need(end === ",", "Invalid JSON array delimiter");
      }
    }
    const token = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(text.slice(at));
    need(token !== null, "Invalid JSON value"); at += token[0].length;
    const result = JSON.parse(token[0]); need(typeof result !== "number" || Number.isFinite(result), "Nonfinite JSON number");
    return result;
  };
  const result = value(0); ws(); need(at === text.length, "Trailing JSON content"); return result;
}

/** The registry-evidence member for the plan's 1-based change index (the plan admits at most 32 changes). */
export function metadataMember(index) {
  need(Number.isInteger(index) && index >= 1 && index <= MAX_CHANGES, "Registry metadata index outside the plan bound");
  return `metadata/${String(index).padStart(2, "0")}.json`;
}
/** A declared output member name, or a refusal: fixed names plus metadata/01.json to metadata/32.json. */
export function outputMember(name) {
  need(typeof name === "string" && (FIXED_MEMBERS.has(name) || METADATA_MEMBER.test(name)), "Undeclared preparation output member");
  return name;
}
/**
 * The only network bytes this helper writes are exact-version registry documents, kept verbatim because the
 * receiver re-admits the raw member against its receipt digest and independently selected registry metadata.
 * They are admitted BEFORE any byte reaches disk: HTTP 200, at most 2 MiB, one strict (bounded, UTF-8,
 * duplicate-key-free) JSON object. A refused response is recorded by status, size and digest only.
 *
 * CodeQL js/http-to-file-access (alert #78, the writeSync in writeOrdinary) reports this intended evidence
 * flow. The destination is never derived from the response: it is a fixed member name (outputMember) under a
 * fresh 0700 directory outside the checkout, opened O_CREAT|O_EXCL|O_NOFOLLOW. The bytes are never executed,
 * installed or imported; they reach review only through frontend_artifact_receive.py's re-admission.
 */
export function registryEvidence(status, bytes) {
  need(bytes instanceof Uint8Array && bytes.length <= MAX_REGISTRY, "Registry response is not a byte buffer within its bound");
  need(status === 200, "Exact requested registry version is unavailable");
  const document = strictJson(bytes);
  need(object(document), "Registry response is not a JSON object");
  return document;
}

export function registryUrl(value) {
  need(typeof value === "string", "Registry source URL missing");
  const url = new URL(value);
  need(url.origin === REGISTRY.slice(0, -1) && url.protocol === "https:" && !url.username && !url.password
    && !url.search && !url.hash && !url.port && url.href === value, "Noncanonical or nonregistry package source");
  return value;
}
function registrySpecs(value, label) {
  need(object(value), `${label} must be an object`);
  for (const [name, spec] of Object.entries(value)) {
    need(NAME.test(name) && typeof spec === "string" && spec.length <= 256
      && /^[0-9A-Za-z .^~*<>=|+-]+$/.test(spec) && !/\b(?:https?|git|file|workspace|link|npm)\b/i.test(spec),
    `${label} contains a nonregistry or unsupported package specification`);
  }
}
function integrity(value) {
  need(typeof value === "string" && /^sha512-[A-Za-z0-9+/]{86}==$/.test(value)
    && Buffer.from(value.slice(7), "base64").toString("base64") === value.slice(7), "Missing canonical SHA-512 registry integrity");
}
function direct(manifest) {
  need(object(manifest) && !Object.hasOwn(manifest, "workspaces") && !Object.hasOwn(manifest, "optionalDependencies"),
    "Unexpected manifest shape");
  const result = new Map();
  for (const section of GROUPS) {
    registrySpecs(manifest[section], section);
    for (const [name, spec] of Object.entries(manifest[section])) {
      need(!result.has(name), "Ambiguous duplicate direct dependency"); result.set(name, { section, spec });
    }
  }
  return result;
}
export function planManifest(plan, manifest) {
  closed(plan, ["schema", "changes"], "Plan");
  need(plan.schema === "frontend-dependency-plan/1" && Array.isArray(plan.changes)
    && plan.changes.length > 0 && plan.changes.length <= 32, "Invalid preparation plan");
  const baseline = direct(manifest); const seen = new Set(); const next = structuredClone(manifest);
  for (const change of plan.changes) {
    closed(change, ["section", "name", "from", "to", "version"], "Change");
    need(GROUPS.includes(change.section) && typeof change.name === "string" && NAME.test(change.name)
      && typeof change.version === "string" && VERSION.test(change.version), "Invalid planned target");
    need(!seen.has(change.name), "Duplicate planned target"); seen.add(change.name);
    need(baseline.get(change.name)?.section === change.section && baseline.get(change.name)?.spec === change.from,
      "Plan does not match the current direct specification");
    need(change.to !== change.from && [change.version, `^${change.version}`].includes(change.to),
      "Planned specification is not the reviewed exact or caret target");
    next[change.section][change.name] = change.to;
  }
  return next;
}
export function admitLock(lock, manifest) {
  need(object(lock) && lock.lockfileVersion === 3 && object(lock.packages) && object(lock.packages[""])
    && lock.name === manifest.name && lock.version === manifest.version, "Invalid npm lock identity");
  for (const section of GROUPS) need(same(lock.packages[""][section], manifest[section]), "Root lock declarations differ from manifest");
  need(same(lock.packages[""].engines, manifest.engines), "Root lock engine declaration differs");
  need(Object.keys(lock.packages).length <= 10000, "Lock package census exceeds bound");
  for (const [path, row] of Object.entries(lock.packages)) {
    if (path === "") continue;
    need(/^(?:node_modules\/(?:@[a-z0-9][a-z0-9._-]*\/)?[a-z0-9][a-z0-9._-]*)(?:\/node_modules\/(?:@[a-z0-9][a-z0-9._-]*\/)?[a-z0-9][a-z0-9._-]*)*$/.test(path),
      "Unexpected lock installation path");
    need(object(row) && !row.link && typeof row.version === "string" && VERSION.test(row.version), "Nonordinary locked package");
    for (const flag of GRAPH_FLAGS) need(row[flag] === undefined || typeof row[flag] === "boolean", "Invalid graph classification flag");
    registryUrl(row.resolved);
    integrity(row.integrity);
    for (const field of ["dependencies", "optionalDependencies", "peerDependencies"])
      if (row[field] !== undefined) registrySpecs(row[field], `Lock ${field}`);
  }
  for (const name of direct(manifest).keys()) need(object(lock.packages[`node_modules/${name}`]), "Missing direct installed package");
}
export function admitMetadata(metadata, change) {
  need(object(metadata) && metadata.name === change.name && metadata.version === change.version, "Registry metadata identity mismatch");
  need(typeof metadata.license === "string" && metadata.license.length > 0, "Registry license is missing or requires separate review");
  need(object(metadata.dist), "Registry distribution metadata missing"); registryUrl(metadata.dist.tarball);
  integrity(metadata.dist.integrity);
  for (const field of ["dependencies", "optionalDependencies", "peerDependencies"])
    if (metadata[field] !== undefined) registrySpecs(metadata[field], `Metadata ${field}`);
  need(metadata.engines === undefined || object(metadata.engines) && Object.values(metadata.engines).every((v) => typeof v === "string"),
    "Invalid engine metadata");
  need(metadata.peerDependenciesMeta === undefined || object(metadata.peerDependenciesMeta), "Invalid optional peer metadata");
  return { name: metadata.name, version: metadata.version, license: metadata.license,
    engines: metadata.engines ?? null, peerDependencies: metadata.peerDependencies ?? {},
    peerDependenciesMeta: metadata.peerDependenciesMeta ?? {}, dependencies: metadata.dependencies ?? {},
    optionalDependencies: metadata.optionalDependencies ?? {}, dist: metadata.dist };
}
export function admitCandidate(plan, beforeManifest, beforeLock, candidateManifest, candidateLock, metadata) {
  const wanted = planManifest(plan, beforeManifest);
  need(same(candidateManifest, wanted), "Candidate changed an unrequested manifest field");
  admitLock(beforeLock, beforeManifest); admitLock(candidateLock, wanted);
  const withoutPackages = (value) => Object.fromEntries(Object.entries(value).filter(([key]) => key !== "packages"));
  need(same(withoutPackages(beforeLock), withoutPackages(candidateLock)), "Candidate changed non-package lock metadata");
  const rootExpected = structuredClone(beforeLock.packages[""]);
  for (const section of GROUPS) rootExpected[section] = wanted[section];
  need(same(rootExpected, candidateLock.packages[""]), "Candidate changed unrequested root lock fields");
  const changes = new Map(plan.changes.map((change) => [change.name, change]));
  for (const name of direct(beforeManifest).keys()) {
    const old = beforeLock.packages[`node_modules/${name}`]; const next = candidateLock.packages[`node_modules/${name}`];
    const change = changes.get(name); const target = change?.version ?? old.version;
    need(next.version === target, `Unreviewed resolved direct version: ${name}`);
    if (change) {
      const published = metadata.get(name); need(published !== undefined, "Selected metadata missing");
      need(next.resolved === published.dist.tarball && next.integrity === published.dist.integrity,
        "Selected direct bytes disagree with exact registry metadata");
      need(same(next.engines ?? null, published.engines) && same(next.peerDependencies ?? {}, published.peerDependencies)
        && same(next.peerDependenciesMeta ?? {}, published.peerDependenciesMeta)
        && same(next.dependencies ?? {}, published.dependencies) && same(next.optionalDependencies ?? {}, published.optionalDependencies)
        && next.license === published.license,
      "Selected direct peer/engine/license metadata differs from lock");
    } else {
      const distribution = (row) => Object.fromEntries(Object.entries(row).filter(([key]) => !GRAPH_FLAGS.includes(key)));
      need(same(distribution(old), distribution(next)), `Unreviewed distribution or declared metadata change for unchanged direct: ${name}`);
    }
  }
  return dependencyDiff(plan, beforeManifest, beforeLock, candidateManifest, candidateLock);
}
/** Observation only: emitted even for a refused candidate, with full changed lock rows. */
export function dependencyDiff(plan, beforeManifest, beforeLock, candidateManifest, candidateLock) {
  need(object(beforeLock?.packages) && object(candidateLock?.packages) && object(candidateManifest), "Cannot describe incomplete candidate graph");
  const planned = new Set(plan.changes.map((change) => change.name));
  const directs = [...direct(beforeManifest)].map(([name, row]) => ({ name, section: row.section,
    disposition: planned.has(name) ? "planned" : "unchanged-direct-required",
    before: beforeLock.packages[`node_modules/${name}`]?.version ?? null,
    after: candidateLock.packages[`node_modules/${name}`]?.version ?? null,
    before_spec: row.spec, after_spec: candidateManifest[row.section]?.[name] ?? null }));
  const paths = [...new Set([...Object.keys(beforeLock.packages), ...Object.keys(candidateLock.packages)])].sort();
  return { status: "UNAPPROVED_GRAPH_OBSERVATION", manifest_before: beforeManifest, manifest_after: candidateManifest,
    direct: directs, changed_packages: paths.filter((path) => !same(beforeLock.packages[path], candidateLock.packages[path]))
    .map((path) => ({ path, change: beforeLock.packages[path] === undefined ? "added" : candidateLock.packages[path] === undefined ? "removed" : "modified",
      before: beforeLock.packages[path] ?? null, after: candidateLock.packages[path] ?? null })) };
}

function readOrdinary(path, maximum = MAX_FILE) {
  need(realpathSync(path) === resolve(path), "Indirect source or output file");
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const stat = fstatSync(fd); need(stat.isFile() && stat.nlink === 1 && stat.size <= maximum, "Nonordinary or oversized file");
    const bytes = Buffer.alloc(stat.size + 1); let count = 0;
    while (count < bytes.length) { const n = readSync(fd, bytes, count, bytes.length - count, null); if (n === 0) break; count += n; }
    const end = fstatSync(fd);
    need(count === stat.size && end.size === stat.size && end.mtimeMs === stat.mtimeMs && end.ctimeMs === stat.ctimeMs && end.nlink === 1,
      "File changed during bounded read"); return bytes.subarray(0, count);
  } finally { closeSync(fd); }
}
function writeOrdinary(path, data, replace = false) {
  need(realpathSync(dirname(path)) === dirname(path), "Indirect output directory");
  const bytes = Buffer.isBuffer(data) ? data : Buffer.from(data);
  need(bytes.length <= MAX_FILE, "Output exceeds bound");
  const flags = constants.O_WRONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK
    | (replace ? 0 : constants.O_CREAT | constants.O_EXCL);
  const fd = openSync(path, flags, 0o600);
  try {
    const stat = fstatSync(fd); need(stat.isFile() && stat.nlink === 1, "Nonordinary output file");
    if (replace) ftruncateSync(fd, 0);
    let at = 0;
    while (at < bytes.length) { const n = writeSync(fd, bytes, at, bytes.length - at, at); need(n > 0, "Output write stalled"); at += n; }
  } finally { closeSync(fd); }
}
const jsonBytes = (value) => Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
function git(...args) {
  const result = spawnSync("git", ["--no-optional-locks", "-C", ROOT, ...args], { maxBuffer: MAX_FILE, timeout: 30000 });
  need(!result.error && result.status === 0, `Read-only Git command failed: ${args[0]}`); return result.stdout;
}

async function main() {
  need(process.env.GITHUB_ACTIONS === "true" && process.env.RUNNER_ENVIRONMENT === "github-hosted"
    && process.platform === "linux" && process.version === "v24.19.0", "Preparation requires pinned Node 24.19.0 on GitHub-hosted Linux");
  need(process.argv.length === 2, "Preparation accepts no path, command or URL arguments");
  const temp = realpathSync(process.env.RUNNER_TEMP ?? "");
  const output = join(temp, "frontend-dependency-preparation");
  const inRepo = relative(ROOT, output);
  need(isAbsolute(temp) && (inRepo === ".." || inRepo.startsWith(`..${sep}`)) && !existsSync(output), "Output must be fresh and outside checkout");
  mkdirSync(output, { mode: 0o700 });
  const receipt = { schema: "frontend-dependency-preparation/1", status: "INCOMPLETE_OR_FAILED", errors: [], commands: [],
    selected_source: null, metadata: [], source_preserved: false, candidate_admitted: false,
    qualification: false, dependency_validation: false, independent_custody: false, review_required: true,
    limits: "Scratch-only resolution; no candidate package code/install/test/build execution. npm is not a complete transport-origin sandbox. Registry source admission is not vulnerability or compatibility approval." };
  const receiptPath = join(output, outputMember("preparation.json")); let saved = false;
  const save = () => { writeOrdinary(receiptPath, jsonBytes(receipt), saved); saved = true; };
  save(); const originals = new Map(); let scratch = null;
  const emit = (name, bytes) => writeOrdinary(join(output, outputMember(name)), bytes);
  try {
    const head = git("rev-parse", "HEAD").toString().trim();
    need(/^[0-9a-f]{40}$/.test(head) && head === process.env.GITHUB_SHA, "Checkout does not match exact workflow source");
    need(git("status", "--porcelain=v1", "--untracked-files=no").length === 0, "Tracked checkout is not clean");
    const inputs = {};
    for (const path of INPUTS) {
      const bytes = readOrdinary(join(ROOT, path));
      need(bytes.equals(git("cat-file", "blob", `${head}:${path}`)), `Input is not the selected tracked Git blob: ${path}`);
      originals.set(path, bytes); inputs[path] = { sha256: hash(bytes), bytes: bytes.length, git_blob: git("rev-parse", `${head}:${path}`).toString().trim() };
    }
    receipt.selected_source = { head, tree: git("rev-parse", "HEAD^{tree}").toString().trim(), inputs,
      run_id: process.env.GITHUB_RUN_ID, run_attempt: process.env.GITHUB_RUN_ATTEMPT, job: process.env.GITHUB_JOB,
      runner_os: process.env.RUNNER_OS, runner_environment: process.env.RUNNER_ENVIRONMENT, node: process.version };
    save();
    const plan = strictJson(originals.get(PLAN)); const manifest = strictJson(originals.get(PACKAGE));
    const lock = strictJson(originals.get(LOCK)); const wanted = planManifest(plan, manifest); admitLock(lock, manifest);
    scratch = mkdtempSync(join(temp, "frontend-dependency-scratch-"));
    const candidate = join(scratch, "candidate"); const config = join(scratch, "config");
    for (const directory of [candidate, config, join(scratch, "cache"), join(scratch, "tmp")]) mkdirSync(directory, { mode: 0o700 });
    writeOrdinary(join(candidate, "package.json"), jsonBytes(wanted));
    writeOrdinary(join(candidate, "package-lock.json"), originals.get(LOCK));
    for (const name of ["user.npmrc", "global.npmrc"]) writeOrdinary(join(config, name), "");
    const node = realpathSync(process.execPath); const npm = realpathSync(join(dirname(node), "npm"));
    need(npm === join(dirname(dirname(node)), "lib", "node_modules", "npm", "bin", "npm-cli.js"), "Unexpected npm toolchain location");
    const env = { PATH: `${dirname(node)}:/usr/bin:/bin`, LANG: "C.UTF-8", LC_ALL: "C.UTF-8", CI: "true", TMPDIR: join(scratch, "tmp") };
    if (process.env.HOME !== undefined) env.HOME = process.env.HOME; // Preserve HOME; private explicit npm configs supersede user/global files.
    const options = ["--registry=" + REGISTRY, "--userconfig=" + join(config, "user.npmrc"),
      "--globalconfig=" + join(config, "global.npmrc"), "--cache=" + join(scratch, "cache"),
      "--git=/usr/bin/false", "--engine-strict", "--ignore-scripts", "--audit=false", "--fund=false",
      "--update-notifier=false", "--fetch-retries=0", "--fetch-timeout=30000"];
    const command = (name, args, timeout) => {
      const result = spawnSync(node, [npm, ...options, ...args], { cwd: candidate, env, timeout, maxBuffer: MAX_FILE });
      emit(`${name}.stdout.log`, result.stdout ?? Buffer.alloc(0)); emit(`${name}.stderr.log`, result.stderr ?? Buffer.alloc(0));
      receipt.commands.push({ name, argv: [node, npm, ...options, ...args], exit_code: result.status, signal: result.signal,
        error: result.error?.message ?? null }); save();
      need(!result.error && result.signal === null && result.status === 0, `${name} failed; preserved stdout/stderr are not a candidate approval`);
      return result.stdout.toString().trim();
    };
    receipt.toolchain = { node, node_version: process.version, npm_cli: npm, npm_version: command("npm-version", ["--version"], 30000) };
    const metadata = new Map(); mkdirSync(join(output, "metadata"), { mode: 0o700 });
    for (const [index, change] of plan.changes.entries()) {
      const url = `${REGISTRY}${encodeURIComponent(change.name)}/${encodeURIComponent(change.version)}`;
      const response = await fetch(url, { redirect: "error", signal: AbortSignal.timeout(30000), headers: { accept: "application/json" } });
      need(response.body !== null, "Registry response has no body"); const pieces = []; let size = 0;
      for await (const chunk of response.body) { size += chunk.length; need(size <= MAX_REGISTRY, "Registry response exceeds bound"); pieces.push(chunk); }
      const bytes = Buffer.concat(pieces); const file = metadataMember(index + 1);
      // Account for the response first (status, size, digest); its bytes reach disk only once admitted.
      const observation = { requested: change, url, status: response.status, file: null, bytes: size, sha256: hash(bytes) };
      receipt.metadata.push(observation); save();
      const document = registryEvidence(response.status, bytes);
      emit(file, bytes); observation.file = file; save();
      metadata.set(change.name, admitMetadata(document, change));
    }
    emit("selected-metadata.json", jsonBytes(Object.fromEntries(metadata)));
    command("npm-lock-only", ["install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund", "--engine-strict",
      "--force=false", "--legacy-peer-deps=false", "--workspaces=false"], 600000);
    need(!existsSync(join(candidate, "node_modules")), "Preparation unexpectedly installed a package tree");
    const packageBytes = readOrdinary(join(candidate, "package.json")); const lockBytes = readOrdinary(join(candidate, "package-lock.json"));
    need(packageBytes.equals(jsonBytes(wanted)), "npm changed the requested manifest bytes");
    const candidateManifest = strictJson(packageBytes); const candidateLock = strictJson(lockBytes);
    emit("dependency-diff.json", jsonBytes(dependencyDiff(plan, manifest, lock, candidateManifest, candidateLock)));
    admitCandidate(plan, manifest, lock, candidateManifest, candidateLock, metadata);
    const patchRoot = join(scratch, "patch");
    for (const side of ["a", "b"]) mkdirSync(join(patchRoot, side, "webapp", "frontend"), { recursive: true, mode: 0o700 });
    for (const [path, before, after] of [[PACKAGE, originals.get(PACKAGE), packageBytes], [LOCK, originals.get(LOCK), lockBytes]]) {
      writeOrdinary(join(patchRoot, "a", path), before); writeOrdinary(join(patchRoot, "b", path), after);
    }
    const patch = spawnSync("git", ["diff", "--no-index", "--no-ext-diff", "--no-textconv", "--binary", "--src-prefix=", "--dst-prefix=", "--", "a", "b"],
      { cwd: patchRoot, env: { ...env, GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null" }, timeout: 30000, maxBuffer: MAX_FILE });
    emit("candidate.patch", patch.stdout ?? Buffer.alloc(0)); emit("patch.stderr.log", patch.stderr ?? Buffer.alloc(0));
    need(!patch.error && patch.status === 1 && patch.stdout.length > 0, "Candidate Git patch could not be emitted");
    receipt.candidate_admitted = true;
  } catch (error) {
    receipt.errors.push(error instanceof Error ? error.message : String(error));
  } finally {
    // Preserve exact candidate bytes even on resolver/admission failure. They remain unapproved.
    if (scratch !== null) {
      mkdirSync(join(output, "candidate"), { mode: 0o700 });
      for (const name of ["package.json", "package-lock.json"]) {
        try { emit(`candidate/${name}`, readOrdinary(join(scratch, "candidate", name))); }
        catch (error) { receipt.errors.push(`Candidate ${name} preservation failed: ${error.message}`); }
      }
      if (!existsSync(join(output, "dependency-diff.json"))) {
        try {
          emit("dependency-diff.json", jsonBytes(dependencyDiff(strictJson(originals.get(PLAN)), strictJson(originals.get(PACKAGE)),
            strictJson(originals.get(LOCK)), strictJson(readOrdinary(join(scratch, "candidate", "package.json"))),
            strictJson(readOrdinary(join(scratch, "candidate", "package-lock.json"))))));
        } catch (error) { receipt.errors.push(`Candidate graph observation incomplete: ${error.message}`); }
      }
    }
    try {
      need(receipt.selected_source !== null && originals.size === INPUTS.length, "Source selection incomplete");
      for (const [path, bytes] of originals) need(readOrdinary(join(ROOT, path)).equals(bytes), "Selected checkout input changed");
      need(git("rev-parse", "HEAD").toString().trim() === receipt.selected_source.head
        && git("rev-parse", "HEAD^{tree}").toString().trim() === receipt.selected_source.tree
        && git("status", "--porcelain=v1", "--untracked-files=no").length === 0, "Tracked checkout identity changed");
      receipt.source_preserved = true;
    } catch (error) { receipt.errors.push(`Final source preservation failed: ${error.message}`); }
    if (receipt.candidate_admitted && receipt.source_preserved && receipt.errors.length === 0) receipt.status = "PREPARED_REVIEW_REQUIRED";
    save();
  }
  console.log(`${receipt.status}: ${output}; no dependency validation, independent custody, acceptance or release approval`);
  if (receipt.status !== "PREPARED_REVIEW_REQUIRED") process.exitCode = 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
