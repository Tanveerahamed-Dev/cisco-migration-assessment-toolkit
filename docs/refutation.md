# Refutation record

**Acceptance F3** — *"Every engine has survived an adversarial refuter whose stated job was to
disprove it; confirmed defects fixed with a regression test that failed before the fix."* Evidence:
*"Refutation reports and the regression tests."*

Until 2026-09-21 the reports half of that evidence did not exist. The regression tests did — several
hundred of them, several dozen of which cite a refuter in a comment — but there was no document a
reviewer could open to answer "which engines were attacked, by what, and what did it find?". An
independent auditor reading `docs/` found four files and none of them was this one, so F3 was
**UNPROVEN**, which by this project's own vocabulary counts as FAIL for release.

This file is that document. It is written to be checkable rather than reassuring: every claim below
cites the file and line that carries it, every engine has an explicit verdict including the ones
that come out badly, and the two places where the evidence is weaker than F3 asks for are stated in
their own section rather than left for the next reader to discover.

---

## 0. What "refuted" means here, and the limit on all of it

A refuter is an adversarial pass whose stated job is to **disprove** a module — not to test it.
The distinction matters: a test suite written by the author encodes the author's model of the
problem, so it agrees with the author's mistakes. The refuter's question is "what does this claim
that it did not measure?", and the finding is a counterexample, not an opinion.

**The provenance limit, stated first because it qualifies everything else.** When this section was
first written, `atlas-scope` had no Git history of its own; it was an untracked directory inside its
parent repository
(`git status --short` in the parent reports `?? atlas-scope/`). F3 asks for "a regression test that
**failed before the fix**", and for every engine except `claims` that half is **attested in prose
by the refuter, not verifiable from history**. A reader can confirm the test exists, that it pins a
named defect, and that the code now satisfies it. A reader cannot independently confirm that it was
red first. That is a real gap in F3's evidence and it is not closed by this document.

It is closed going forward: a repository was initialised for `atlas-scope` on 2026-09-21, baseline
commit `857b520` — since rebuilt marker-free as `50a3dc5`, which differs from it by one comment line
(`docs/open-issues.md` O10; the history continues `254694b`, `1d19e22`) — so every refutation from
this point has a before and an after. That commit is a
snapshot taken while several repair agents were working in the tree — its value is being a
*before*, not being tidy. Retroactively the gap cannot be closed at all, and asserting otherwise
would be exactly the kind of unearned confidence the refuters exist to catch.

**Second limit.** "Survived a refuter" is not "is correct". A refuter is a bounded adversary with a
finite budget who attacks the claims it can see. Each section below therefore records what was
**not** examined alongside what was.

---

## 1. Forwarding engine — `src/forwarding/engine.ts`

**Refuted: yes. Two independent passes, both confirmed defects, both fixed and pinned.**

### 1.1 Against the real producer (`cisco_toolkit.parse._acl_rule`)

Report: `src/forwarding/producer-trust.test.ts:1-40`. The refuter attacked the seam between the
upstream ACL parser and this consumer, and both confirmed defects were **the same underlying
mistake — the consumer re-deriving something the producer had already decided**:

| # | Defect | Pinned by |
|---|---|---|
| 1 | **Evaluability drift.** The producer marks a line `unevaluable` when it could not model it. The engine re-derived that from the raw text, so the two could disagree — and where the engine's derivation was the more optimistic one, an unknown became a confident wrong answer. | `producer-trust.test.ts` — "the producer's own verdict is the ground truth" block |
| 2 | **A null port compared as a number.** The producer emits `{"op":"eq","val":null}` for a port NAME it cannot resolve (`eq citrix`). Compared numerically that is a definite non-match, so a `permit` line silently stops firing and the flow falls through to a `deny` — a definite "denied" for a flow the configuration explicitly permits. | `producer-trust.test.ts:145-160`, and independently at the compiler boundary, `compiler-fidelity.test.ts:101-115` |

Defect 2 is the sharpest thing any refuter found in this product: a *missing* value silently became
a *decided* one, and the decided one was wrong in the unsafe direction. The fixture in
`producer-trust.test.ts:151` is shaped exactly like the real producer's output for that case rather
than hand-invented, which is what stops the test agreeing with the bug.

### 1.2 Against the engine's own claim honesty (external audit, 2026-09-21)

Report: `src/forwarding/engine.test.ts:530-533` — *"the three claim-honesty defects found by an
external audit"*. All three were **a positive claim the code asserted rather than measured**, and
all three were "true-looking and wrong on the app's own headline flow"
(`10.0.10.50 → 10.0.30.10 tcp/443`). The lead one: **undecidability was treated as a property of the
ACL the heuristic picked, rather than of the deciding HOST**. Pinned from
`engine.test.ts:534` onward, against the real compiled snapshot, with the test's own preconditions
asserted first (`engine.test.ts:537-545`) so the assertions cannot quietly stop meaning what they
say.

**Not examined:** IPv6, multicast, and any stateful behaviour — the model is forward-direction and
stateless by design, and the refuter took that as scope rather than as a defect.

---

## 2. Blast radius — `src/analysis/blast.ts`

**Refuted: yes. Seven confirmed defects, each with its own named regression block.**

Reports are inline at `src/analysis/blast.test.ts:416` onward. Unusually for this tree the refuter's
findings are legible from the test names alone, which is why they are reproduced verbatim:

| Regression block | The claim that was not measured |
|---|---|
| `blast.test.ts:468` | a blast radius is measured inside the failed element's **own component** |
| `blast.test.ts:537` | a cut vertex separates **only what its removal separates** |
| `blast.test.ts:561` | a cut vertex's endpoint count keeps its **coverage honesty** |
| `blast.test.ts:614` | reachability from a host whose **own cabling was never observed** |
| `blast.test.ts:646` | projection prose quotes **the quantity that actually moved** |
| `blast.test.ts:678` | the shared graph is evidence **a renderer cannot edit** |
| `blast.test.ts:700` | the path-enumeration **ceiling is a ceiling** |

Four of the seven are the same shape — *a number computed over one population and reported as
though it described another*. The module additionally carries a brute-force cross-check of its
Hopcroft–Tarjan implementation (`blast.test.ts:342`), which is a stronger form of refutation than
any of the above: an independent algorithm disagreeing is a counterexample, not an opinion.

**Not examined:** weighted or directed failure propagation. The graph is undirected and unweighted.

---

## 3. Layout — `src/fabric3d/layout.ts`

**Refuted: yes. Four confirmed defects, grouped by shape.**

Report: `src/fabric3d/layout.test.ts:570-574`, which states the grouping explicitly — *"a claim the
code did not compute, a positional artifact published as evidence, an unvalidated input, and
missing evidence rendered as a structural fact."* The first regression block is
`layout.test.ts:576` — *"the suggested detour is measured, not assumed"*.

The fourth of those — *missing evidence rendered as a structural fact* — is this repository's
signature failure class appearing in a geometry module, which is worth noting because it is the
last place anyone would look for it.

**Not examined:** aesthetic quality of the layout. That is what the blind comparison adjudicates,
not a refuter.

---

## 4. Query — `src/core/query.ts`

**Refuted: yes. A confirmed defect class, pinned by seven assertions.**

Report: `src/core/query.test.ts:566-571`. The refuter's finding was a single class rather than a
list: **a never-collected device rendered as an empty result rather than as an evidence gap** — the
canonical "absence presented as health" defect, in the surface a user reaches first.

What makes this block good evidence is its scoping, stated at `query.test.ts:611`: the property is
pinned as *"a property of the clause's device scope, not of a list of hostnames"*. The refuter
explicitly refused the fix-by-longer-list that this repository keeps having to reject elsewhere.
The block also pins the **partial** case (`:626`) and the **fully-collected** case (`:646`), so the
gap prose cannot be produced unconditionally and score a pass.

Every expectation in the block is derived by traversing `fabric.json` directly rather than by
re-running the code path under test (`query.test.ts:569-570`) — i.e. the oracle is independent of
the subject, which is the property that makes a regression test worth having.

**Not examined:** query performance, and free-text parsing of clauses the grammar does not define.

---

## 5. Compiler — `tools/compile-snapshot.mjs`

**Refuted: yes, at the boundary. Fidelity, not correctness.**

Report: `src/core/compiler-fidelity.test.ts:8-20`. The refuter attacked the compiler's *lossiness*
against the real producer and pinned the fields whose loss is **not merely lossy but misleading**:

- `unevaluable` — the producer's own verdict that a line cannot be modelled. Re-deriving it
  downstream is the parser-versus-detector drift this repository names explicitly.
- `unmodeled_qualifiers` — which specific qualifier defeated it.
- `established` — a stateful match a forward-direction model cannot decide.
- a port match with a **null value** — the same defect as §1.1/2, caught independently at a second
  boundary, which is the only reason to believe either catch was not luck.

**Not examined, and this is the notable gap:** the compiler was refuted for what it *drops*, not
for what it *transforms*. A field that survives compilation with a changed meaning would not be
caught by any assertion in that file.

---

## 6. Claims — `src/core/claims.ts`

**Before 2026-09-21: NOT REFUTED. No refuter had ever been run against it.**

This was the worst gap in F3, and it was not a small one: `claims.ts` decides the
`RESOLVED` / `REFUTED` / `UNDETERMINED` banding and the
`SCOPED` / `OBSERVED` / `INDETERMINATE` / `OUT OF SCOPE` badge that **every B-criterion in
`docs/acceptance.md` rests on**. The most load-bearing honesty module in the product was the one
module nothing had tried to disprove.

A refuter was run on 2026-09-21. Method: adversarial inputs to every exported decision function —
`claimBadge`, `scopeTuple`, `bandOfOutcome`, `bandOfHop`, `forbiddenWordsIn` — constructed to
attack the *shape* of each decision rather than its typical case. Six probes, all six of which
returned something other than what the module's own documentation implies.

### CONFIRMED and FIXED

**C1 — `claimBadge` awarded `SCOPED` to a traversal that visited nothing.** BLOCKER.

Measured: `claimBadge({outcome: "delivered", hops: [], unmodelledHosts: []})` returned `"SCOPED"` —
the strongest badge in the product, on a trace with no hops, no evidence and nothing decided.

Root cause, and the reason it is worth more than a one-line fix: **every check in `claimBadge` was
a check for a DISQUALIFIER.** No unmodelled host on the path; no indeterminate evidence; and
`trace.hops.every(…)`, which is vacuously `true` on an empty array. An empty trace satisfies all
three by having nothing in it. The badge was computed from what was ABSENT rather than from what
was PRESENT — this product's own named failure shape, occurring in the function that decides its
strongest claim.

The repair requires positive evidence: at least one hop actually traversed (`claims.ts`,
`claimBadge`). Pinned by `claims.test.ts` → *"bands a delivered trace with no hops as
INDETERMINATE, not SCOPED"*. **This test fails against the pre-fix source** — verified by running
the refuter before the change, which is what produced the `"SCOPED"` reading above.

*Escalation found while writing the non-regression test.* The empty traversal is **reachable from
real data**: the product's own `suggestedFlows()` includes `198.51.100.7 → 10.0.30.10 tcp/443`,
which produces `hops: []` on this snapshot. The only thing that kept it off the `SCOPED` path was
that the engine also set `outcome: "out-of-scope"`, which `claimBadge` answers before reaching any
of the checks above. So the badge's correctness on live data depended on a second, separate
decision being right — not on the badge logic. The companion test
(*"changes no real trace's badge, because the new guard is unreachable for all of them"*) asserts
exactly that property, and deliberately asserts `empties > 0`, so if the empty case ever stops
occurring the test says so instead of quietly becoming vacuous.

**C3 — `bandOfOutcome` and `bandOfHop` returned `undefined` for an unrecognised value.** MAJOR.

Measured: `bandOfOutcome("bogus")` → `undefined`; `bandOfHop({verdict: "bogus"})` → `undefined`.
Both are exhaustive `switch`es with no trailing return. TypeScript makes that safe for a
well-typed caller — but these values originate in **compiled snapshot JSON**, so a verdict string a
future producer emits is a runtime input, not a hypothetical. A renderer draws `undefined` as a
blank band, and a verdict with no band reads as "nothing to say here": absence presented as a
settled state, in the module that exists to prevent that.

Repair: both functions fall through to `"UNDETERMINED"`. Exhaustiveness is **not** given up to get
it — `outcome` / `hop.verdict` are narrowed to `never` by the switch and assigned to a `never`
binding, so adding a variant without handling it still fails the compile rather than quietly
banding `UNDETERMINED`. Pinned by `claims.test.ts` →
*"REFUTED: an unrecognised verdict bands as UNDETERMINED, never as nothing"* (two tests). **Both
fail against the pre-fix source.**

**C2 — `claimBadge` never cross-checked `trace.outcome` against the hop verdicts.** FIXED
(open-issues R16; this section recorded it as OPEN until 2026-09-22, after the fix had landed).

Measured: a trace with `outcome: "delivered"` whose only hop has `verdict: "loop"` returned
`"SCOPED"`, while `bandOfHop` on that same hop correctly returned `"REFUTED"`. The badge consulted
only the trace-level outcome and the host-modelling coverage; it never looked at what the hops
actually said. Two parts of the same module disagreed about the same trace and the badge took the
more flattering side.

The tempting repair — "every hop must band `RESOLVED`" — is wrong: it would turn a genuinely
`denied` flow into `INDETERMINATE`, and a denied flow is a *confidently answered* question. The
repair that landed is `hopsSupportOutcome` in `claims.ts`: one rule, read through `bandOfHop`, that
no hop bands `UNDETERMINED`, the last hop bands exactly as the outcome does, and a `delivered`
outcome needs every hop `RESOLVED`. `claimBadge` and `isDecidedOutcome` (and so `bandOfTrace`) both
ask it, so the badge and the band cannot disagree about one trace. It was placed in the claims
module after all, not the engine: the function is exported and applied to whatever `Trace` a caller
holds, so an engine-side invariant alone would again be an assumption about a caller. Pinned by
`claims.test.ts` → *"REFUTED (C2): no outcome earns a stronger badge than its hops support"*.

**C2/C3 follow-up, found 2026-09-22 by probe.** `hopsSupportOutcome` waves through an outcome word
it does not recognise ("claims nothing, so nothing for the hops to contradict"), and `claimBadge`
only answered the literal word `indeterminate` early. So a trace whose outcome was an
unrecognised runtime value (C3's input) over ORDINARY hops — every host modelled, no policy gap —
earned `"SCOPED"` while `bandOfTrace` beside it said `UNDETERMINED`: the C2 disagreement, reached
through the C3 door. Measured red before the fix: `expected 'SCOPED' to be 'INDETERMINATE'`.
Repair: `claimBadge` withholds every badge above `INDETERMINATE` from ANY word that
`bandOfOutcome` bands `UNDETERMINED`. Pinned by *"an unrecognised outcome word over a clean,
fully-modelled traversal is INDETERMINATE, not SCOPED"* and by a sweep over every
UNDETERMINED-banding word against no hop and every hop verdict.

**Consequence for C1's line.** The C1 repair had been a dedicated line in `claimBadge`
(`if (trace.hops.length === 0) return "INDETERMINATE"`) that the acceptance grading found
UNPINNED: deleting it left every claims test green, because for a decided word
`hopsSupportOutcome` refuses a zero-hop trace too. It decided only the unrecognised-word case —
which the follow-up rule above now covers, hops or none. The line then decided nothing on any input
(measured: deleted, all claims tests stay green) and was removed. The empty-traversal rule has two
owners, each load-bearing and each killed by a mutation (`review/mutation-check.mjs`
`claims-c1-decided-owner`, `claims-undetermined-word-badge`, `claims-c1-both-owners`), and a
property test — *"an EMPTY traversal earns no badge above INDETERMINATE under any outcome word at
all"* — pins it across every word.

### CONFIRMED as a disclosed limit — no change

**C6 — `forbiddenWordsIn` misses an overclaim negated across an unpunctuated clause.** Measured:

| input | flagged |
|---|---|
| `we found no errors so the link is healthy` | *nothing* |
| `we found no errors. the link is healthy` | `healthy` |
| `the path is SAFE` | `safe` |
| `nothing can be proven about forwarding on them` | *nothing* (correct — an honest disclaimer) |
| `this is unproven` / `unhealthy` / `not healthy` | *nothing* (correct) |
| `It is not the case that this is verified, clean and passing` | `clean`, `passing` |

The first row is a false negative: `CLAUSE_BOUNDARY` is `/[.;:,\n—]|\s-\s/`, so "so" does not end a
clause and the negation "no" carries across into the claim. The module's own doc comment gives the
*comma* form of that sentence as its worked example, and the comma form IS caught — so the
documentation is accurate and the gap is adjacent to it rather than contradicted by it. The module
already declares the honest limit at `claims.ts:95-97`: *"this is lexical, not semantic… a backstop
against the common case, not a proof of honesty."* No change made; recorded so the limit is known
by example and not only by adjective.

The last row confirms the negation scope is **clause-before-the-word**, not sentence: "verified" is
correctly cleared by the leading "not", while "clean" and "passing" — in a later clause — are
flagged. That is the documented behaviour, arguably over-strict, and over-strict is the safe
direction for this gate.

### NOT defects — refuted claims that survived

- **`scopeTuple.unmodelledOnPath` counts `trace.unmodelledHosts` without intersecting the path**,
  despite its name and its doc comment ("Hosts on **this path** with no collected RIB"). Measured:
  an unmodelled host that is not on the path still forecloses `SCOPED`. The count can only be ≥ the
  true on-path count, so it can only ever *weaken* a claim, never strengthen one. **Naming
  inaccuracy, not a correctness defect** — left alone rather than "fixed" into something less
  conservative.
- **`modelledOnPath` de-duplicates hosts while `hops` counts hops.** Two hops through `core1` give
  `hops: 2, modelledOnPath: 1`. Consistent with the implementation (`[...onPath]`) and with what
  the field means. Not a defect.
- **Word-boundary handling.** `unhealthy`, `unproven`, `unverified` are correctly not flagged, which
  is the trap `claims.ts:103-106` documents and avoids. Confirmed working.

**Not examined** (added 2026-09-23; §0 says every section records this, and until today this one did
not — acceptance report F3). The 2026-09-21 refuter attacked five exported decision functions —
`claimBadge`, `scopeTuple`, `bandOfOutcome`, `bandOfHop`, `forbiddenWordsIn` — and the 2026-09-22
probe attacked `claimBadge` against `hopsSupportOutcome` through the C3 input. Nothing in this record
is an adversarial pass over the rest of the module:
- the other decision exports: `isDecidedOutcome`, `bandOfTrace`, `outcomeUndecidingGaps`,
  `outcomeUndecidedCauses`, `undecidedOutcomeWord`, `hopUndecided`, `hopUndecidedGaps`, `bandOfHopIn`
  and `isInvalidInput` — pinned by `claims.test.ts` and, for the owners of the empty-traversal rule,
  by `review/mutation-check.mjs`, but written by the author, not attacked by a refuter;
- the literal templates (`T1_verdict` … `T10_SAMPLE_PATH`, `sharePayload`), the absence helpers
  (`absence`, `resolveAbsence`, `isAbsence`), the route-field readers (`routeFieldReading`,
  `adminDistanceRank`, `notApplicableReason`, `isRouteRecord`) and `missingInventoryFields`;
- the completeness of `FORBIDDEN_CLAIM_WORDS` and `STRONG_CLAIM_WORDS` — C6 probed where a
  negation's scope ends, not whether an overclaim can be phrased in a word the lists do not hold;
- the consumers: whether every surface that shows a band or badge (`ClaimCard`, `HopList`,
  `PathTrace`, the fabric's `Fabric3D` / `flow`) renders the value this module returns rather than
  re-deriving or overriding it. A correct badge rendered by a caller that ignores it is not examined
  by any pass recorded here.

The export list is read from `src/core/claims.ts` as of this date; `claims.ts` is edited by later
repair waves, so re-derive it (`grep -n "^export" src/core/claims.ts`) rather than trusting this list.

---

## 7. Where F3 stands

| Engine | Refuted | Confirmed defects | Fixed | Pre-fix history | Reverted guard turns its test red (`review/mutation-check.mjs`) |
|---|---|---|---|---|---|
| forwarding | yes (×2 passes) | 5 | 5 | no — attested in prose only | yes — 4 mutations, 4 killed |
| blast | yes | 7 | 7 | no — attested in prose only | yes — 2 mutations, 2 killed |
| layout | yes | 4 | 4 | no — attested in prose only | yes — 2 mutations, 2 killed |
| query | yes | 1 class | yes | no — attested in prose only | yes — 1 mutation, 1 killed |
| compiler | yes (fidelity only) | 4 | 4 | no — attested in prose only | yes — 2 mutations, 2 killed (rebuilt, then tested) |
| claims | **yes, 2026-09-21** | 3 confirmed (+ the 2026-09-22 C2/C3 follow-up) + 1 disclosed limit | **3 of 3, and the follow-up** | **yes — refuter output recorded above** | yes — 5 mutations, 5 killed |

(Counts as run on 2026-09-23 on the working tree: `node review/mutation-check.mjs` exited 0, **18 of
18 mutations killed** — the 16 in the table above plus two source-binding mutations (O15, not engine
sections, reported after the documented engines) — every targeted test green unmutated first. The
2026-09-22 reading here said "16 of 16"; read the count from the run, not from this line.)

**F3 is supportable for the report half; the history half is now executable evidence of a stated,
narrower kind.** The reports exist and cite their evidence. For every engine, `review/mutation-check.mjs`
reverts each recorded guard in a scratch copy of the current tree and requires the named regression
test to go red; a mutation that survives, a guard text that no longer occurs exactly once, a baseline
that was not green, or an engine section of this document with no mutation, all exit non-zero. **It
does not recreate pre-fix history** — it proves each test detects the defect's shape in today's
code, not that the test was red on the source as it stood before the fix — and it says so in its
own output. A reviewer grading F3 should grade it on that split rather than on a single word.

One item remains open and should not be silently carried:

1. **The compiler was refuted for what it drops, not for what it transforms.** No pass has yet
   attacked a field that survives compilation with a changed meaning.

(C2 was listed here as open until 2026-09-22; it had been fixed in `claims.ts` — see §6.)
