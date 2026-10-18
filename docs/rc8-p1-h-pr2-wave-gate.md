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

Neutral producer `info` checks remain neutral; a `NOT ASSESSABLE` info row remains a coverage gap.
Remediation `items` and `by_device` are mirrored views, so matched occurrences count once; genuine
duplicates and unmatched negative rows survive. Punch-list scope reads the producer's `devices`.
Malformed finding scope cannot masquerade as a clean disjoint row. Failure custody reads the existing
`ssot.failed_sections` owner plus explicit malformed-record checks.

`webapp/backend/cutover.py` deletes `_gate` and its fleet verdict reducer and displays the engine
batch through `backend.engine.wave_rollup`; `wave_cutover` exposes the same single-wave entry.
The API includes the full `gate_evidence` record, and the cutover DOCX displays its reasons/gaps.
`cisco_toolkit/mop.py` deletes `_worst_readiness`, delegates `_join_group_records` to
`analyze.join_wave_group_records`, and displays the batch verdict in BLUF, overview and every wave.
Its old assessment readiness is separately labelled; it is no longer the cutover decision.

Existing schedules remain explicit: AssessHub currently schedules sequencing groups; MOP may render
the design wave plan's combined or split scopes. The same scope always uses the same function and
policy. This change does not claim that those two scheduling models are identical.

## Debt, output custody and validation

The Divergent pre-change gate domain shrinks. The JSON edit removes 26 exact retired-symbol rows
and adds zero, taking the current v3 file from 36,891 to 36,865. This is a **provisional partial
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
