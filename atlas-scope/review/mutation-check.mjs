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
 *         node review/mutation-check.mjs --list
 *         node review/mutation-check.mjs --history   per mutation, from git: the first commit whose
 *                                                    file holds each guard text, and whether the root does
 * Exit:   0 every mutation KILLED by its targeted assertion (and every expected-equivalent probe
 *           behaved as recorded)
 *         1 any mutation SURVIVED, was MISATTRIBUTED (red, but not by `killedBy`, or only by an error
 *           message), was INVALID, or its baseline was not green; or an engine the document names has
 *           no mutation
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
 *   killedBy: RegExp,
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
    tests: ["src/panels/DataGrid.c2-chrome-slice.test.tsx"],
    killedBy: /the shared rail did not move \(the grid could show the row itself\)/,
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
  const out = `${r.stdout ?? ""}\n${r.stderr ?? ""}`.replace(/\u001b\[[0-9;]*m/g, "");
  const failed = Number(/Tests\s+(\d+) failed/.exec(out)?.[1] ?? 0);
  const passed = Number(/(\d+) passed/.exec(/Tests\s+[^\n]*/.exec(out)?.[0] ?? "")?.[1] ?? 0);
  const firstFailure = /(AssertionError[^\n]*|Error:[^\n]*)/.exec(out)?.[1] ?? "";
  return { code: r.status ?? -1, failed, passed, firstFailure: firstFailure.slice(0, 160), failures: parseFailures(out), out };
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
