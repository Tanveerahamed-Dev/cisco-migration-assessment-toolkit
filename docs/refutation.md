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

**The provenance limit, stated first because it qualifies everything else.** `atlas-scope` has no
Git history of its own; it is an untracked directory inside its parent repository
(`git status --short` in the parent reports `?? atlas-scope/`). F3 asks for "a regression test that
**failed before the fix**", and for every engine except `claims` that half is **attested in prose
by the refuter, not verifiable from history**. A reader can confirm the test exists, that it pins a
named defect, and that the code now satisfies it. A reader cannot independently confirm that it was
red first. That is a real gap in F3's evidence and it is not closed by this document.

It is closed going forward: a repository was initialised for `atlas-scope` on 2026-09-21 with a
baseline commit, so every refutation from this point has a before and an after. Retroactively it
cannot be closed at all, and asserting otherwise would be exactly the kind of unearned confidence
the refuters exist to catch.

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

### CONFIRMED and NOT fixed — open

**C2 — `claimBadge` never cross-checks `trace.outcome` against the hop verdicts.** OPEN.

Measured: a trace with `outcome: "delivered"` whose only hop has `verdict: "loop"` returns
`"SCOPED"`, while `bandOfHop` on that same hop correctly returns `"REFUTED"`. The badge consults
only the trace-level outcome and the host-modelling coverage; it never looks at what the hops
actually say. Two parts of the same module disagree about the same trace and the badge takes the
more flattering side.

**Not fixed here, deliberately.** The tempting repair — "every hop must band `RESOLVED`" — is
wrong: it would turn a genuinely `denied` flow into `INDETERMINATE`, and a denied flow is a
*confidently answered* question. That is visible immediately in capture state `06-path-blocked`.
The honest repair is an **invariant on the engine** (a `delivered` outcome requires a final
`delivered` hop; a `denied` outcome requires a `denied` hop), enforced where traces are produced,
which is `src/forwarding/engine.ts`'s lane and not the badge's. Recorded here rather than patched
in the wrong module.

**Reachability:** not reachable from the current engine, which does not emit self-contradictory
traces. That is an assumption about a caller, not a property of an exported function — which is the
precise thing C1 proved can go wrong.

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

---

## 7. Where F3 stands

| Engine | Refuted | Confirmed defects | Fixed | "Failed before the fix" verifiable |
|---|---|---|---|---|
| forwarding | yes (×2 passes) | 5 | 5 | no — attested in prose only |
| blast | yes | 7 | 7 | no — attested in prose only |
| layout | yes | 4 | 4 | no — attested in prose only |
| query | yes | 1 class | yes | no — attested in prose only |
| compiler | yes (fidelity only) | 4 | 4 | no — attested in prose only |
| claims | **yes, 2026-09-21** | 3 confirmed + 1 disclosed limit | 2 of 3 | **yes — refuter output recorded above** |

**F3 is now supportable for the report half and remains qualified on the history half.** The
reports exist and cite their evidence; the "failed before the fix" half is verifiable for `claims`
and, for the other five engines, rests on the refuters' own prose. A reviewer grading F3 should
grade it on that split rather than on a single word.

Two items remain open and neither should be silently carried:

1. **C2** — the badge does not cross-check the trace outcome against the hop verdicts. Owner:
   whoever owns the engine's trace invariants.
2. **The compiler was refuted for what it drops, not for what it transforms.** No pass has yet
   attacked a field that survives compilation with a changed meaning.
