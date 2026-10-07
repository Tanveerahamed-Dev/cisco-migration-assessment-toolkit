/**
 * mutation-check.mjs — acceptance F3, the "failed before the fix" half, made executable.
 *
 * WHAT F3 ASKS. "Confirmed defects fixed with a regression test that failed before the fix." This
 * repository's history starts at its root commit `50a3dc5` (2026-09-21; `git rev-list --max-parents=0
 * HEAD`), and by then the guards this file reverts for blast, layout, query and the compiler were
 * already in the source, as were forwarding's §1.1 and R19 guards: no commit holds their pre-fix code,
 * so for them the "failed before the fix" half is prose (docs/refutation.md §0, §7; acceptance report
 * F3), and prose cannot be re-run. Some later fixes DO have a before in history — forwarding R17 and
 * claims C1/C2 landed in `254694b`, the C2/C3 follow-up and the two O15 source-binding guards in
 * `1d19e22` — and `--history` prints, from
 * git, which commit first holds each guard reverted here. That is where history exists; this file does
 * not replace it.
 *
 * WHAT THIS DOES. It copies the CURRENT source into a scratch directory and, one mutation at a time,
 * reverts a guard that a recorded refutation fix added — the named `find` text must occur exactly
 * once, or the mutation is INVALID rather than silently skipped — then runs the regression test that
 * fix names and requires it to go RED with at least one failed assertion. Before any mutation the same
 * tests are run unmutated in the same scratch copy and must be GREEN with at least one test executed,
 * so a red below cannot be explained by a test that was already red or matched nothing.
 *
 * A RED IS NOT A KILL UNTIL THE TARGETED ASSERTION IS WHAT WENT RED (repair wave 7). Every mutation
 * names, in `killedBy`, the assertion that exists to catch it — matched against each failure's test
 * name, message and the source line vitest's code frame points at. A mutant is KILLED only when at least one failure
 * is that assertion AND that failure is not a bare error-message mismatch (`toThrow(/x/)` failing with
 * "… but got '<another message>'": the code still threw, only its wording changed, which is not the
 * behaviour the guard exists for). A red from anything else is reported as MISATTRIBUTED and fails the
 * run. Measured before this rule: `layout-nonfinite-option` was "KILLED" by "expected [Function] to
 * throw error matching /tierYPitch/ but got 'layout: non-finite coordinates for ac…'" — the layout's
 * output post-condition had thrown instead, so the only thing the test noticed was the message.
 *
 * WHAT THIS DOES NOT DO — printed in its output too, because it is the limit on the evidence. It does
 * NOT recreate pre-fix history. A reverted guard is the defect's SHAPE reintroduced into today's code,
 * not the code as it stood before the fix was written. KILLED proves the regression test detects that
 * shape now; it does not prove the test was red on the historical source. For blast, layout, query and
 * the compiler (and forwarding's §1.1 and R19 guards) that remains prose: their guards predate the root
 * commit.
 *
 * THE DENOMINATOR IS THE DOCUMENT, NOT THIS FILE'S LIST. Every engine section of docs/refutation.md
 * (`## N. <Name> — \`<path>\``) names the file it refutes; each such path must be the target of at
 * least one mutation here, so a new engine section with no executable check fails this script instead
 * of being silently outside it.
 *
 * Usage:  node review/mutation-check.mjs            every mutation
 *         node review/mutation-check.mjs --only ID  one (repeatable), still baseline-checked
 *         ... --only a3-outcome-only --output <fresh RUNNER_TEMP directory>
 *         node review/mutation-check.mjs --list
 *         node review/mutation-check.mjs --history   per mutation, from git: the first commit whose
 *                                                    file holds each guard text, and whether the root does
 * Exit:   0 every mutation KILLED by its targeted assertion (and every expected-equivalent probe
 *           behaved as recorded)
 *         1 any mutation SURVIVED, was MISATTRIBUTED (red, but not by `killedBy`, or only by an error
 *           message), was INVALID, or its baseline was not green; or an engine the document names has
 *           no mutation
 * A3 strict profiles additionally require complete identical JSON case censuses without skips,
 * and the named real assertion in BOTH JSON and the default reporter's source frame. Raw reports,
 * stdout/stderr and a nonpromoting terminal summary survive scratch cleanup under --output.
 * They run only on GitHub-hosted Linux. The default all-mutation selection now also requires
 * --output and that hosted environment; explicitly selected legacy-only commands remain unchanged.
 * Never targets checkout source for edits: every mutation happens inside the scratch copy.
 */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { closeSync, constants, cpSync, existsSync, fstatSync, ftruncateSync, lstatSync, mkdirSync, mkdtempSync, openSync, readFileSync, readSync, readdirSync, realpathSync, rmdirSync, rmSync, symlinkSync, unlinkSync, writeFileSync, writeSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = resolve(HERE, "..");
const SNAPSHOT = resolve(PKG, "..", "webapp", "sample_data", "sample_fleet.snapshot.json");
const DOC = resolve(PKG, "docs", "refutation.md");
// vitest.config.ts merges vite.config.ts, which imports the real shared embed protocol.
// Keep its type-only owner too; neither sibling imports any further runtime owner.
// This single list owns both scratch copies and strict before/after source bindings.
const CONFIG_SIBLING_INPUTS = [
  "webapp/frontend/src/projectionEmbed.ts",
  "webapp/frontend/src/generated/openapi.ts",
];

/**
 * @typedef {{ file: string, find: string, replace: string }} Edit
 * @typedef {{
 *   id: string, engine: string, record: string, what: string,
 *   edits: Edit[], tests: string[], pattern?: string, rebuild?: string[],
 *   killedBy: RegExp,
 *   strictWitness?: { testName: string, marker: string },
 *   expect?: "killed" | "survives", why?: string
 * }} Mutation
 *
 * `killedBy` is REQUIRED on every mutation (a mutation without one is INVALID, never "any red will
 * do"): it identifies the assertion that targets this mutation, tested against each failure's
 * `<test name>\n<message>\n<source line>`.
 */

/** @type {Mutation[]} */
const MUTATIONS = [
  /* ── forwarding — src/forwarding/engine.ts (refutation §1; open-issues R17, R19) ─────────────── */
  {
    id: "a3-chosen-path-ignored",
    engine: "src/forwarding/engine.ts",
    record: "O79 A3 chosen-path qualification (W18)",
    what: "an identical terminal refusal hides an earlier unmodeled chosen hop",
    edits: [{ file: "src/forwarding/engine.ts",
      find: "const chosenDenialOpen = chosenDenialGaps.length > 0 || chosenDenialEvidence.length > 0;",
      replace: "const chosenDenialOpen = false;" }],
    tests: ["src/forwarding/engine.ingress-decider.test.ts"],
    killedBy: /chosen-path witness: an earlier unmodeled hop cannot be hidden by an identical terminal denial[\s\S]*AssertionError: chosen-path witness[\s\S]*expect\(/,
    strictWitness: {
      testName: "chosen-path witness: an earlier unmodeled hop cannot be hidden by an identical terminal denial",
      marker: "chosen-path witness",
    },
  },
  {
    id: "a3-outcome-only",
    engine: "src/forwarding/engine.ts",
    record: "O79 A3 narrow refusal identity (W18)",
    what: "matching outcome words alone certify an alternate with a different deciding ACL row",
    edits: [{ file: "src/forwarding/engine.ts", find: "const sameDecision = sameRefusalDecision(t, at);", replace: "const sameDecision = true;" }],
    tests: ["src/forwarding/engine.ingress-decider.test.ts"],
    killedBy: /outcome-only witness: different deciding ACL lines cannot certify reproduction[\s\S]*AssertionError: outcome-only witness[\s\S]*expect\(/,
    strictWitness: {
      testName: "outcome-only witness: different deciding ACL lines cannot certify reproduction",
      marker: "outcome-only witness",
    },
  },
  {
    id: "a3-binding-ignored",
    engine: "src/forwarding/engine.ts",
    record: "O79 A3 narrow refusal binding provenance (W18)",
    what: "an equal deciding ACL row is credited despite different observed interface bindings",
    edits: [{ file: "src/forwarding/engine.ts",
      find: "return ab !== null && bb !== null && ab.intf === bb.intf && ab.dir === bb.dir && ab.cite === bb.cite;",
      replace: "return true;" }],
    tests: ["src/forwarding/engine.ingress-decider.test.ts"],
    killedBy: /binding witness: the same ACL line through different observed interfaces is not reproduced[\s\S]*AssertionError: binding witness[\s\S]*expect\(/,
    strictWitness: {
      testName: "binding witness: the same ACL line through different observed interfaces is not reproduced",
      marker: "binding witness",
    },
  },
  {
    id: "a3-always-false",
    engine: "src/forwarding/engine.ts",
    record: "O79 A3 positive refusal-reproduction control (W18)",
    what: "every alternate is declined, including an identical uniquely observed refusal",
    edits: [{ file: "src/forwarding/engine.ts", find: "const sameDecision = sameRefusalDecision(t, at);", replace: "const sameDecision = false;" }],
    tests: ["src/forwarding/engine.ingress-decider.test.ts"],
    killedBy: /positive witness: identical uniquely observed refusals still reproduce[\s\S]*AssertionError: positive witness[\s\S]*expect\(/,
    strictWitness: {
      testName: "positive witness: identical uniquely observed refusals still reproduce",
      marker: "positive witness",
    },
  },
  {
    id: "fwd-received-at-owner",
    engine: "src/forwarding/engine.ts",
    record: "open-issues R17 (receivedAtOwner)",
    what: "a packet addressed to the router's own address is evaluated against its OUTBOUND list again",
    edits: [{ file: "src/forwarding/engine.ts", find: "    if (receivedAs !== undefined) {", replace: "    if (false as boolean && receivedAs !== undefined) {" }],
    tests: ["src/forwarding/router-destined.test.ts"],
    killedBy: /is not a PROTECT_SERVERS denial[\s\S]*expect\(t\.outcome\)\.toBe\("indeterminate"\)/,
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
    killedBy: /no flow toward any collected interface address is delivered[\s\S]*expect\(bad\)\.toEqual\(\[\]\)/,
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
    killedBy: /an unresolved port name must not be evaluated: expected true to be false/,
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
    killedBy: /cites the line its own trace was decided by[\s\S]*expect\(cited\)\.toEqual\(decidedByOwnTrace\)/,
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
    killedBy: /ceiling is a ceiling[\s\S]*resolvePathLimit\(Number\.NaN\)/,
    pattern: "ceiling is a ceiling",
  },
  {
    id: "blast-graph-unfrozen",
    engine: "src/analysis/blast.ts",
    record: "refutation §2 (blast.test.ts: the shared graph is evidence a renderer cannot edit)",
    what: "the memoised topology graph is handed out mutable again",
    edits: [{ file: "src/analysis/blast.ts", find: "  return freezeGraph(graph);", replace: "  return graph;" }],
    tests: ["src/analysis/blast.test.ts"],
    killedBy: /renderer cannot edit[\s\S]*Object\.isFrozen\(g\)\)\.toBe\(true\)/,
    pattern: "renderer cannot edit",
  },

  /* ── layout — src/fabric3d/layout.ts (refutation §3) ────────────────────────────────────────── */
  {
    id: "layout-nonfinite-option",
    engine: "src/fabric3d/layout.ts",
    record: "refutation §3 (layout.test.ts: an unvalidated input)",
    what: "a non-finite option is no longer refused up front: a NaN seed or sweep count returns a plausible fabric, an infinite sweep count never returns, and a NaN pitch is laid out before the output post-condition throws",
    edits: [
      {
        file: "src/fabric3d/layout.ts",
        find: "  if (!Number.isFinite(v)) throw new Error(`layout: ${name} must be a finite number, got ${v}`);",
        replace: "  if ((false as boolean) && !Number.isFinite(v)) throw new Error(`layout: ${name} must be a finite number, got ${v}`);",
      },
    ],
    tests: ["src/fabric3d/layout.test.ts"],
    killedBy: /refuses every non-finite numeric option[\s\S]*a non-finite option was not refused before layout work began/,
    pattern: "refuses every non-finite numeric option",
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
    killedBy: /a dropped link is not an absence of neighbours[\s\S]*isolatedHosts\)\.not\.toContain/,
    pattern: "a dropped link is not an absence of neighbours",
  },
  /* The O26 replacement's red-proof, executed (W6 gate, 2026-09-25). layout.test.ts's wall-clock
     median was replaced by a counted work budget stated in the fabric's own size; these three blow
     the layout's cost up by a factor of n (or worse) without changing its output, so only that
     budget can kill them. */
  {
    id: "layout-crossings-per-node",
    engine: "src/fabric3d/layout.ts",
    record: "open-issues O26 (layout.test.ts: a counted work budget replaced the wall-clock median)",
    what: "the crossing count is recomputed once per node inside every ordering sweep",
    edits: [
      {
        file: "src/fabric3d/layout.ts",
        find: "      for (const id of g.ids) {\n        let sum = 0;",
        replace: "      for (const id of g.ids) {\n        crossings();\n        let sum = 0;",
      },
    ],
    tests: ["src/fabric3d/layout.test.ts"],
    killedBy: /counted work budget[\s\S]*primitive operations: expected \d+ to be less than or equal to \d+/,
    pattern: "work budget",
  },
  {
    id: "layout-clearance-quadratic",
    engine: "src/fabric3d/layout.ts",
    record: "open-issues O26 (layout.test.ts: a counted work budget replaced the wall-clock median)",
    what: "the edge-clearance pass measures every node against every segment once more per node pair",
    edits: [
      {
        file: "src/fabric3d/layout.ts",
        find: "      const { distance, t } = pointToSegment([other.x, other.y, other.z], pa, pb);",
        replace:
          "      for (const o2 of nodes) pointToSegment([o2.x, o2.y, o2.z], pa, pb);\n      const { distance, t } = pointToSegment([other.x, other.y, other.z], pa, pb);",
      },
    ],
    tests: ["src/fabric3d/layout.test.ts"],
    killedBy: /counted work budget[\s\S]*primitive operations: expected \d+ to be less than or equal to \d+/,
    pattern: "work budget",
  },
  {
    id: "layout-sweeps-times-n",
    engine: "src/fabric3d/layout.ts",
    record: "open-issues O26 (layout.test.ts: a counted work budget replaced the wall-clock median)",
    what: "the ordering runs its sweep count once per device instead of once",
    edits: [
      {
        file: "src/fabric3d/layout.ts",
        find: "  for (let s = 0; s < sweepCount; s += 1) {",
        replace: "  for (let s = 0; s < sweepCount * devices.length; s += 1) {",
      },
    ],
    tests: ["src/fabric3d/layout.test.ts"],
    killedBy: /counted work budget[\s\S]*primitive operations: expected \d+ to be less than or equal to \d+/,
    pattern: "work budget",
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
    killedBy: /never collected[\s\S]*evidenceBlind\)\.toBe\(true\)/,
    pattern: "never-collected device is an evidence gap",
  },

  /* ── compiler — tools/compile-snapshot.mjs (refutation §5). Mutated, RE-RUN in the scratch copy
        against the scratch snapshot, and only then tested: the fidelity tests read the compiled
        model, so a compiler mutation that is not rebuilt would test the shipped bytes. ─────────── */
  {
    id: "compiler-drops-unevaluable",
    /* engine = refutation.md §5's attribution key (the denominator); the compile logic that CLI runs now
       lives in tools/lib/compile-model.mjs, so the reverted guard is edited there. */
    engine: "tools/compile-snapshot.mjs",
    record: "refutation §5 (compiler-fidelity.test.ts: unevaluable)",
    what: "the producer's own `unevaluable` verdict is dropped at compilation again",
    edits: [{ file: "tools/lib/compile-model.mjs", find: "        unevaluable: l.unevaluable === true,", replace: "        unevaluable: false," }],
    rebuild: ["tools/compile-snapshot.mjs"],
    tests: ["src/core/compiler-fidelity.test.ts"],
    killedBy: /the producer marked this line unevaluable: expected false to be true/,
    pattern: "unevaluable",
  },
  {
    id: "compiler-drops-established",
    engine: "tools/compile-snapshot.mjs",
    record: "refutation §5 (compiler-fidelity.test.ts: established)",
    what: "`established`, a stateful match a forward model cannot decide, is dropped again",
    edits: [{ file: "tools/lib/compile-model.mjs", find: "        established: l.established === true,", replace: "        established: false," }],
    rebuild: ["tools/compile-snapshot.mjs"],
    tests: ["src/core/compiler-fidelity.test.ts"],
    killedBy: /keeps .established.[\s\S]*\.established\)\.toBe\(true\)/,
    pattern: "established",
  },

  /* ── claims — src/core/claims.ts (refutation §6; open-issues R16) ───────────────────────────── */
  {
    id: "claims-c1-decided-owner",
    engine: "src/core/claims.ts",
    record: "refutation §6 C1 (the empty-traversal rule for decided outcome words: hopsSupportOutcome)",
    what: "a delivered traversal that visited nothing earns SCOPED again",
    edits: [{ file: "src/core/claims.ts", find: "  if (last === undefined) return false;", replace: "  if (last === undefined) return true;" }],
    tests: ["src/core/claims.test.ts"],
    killedBy: /with no hops as INDETERMINATE[\s\S]*claimBadge\(empty\(\)\)\)\.toBe\("INDETERMINATE"\)/,
  },
  {
    id: "claims-undetermined-word-badge",
    engine: "src/core/claims.ts",
    record: "refutation §6 C2/C3 (2026-09-22 probe: an unrecognised outcome word earned SCOPED; the outcome-band rule)",
    what: "an outcome word that bands UNDETERMINED earns a badge from its traversal again (SCOPED over clean hops, and over none)",
    edits: [
      {
        file: "src/core/claims.ts",
        find: '  if (bandOfOutcome(trace.outcome) === "UNDETERMINED") return "INDETERMINATE";',
        replace: '  if (trace.outcome === "indeterminate") return "INDETERMINATE";',
      },
    ],
    tests: ["src/core/claims.test.ts"],
    killedBy: /(?:outcome word is unrecognised|unrecognised outcome word over a clean|whose band is UNDETERMINED)[\s\S]*expected 'SCOPED' to be 'INDETERMINATE'/,
  },
  {
    id: "claims-c1-both-owners",
    engine: "src/core/claims.ts",
    record: "refutation §6 C1 (both owners of the empty-traversal rule reverted together)",
    what: "a traversal that visited nothing earns SCOPED again, under any outcome word",
    edits: [
      { file: "src/core/claims.ts", find: "  if (last === undefined) return false;", replace: "  if (last === undefined) return true;" },
      {
        file: "src/core/claims.ts",
        find: '  if (bandOfOutcome(trace.outcome) === "UNDETERMINED") return "INDETERMINATE";',
        replace: '  if (trace.outcome === "indeterminate") return "INDETERMINATE";',
      },
    ],
    tests: ["src/core/claims.test.ts"],
    killedBy: /EMPTY traversal earns no badge[\s\S]*with zero hops: expected 'SCOPED' to be 'INDETERMINATE'/,
    pattern: "EMPTY traversal",
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
    killedBy: /unrecognised verdict bands as UNDETERMINED[\s\S]*expected undefined to be 'UNDETERMINED'/,
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
    killedBy: /REFUTED \(C2\)[\s\S]*expected 'SCOPED' to be 'INDETERMINATE'/,
    pattern: "C2",
  },

  /* ── source binding — O15 / acceptance F5 (not a refutation.md engine section; reported below
        the documented engines, and a survivor still fails the run). ─────────────────────────────── */
  {
    id: "binding-raw-working-tree",
    engine: "tools/lib/compile-model.mjs",
    record: "open-issues O15 / acceptance F5 (the digest binds the LF-normalised form)",
    what: "every compiler hashes the raw working-tree bytes again, so a CRLF checkout binds another digest",
    edits: [{ file: "tools/lib/compile-model.mjs", find: "export function lfNormalise(raw) {\n", replace: "export function lfNormalise(raw) {\n  if (raw !== null) return raw;\n" }],
    tests: ["src/core/provenance.test.ts"],
    killedBy: /CRLF or LF line endings \(O15\)[\s\S]*compileInSandbox\(crlf\)/,
    pattern: "O15",
  },
  {
    id: "binding-trust-digest-only",
    engine: "src/forwarding/bindings.ts",
    record: "open-issues O15 (a sidecar is trusted only on the same digest, form and length)",
    what: "acl-bindings.json is trusted on a matching digest string alone, whatever byte form or length it states",
    edits: [
      {
        file: "src/forwarding/bindings.ts",
        find: "export const BINDINGS_TRUSTED = sameSourceBinding(FILE.meta, fabric.meta);",
        replace: "export const BINDINGS_TRUSTED = FILE.meta.sourceSha256 === fabric.meta.sourceSha256 || sameSourceBinding(FILE.meta, fabric.meta);",
      },
    ],
    tests: ["src/forwarding/bindings-trust.test.ts"],
    killedBy: /expect\(b\.BINDINGS_TRUSTED\)\.toBe\(false\)/,
    pattern: "same sourceSha256",
  },

  /* ── scroll-edge slices — acceptance C2 (2026-09-26 overturn: the path panel's tab strip cut by
        Rail A's top edge at 1440, state 06). Not refutation.md engine sections; reported below the
        documented engines, and a survivor still fails the run. ──────────────────────────────────── */
  {
    id: "c2-reveal-rail-first",
    engine: "src/panels/DataGrid.tsx",
    record: "acceptance C2 (fits first: the grid moves before a shared rail when its band holds the row)",
    what: "a nested-port reveal moves the shared rail even when the grid's own band can show the row, cutting whatever else the rail carries",
    edits: [
      {
        file: "src/panels/DataGrid.tsx",
        find: "ownPortShows(scroller, head, el) && !bandHoldsRow(scroller, head, el)) {",
        replace: "ownPortShows(scroller, head, el) && !((false as boolean) && bandHoldsRow(scroller, head, el))) {",
      },
    ],
    tests: ["src/panels/DataGrid.c2-chrome-slice.test.tsx", "src/panels/PriorityQueue.c2-rail-reveal.test.tsx"],
    killedBy: /the shared rail did not move \(the grid could show the row itself\)|the shared rail did not move: the grid's own band could hold the row/,
  },
  {
    id: "c2-takeout-loses-row",
    engine: "src/panels/DataGrid.tsx",
    record: "acceptance C2 (a reveal never costs the row: the take-out keeps the row it moves for)",
    what: "a reveal that clips nothing returns before checking the row it moved is still in view",
    edits: [
      {
        file: "src/panels/DataGrid.tsx",
        find: "  if (cut === null && Math.abs(rowOff()) <= offBefore + 0.5) return;",
        replace: "  if (cut === null) return;",
      },
    ],
    tests: ["src/panels/DataGrid.c2-chrome-slice.test.tsx"],
    killedBy: /the reveal cost the row: \d/,
  },
  {
    id: "c2-overlay-not-a-cut",
    engine: "src/panels/DataGrid.tsx",
    record: "acceptance C2 (an overlay covering a control is a clip)",
    what: "the band ignores an overlay that covers part of the control",
    edits: [
      {
        file: "src/panels/DataGrid.tsx",
        find: "  ({ top, bottom } = uncovered(el, doc, r, top, bottom));",
        replace: "  if ((false as boolean)) ({ top, bottom } = uncovered(el, doc, r, top, bottom));",
      },
    ],
    tests: ["src/panels/DataGrid.c2-overlay-slice.test.tsx"],
    killedBy: /is whole or gone, not \d+(?:\.\d+)? of \d+ px seen past/,
  },
  {
    id: "c2-empty-band-moves-carrier",
    engine: "src/panels/DataGrid.tsx",
    record: "acceptance C2 (an empty band scrolls the carrier back to the grid)",
    what: "a reveal with no visible band moves the carrier to the row instead of back to the grid",
    edits: [
      {
        file: "src/panels/DataGrid.tsx",
        find: "  let off = offsetFromView(scroller, head, el);\n  if (off === 0) return;",
        replace:
          "  let off = offsetFromView(scroller, head, el);\n" +
          "  if (off === 0) { const cb = clippedBand(scroller, head); if (cb.bottom <= cb.top && ownPortShows(scroller, head, el)) { const a = scroller.parentElement!; const r = (el.closest<HTMLElement>('[role=\"row\"]') ?? el).getBoundingClientRect(); const pr = a.getBoundingClientRect(); a.scrollTop += r.bottom > pr.bottom ? r.bottom - pr.bottom : r.top - pr.top; } return; }",
      },
    ],
    tests: ["src/panels/DataGrid.c2-chrome-slice.test.tsx"],
    killedBy: /the carrier is not scrolled back to the grid/,
  },
  {
    id: "c2-reveal-cuts-nav-strip",
    engine: "src/panels/DataGrid.tsx",
    record: "acceptance C2 (navigation is whole or absent after any ancestor half of a reveal)",
    what: "the ancestor or document half of a reveal leaves a tablist/toolbar/menubar partly visible",
    edits: [{ file: "src/panels/DataGrid.tsx", find: "  if (moved === 0 || strips.length === 0) return;", replace: "  if (moved === 0 || strips.length === 0 || (true as boolean)) return;" }],
    tests: ["src/panels/DataGrid.c2-chrome-slice.test.tsx"],
    killedBy: /the (?:strip|toolbar) is whole or gone, not \d/,
  },
  {
    id: "c2-landing-slices-previous-control",
    engine: "src/panels/PathTrace.tsx",
    record: "acceptance C2 (the answer landing's top edge falls in a gap, never through the control above)",
    what: "the landing aligns its target a fixed 8 px below the port's edge and shows a sliver of the citation above it",
    edits: [{ file: "src/panels/PathTrace.tsx", find: "      return Math.max(0, Math.min(pad, top - r.bottom));", replace: "      return pad;" }],
    tests: ["src/panels/PathTrace.c2-landing.test.tsx"],
    killedBy: /no sliver of the citation shows[\s\S]*expected 8 to be 4/,
  },
  {
    id: "c2-mode-panel-without-scrim",
    engine: "src/panels/PathTrace.tsx",
    record: "acceptance C2 (a row cut at the path panel's own bottom edge carries the house cut-row cue)",
    what: "the trace mode panel owns a scroller without the cut-row scrim",
    edits: [{ file: "src/panels/PathTrace.tsx", find: 'tabId="trace" active={mode === "trace"} className="pt-panel scroll-scrim"', replace: 'tabId="trace" active={mode === "trace"} className="pt-panel"' }],
    tests: ["src/panels/PathTrace.c2-landing.test.tsx"],
    killedBy: /mode panels that own a scroller without the cut-row cue/,
  },
  {
    id: "c2-reveal-overshoot-scrolls-back",
    engine: "src/panels/DataGrid.tsx",
    record: "acceptance C2 (a strip taken out past the row's remainder hands the outer scrollers nothing)",
    what: "the take-out's overshoot is subtracted from the remainder, so the next scroller out (the document) scrolls back by it",
    edits: [{ file: "src/panels/DataGrid.tsx", find: "    rest = Math.sign(left) === Math.sign(rest) ? left : 0;", replace: "    rest = left;" }],
    tests: ["src/panels/DataGrid.c2-chrome-slice.test.tsx"],
    killedBy: /the document must not move when the rail alone showed the row/,
  },
  {
    id: "c2-landing-head-fixed-pad",
    engine: "src/panels/PathTrace.tsx",
    record: "acceptance C2 (the head landing uses the gap above the hop card, not a fixed pad)",
    what: "landOnAnswer aligns the hop card a fixed 8 px below the port's edge, through the control above it",
    edits: [
      {
        file: "src/panels/PathTrace.tsx",
        find: "const headDelta = target.getBoundingClientRect().top - box.top - landingInset(target, scroller, PAD);",
        replace: "const headDelta = target.getBoundingClientRect().top - box.top - PAD;",
      },
    ],
    tests: ["src/panels/PathTrace.c2-landing.test.tsx"],
    killedBy: /the port edge falls in the gap above the hop/,
  },
  {
    id: "c2-landing-decided-fixed-pad",
    engine: "src/panels/PathTrace.tsx",
    record: "acceptance C2 (the decided-fact landing uses the gap above the fact, not a fixed pad)",
    what: "landOnAnswer aligns the deciding fact a fixed 8 px below the port's edge, through the citation above it",
    edits: [
      {
        file: "src/panels/PathTrace.tsx",
        find: "delta = at.top - box.top - landingInset(decided, scroller, PAD);",
        replace: "delta = at.top - box.top - PAD;",
      },
    ],
    tests: ["src/panels/PathTrace.c2-landing.test.tsx"],
    killedBy: /the port edge falls in the gap above the decided fact/,
  },
  {
    id: "c2-scrim-cover-rail-fill",
    engine: "src/panels/PathTrace.tsx",
    record: "acceptance C2 (the mode panels' scrim cover is the path surface's own ground)",
    what: "the mode panels' scrim cover keeps the rail's --surface-1 on a --bg surface and paints a band where the list ends",
    edits: [{ file: "src/panels/PathTrace.tsx", find: "      ref={groundModeScrims}", replace: "      ref={undefined}" }],
    tests: ["src/panels/PathTrace.c2-landing.test.tsx"],
    killedBy: /scrim panels whose cover is not the path surface's ground/,
  },
];

/* ── every mutation names the assertion that must kill it ─────────────────────────────────────── */
const untargeted = MUTATIONS.filter((m) => !(/** @type {unknown} */ (m.killedBy) instanceof RegExp));
if (untargeted.length > 0) {
  console.error(`INVALID  ${untargeted.map((m) => m.id).join(", ")}: no \`killedBy\` — a mutation must name the assertion that targets it, or any red would count as a kill`);
  process.exit(1);
}

/* ── arguments ─────────────────────────────────────────────────────────────────────────────────── */
const argv = process.argv.slice(2);
if (argv.includes("--list")) {
  for (const m of MUTATIONS) console.log(`${m.id.padEnd(40)} ${m.engine.padEnd(28)} ${m.record}`);
  process.exit(0);
}
if (argv.includes("--history")) {
  /* Facts from git only: for each mutation, whether the ROOT commit's file already holds each guard
     text this file reverts (if it does, no commit holds the pre-fix source for that guard), and the
     first commit on HEAD's first-parent line whose file holds it. The exact text is searched, so a
     guard that existed in another wording reads as absent: this bounds history, it does not prove a
     red. */
  const git = (/** @type {string[]} */ ...a) => {
    const r = spawnSync("git", ["-C", PKG, ...a], { encoding: "utf8", maxBuffer: 256 * 1024 * 1024 });
    return r.status === 0 ? r.stdout : null;
  };
  const line = git("rev-list", "--reverse", "--first-parent", "HEAD");
  if (line === null) {
    console.error("FAIL  not a git checkout, or git is unavailable: --history reads only git");
    process.exit(1);
  }
  const commits = line.trim().split("\n");
  const root = commits[0] ?? "";
  console.log(`history: ${commits.length} commit(s) on HEAD's first-parent line, root ${root.slice(0, 7)}`);
  /** @type {Map<string, string | null>} */
  const blobs = new Map();
  const at = (/** @type {string} */ c, /** @type {string} */ f) => {
    const k = `${c}:${f}`;
    if (!blobs.has(k)) blobs.set(k, git("show", k)?.replace(/\r\n/g, "\n") ?? null);
    return blobs.get(k) ?? null;
  };
  for (const m of MUTATIONS) {
    const parts = m.edits.map((ed) => {
      const first = commits.find((c) => (at(c, ed.file) ?? "").includes(ed.find));
      const inRoot = (at(root, ed.file) ?? "").includes(ed.find);
      return inRoot ? "in root (no pre-fix commit)" : first === undefined ? "in no commit (working tree only)" : `first in ${first.slice(0, 7)}`;
    });
    const tests = m.tests.map((t) => `${t} ${commits.find((c) => at(c, t) !== null)?.slice(0, 7) ?? "untracked"}`);
    console.log(`${m.id.padEnd(36)} guard: ${parts.join("; ")}  |  test first tracked: ${tests.join(", ")}`);
  }
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
const strictSelected = selected.filter((m) => m.strictWitness !== undefined);
const strictMode = strictSelected.length > 0;
const need = (/** @type {unknown} */ ok, /** @type {string} */ message) => { if (!ok) throw new Error(message); };
const sha = (/** @type {Buffer | string} */ bytes) => createHash("sha256").update(bytes).digest("hex");
const inside = (/** @type {string} */ parent, /** @type {string} */ child) => {
  const path = relative(parent, child);
  return path === "" || (!isAbsolute(path) && path !== ".." && !path.startsWith(`..${sep}`));
};
const stripAnsi = (/** @type {string} */ text) => text.replace(/\u001b\[[0-9;]*m/g, "");
const posix = (/** @type {string} */ path) => path.split(sep).join("/");
const ordinaryBytes = (/** @type {string} */ path, maximum = 64 * 1024 * 1024) => {
  need(realpathSync(path) === resolve(path), "strict input path is indirect");
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(fd);
    need(before.isFile() && before.nlink === 1 && before.size <= maximum, "strict input is nonregular, hardlinked or oversized");
    const chunks = [];
    const chunk = Buffer.alloc(65536);
    let size = 0;
    while (size <= maximum) {
      const n = readSync(fd, chunk, 0, Math.min(chunk.length, maximum + 1 - size), null);
      if (n === 0) break;
      chunks.push(Buffer.from(chunk.subarray(0, n))); size += n;
    }
    const after = fstatSync(fd);
    need(size <= maximum && size === before.size && after.size === before.size && after.mtimeMs === before.mtimeMs
      && after.ctimeMs === before.ctimeMs && after.nlink === 1, "strict input changed or exceeded its bound during read");
    return Buffer.concat(chunks, size);
  } finally { closeSync(fd); }
};
const strictGit = (/** @type {string[]} */ ...args) => {
  const result = spawnSync("git", ["--no-optional-locks", "-C", PKG, ...args], { maxBuffer: 64 * 1024 * 1024 });
  need(result.status === 0 && !result.error, `source Git read failed: ${args[0]}`);
  return result.stdout;
};
/** @type {string | null} */
let strictOutput = null;
/** @type {Map<string, Buffer>} */
const checkoutInputs = new Map();
/** @type {Record<string, unknown> | null} */
let sourceBefore = null;
/** @type {{ id: string, status: string, [key: string]: unknown }[]} */
const strictObservations = [];
/** @type {Record<string, unknown>[]} */
const strictBaselines = [];
/** @type {string[]} */
const strictProblems = [];
let strictSourceAfterPreserved = false;
let strictScratchRestored = false;
const saveStrict = () => {
  if (strictOutput === null) return;
  const complete = strictObservations.length === strictSelected.length
    && strictObservations.every((row) => row.status === "KILLED_BY_DISTINCT_ASSERTION")
    && strictProblems.length === 0 && strictSourceAfterPreserved && strictScratchRestored;
  writeFileSync(join(strictOutput, "summary.json"), `${JSON.stringify({
    schema: "atlas-scope.a3-refusal-mutations/1", status: complete ? "BOUNDED_SYNTHETIC_WITNESSES_PASS" : "INCOMPLETE_OR_FAILED",
    selected: strictSelected.map((m) => ({ id: m.id, tests: m.tests, witness: m.strictWitness })),
    sourceBefore, baselines: strictBaselines, observations: strictObservations, problems: strictProblems,
    checkoutSelectedInputsPreserved: strictSourceAfterPreserved, scratchPristineRestored: strictScratchRestored,
    qualification: false, acceptanceRegrade: false, historicalRedRecreated: false,
    limits: "Current synthetic engine assertions only; not rendered A3 acceptance, independent archive custody or historical pre-fix execution.",
  }, null, 2)}\n`, { mode: 0o600 });
};

if (strictMode) {
  need(process.env.GITHUB_ACTIONS === "true" && process.env.RUNNER_ENVIRONMENT === "github-hosted"
    && process.platform === "linux", "A3 strict mutation execution requires GitHub-hosted Linux");
  const options = argv.flatMap((value, index) => value === "--output" ? [argv[index + 1]] : []);
  need(options.length === 1 && typeof options[0] === "string" && isAbsolute(options[0]), "A3 strict profiles require one absolute --output");
  const output = resolve(/** @type {string} */ (options[0]));
  const runnerTemp = realpathSync(process.env.RUNNER_TEMP ?? "");
  const repo = realpathSync(strictGit("rev-parse", "--show-toplevel").toString().trim());
  need(!existsSync(output) && realpathSync(dirname(output)) === dirname(output) && inside(runnerTemp, output)
    && !inside(repo, output), "A3 evidence must be a fresh external runner-temp directory");
  need(!process.env.ATLAS_DATASET_DIR?.trim(), "A3 strict source selection does not admit an external dataset override");
  mkdirSync(output, { mode: 0o700 });
  strictOutput = output;
  // An admission failure still leaves a visibly incomplete record beside the caller's log.
  saveStrict();
  const commit = strictGit("rev-parse", "HEAD").toString().trim();
  const tree = strictGit("rev-parse", "HEAD^{tree}").toString().trim();
  need(/^[0-9a-f]{40}$/.test(commit) && commit === process.env.GITHUB_SHA, "A3 checkout must match the workflow's full SHA");
  need(strictGit("status", "--porcelain=v1", "--untracked-files=all").length === 0, "A3 checkout must start clean");
  /** @type {Record<string, unknown>} */
  const inputs = {};
  const packageInputs = new Set([
    "review/mutation-check.mjs", "package.json", "package-lock.json", "vite.config.ts", "vitest.config.ts", "tsconfig.json",
    ...strictSelected.flatMap((m) => [...m.edits.map((ed) => ed.file), ...m.tests]),
  ]);
  const paths = [...packageInputs].map((path) => `atlas-scope/${path}`);
  paths.push("webapp/sample_data/sample_fleet.snapshot.json", ...CONFIG_SIBLING_INPUTS);
  for (const path of paths.sort()) {
    const absolute = join(repo, path);
    const bytes = ordinaryBytes(absolute);
    need(bytes.equals(strictGit("cat-file", "blob", `${commit}:${path}`)), `A3 input differs from selected Git: ${path}`);
    checkoutInputs.set(absolute, bytes);
    inputs[path] = { bytes: bytes.length, sha256: sha(bytes), gitBlob: strictGit("rev-parse", `${commit}:${path}`).toString().trim() };
  }
  let prHead = null;
  if (process.env.GITHUB_EVENT_PATH) {
    const eventPath = process.env.GITHUB_EVENT_PATH;
    const event = JSON.parse(ordinaryBytes(eventPath, 4 * 1024 * 1024).toString("utf8"));
    const selectedHead = event.pull_request?.head?.sha;
    if (selectedHead !== undefined) {
      need(typeof selectedHead === "string" && /^[0-9a-f]{40}$/.test(selectedHead), "A3 PR head metadata is invalid");
      prHead = selectedHead;
    }
  }
  sourceBefore = { commit, tree, githubSha: process.env.GITHUB_SHA, prHead,
    runId: process.env.GITHUB_RUN_ID, runAttempt: process.env.GITHUB_RUN_ATTEMPT, job: process.env.GITHUB_JOB,
    runnerEnvironment: process.env.RUNNER_ENVIRONMENT, node: process.version, inputs };
  writeFileSync(join(output, "source-before.json"), `${JSON.stringify(sourceBefore, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  console.log(`A3 SOURCE checkout/tested=${commit} tree=${tree} PR-head=${prHead ?? "not-a-PR"}; evidence=${output}`);
  saveStrict();
}

console.log("mutation-check — F3 'failed before the fix', executed against TODAY's source");
console.log("LIMIT: this does NOT recreate pre-fix history. Each mutation reverts one recorded guard in a scratch");
console.log("copy of the current tree; KILLED proves the regression test detects that defect shape now, not that");
console.log("it was red on the historical source. For blast, layout, query and the compiler (and forwarding's §1.1");
console.log("and R19 guards) no commit holds that source: their guards predate the root commit. Where a commit does");
console.log("hold one, `--history` names it; a KILLED line below is never that history.");
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
// contracts/ holds the engine-contract projection that tools/lib/compile-model.mjs imports; a scratch copy
// without it fails every compiler rebuild.
for (const dir of ["src", "tools", "contracts"]) cpSync(join(PKG, dir), join(scratch, dir), { recursive: true });
for (const f of ["package.json", "vite.config.ts", "vitest.config.ts", "tsconfig.json", "tsconfig.scripts.json", "index.html"]) {
  if (existsSync(join(PKG, f))) cpSync(join(PKG, f), join(scratch, f));
}
for (const path of CONFIG_SIBLING_INPUTS) {
  const source = resolve(PKG, "..", path);
  const target = join(root, path);
  mkdirSync(dirname(target), { recursive: true });
  if (strictMode) {
    const bytes = checkoutInputs.get(source);
    need(bytes !== undefined, `config sibling was not selected before scratch construction: ${path}`);
    writeFileSync(target, /** @type {Buffer} */ (bytes), { flag: "wx", mode: 0o600 });
    need(ordinaryBytes(target).equals(bytes), `config sibling scratch bytes differ from selected source: ${path}`);
  } else cpSync(source, target);
}
/** @type {{ path: string, target: string }[]} */
const dependencyLinks = [];
if (strictMode) {
  // A whole node_modules junction lets Vite's .vite/.vite-temp writes reach the
  // source checkout. Keep the container (and each @scope container) scratch-owned,
  // linking only dependency entries. Never link hidden cache/metadata directories.
  const installed = join(PKG, "node_modules");
  const dependencies = join(scratch, "node_modules");
  mkdirSync(dependencies);
  const link = (/** @type {string} */ from, /** @type {string} */ to) => {
    const target = realpathSync(from);
    symlinkSync(target, to, lstatSync(target).isDirectory() ? "junction" : "file");
    dependencyLinks.push({ path: to, target });
  };
  for (const name of readdirSync(installed).filter((name) => !name.startsWith(".")).sort()) {
    if (name.startsWith("@")) {
      const scope = join(dependencies, name);
      mkdirSync(scope);
      for (const member of readdirSync(join(installed, name)).filter((member) => !member.startsWith(".")).sort()) {
        link(join(installed, name, member), join(scope, member));
      }
    } else link(join(installed, name), join(dependencies, name));
  }
} else symlinkSync(join(PKG, "node_modules"), join(scratch, "node_modules"), "junction");
mkdirSync(join(root, "webapp", "sample_data"), { recursive: true });
cpSync(SNAPSHOT, join(root, "webapp", "sample_data", "sample_fleet.snapshot.json"));
const VITEST = join(PKG, "node_modules", "vitest", "vitest.mjs");

/** @param {string[]} tests @param {string | undefined} pattern @param {string | undefined} strictLabel */
function runTests(tests, pattern, strictLabel) {
  /** @type {string | null} */
  let evidence = null;
  if (strictLabel !== undefined) {
    need(strictOutput !== null && /^[a-z0-9-]+$/.test(strictLabel), "strict evidence label is invalid");
    evidence = join(/** @type {string} */ (strictOutput), strictLabel);
    mkdirSync(evidence, { mode: 0o700 });
  }
  const reportPath = evidence === null ? null : join(evidence, "vitest.json");
  const args = [VITEST, "run", ...tests, ...(pattern === undefined ? [] : ["-t", pattern]),
    ...(reportPath === null ? [] : ["--reporter=default", "--reporter=json", `--outputFile.json=${reportPath}`, "--cache=false"])];
  const r = spawnSync(process.execPath, args, { cwd: scratch, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  const out = stripAnsi(`${r.stdout ?? ""}\n${r.stderr ?? ""}`);
  const failed = Number(/Tests\s+(\d+) failed/.exec(out)?.[1] ?? 0);
  const passed = Number(/(\d+) passed/.exec(/Tests\s+[^\n]*/.exec(out)?.[0] ?? "")?.[1] ?? 0);
  const firstFailure = /(AssertionError[^\n]*|Error:[^\n]*)/.exec(out)?.[1] ?? "";
  let strictError = null;
  /** @type {{ census: string[], cases: { file: string, fullName: string, title: string, status: string, failureMessages: string[] }[], success: boolean } | null} */
  let jsonResult = null;
  if (evidence !== null && reportPath !== null) {
    writeFileSync(join(evidence, "stdout.log"), r.stdout ?? "", { flag: "wx", mode: 0o600 });
    writeFileSync(join(evidence, "stderr.log"), r.stderr ?? "", { flag: "wx", mode: 0o600 });
    try {
      need(!r.error && r.signal === null && (r.status === 0 || r.status === 1), "strict test process did not exit normally");
      jsonResult = readStrictCases(reportPath, tests, failed, passed);
      need(jsonResult.success === (r.status === 0), "strict JSON success and process exit disagree");
    } catch (error) {
      strictError = error instanceof Error ? error.message : String(error);
    }
    writeFileSync(join(evidence, "execution.json"), `${JSON.stringify({
      code: r.status, signal: r.signal, spawnError: r.error?.message ?? null, failed, passed,
      strictError, census: jsonResult?.census ?? null, args: args.slice(1),
    }, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  }
  return { code: r.status ?? -1, failed, passed, firstFailure: firstFailure.slice(0, 160), failures: parseFailures(out), out,
    strictError, jsonResult, evidence: strictLabel ?? null };
}

/** Read one complete default+JSON report; a skipped, duplicate or missing case is not a mutation verdict.
 * @param {string} reportPath @param {string[]} tests @param {number} failed @param {number} passed
 */
function readStrictCases(reportPath, tests, failed, passed) {
  const report = JSON.parse(ordinaryBytes(reportPath).toString("utf8"));
  need(typeof report.success === "boolean" && Array.isArray(report.testResults)
    && report.testResults.length === tests.length, "strict JSON has an incomplete suite census");
  /** @type {{ file: string, fullName: string, title: string, status: string, failureMessages: string[] }[]} */
  const cases = [];
  /** @type {string[]} */
  const suites = [];
  for (const suite of report.testResults) {
    need(typeof suite.name === "string" && Array.isArray(suite.assertionResults), "strict JSON suite identity is unreadable");
    const file = posix(relative(scratch, resolve(suite.name)));
    need(tests.includes(file) && !suites.includes(file), "strict JSON names a missing, repeated or unselected suite");
    suites.push(file);
    for (const entry of suite.assertionResults) {
      need(typeof entry.fullName === "string" && entry.fullName.length > 0 && typeof entry.title === "string" && entry.title.length > 0
        && (entry.status === "passed" || entry.status === "failed")
        && Array.isArray(entry.failureMessages) && entry.failureMessages.every((/** @type {unknown} */ text) => typeof text === "string"),
      "strict JSON case is unreadable, pending, skipped or todo");
      const messages = entry.failureMessages.map((/** @type {string} */ text) => stripAnsi(text));
      need(entry.status !== "failed" || messages.some((/** @type {string} */ text) => /\bAssertionError:/.test(text)),
        "strict case failed without an actual assertion (import/runtime/timeout is not a witness)");
      cases.push({ file, fullName: entry.fullName, title: entry.title, status: entry.status, failureMessages: messages });
    }
  }
  const census = cases.map((entry) => JSON.stringify([entry.file, entry.fullName])).sort();
  need(census.length > 0 && new Set(census).size === census.length, "strict JSON case census is empty or ambiguous");
  need(report.numTotalTests === cases.length && report.numPendingTests === 0 && (report.numTodoTests ?? 0) === 0
    && report.numFailedTests === failed && report.numPassedTests === passed
    && failed === cases.filter((entry) => entry.status === "failed").length
    && passed === cases.filter((entry) => entry.status === "passed").length, "strict JSON/default case counts disagree");
  need((report.numRuntimeErrorTestSuites ?? 0) === 0 && (report.numUnhandledErrors ?? 0) === 0
    && (report.unhandledErrors === undefined || Array.isArray(report.unhandledErrors) && report.unhandledErrors.length === 0),
  "strict JSON records an unhandled runtime failure");
  return { census, cases, success: report.success };
}

/**
 * Every failed test in a vitest run, as { test, message, at, source }: the test's full name (the
 * `FAIL  file > describe > it` line), the first error line under it, and the code-frame location and
 * source line vitest's caret points at — the assertion that actually went red. Read from vitest's own
 * failure blocks (each ends at a `⎯⎯⎯` rule), so nothing here guesses which assertion failed.
 * @param {string} out
 * @returns {{ test: string, message: string, at: string, source: string }[]}
 */
function parseFailures(out) {
  /** @type {{ test: string, message: string, at: string, source: string }[]} */
  const failures = [];
  const lines = out.split(/\r?\n/);
  for (let i = 0; i < lines.length; i += 1) {
    const head = /^\s*FAIL\s+(\S+\s+>\s+.+)$/.exec(lines[i] ?? "");
    if (head === null || head[1] === undefined) continue;
    let message = "";
    let at = "";
    let source = "";
    let j = i + 1;
    for (; j < lines.length; j += 1) {
      const line = lines[j] ?? "";
      if (/^\s*FAIL\s+\S+\s+>/.test(line) || /^⎯{3,}/.test(line.trim())) break;
      if (message === "" && /^\s*(?:[A-Za-z]*Error|AssertionError)\b[:\s]/.test(line)) message = line.trim();
      const loc = /^\s*❯\s+(\S+:\d+:\d+)\s*$/.exec(line);
      if (loc !== null && at === "" && loc[1] !== undefined && /\.test\.[cm]?[tj]sx?:/.test(loc[1])) at = loc[1];
      /* The caret line (`   |    ^`) follows the source line it points at. */
      if (source === "" && /^\s*\|\s*\^\s*$/.test(line)) source = (/^\s*\d+\|(.*)$/.exec(lines[j - 1] ?? "")?.[1] ?? "").trim();
    }
    failures.push({ test: head[1].trim(), message, at, source });
    i = j - 1;
  }
  return failures;
}

/**
 * A failure that is ONLY an error-message mismatch: the code under test still threw, and the test
 * noticed nothing but the wording. Vitest words it "expected [Function] to throw error matching /x/
 * but got '…'" (or "including"). Such a failure cannot be what kills a mutant whose guard's job is to
 * throw at all: the throw still happened.
 * @param {string} message
 */
const messageOnly = (message) => /\bto throw (?:an )?error (?:matching|including)\b.*\bbut got\b/.test(message);

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
  if (!pristine.has(rel)) pristine.set(rel, strictMode ? ordinaryBytes(join(scratch, rel)) : readFileSync(join(scratch, rel)));
};
for (const m of selected) for (const e of m.edits) touch(e.file);
const REBUILT_OUTPUTS = ["src/data/fabric.json"];
if (selected.some((m) => m.rebuild !== undefined)) for (const f of REBUILT_OUTPUTS) touch(f);
const writeScratch = (/** @type {string} */ rel, /** @type {Buffer} */ bytes) => {
  const path = resolve(scratch, rel);
  need(inside(scratch, path) && realpathSync(path) === path, "strict write is not an ordinary scratch path");
  const fd = openSync(path, constants.O_RDWR | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const stat = fstatSync(fd);
    need(stat.isFile() && stat.nlink === 1, "strict write refuses a nonregular or shared scratch file");
    ftruncateSync(fd, 0);
    let offset = 0;
    while (offset < bytes.length) {
      const n = writeSync(fd, bytes, offset, bytes.length - offset, offset);
      need(n > 0, "strict scratch write made no progress"); offset += n;
    }
  } finally { closeSync(fd); }
  need(ordinaryBytes(path).equals(bytes), "strict scratch write did not preserve the selected bytes");
};
const restoreAll = () => {
  for (const [rel, bytes] of pristine) {
    if (strictMode) writeScratch(rel, bytes);
    else writeFileSync(join(scratch, rel), bytes);
  }
};

/* ── baselines: every (tests, pattern) the mutations use must be green, and non-vacuous, unmutated ── */
/** @param {Mutation} m */
const keyOf = (m) => JSON.stringify([m.tests, m.pattern ?? null, m.strictWitness !== undefined]);
/** @type {Map<string, ReturnType<typeof runTests>>} */
const baselines = new Map();
let bad = 0;
for (const m of selected) {
  const key = keyOf(m);
  if (baselines.has(key)) continue;
  const b = runTests(m.tests, m.pattern, m.strictWitness === undefined ? undefined : `baseline-${strictBaselines.length + 1}`);
  baselines.set(key, b);
  let ok = b.code === 0 && b.failed === 0 && b.passed > 0;
  if (m.strictWitness !== undefined) {
    const witnesses = strictSelected.filter((candidate) => keyOf(candidate) === key).map((candidate) => candidate.strictWitness?.testName);
    ok = ok && b.strictError === null && b.jsonResult?.success === true
      && witnesses.every((name) => b.jsonResult?.cases.filter((entry) => entry.title === name && entry.status === "passed").length === 1);
    strictBaselines.push({ tests: m.tests, evidence: b.evidence, status: ok ? "GREEN" : "FAILED_OR_INCOMPLETE",
      census: b.jsonResult?.census ?? null, passed: b.passed, failed: b.failed, error: b.strictError });
    if (!ok) strictProblems.push("strict unmutated baseline or required positive witness was not complete and green");
    saveStrict();
  }
  console.log(`${ok ? "BASELINE green" : "BASELINE RED  "}  ${m.tests.join(" ")}${m.pattern === undefined ? "" : ` -t "${m.pattern}"`}  (${b.passed} passed, ${b.failed} failed, exit ${b.code})`);
  if (!ok) bad += 1;
}
console.log("");

/* ── mutations ─────────────────────────────────────────────────────────────────────────────────── */
/** @type {Map<string, { killed: number, total: number, problems: string[] }>} */
const byEngine = new Map();
for (const m of selected) {
  const e = byEngine.get(m.engine) ?? { killed: 0, total: 0, problems: [] };
  byEngine.set(m.engine, e);
  const expectSurvive = m.expect === "survives";
  if (!expectSurvive) e.total += 1;

  const baseline = baselines.get(keyOf(m));
  if (m.strictWitness !== undefined) {
    const witness = m.strictWitness;
    /** @type {{ id: string, status: string, [key: string]: unknown }} */
    const observation = { id: m.id, status: "INCOMPLETE", restored: false };
    try {
      restoreAll();
      need(baseline !== undefined && baseline.code === 0 && baseline.failed === 0 && baseline.passed > 0
        && baseline.strictError === null && baseline.jsonResult?.success === true, "strict baseline was not complete and green");
      const base = /** @type {NonNullable<typeof baseline>} */ (baseline);
      need(base.jsonResult?.cases.filter((entry) => entry.title === witness.testName && entry.status === "passed").length === 1,
        "strict baseline did not execute the unique positive control");
      for (const ed of m.edits) {
        const text = ordinaryBytes(join(scratch, ed.file)).toString("utf8");
        const count = text.split(ed.find).length - 1;
        need(count === 1, `strict guard anchor occurs ${count} times in ${ed.file}; expected exactly one`);
        writeScratch(ed.file, Buffer.from(text.replace(ed.find, () => ed.replace)));
      }
      const r = runTests(m.tests, m.pattern, m.id);
      observation.evidence = r.evidence;
      observation.code = r.code; observation.passed = r.passed; observation.failed = r.failed;
      observation.census = r.jsonResult?.census ?? null;
      need(r.strictError === null && r.jsonResult !== null, r.strictError ?? "strict JSON result is unavailable");
      const json = /** @type {NonNullable<typeof r.jsonResult>} */ (r.jsonResult);
      need(JSON.stringify(json.census) === JSON.stringify(base.jsonResult?.census), "strict mutant changed the complete test census");
      if (r.code === 0) {
        observation.status = "SURVIVED";
      } else {
        need(r.code === 1 && r.failed > 0 && json.success === false, "strict mutant did not produce a normal assertion failure");
        const exact = json.cases.filter((entry) => entry.title === witness.testName && entry.status === "failed");
        const frames = r.failures.filter((f) => f.test.endsWith(` > ${witness.testName}`)
          && m.tests.some((file) => f.at.startsWith(`${file}:`) || f.at.startsWith(`${join(scratch, file)}:`))
          && f.message.startsWith(`AssertionError: ${witness.marker}`) && !messageOnly(f.message)
          && f.source.includes("expect(") && f.source.includes(witness.marker)
          && m.killedBy.test(`${f.test}\n${f.message}\n${f.source}`));
        const jsonWitness = exact.length === 1 && exact[0]?.failureMessages.some((message) =>
          message.includes(`AssertionError: ${witness.marker}`) && !messageOnly(message));
        observation.witness = frames;
        observation.status = jsonWitness && frames.length === 1 ? "KILLED_BY_DISTINCT_ASSERTION" : "MISATTRIBUTED";
      }
    } catch (error) {
      observation.status = "INVALID_OR_INCONCLUSIVE";
      observation.error = error instanceof Error ? error.message : String(error);
    } finally {
      try { restoreAll(); observation.restored = true; }
      catch (error) {
        observation.restored = false; observation.status = "RESTORATION_FAILED";
        strictProblems.push(`${m.id} restoration failed: ${error instanceof Error ? error.message : String(error)}`);
      }
      strictObservations.push(observation);
      saveStrict();
    }
    if (observation.status === "KILLED_BY_DISTINCT_ASSERTION") e.killed += 1;
    else { e.problems.push(`${m.id} ${observation.status}`); bad += 1; }
    console.log(`${observation.status} ${m.id}: ${JSON.stringify(observation)}`);
    continue;
  }
  restoreAll();
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
    const targeted = r.failures.filter((f) => m.killedBy.test(`${f.test}\n${f.message}\n${f.source}`));
    const behavioural = targeted.filter((f) => !messageOnly(f.message));
    const by = behavioural[0];
    if (by !== undefined) {
      e.killed += 1;
      console.log(`KILLED    ${m.id}  [${m.record}]  ${where}: ${r.failed} failed, ${r.passed} passed`);
      console.log(`          by the targeted assertion ${by.at}: ${by.source}`);
      console.log(`          ${by.message.slice(0, 200)}`);
    } else {
      const why =
        targeted.length > 0
          ? `its targeted assertion failed only on an error-message mismatch (the code still threw): ${targeted[0]?.message.slice(0, 160) ?? ""}`
          : r.failures.length === 0
            ? `${r.failed} failed, but no failure block could be read from vitest's output, so what went red is unknown`
            : `red, but not by its targeted assertion ${String(m.killedBy)}; what failed: ${r.failures.map((f) => `${f.at} ${f.message.slice(0, 100)}`).join(" | ")}`;
      console.log(`MISATTRIBUTED ${m.id}  [${m.record}]  ${where}: ${why}`);
      e.problems.push(`${m.id} MISATTRIBUTED`);
      bad += 1;
    }
  } else if (r.code !== 0) {
    /* No failed test, but a non-zero exit: a crashed worker or an unhandled error. That is neither a
       kill nor a survival — nothing was judged. */
    console.log(`INCONCLUSIVE ${m.id}  [${m.record}]  ${where}: exit ${r.code} with ${r.passed} passed and 0 failed (a crash or unhandled error, not a verdict): ${r.firstFailure}`);
    e.problems.push(`${m.id} INCONCLUSIVE`);
    bad += 1;
  } else {
    console.log(`SURVIVED  ${m.id}  [${m.record}]  ${where}: ${r.passed} passed, 0 failed (exit ${r.code}) — the test does not catch: ${m.what}`);
    e.problems.push(`${m.id} SURVIVED`);
    bad += 1;
  }
}
if (strictMode) {
  try {
    restoreAll();
    strictScratchRestored = strictObservations.every((row) => row.restored === true)
      && [...pristine].every(([rel, bytes]) => ordinaryBytes(join(scratch, rel)).equals(bytes));
    need(strictScratchRestored, "one or more strict scratch restorations remain incomplete");
    for (const [path, bytes] of checkoutInputs) need(ordinaryBytes(path).equals(bytes), "selected checkout input changed during scratch execution");
    need(strictGit("rev-parse", "HEAD").toString().trim() === sourceBefore?.commit
      && strictGit("rev-parse", "HEAD^{tree}").toString().trim() === sourceBefore?.tree
      && strictGit("status", "--porcelain=v1", "--untracked-files=all").length === 0,
    "checkout identity or tracked/untracked state changed during scratch execution");
    strictSourceAfterPreserved = true;
  } catch (error) {
    strictProblems.push(error instanceof Error ? error.message : String(error)); bad += 1;
  }
  try {
    // Unlink only entries this process created. Never descend into dependency targets.
    // Node's rm does not follow remaining symlinks; the recursive target is the owned scratch root.
    need(realpathSync(root) === root && dirname(root) === realpathSync(tmpdir())
      && root.startsWith(join(realpathSync(tmpdir()), "atlas-mutation-"))
      && realpathSync(scratch) === scratch, "refusing cleanup outside the owned scratch root");
    for (const entry of dependencyLinks) {
      need(inside(scratch, entry.path) && lstatSync(entry.path).isSymbolicLink()
        && realpathSync(entry.path) === entry.target, "scratch dependency link changed before cleanup");
      unlinkSync(entry.path);
    }
    rmSync(root, { recursive: true, force: true });
  } catch (error) {
    strictProblems.push(`scratch cleanup failed: ${error instanceof Error ? error.message : String(error)}`); bad += 1;
  }
  saveStrict();
} else {
  restoreAll();
  /* Remove the node_modules JUNCTION itself first (rmdir removes the link, never its target), so the
     recursive delete below cannot reach the real node_modules through it. */
  rmdirSync(join(scratch, "node_modules"));
  rmSync(root, { recursive: true, force: true });
}

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
  console.log(`ENGINE ${path}: ${verdict} — ${e.killed} of ${e.total} reverted guard(s) killed by their targeted assertion${e.problems.length === 0 ? "" : `; ${e.problems.join(", ")}`}`);
}
for (const [path, e] of byEngine) {
  if (documented.includes(path)) continue;
  const verdict = e.problems.length === 0 && e.killed === e.total && e.total > 0 ? "PASS" : "FAIL";
  console.log(`ENGINE ${path} (not a refutation.md section): ${verdict} — ${e.killed} of ${e.total} reverted guard(s) killed by their targeted assertion${e.problems.length === 0 ? "" : `; ${e.problems.join(", ")}`}`);
}
for (const path of uncovered) {
  if (only.length === 0) bad += 1;
}
console.log("(not pre-fix history — see LIMIT above)");
process.exit(bad === 0 ? 0 : 1);
