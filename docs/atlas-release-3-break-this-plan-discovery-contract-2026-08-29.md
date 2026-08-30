# Atlas Release 3 QDP-001 “Break This Plan” discovery contract

Date: 2026-08-29

State: `DISCOVERY_PLANNING_ONLY`

Machine authority: none

Promotion effect: none

## Outcome

This slice makes the first bounded QDP-001 user moment executable without creating a Release 3
product gate. An architect can submit a finite set of wholly synthetic, ordered cutover candidates;
the adapter checks every candidate independently through the existing cutover simulator and returns
either:

- a digest-bound, replayable synthetic counterexample where an explicitly required flow changes
  from `computed:reached` to `computed:unreachable` through a positively observed discard route,
  with no ECMP partial-drop evidence; or
- an explicit abstention that preserves invalid, no-op, incomplete, conflicting, unqualified, and
  no-counterexample-observed states.

The adapter is `tools/run_atlas_r3_break_this_plan_discovery.py`. It is deliberately outside the
installable package, engine CLI, AssessHub, portable bundle, and Release 2 trusted-computing-base
census. It writes only canonical JSON to stdout. It cannot collect evidence, write a device, write a
file, call a network service, create a key or signature, rank candidates, select a candidate, compile
a TransitionCase, or invoke an authoritative gate.

## Fixed claim boundary

Every result emits:

```text
R3 DISCOVERY PROTOTYPE — NON-AUTHORITATIVE
qualification_state=EXPERIMENTAL
promotion_eligible=false
feasibility_verdict=null
selected_candidate=null
translation_checked=false
translation_state=TRANSLATION_NOT_ESTABLISHED
preview_eligible=false
authoritative_gate=null
decision_effect=NONE
```

The request must repeat, and the adapter must revalidate, the following exact product boundary:

- Release 2: `CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT`
- QCP-001: `EXPERIMENTAL` / `CONTRACT_ONLY`
- runtime: `PARTIAL_NONPORTABLE_PROTOTYPE`
- Release 3: `DISCOVERY_PLANNING_ONLY`

Any attempted state change is a refusal, not an input override.

## Why this is the selected discovery slice

The existing `cisco_toolkit.cutover_sim.simulate_cutover` owner already supplies the narrow technical
behavior QDP-001 needs first: bounded ordered mutations over a deep copy, fixed flow-pair evaluation,
per-step marginal loss and recovery, invalid/no-op disclosure, and L2 election indeterminacy. Reusing
that owner avoids creating a second network model or an unqualified solver.

Alternatives were rejected for this slice:

- another R2 authority packet would be governance-only and duplicate the existing immutable packet;
- a new generic finite-state solver would add unqualified semantics and a shipping/module-census
  commitment before the user workflow is validated;
- `comparison.compare_bound_pair` owns exact before/after snapshot comparison, not architecture
  candidate comparison;
- `precert.compute_precert` can emit `PASS` and therefore creates avoidable result-laundering risk;
- the reviewed R2 DSL and transition verifier expose gate-shaped outputs and are intentionally not
  invoked while QCP-001 remains unqualified.

## Request contract

The machine schema is
`docs/schemas/atlas-r3-break-this-plan-discovery-input-v1.schema.json`. In addition to schema
validation, the adapter enforces exact keys, canonical JSON, sorted unique identities, and fixed
limits. The CLI accepts custom request bytes only from bounded stdin; it exposes no caller-supplied
file or network path. `--fixture` reads only the one fixed tracked fixture through a single bounded,
regular, non-reparse file handle.

| Object | Discovery meaning | Boundary |
|---|---|---|
| `synthetic_snapshot` | Fictional current-state comparator consumed by existing offline FIB and cutover owners. | Raw authority-, policy-, trust-, key-, signature-, receipt-, approval-, ranking-, and selection-shaped keys are rejected. |
| `requirements` | Synthetic flow-preservation assertions plus optional explicitly human-only requirements. | At least one unique IPv4 or IPv6 flow is mandatory; human-only rows remain unevaluated. |
| `candidates` | A sorted, bounded candidate set; each candidate contains an ordered step list. | Every candidate is evaluated and accounted for; no aggregate score, preference, winner, or selected candidate exists. |
| `assumptions` | Synthetic assertions or explicit unresolved identifiers. | Unresolved assumptions survive in limitations and `next_evidence_requests`; they never default true. |
| `unresolved_dependency_ids` | Exact `R3-DEP-001` through `R3-DEP-011` census from the discovery-entry owner. | Missing, reordered, or narrowed dependency sets are refused. |
| `authority_placeholders` | `R2-AUTH-001`, `R2-AUTH-002`, and `R2-AUTH-004`. | All three values must be JSON `null`; the adapter accepts no receipt, policy, key, signature, principal, threshold, or custody value. |

The canonical synthetic fixture is
`tests/fixtures/atlas-r3-break-this-plan/unsafe-middle.synthetic.json`. It contains three candidates:
one unsupported candidate that must abstain, one candidate limited by unresolved/L2 evidence, and one
three-step candidate whose middle step strands an explicitly required flow.

## Bounded challenge and replay semantics

The adapter performs the following deterministic sequence:

1. Refuse oversized bytes before hashing or parsing.
2. Require exact canonical JSON, the synthetic-only mode, fixed product boundary, full dependency
   census, and null-only authority placeholders.
3. Establish non-vacuous baseline coverage for every flow requirement using
   `fib.trace_fib_path(..., disclose=True)`.
4. Bind the input, candidate set, requirements, product boundary, adapter source, simulator source,
   FIB/failover/what-if/transition-contract sources, request/result schemas, fixed limit profile,
   and exact Python implementation/version by SHA-256.
5. Call `simulate_cutover` once per candidate using exactly the declared flow pairs and ordered
   candidate steps.
6. Project a deliberately smaller result; never pass through simulator narrative, verdict, path,
   election, or readiness structures.
7. Emit a counterexample only for a matched required flow with all of these exact simulator facts:
   `kind=blocked`, `verdict=newly_blocked`, `old_status=computed:reached`,
   `new_status=computed:unreachable`, `new_drop_evidence=observed_discard`, and an empty
   `ecmp_dropping_legs` list. Absence-derived `no_route_observed` remains an abstention.
8. Bind the witness to the complete input and candidate-set digests. Replay reruns the complete
   request and accepts only an exact byte-for-byte re-emitted witness.

Witness replay therefore rejects changes to the case, candidate, candidate set, requirements,
product boundary, source semantics, step, observation, or witness digest. It proves only that this
non-authoritative adapter reproduced the same synthetic counterexample under the same checked source
bytes. It is not a signed receipt, independent review, feasibility result, or trusted completeness
certificate.

## Result taxonomy

Candidate results contain only `COUNTEREXAMPLE` or `ABSTENTION`.

| Result | Meaning | Explicit non-meaning |
|---|---|---|
| `COUNTEREXAMPLE / REPLAYABLE_OBSERVED_DISCARD_SYNTHETIC_FLOW` | A declared synthetic flow hit a positively observed discard route at a named candidate step and the witness replays against the complete candidate set. | Not field evidence, qualification, selection, ranking, or proof that other paths/services fail. |
| `ABSTENTION / NOT_EVALUABLE` | The candidate contains an invalid, unsupported, truncated, or no-op step, or the simulator cannot account for every step. | Never silently treated as safe. |
| `ABSTENTION / MODEL_CONFLICT` | A preservation requirement is already not reached in the declared synthetic baseline. | The candidate is not blamed for a pre-existing or inconsistent model. |
| `ABSTENTION / ABSTAIN_EVIDENCE_INCOMPLETE` | Baseline coverage, path custody, L2 continuity, a human requirement, an assumption, or a no-counterexample-observed run remains unresolved. | Election projections, `path_lost`, and an empty witness set are not counterexamples, support, completeness, or continuity proof. |

`path_lost` remains inconclusive because a once-computed path can become unprovable when its next hop
moves off the collected model. STP/FHRP rows remain election candidates only; the simulator explicitly
does not assess client attachment, component continuity, convergence, or surviving-gateway reachability.
Those negatives remain visible even when a separate definitive L3 counterexample exists.

## Fixed limits

The v1 limit profile is code-owned and cannot be widened by a request:

- input/output: 1,048,576 bytes each;
- witness: 65,536 bytes;
- candidates: 4;
- steps per candidate: 16;
- requirements: 32;
- assumptions per candidate: 32;
- step parameters: 8;
- emitted counterexamples: 128.

An exceeded input, output, step, candidate, or witness bound refuses the request. Counterexamples are
never silently truncated.

## Shape mapping to current R2 contracts

This is a static discovery map only. The adapter emits no TransitionCase or verifier receipt.

| R3 field | Current R2 shape | Mapping state | Held work |
|---|---|---|---|
| `case_id` and synthetic comparator digest | `transition_identity` and `before_snapshot_digest` concepts | `SHAPE_ALIGNED_ONLY` | No exact R2 identity, source, time, or custody envelope is produced. |
| ordered candidate steps | `evolution_ir` has states and transition relations | `PARTIAL_EXTERNAL_CONTENT_REQUIRED` | R2 `predecessor_edges` are inter-transition relations, not this internal candidate-step sequence. |
| flow requirements | obligation and evidence-atom concepts | `PARTIAL_EXTERNAL_CONTENT_REQUIRED` | No QCP applicability, obligation compilation, or authoritative evidence status is minted. |
| unresolved assumptions and human requirements | no first-class candidate-assumption owner | `UNMAPPED_R3_STRATEGY` | A future R3 information model must own assumptions, defeaters, expiry, and human disposition. |
| replayable counterexample | could later supply counter-evidence content | `PROHIBITED_DURING_DISCOVERY` | It cannot become R2 `COUNTER_EVIDENCE`/`VIOLATED` without full source, qualification, policy, and custody bindings. |
| candidate set, ranking, selection, and Transition Program | no current qualified QDP owner | `PROHIBITED_DURING_DISCOVERY` | No ranking, selection, compilation, or `TRANSLATION_CHECKED` result exists. |

## R2 closure-ready handoffs remain null

The output references the existing owner
`docs/atlas-release-2-authority-candidate-protocol-2026-08-29.md` and preserves:

- `R2-AUTH-001`: selection receipt `null`; runtime evidence collection not started.
- `R2-AUTH-002`: Stage A plan receipt `null`; Stage B adequacy receipt `null`; workload evidence
  collection not started. The existing protocol remains the owner for population, sampling frame,
  strata, weights, role denominator, reconciled counts, criteria, thresholds, corpus, executions,
  coverage, custody, gaps, and decision rules.
- `R2-AUTH-004`: Profile P1 remains `PROPOSED_UNAPPROVED`; implementation approval and operational
  designation receipts remain `null`; no real key or signature is created. The existing protocol
  remains the owner for policy succession, revocation, trusted time, role separation, and custody.

The adapter cannot consume a future `SELECT` receipt. Runtime or workload collection remains forbidden
until a separate current authority consumer validates an externally effective receipt.

## Threat model and permanent tests

`tests/test_atlas_r3_break_this_plan_discovery.py` guards:

- canonical and schema-valid input/output;
- unsafe-middle witness production and exact replay;
- cross-case and candidate-set-narrowing witness teleportation;
- candidate-set totality and input immutability;
- invalid/no-op preservation, path-loss abstention, baseline conflict, and human-only requirements;
- N−1/N/N+1 candidate and step bounds, plus fail-closed byte, output, witness, and counterexample ceilings;
- rejection of duplicate keys, non-canonical bytes, non-null authority values, and authority-shaped
  snapshot keys;
- absence of R2 verifier/DSL/authority imports and authoritative gate tokens;
- exact per-action parameter consumption, camelCase authority-key rejection, and closed limitation vocabulary;
- exact R2/QCP/runtime/R3 boundary reconciliation; and
- stdout-only CLI operation from an arbitrary directory.

The highest-risk defect shapes are a clean simulation laundered into support, candidate-set narrowing
after a witness is found, an incomplete path treated as a block, an unsupported step silently omitted,
or a null authority field filled by prose. Each is fail-closed in v1.

The 2026-08-30 semantic-dependency closure strengthens the existing v1 digest without changing its
schema shape. The original digest omitted transitive `failover.py`, `whatif.py`, and
`transition_contract.py` behavior plus the request/result schemas. Those exact source bytes and the
interpreter identity are now bound, so a prior witness cannot replay after a bound source/schema
change. The separate campaign capsule additionally binds each replay to the full child result,
including limitations; see
`docs/atlas-release-3-break-this-plan-campaign-contract-2026-08-30.md`.

## Evaluation and next decision boundary

This slice is useful if synthetic studies show that architects can understand a named unsafe step,
its requirement, and its limitations without raw simulator JSON. It should be killed or redesigned if
the fixed mutation vocabulary cannot express realistic candidate differences, if definitive-blocked
projection is too narrow to produce actionable counterexamples, or if operators interpret abstention as
candidate support.

No implementation beyond this synthetic discovery surface is authorized by the slice. The next genuine
R3 decision is whether reviewed discovery evidence justifies a separately scoped information model and
operator study. That decision is distinct from R2 source selection, runtime/workload collection, QCP-001
qualification, Release 3 preview, promotion, publication, shipment, or GA.

## Reproduce locally

```powershell
py -3.12 -B tools/run_atlas_r3_break_this_plan_discovery.py --fixture
py -3.12 -m pytest -q tests/test_atlas_r3_break_this_plan_discovery.py
```

Both commands are offline and synthetic-only. Neither authorizes a real observation or device action.
