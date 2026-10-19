# RC8-P1-H PR-2: one pre-change wave gate

Local author handoff, 2026-10-18. Base: `e679c524d364c1bc6462746486b0f06e4b3d6256`.
Branch: `codex/rc8-p1-h-pr2`. The current supervisor assignment authorizes local implementation.
No push, workflow dispatch, local test, build, engine, Graphify or verification-controller run is authorized.
The supervisor owns `docs/NOW.md`; this feature branch does not edit that board.

## Design and implementation

`cisco_toolkit/analyze.py :: compute_wave_cutover_gate(snapshot, group_names, switches)` is the
single per-wave decision owner. Inputs are the assessment snapshot, exact move-group labels, and
explicit wave device membership. Its internal `_wave_cutover_record` composes the policy.
`rollup_wave_cutover_gates(snapshot, waves)` accepts the existing `(name, switches, kind, groups)`
scope tuples, computes the canonical current-baseline receipt once, returns every wave record in
input order, and owns the worst-wave fleet decision. Both consumers use that batch and reuse the
same records throughout their output. No stored snapshot section, module role or detector changes.

The closed `wave_cutover_gate/1` record has these fields:

| Field | Meaning |
|---|---|
| `schema` | `wave_cutover_gate/1` |
| `verdict` | `GO`, `CONDITIONAL GO`, `NO-GO`, or `NOT ASSESSED` only |
| `scope` | Exact sorted `groups` and `switches`; no positional identity repair |
| `counts` | Readiness fail/warn, Critical cross-layer, High/Critical remediation and punch-list, and blind-health occurrence counts |
| `reasons` | Blocking and conditional evidence descriptions |
| `coverage` | `complete` and deduplicated `gaps`; incomplete collection, failed phases, malformed or missing evidence stay visible |
| `current_baseline` | Projection of the existing baseline receipt's schema, verdict, assessed state, integrity, item and blocker totals; no duplicated diagnostic sample |
| `limitations` | Assessment scope, conservative group-to-slice restriction and fleet baseline hold |

`wave_cutover_rollup/1` has `schema`, `verdict`, and ordered `waves`. No waves, or only empty
unassessed scopes, is `NOT ASSESSED`; a known blocker takes priority. A mixed assessed/unassessed
schedule cannot become `GO`. These are assessment decisions, never CAB approval, custody admission,
observed migration success or execution acceptance.

Policy keeps negative witnesses from both former rule sets. `NOT READY`, failing counts or checks,
Critical cross-layer findings, and any valid fleet baseline blocker produce `NO-GO`. A group blocker
applies to every sub-wave slice even when presentation counts attribute a check to one slice.
Legacy coercible positive fail counts and lowercase negative labels retain their negative effect;
malformed values cannot certify a pass. Warnings, `CAUTION`, High/Critical remediation or punch-list items, partial/blind collection and
unverified evidence prevent `GO`. Only recognized readiness, nonvacuous observed checks, complete
health evidence, readable findings inputs and a clear, bound baseline can yield `GO`.

`CONDITIONAL GO` retains an evidence hold: its reasons/gaps must be resolved or explicitly
dispositioned through the human change process. Existing MOP baseline HOLD wording and human
preconditions remain. Every non-GO wave receives at least the former MOP high-risk controls.

Neutral producer `info` checks remain neutral; explicit unobserved markers such as `NOT ASSESSABLE`
remain coverage gaps regardless of check status, including a contradictory `pass`.
Remediation `items` and `by_device` are mirrored views, so matched occurrences count once; genuine
duplicates and unmatched negative rows survive. Punch-list scope reads the producer's `devices`.
Malformed finding scope cannot masquerade as a clean disjoint row. Failure custody reads the existing
`ssot.failed_sections` owner plus explicit malformed-record checks.

`webapp/backend/cutover.py` deletes `_gate` and its fleet verdict reducer and displays the engine
batch through `backend.engine.wave_rollup`; `wave_cutover` exposes the same single-wave entry.
The API includes the full `gate_evidence` record, and the cutover DOCX displays its reasons/gaps.
`cisco_toolkit/mop.py` deletes `_worst_readiness`, delegates `_join_group_records` to
`analyze.join_wave_group_records`, and displays the batch verdict in BLUF, overview and every wave.
Its old assessment readiness is retained as assessment context under an explicit precedence notice;
it is no longer the cutover decision.

Existing schedules remain explicit: AssessHub currently schedules sequencing groups; MOP may render
the design wave plan's combined or split scopes. The same scope always uses the same function and
policy. This change does not claim that those two scheduling models are identical.

## Debt, output custody and validation

The Divergent pre-change gate domain shrinks. The original JSON edit removed 26 exact retired-symbol
rows. The local review correction removes four more stale verdict-symbol occurrences, for 30
deletions and zero additions, taking the current v3 file from 36,891 to 36,861. This is a **provisional partial
deletion**, not an admitted current census: removal of calculations in retained functions also leaves
stale expression/lexical rows that require the authorized hosted observation. No local inspector was
run. The final register must equal current detections and remain a strict subset with no additions;
do not publish or call its gate green from this provisional count.

PR #682 was still OPEN on the last live check. After it merges, rebase onto current main and retain
its schema/policy. Reapply these deletions by exact identities against that schema; obtain the
hosted observation only after supervisor CI authorization. If source edits produce any new detected
site, refactor it away; no admission, detector change or role exemption is authorized here.

Tracked golden snapshot, sheet schema and sample fleet bytes are held at the base. No persisted
engine section or module census was added, so no regeneration is expected. Static unchanged-byte
evidence does not establish regeneration reproducibility. If hosted evidence finds any difference,
review the cause and use `docs/engine-output-handoff.md` on the exact source before importing any
replacement. Changed sample bytes additionally require the separate Scope owner handoff.

Generated MOP/cutover DOCX content intentionally changes: unified vocabulary, stricter hold cases,
engine reasons/gaps and distinct assessment-readiness labelling. No generated DOCX is replaced in
this branch. DOCX semantic/render checks remain hosted work; they are outside the handoff's closed
three stored-output paths. No test, gate, budget, timeout, assertion strength, frozen source,
module boundary, release version or comparison/post-change decision policy is relaxed.

Hosted tests authored in `tests/test_wave_cutover_gate.py` cover a nonvacuous GO control, both prior
disagreement directions, contradictory checks/counts, all required sections absent/malformed,
unknown/duplicate readiness, normal and unobserved info, malformed nested scope, remediation mirror
and duplicate accounting, disjoint canonical punch scope, partial/nonfinite/invalid data quality,
unbound baseline blockers, split-group safety, failed-phase fallback, empty scope/schedule,
immutability, and API/MOP/cutover-DOCX equality for identical scope. Existing assertions are updated
to require the stronger fleet hold and the engine vocabulary; GO controls gain real evidence inputs.

Local validation is limited to touched-file Ruff, AST/compilation syntax, JSON parsing and Git diff
checks. No tests, builds, engine, detector or Graphify execution supplies local evidence. Independent
static review found six defects during authoring; source corrections address them, with runtime
closure still unverified. Final acceptance requires the exact-head hosted full gates, unchanged
budgets/timeouts, exact debt subset/equality, golden/sample reproducibility and independent review.

## Open work for the supervisor

1. Merge #682, then rebase this local branch onto current main before any authorized publication.
2. Authorize stream capacity, push and hosted execution explicitly. Neither was performed.
3. Obtain the current-schema observation; delete all remaining stale rows and reject every addition.
4. Execute the new focused tests, all affected existing tests, full required workflows and output
   reproducibility checks. Runtime behavior, rendering, response size and performance are not verified.
5. Review the conservative group-to-slice and fleet baseline restrictions and explicit scheduling
   scope difference. No change to the scheduling model or human authority is implied.
6. If output regeneration becomes necessary, review and import only through the engine-output handoff.

No unrelated defect is represented as resolved by this local implementation.

## BLOCKED-LOCAL review correction of 8b0d10dd

The independent local review identified three findings. This correction remains local; the same
reviewer owns the next acceptance decision. No hosted observation, test, build, engine or detector
run was performed, and no push, PR or CI was started.

| Finding | Local source correction | Verification and remaining status |
|---|---|---|
| P1: unobserved evidence could produce GO when status was `pass` | `_wave_cutover_record` checks the engine-owned unobserved-note markers before interpreting status. Case, whitespace and underscore/hyphen separators are normalized. Existing fail/warn restrictions remain. | Added the exact positive-control-to-contradictory-pass regression, plus status/marker combinations. Ruff and syntax only; runtime not verified. |
| P2: stale register entries violate exact equality | Removed `fleet_gate` verdict-symbol occurrences 2 and 3 in `cutover.build_plan`, and `combined_gate` occurrences 2 and 3 in `mop._write_bluf`; each has exactly one remaining source assignment. | Four further deletions, zero additions. **Still blocked:** obtaining the requested exact-head hosted observation conflicts with the unchanged no-CI instruction. Remaining expression/lexical staleness and current-schema census equality are not verified. No local inspector substitutes for that evidence. |
| P2: the app discarded gate explanations | `CutoverWave` now types the engine's `gate_evidence`. `WaveCard` displays every supplied reason and coverage gap without counts, filtering, caps or gate derivation. The explanation is visible with run-of-show collapsed. | Added rendered regressions for CONDITIONAL GO beside READY/CLEAR and for all engine reasons/gaps. TS/TSX syntax parsing passed; rendered behavior, type checking and generated frontend distribution remain unverified until authorized hosted execution. |

The tracked golden snapshot, sheet schema and sample bytes remain unchanged. This correction does
not modify detector, boundary, workflow, budget, timeout or assertion policy. PR #682 remains OPEN;
its schema rebase remains pending. The new frontend source intentionally needs the ordinary reviewed
hosted frontend build; no generated distribution or visual baseline is replaced locally.


## Authorized hosted closing phase — 2026-10-19

The supervisor released HOLD after #682 and #681 merged and authorized source pushes,
then one final push containing only received frontend dist and its receipt. No merge is
permitted. This section supersedes the earlier local-only authority statements above.

PR-2 is rebased onto main `bc54fa80721adf00f0e4c9f309b7264739ffc6fb`.
The original local heads remain `8b0d10dd` and `e6fb1933`; their rebased equivalents
are `8d2c5ebd` and `2c1a6978`. Main's v4 schema and empty boundary registry are preserved,
and main's `docs/NOW.md` is byte-identical. The only conflict was the append-only debt
narrative: both the complete PR-1 JSX history and PR-2 handoff were retained. PR-1's
summary/topology source, distribution and admission receipt are retained unchanged.

Post-#681 main has 36,784 registered sites. The existing 30 PR-2 deletions leave
36,754 provisionally; exact-source hosted observation must remove every remaining stale
identity with zero additions before completion. No local census or runtime probe is used.

The added wave-gate tests use synthetic mappings and per-test temporary outputs, with no
millisecond budget, live host capture or shared runner mutation. They do not require the
runner exclusively. Any hosted discovery of such a requirement must be fixed with the
existing `unshared` marker, retaining the full complementary execution and every assertion.

The unchanged matrix census supplies the first P2's evidence. A successful webapp-ci
producer, hosted frontend receiver, dist/receipt-only import and hosted post_import supply
the second P2's custody chain. The source/dist reproduction checks remain required. Final
acceptance requires 14/14 exact-head protected contexts and applicable app workflows, then
one completion comment with every source/import head and per-finding evidence. Independent
review follows; CI success grants no merge or release authority.


### First hosted source and download-name binding correction

Source `ec7d66b89109481c0207b6cf0c1090a3ede5be43` opened PR #692. CI run
`39168276107`, Windows job `117795745785`, failed two unchanged client-artifact
census assertions before reaching the interface census. The complete endpoint-chain
source proof was stale: the new `WaveCutoverEvidence` type and `WaveCard` panel changed
`api.ts` and `CutoverPlanner.tsx`. Consequently all three retained implicit-download
obligations correctly became unclassified, including unchanged Execution/Snapshot callers.
This failed head supplies no interface census and no admitted frontend artifact.

Source review retains the exact original imports, useAsync/catalogue flow, three href
expressions, URL factories, GET routes, success headers, sanitized filename stem, SPECS
and docmeta suffix owners. Six of the eight pinned files are byte-identical to main.
The only two pin updates are api.ts `108849be` -> `db43befd` and CutoverPlanner.tsx
`b16306b6` -> `9f4d3f8a`; their complete diffs contain only the evidence type/panel.
The helper, bindings, classifier and every source-mutation/unknown-name assertion remain
unchanged. This refreshes inspected source identity, not a pass-through allowance or
weaker test. Hosted execution must close both failures before the existing census runs.

The same source's Distribution job `117795745715` failed immutable SPA reproduction;
Atlas job `117795745562` stopped at its tracked-SPA rebuild check. Both are retained
negative evidence for the pending source-bound dist import; no reproduction assertion
is bypassed. Superseded or cancelled jobs do not supply final-head acceptance.


### Source 3080e267 observation and refused presentation footprints

CI `39169510130`, Linux 3.13 job `117799615223`, passes the repaired download-name
contracts, 491 early refusal/stability controls (three full-census tests deselected),
and the real-producer canonical check. Its complete guard reports 493 passed / one
failed. The unchanged observation emits 36,732 sites, fingerprint
`4d7c07acc78e392d6dee5a798dc15ce441df1eebc799ad86fd093b1abf2fbaa9`,
for tested merge `b56baa0b5bc67ab4c9c921708726be058b99c26a`, tree
`33e8855bfb7da452a834ec386ca7697acb0fcbae` (the source head's exact tree).

The proposal has 25 stale identities and three unregistered candidates relative to
36,754 retained rows. It was refused without importing any row. The candidates are:

| File/symbol/rule | Unadmitted fingerprint (occurrence 1) | Repair |
|---|---|---|
| cutover.py / build_plan / collection-update | `75151d2b3b8ecadd5dfc503e35e52d44cf6e9f0393429bf9223c70892dd390ed` | Keep the original wave append expression and attach the engine receipt afterward by direct assignment. |
| mop.py / write_mop_docx / collection-update | `b9c921874b91cb750f8fc260dd81a6dff0a1d66a3c8085d53290c2a0b6d3b07a` | Keep the original overview append expression; a fresh local render copy binds its historical readiness cell to the engine gate. Source/assessment records are not mutated, and the header remains Engine gate. |
| mop.py / write_mop_docx / graph-traversal | `9974fad6ac2f27832f746c7798c1e579bccd9809ddcf4a028ef141b1d0e0647e` | Restore the complete original per-wave loop byte-for-byte, retaining its existing entry. Put the scoped engine decision/evidence register and mandatory non-GO controls before that unchanged legacy loop. |

Both original aggregation call ASTs are statically identical to main, and the complete
original per-wave loop is statically byte-identical to main. Every actual count,
threshold, ordering and validation expression stays visible and registered. A new
scoped engine-decision register is a mandatory precondition for each named window;
its notice explicitly says legacy READY/CAUTION/readiness rows and proceed wording
cannot clear an engine hold. It preserves all engine reasons/gaps and adds the
engine-required TAC pre-open instruction for every non-GO window. No gate reducer
is restored: the group join remains engine-owned, and BLUF/overview remain engine
projections. New DOCX assertions pin the named engine decision, scope, mandatory
precedence, non-GO control, unchanged fallback prose, overview gate and source purity.

The initial unpushed local `fc29915d` used fixed-prose extraction; the supervisor's
explicit restore-or-engine routing superseded that approach before publication.
The final repair uses complete literal loop restoration. There is no detector,
role or boundary change and no candidate admission. A fresh exact-source hosted
observation, not a locally reconstructed census, must validate the repaired source
before all remaining stale entries can be removed.


### Complete stale-set import from the literal-restored source

Source `897b2d4a1035f82987ee2a9ab4c485d8bd868f58`, CI `39171530046`, Linux 3.11
job `117805473118`, passes 491 early controls and the real-producer canonical check.
Its complete ratchet reports 493 passed / one failed solely for stale rows;
**unregistered or resurrected sites is empty**. The complete observation emits
36,732 sites, fingerprint `74baca876c01142eb78a081f95ce88ec6bb3cc2f0882038bd326991d8d1e3d17`,
for tested merge `b8bb9005554b3ff59f407fbbd25e94b3ec6c9f37`, exact source tree
`4b3501885591253899cec7b2a9da0a61eadb95b7`.

The edit compares the full 36,754-row provisional register with the full hosted
proposal, refuses every addition and policy/boundary change, and deletes all 22
stale rows. It does not use only the error message's capped twelve examples and
never executes the census locally. `docs/rc8-p1-h-pr2-census-retirement.json` records
every one of these 22 deletions and all 52 cumulative identities removed from the
post-#681 main register: **36,784 -> 36,732, 52 removals, zero additions**. All removals
are in cisco_toolkit/mop.py or webapp/backend/cutover.py. Schema, origin, active stage,
boundary rows and detector bytes remain unchanged. Restored legacy assembly identities
were retained throughout; the three unadmitted candidates were never registered.

This data edit closes the known stale set for that exact source observation, not the
final-head gate by itself. The new pushed head must pass the unchanged complete census,
all canonical checks, full default/unshared complements, every required context and the
source-bound frontend import/reproduction chain. The failed/superseded source runs stay
negative history. No local runtime, test, engine, build or receipt controller is used.
