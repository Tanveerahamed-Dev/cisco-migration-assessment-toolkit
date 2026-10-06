/** Hosted-only independent witnesses for A6 placement and reporting guards.
 * Mutants are temporary diagnostic source, never build/release inputs. Restore
 * the original bytes even when a witness fails; retain every failed observation.
 */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { closeSync, constants, existsSync, fstatSync, ftruncateSync, mkdirSync, openSync, readFileSync, realpathSync, writeFileSync, writeSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const PKG = realpathSync(resolve(dirname(fileURLToPath(import.meta.url)), ".."));
const ROOT = realpathSync(resolve(PKG, ".."));
const SOURCE = "atlas-scope/src/fabric3d/FabricLabels.tsx";
const TEST = "src/fabric3d/FabricLabels.marks.test.tsx";
const MAX_BYTES = 16 * 1024 * 1024;
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const requireThat = (ok, message) => { if (!ok) throw new Error(message); };
const inside = (parent, child) => {
  const p = relative(parent, child);
  return p === "" || (!isAbsolute(p) && p !== ".." && !p.startsWith(`..${sep}`));
};
const arg = (name) => {
  const at = process.argv.indexOf(name);
  requireThat(at > 0 && typeof process.argv[at + 1] === "string", `required argument ${name}`);
  return process.argv[at + 1];
};
const git = (...args) => {
  const result = spawnSync("git", ["--no-optional-locks", ...args], {
    cwd: ROOT, timeout: 30000, maxBuffer: MAX_BYTES,
  });
  requireThat(result.status === 0 && !result.error, `read-only git ${args[0]} failed`);
  return result.stdout;
};
function writeNew(path, bytes) {
  const fd = openSync(path, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
  try { writeFileSync(fd, bytes); } finally { closeSync(fd); }
}
function readBounded(path) {
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const stat = fstatSync(fd);
    requireThat(stat.isFile() && stat.nlink === 1 && stat.size <= MAX_BYTES, "nonregular or oversized evidence");
    const bytes = readFileSync(fd);
    requireThat(bytes.length === stat.size && fstatSync(fd).size === stat.size, "evidence changed during read");
    return bytes;
  } finally { closeSync(fd); }
}
function replaceBytes(fd, bytes) {
  ftruncateSync(fd, 0);
  let written = 0;
  while (written < bytes.length) {
    const n = writeSync(fd, bytes, written, bytes.length - written, written);
    requireThat(n > 0, "source write made no progress");
    written += n;
  }
}

requireThat(process.env.GITHUB_ACTIONS === "true" && process.env.RUNNER_ENVIRONMENT === "github-hosted"
  && process.platform === "linux", "A6 mutation execution requires a GitHub-hosted Linux runner");
const expected = arg("--expected-commit");
requireThat(/^[0-9a-f]{40}$/.test(expected) && git("rev-parse", "HEAD").toString().trim() === expected,
  "checkout does not match independently selected workflow commit");
const outArg = arg("--output");
requireThat(isAbsolute(outArg) && !existsSync(outArg), "output must be an absolute fresh path");
const output = join(realpathSync(dirname(outArg)), outArg.slice(dirname(outArg).length + 1));
const runnerTemp = realpathSync(process.env.RUNNER_TEMP ?? "");
requireThat(output === resolve(outArg) && inside(runnerTemp, output) && !inside(ROOT, output),
  "evidence must be in the runner temporary directory outside the checkout");
requireThat(git("status", "--porcelain=v1", "--untracked-files=all").length === 0, "initial source is not clean");
mkdirSync(output, { mode: 0o700 });

const mutations = [
  {
    id: "placement-only",
    before: " || (marked && outsideStage(t))",
    after: "",
    witness: "moves a shown cut mark wholly inside the bottom edge without any reporting callback",
    marker: "A6_PLACEMENT_PHYSICAL_BOUNDS",
  },
  {
    id: "reporting-only",
    before: 'publishReport(stageW > 0 && stageHeightNow() > 0 ? "ready" : "unmeasured", outOfView, coveredMarks);',
    after: 'publishReport(stageW > 0 && stageHeightNow() > 0 ? "ready" : "unmeasured", [], []);',
    witness: "names a physically clipped cut mark when no whole placement can exist",
    marker: "A6_REPORTING_PHYSICAL_CLIP",
  },
];
const summary = {
  schema: "atlas-scope.a6-guard-mutations/1", status: "FAIL", qualification: false,
  checkout_commit: expected, checkout_tree: git("rev-parse", "HEAD^{tree}").toString().trim(),
  run_id: process.env.GITHUB_RUN_ID, run_attempt: process.env.GITHUB_RUN_ATTEMPT,
  source: SOURCE, test: TEST, observations: [], restored: false,
  limits: "Synthetic guard witnesses only. No rendered browser, canvas, performance or acceptance re-grade proof.",
};
const original = git("show", `${expected}:${SOURCE}`);
const initialIndex = git("ls-files", "--stage", "-z");
const testBytes = readBounded(join(PKG, TEST));
summary.source_sha256 = sha(original);
summary.test_sha256 = sha(testBytes);
const sourcePath = join(ROOT, SOURCE);
requireThat(realpathSync(sourcePath) === sourcePath, "source path is indirect");
const originalText = new TextDecoder("utf-8", { fatal: true }).decode(original);
let fd;
let failure;
let failed = false;
let admitted = false;
let mutationActive = false;
let witnessesComplete = false;
summary.cleanupFailures = [];
summary.ownedMutationWrites = 0;

function sourcePreserved() {
  return readBounded(sourcePath).equals(original) && readBounded(join(PKG, TEST)).equals(testBytes)
    && git("ls-files", "--stage", "-z").equals(initialIndex)
    && git("rev-parse", "HEAD").toString().trim() === expected
    && git("status", "--porcelain=v1", "--untracked-files=all").length === 0;
}
function cleanupFailure(phase, error) {
  failed = true;
  failure ??= error;
  summary.cleanupFailures.push({ phase, error: String(error) });
}
function restoreOwned(phase) {
  // A refusal before our first write must never overwrite unrelated drift.
  if (!mutationActive) return true;
  try {
    replaceBytes(fd, original);
    requireThat(readBounded(sourcePath).equals(original), "owned source restoration readback failed");
    mutationActive = false;
    return true;
  } catch (error) {
    cleanupFailure(phase, error);
    return false;
  }
}

function runCases(label) {
  const reportPath = join(output, `${label}.json`);
  const result = spawnSync(process.execPath, [join(PKG, "node_modules/vitest/vitest.mjs"), "run", TEST,
    "--reporter=json", "--outputFile", reportPath], {
    cwd: PKG, timeout: 180000, maxBuffer: MAX_BYTES, env: { ...process.env, GIT_OPTIONAL_LOCKS: "0" },
  });
  writeNew(join(output, `${label}.stdout.log`), result.stdout ?? Buffer.alloc(0));
  writeNew(join(output, `${label}.stderr.log`), result.stderr ?? Buffer.alloc(0));
  requireThat(!result.error && result.signal === null && (result.status === 0 || result.status === 1),
    `${label} runner failed or exceeded its bound`);
  const reportRaw = readBounded(reportPath);
  const report = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(reportRaw));
  requireThat(Array.isArray(report.testResults) && report.testResults.length === 1,
    `${label} must collect exactly the declared test file`);
  const suite = report.testResults[0];
  requireThat(resolve(suite.name) === join(PKG, TEST) && Array.isArray(suite.assertionResults),
    `${label} suite identity missing`);
  const cases = suite.assertionResults;
  requireThat(cases.length > 0 && cases.every((c) => typeof c.fullName === "string"
    && (c.status === "passed" || c.status === "failed"))
    && new Set(cases.map((c) => c.fullName)).size === cases.length,
  `${label} has missing, duplicate or skipped cases`);
  requireThat(report.numTotalTests === cases.length && report.numPendingTests === 0
    && report.numFailedTests === cases.filter((c) => c.status === "failed").length
    && report.numPassedTests === cases.filter((c) => c.status === "passed").length,
  `${label} printed census does not reconcile`);
  summary.observations.push({ label, exit_code: result.status, report_sha256: sha(reportRaw),
    total: cases.length, failed: report.numFailedTests, passed: report.numPassedTests,
    failed_cases: cases.filter((c) => c.status === "failed").map((c) => c.fullName) });
  return { report, cases, exitCode: result.status };
}

try {
  fd = openSync(sourcePath, constants.O_RDWR | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  const sourceStat = fstatSync(fd);
  requireThat(sourceStat.isFile() && sourceStat.nlink === 1 && sourceStat.size <= MAX_BYTES,
    "source is not an ordinary bounded file");
  requireThat(readFileSync(fd).equals(original), "working source differs from committed source");
  admitted = true;
  for (const mutation of mutations) {
    requireThat(originalText.split(mutation.before).length === 2, `mutation anchor is not unique: ${mutation.id}`);
  }
  const baseline = runCases("baseline");
  requireThat(baseline.exitCode === 0 && baseline.report.success === true && baseline.report.numFailedTests === 0,
    "unmodified focused baseline must pass");
  const baselineNames = baseline.cases.map((c) => c.fullName).sort();
  for (const mutation of mutations) {
    const selected = baseline.cases.filter((c) => c.fullName.endsWith(mutation.witness));
    requireThat(selected.length === 1, `missing/ambiguous baseline witness: ${mutation.id}`);
    const mutated = Buffer.from(originalText.replace(mutation.before, mutation.after));
    requireThat(sourcePreserved(), "unexpected source drift before owned mutation");
    try {
      // Ownership starts before truncation, so a partial write is ours to repair.
      mutationActive = true;
      summary.ownedMutationWrites += 1;
      replaceBytes(fd, mutated);
      const result = runCases(mutation.id);
      requireThat(JSON.stringify(result.cases.map((c) => c.fullName).sort()) === JSON.stringify(baselineNames),
        `${mutation.id} changed the case census`);
      const witness = result.cases.find((c) => c.fullName === selected[0].fullName);
      requireThat(result.exitCode === 1 && result.report.success === false && witness?.status === "failed"
        && Array.isArray(witness.failureMessages)
        && witness.failureMessages.some((s) => typeof s === "string" && s.includes(`AssertionError: ${mutation.marker}`)),
      `${mutation.id} did not refute the intended independent assertion`);
      summary.observations.at(-1).mutated_source_sha256 = sha(mutated);
      summary.observations.at(-1).required_witness = witness.fullName;
    } finally {
      requireThat(restoreOwned(`${mutation.id}-restore`), "owned mutation restoration failed");
    }
  }
  requireThat(sourcePreserved(), "source/index/test state was not restored exactly");
  witnessesComplete = true;
} catch (error) {
  failed = true;
  failure = error;
  summary.failure = String(error);
} finally {
  restoreOwned("final-owned-restore");
  if (fd !== undefined) {
    try { closeSync(fd); } catch (error) { cleanupFailure("source-close", error); }
  }
  summary.initialSourceAdmitted = admitted;
  try {
    summary.sourcePreservedAfter = sourcePreserved();
    if (!summary.sourcePreservedAfter) cleanupFailure("final-readback", new Error("source/index/test state differs"));
  } catch (error) { cleanupFailure("final-readback", error); }
  summary.restored = admitted && !mutationActive && summary.cleanupFailures.length === 0
    && summary.sourcePreservedAfter === true;
  summary.status = witnessesComplete && !failed && summary.restored
    ? "PASS_SEPARATE_SYNTHETIC_GUARD_WITNESSES" : "FAIL";
  // Restoration/readback/close errors still reach this terminal failure record.
  writeNew(join(output, "summary.json"), Buffer.from(JSON.stringify(summary, null, 2) + "\n"));
}
if (summary.status !== "PASS_SEPARATE_SYNTHETIC_GUARD_WITNESSES") {
  throw failure ?? new Error("A6 mutation verification or restoration failed");
}
console.log(summary.status);
