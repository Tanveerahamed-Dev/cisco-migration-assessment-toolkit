/**
 * mutation-check.mjs — acceptance F3, the "failed before the fix" half, made executable.
 *
 * WHAT F3 ASKS. "Confirmed defects fixed with a regression test that failed before the fix." The only
 * commit of this tree already contains every fix, so for forwarding, blast, layout, query and the
 * compiler that half was prose (docs/refutation.md §0, §7; acceptance report F3). Prose cannot be
 * re-run.
 *
 * WHAT THIS DOES. It copies the CURRENT source into a scratch directory and, one mutation at a time,
 * reverts a guard that a recorded refutation fix added — the named `find` text must occur exactly
 * once, or the mutation is INVALID rather than silently skipped — then runs the regression test that
 * fix names and requires it to go RED with at least one failed assertion. Before any mutation the same
 * tests are run unmutated in the same scratch copy and must be GREEN with at least one test executed,
 * so a red below cannot be explained by a test that was already red or matched nothing.
 *
 * WHAT THIS DOES NOT DO — printed in its output too, because it is the limit on the evidence. It does
 * NOT recreate pre-fix history. A reverted guard is the defect's SHAPE reintroduced into today's code,
 * not the code as it stood before the fix was written. KILLED proves the regression test detects that
 * shape now; it does not prove the test was red on the historical source. That remains prose.
 *
 * THE DENOMINATOR IS THE DOCUMENT, NOT THIS FILE'S LIST. Every engine section of docs/refutation.md
 * (`## N. <Name> — \`<path>\``) names the file it refutes; each such path must be the target of at
 * least one mutation here, so a new engine section with no executable check fails this script instead
 * of being silently outside it.
 *
 * Usage:  node review/mutation-check.mjs            every mutation
 *         node review/mutation-check.mjs --only ID  one (repeatable), still baseline-checked
 *         node review/mutation-check.mjs --list
 * Exit:   0 every mutation KILLED (and every expected-equivalent probe behaved as recorded)
 *         1 any mutation SURVIVED, was INVALID, or its baseline was not green; or an engine the
 *           document names has no mutation
 * Never touches the working tree: every edit happens inside the scratch copy, which is deleted.
 */
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = resolve(HERE, "..");
const SNAPSHOT = resolve(PKG, "..", "webapp", "sample_data", "sample_fleet.snapshot.json");
const DOC = resolve(PKG, "docs", "refutation.md");

/**
 * @typedef {{ file: string, find: string, replace: string }} Edit
 * @typedef {{
 *   id: string, engine: string, record: string, what: string,
 *   edits: Edit[], tests: string[], pattern?: string, rebuild?: string[],
 *   expect?: "killed" | "survives", why?: string
 * }} Mutation
 */

/** @type {Mutation[]} */
const MUTATIONS = [
  /* ── forwarding — src/forwarding/engine.ts (refutation §1; open-issues R17, R19) ─────────────── */
  {
    id: "fwd-received-at-owner",
    engine: "src/forwarding/engine.ts",
    record: "open-issues R17 (receivedAtOwner)",
    what: "a packet addressed to the router's own address is evaluated against its OUTBOUND list again",
    edits: [{ file: "src/forwarding/engine.ts", find: "    if (receivedAs !== undefined) {", replace: "    if (false as boolean && receivedAs !== undefined) {" }],
    tests: ["src/forwarding/router-destined.test.ts"],
  },
  {
    id: "fwd-received-elsewhere",
    engine: "src/forwarding/engine.ts",
    record: "open-issues R17 (receivedElsewhereEvidence)",
    what: "a pass onto a subnet whose destination another collected device owns is 'delivered' again",
    edits: [
      {
        file: "src/forwarding/engine.ts",
        find: "const ownedElsewhere = nonHostEv === null && !undecided ? receivedElsewhereEvidence(dstIp) : null;",
        replace: "const ownedElsewhere = (false as boolean) && nonHostEv === null && !undecided ? receivedElsewhereEvidence(dstIp) : null;",
      },
    ],
    tests: ["src/forwarding/router-destined.test.ts"],
  },
  {
    id: "fwd-null-port-compared",
    engine: "src/forwarding/engine.ts",
    record: "refutation §1.1 defect 2 (null port compared as a number)",
    what: "an unresolved port name is a definite non-match again (both halves of the guard reverted)",
    edits: [
      { file: "src/forwarding/engine.ts", find: "  if (portValue(m.val) === null) {\n", replace: "  if ((false as boolean) && portValue(m.val) === null) {\n" },
      { file: "src/forwarding/engine.ts", find: "  const val = portValue(match.val);\n  if (val === null) return \"maybe\";", replace: "  const val = portValue(match.val);\n  if (val === null) return \"no\";" },
    ],
    tests: ["src/forwarding/producer-trust.test.ts"],
  },
  {
    id: "fwd-counterfactual-cites-generator",
    engine: "src/forwarding/engine.ts",
    record: "open-issues R19 (counterfactual cite rule)",
    what: "the counterexample rationale cites the permit line that GENERATED the candidate when its own trace consulted none",
    edits: [
      {
        file: "src/forwarding/engine.ts",
        find: "    const decided = deliveringAclEvidence(t);",
        replace:
          "    const decided = deliveringAclEvidence(t) ?? ((): HopEvidence | null => { const g = Object.values(aclsOf(host)).flat().find((l) => (l.action ?? \"\").toLowerCase() === \"permit\"); return g === undefined ? null : ({ kind: \"acl\", label: `permitted by ${g.raw}`, raw: g.raw, cite: g.cite } as HopEvidence); })();",
      },
    ],
    tests: ["src/forwarding/engine.counterfactual.test.ts"],
    pattern: "cites the line its own trace was decided by",
  },

  /* ── blast — src/analysis/blast.ts (refutation §2) ──────────────────────────────────────────── */
  {
    id: "blast-ceiling-nan",
    engine: "src/analysis/blast.ts",
    record: "refutation §2 (blast.test.ts: the path-enumeration ceiling is a ceiling)",
    what: "a NaN path limit removes the enumeration bound again",
    edits: [{ file: "src/analysis/blast.ts", find: "  if (!Number.isFinite(requested)) {", replace: "  if ((false as boolean) && !Number.isFinite(requested)) {" }],
    tests: ["src/analysis/blast.test.ts"],
    pattern: "ceiling is a ceiling",
  },
  {
    id: "blast-graph-unfrozen",
    engine: "src/analysis/blast.ts",
    record: "refutation §2 (blast.test.ts: the shared graph is evidence a renderer cannot edit)",
    what: "the memoised topology graph is handed out mutable again",
    edits: [{ file: "src/analysis/blast.ts", find: "  return freezeGraph(graph);", replace: "  return graph;" }],
    tests: ["src/analysis/blast.test.ts"],
    pattern: "renderer cannot edit",
  },

  /* ── layout — src/fabric3d/layout.ts (refutation §3) ────────────────────────────────────────── */
  {
    id: "layout-nonfinite-option",
    engine: "src/fabric3d/layout.ts",
    record: "refutation §3 (layout.test.ts: an unvalidated input)",
    what: "a NaN/Infinity option returns a NaN fabric instead of throwing",
    edits: [
      {
        file: "src/fabric3d/layout.ts",
        find: "  if (!Number.isFinite(v)) throw new Error(`layout: ${name} must be a finite number, got ${v}`);",
        replace: "  if ((false as boolean) && !Number.isFinite(v)) throw new Error(`layout: ${name} must be a finite number, got ${v}`);",
      },
    ],
    tests: ["src/fabric3d/layout.test.ts"],
    pattern: "rejects a non-finite option",
  },
  {
    id: "layout-dropped-is-isolated",
    engine: "src/fabric3d/layout.ts",
    record: "refutation §3 (layout.test.ts: missing evidence rendered as a structural fact)",
    what: "a device whose links were dropped is reported structurally isolated again",
    edits: [
      {
        file: "src/fabric3d/layout.ts",
        find: "    .filter((d) => (adjSorted.get(d.id) ?? []).length === 0 && (droppedByHost.get(d.id) ?? []).length === 0)",
        replace: "    .filter((d) => (adjSorted.get(d.id) ?? []).length === 0)",
      },
    ],
    tests: ["src/fabric3d/layout.test.ts"],
    pattern: "a dropped link is not an absence of neighbours",
  },

  /* ── query — src/core/query.ts (refutation §4) ──────────────────────────────────────────────── */
  {
    id: "query-uncollected-is-empty",
    engine: "src/core/query.ts",
    record: "refutation §4 (query.test.ts: a never-collected device is an evidence gap)",
    what: "a clause scoped only to never-collected devices reads as an empty result, not a gap",
    edits: [
      {
        file: "src/core/query.ts",
        find: "    evidenceBlind: inScope.length > 0 && uncollected.length === inScope.length,",
        replace: "    evidenceBlind: false,",
      },
    ],
    tests: ["src/core/query.test.ts"],
    pattern: "never-collected device is an evidence gap",
  },

  /* ── compiler — tools/compile-snapshot.mjs (refutation §5). Mutated, RE-RUN in the scratch copy
        against the scratch snapshot, and only then tested: the fidelity tests read the compiled
        model, so a compiler mutation that is not rebuilt would test the shipped bytes. ─────────── */
  {
    id: "compiler-drops-unevaluable",
    engine: "tools/compile-snapshot.mjs",
    record: "refutation §5 (compiler-fidelity.test.ts: unevaluable)",
    what: "the producer's own `unevaluable` verdict is dropped at compilation again",
    edits: [{ file: "tools/compile-snapshot.mjs", find: "      unevaluable: l.unevaluable === true,", replace: "      unevaluable: false," }],
    rebuild: ["tools/compile-snapshot.mjs"],
    tests: ["src/core/compiler-fidelity.test.ts"],
    pattern: "unevaluable",
  },
  {
    id: "compiler-drops-established",
    engine: "tools/compile-snapshot.mjs",
    record: "refutation §5 (compiler-fidelity.test.ts: established)",
    what: "`established`, a stateful match a forward model cannot decide, is dropped again",
    edits: [{ file: "tools/compile-snapshot.mjs", find: "      established: l.established === true,", replace: "      established: false," }],
    rebuild: ["tools/compile-snapshot.mjs"],
    tests: ["src/core/compiler-fidelity.test.ts"],
    pattern: "established",
  },

  /* ── claims — src/core/claims.ts (refutation §6; open-issues R16) ───────────────────────────── */
  {
    id: "claims-c1-empty-traversal",
    engine: "src/core/claims.ts",
    record: "refutation §6 C1 (both owners of the empty-traversal rule reverted)",
    what: "a traversal that visited nothing earns SCOPED again",
    edits: [
      { file: "src/core/claims.ts", find: "  if (trace.hops.length === 0) return \"INDETERMINATE\";", replace: "" },
      { file: "src/core/claims.ts", find: "  if (last === undefined) return false;", replace: "  if (last === undefined) return true;" },
    ],
    tests: ["src/core/claims.test.ts"],
  },
  {
    id: "claims-c1-guard-alone",
    engine: "src/core/claims.ts",
    record: "refutation §6 C1 (the claimBadge empty-hop line alone; acceptance F2)",
    what: "the claimBadge empty-hop guard alone is deleted",
    edits: [{ file: "src/core/claims.ts", find: "  if (trace.hops.length === 0) return \"INDETERMINATE\";", replace: "" }],
    tests: ["src/core/claims.test.ts"],
  },
  {
    id: "claims-c1-guard-alone-delivered-only",
    engine: "src/core/claims.ts",
    record: "refutation §6 C1 (why the guard was unpinned)",
    what: "the same deletion, judged ONLY by the delivered zero-hop case",
    edits: [{ file: "src/core/claims.ts", find: "  if (trace.hops.length === 0) return \"INDETERMINATE\";", replace: "" }],
    tests: ["src/core/claims.test.ts"],
    pattern: "delivered trace with ZERO hops",
    expect: "survives",
    why:
      "EQUIVALENT for decided outcome words: hopsSupportOutcome's `last === undefined` check refuses the same trace, so no delivered fixture can tell the line apart. The unrecognised-outcome case (claims-c1-guard-alone) is the one that isolates it.",
  },
  {
    id: "claims-c3-undefined-band",
    engine: "src/core/claims.ts",
    record: "refutation §6 C3",
    what: "an unrecognised outcome word bands as `undefined` again",
    edits: [
      {
        file: "src/core/claims.ts",
        find: "  const exhaustive: never = outcome;\n  void exhaustive;\n  return \"UNDETERMINED\";",
        replace: "  const exhaustive: never = outcome;\n  void exhaustive;\n  return undefined as never;",
      },
    ],
    tests: ["src/core/claims.test.ts"],
    pattern: "unrecognised verdict bands as UNDETERMINED",
  },
  {
    id: "claims-c2-hops-ignored",
    engine: "src/core/claims.ts",
    record: "refutation §6 C2 / open-issues R16 (hopsSupportOutcome)",
    what: "the badge stops cross-checking the outcome word against the hops",
    edits: [
      {
        file: "src/core/claims.ts",
        find: "export function hopsSupportOutcome(trace: Trace): boolean {\n",
        replace: "export function hopsSupportOutcome(trace: Trace): boolean {\n  if (trace !== null) return true;\n",
      },
    ],
    tests: ["src/core/claims.test.ts"],
    pattern: "C2",
  },
];

/* ── arguments ─────────────────────────────────────────────────────────────────────────────────── */
const argv = process.argv.slice(2);
if (argv.includes("--list")) {
  for (const m of MUTATIONS) console.log(`${m.id.padEnd(40)} ${m.engine.padEnd(28)} ${m.record}`);
  process.exit(0);
}
/** @type {string[]} */
const only = [];
for (let i = 0; i < argv.length; i += 1) if (argv[i] === "--only" && argv[i + 1] !== undefined) only.push(String(argv[++i]));
const unknown = only.filter((id) => !MUTATIONS.some((m) => m.id === id));
if (unknown.length > 0) {
  console.error(`unknown mutation id(s): ${unknown.join(", ")} (see --list)`);
  process.exit(1);
}
const selected = only.length === 0 ? MUTATIONS : MUTATIONS.filter((m) => only.includes(m.id));

console.log("mutation-check — F3 'failed before the fix', executed against TODAY's source");
console.log("LIMIT: this does NOT recreate pre-fix history. Each mutation reverts one recorded guard in a scratch");
console.log("copy of the current tree; KILLED proves the regression test detects that defect shape now, not that");
console.log("it was red on the historical source (which no commit holds).");
console.log("");

/* ── the denominator, read from the document ───────────────────────────────────────────────────── */
/** @type {string[]} */
const documented = [];
for (const line of readFileSync(DOC, "utf8").split(/\r?\n/)) {
  const m = /^## \d+\.\s+.+?\s+—\s+`([^`]+)`/.exec(line);
  if (m !== null && m[1] !== undefined) documented.push(m[1]);
}
const uncovered = documented.filter((p) => !MUTATIONS.some((m) => m.engine === p && m.expect !== "survives"));
if (documented.length === 0) {
  console.error(`FAIL  no engine sections found in ${DOC} — the denominator is empty, so nothing below would mean anything`);
  process.exit(1);
}

/* ── scratch copy ──────────────────────────────────────────────────────────────────────────────── */
if (!existsSync(SNAPSHOT)) {
  console.error(`FAIL  source snapshot not found at ${SNAPSHOT}; the compiler mutations and the snapshot-reading tests need it`);
  process.exit(1);
}
const root = mkdtempSync(join(tmpdir(), "atlas-mutation-"));
const scratch = join(root, "atlas-scope");
mkdirSync(scratch, { recursive: true });
for (const dir of ["src", "tools"]) cpSync(join(PKG, dir), join(scratch, dir), { recursive: true });
for (const f of ["package.json", "vite.config.ts", "vitest.config.ts", "tsconfig.json", "tsconfig.scripts.json", "index.html"]) {
  if (existsSync(join(PKG, f))) cpSync(join(PKG, f), join(scratch, f));
}
symlinkSync(join(PKG, "node_modules"), join(scratch, "node_modules"), "junction");
mkdirSync(join(root, "webapp", "sample_data"), { recursive: true });
cpSync(SNAPSHOT, join(root, "webapp", "sample_data", "sample_fleet.snapshot.json"));
const VITEST = join(PKG, "node_modules", "vitest", "vitest.mjs");

/** @param {string[]} tests @param {string | undefined} pattern */
function runTests(tests, pattern) {
  const args = [VITEST, "run", ...tests, ...(pattern === undefined ? [] : ["-t", pattern])];
  const r = spawnSync(process.execPath, args, { cwd: scratch, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  const out = `${r.stdout ?? ""}\n${r.stderr ?? ""}`.replace(/\[[0-9;]*m/g, "");
  const failed = Number(/Tests\s+(\d+) failed/.exec(out)?.[1] ?? 0);
  const passed = Number(/(\d+) passed/.exec(/Tests\s+[^\n]*/.exec(out)?.[0] ?? "")?.[1] ?? 0);
  const firstFailure = /(AssertionError[^\n]*|Error:[^\n]*)/.exec(out)?.[1] ?? "";
  return { code: r.status ?? -1, failed, passed, firstFailure: firstFailure.slice(0, 160), out };
}

/** @param {string[]} scripts */
function rebuild(scripts) {
  for (const s of scripts) {
    const r = spawnSync(process.execPath, [join(scratch, s)], { cwd: scratch, encoding: "utf8" });
    if (r.status !== 0) return `${s} exited ${r.status}: ${(r.stderr ?? "").trim().split("\n").pop() ?? ""}`;
  }
  return null;
}

/** Pristine bytes of every file a mutation or rebuild can touch, restored after each mutation. */
/** @type {Map<string, Buffer>} */
const pristine = new Map();
const touch = (/** @type {string} */ rel) => {
  if (!pristine.has(rel)) pristine.set(rel, readFileSync(join(scratch, rel)));
};
for (const m of selected) for (const e of m.edits) touch(e.file);
const REBUILT_OUTPUTS = ["src/data/fabric.json"];
if (selected.some((m) => m.rebuild !== undefined)) for (const f of REBUILT_OUTPUTS) touch(f);
const restoreAll = () => {
  for (const [rel, bytes] of pristine) writeFileSync(join(scratch, rel), bytes);
};

/* ── baselines: every (tests, pattern) the mutations use must be green, and non-vacuous, unmutated ── */
/** @param {Mutation} m */
const keyOf = (m) => JSON.stringify([m.tests, m.pattern ?? null]);
/** @type {Map<string, ReturnType<typeof runTests>>} */
const baselines = new Map();
let bad = 0;
for (const m of selected) {
  const key = keyOf(m);
  if (baselines.has(key)) continue;
  const b = runTests(m.tests, m.pattern);
  baselines.set(key, b);
  const ok = b.code === 0 && b.failed === 0 && b.passed > 0;
  console.log(`${ok ? "BASELINE green" : "BASELINE RED  "}  ${m.tests.join(" ")}${m.pattern === undefined ? "" : ` -t "${m.pattern}"`}  (${b.passed} passed, ${b.failed} failed, exit ${b.code})`);
  if (!ok) bad += 1;
}
console.log("");

/* ── mutations ─────────────────────────────────────────────────────────────────────────────────── */
/** @type {Map<string, { killed: number, total: number, problems: string[] }>} */
const byEngine = new Map();
for (const m of selected) {
  restoreAll();
  const e = byEngine.get(m.engine) ?? { killed: 0, total: 0, problems: [] };
  byEngine.set(m.engine, e);
  const expectSurvive = m.expect === "survives";
  if (!expectSurvive) e.total += 1;

  const baseline = baselines.get(keyOf(m));
  let invalid = baseline === undefined || baseline.code !== 0 || baseline.passed === 0 ? "its baseline was not green" : null;
  for (const ed of m.edits) {
    if (invalid !== null) break;
    const text = readFileSync(join(scratch, ed.file), "utf8");
    const count = text.split(ed.find).length - 1;
    if (count !== 1) {
      invalid = `the guard text occurs ${count} time(s) in ${ed.file} (need exactly 1) — the source moved; update this mutation`;
      break;
    }
    writeFileSync(join(scratch, ed.file), text.replace(ed.find, () => ed.replace));
  }
  if (invalid === null && m.rebuild !== undefined) invalid = rebuild(m.rebuild);
  if (invalid !== null) {
    console.log(`INVALID   ${m.id}: ${invalid}`);
    e.problems.push(`${m.id} INVALID`);
    bad += 1;
    continue;
  }
  const r = runTests(m.tests, m.pattern);
  const red = r.failed > 0;
  const where = `${m.tests.join(" ")}${m.pattern === undefined ? "" : ` -t "${m.pattern}"`}`;
  if (expectSurvive) {
    if (red) {
      console.log(`UNEXPECTED ${m.id}: recorded as an equivalent mutant but KILLED (${r.failed} failed) — the record below is stale; update it`);
      e.problems.push(`${m.id} expected-survivor killed`);
      bad += 1;
    } else {
      console.log(`EQUIVALENT ${m.id}: survives, as recorded — ${m.why ?? ""}`);
    }
    continue;
  }
  if (red) {
    e.killed += 1;
    console.log(`KILLED    ${m.id}  [${m.record}]  ${where}: ${r.failed} failed, ${r.passed} passed — ${r.firstFailure}`);
  } else {
    console.log(`SURVIVED  ${m.id}  [${m.record}]  ${where}: ${r.passed} passed, 0 failed (exit ${r.code}) — the test does not catch: ${m.what}`);
    e.problems.push(`${m.id} SURVIVED`);
    bad += 1;
  }
}
restoreAll();
/* Remove the node_modules JUNCTION itself first (rmdir removes the link, never its target), so the
   recursive delete below cannot reach the real node_modules through it. */
rmdirSync(join(scratch, "node_modules"));
rmSync(root, { recursive: true, force: true });

/* ── one verdict line per engine the document names ────────────────────────────────────────────── */
console.log("");
for (const path of documented) {
  const e = byEngine.get(path);
  if (e === undefined) {
    const inList = MUTATIONS.some((m) => m.engine === path);
    console.log(`ENGINE ${path}: ${inList ? "not selected this run" : "NO MUTATION — refutation.md names this engine and nothing here reverts one of its fixes"}`);
    continue;
  }
  const verdict = e.problems.length === 0 && e.killed === e.total && e.total > 0 ? "PASS" : "FAIL";
  console.log(`ENGINE ${path}: ${verdict} — ${e.killed} of ${e.total} reverted guard(s) turned the named regression test red${e.problems.length === 0 ? "" : `; ${e.problems.join(", ")}`}`);
}
for (const path of uncovered) {
  if (only.length === 0) bad += 1;
}
console.log("(not pre-fix history — see LIMIT above)");
process.exit(bad === 0 ? 0 : 1);
