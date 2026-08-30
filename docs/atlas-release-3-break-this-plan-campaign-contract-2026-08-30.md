# Atlas Release 3 QDP-001 “Break This Plan” synthetic campaign contract

Date: 2026-08-30

State: `DISCOVERY_PLANNING_ONLY`

Machine authority: none

Promotion effect: none

## Outcome

This slice turns the single-case QDP-001 discovery adapter into a bounded adversarial campaign
without adding another network model or a shipping surface. An architect can run a finite ordered
set of complete canonical synthetic cases and receive:

- exact case and candidate accounting;
- every child `COUNTEREXAMPLE` or `ABSTENTION`, without ranking or filtering;
- automatic replay of every emitted counterexample against its complete unchanged case;
- an exact limitation and abstention-frequency census; and
- a deterministic Markdown operator report that keeps negative and unresolved states visible.

The campaign capsule is `tools/run_atlas_r3_break_this_plan_campaign.py`. It calls only the existing
`analyze_request_bytes` and `replay_counterexample_bytes` discovery boundaries. It does not import
`cutover_sim`, FIB, failover, R2 verification, runtime discovery, workload review, or TCB-review
owners directly. It writes only to stdout and cannot collect evidence, access a network, write a
device, create a key or signature, rank or select a candidate, compile a TransitionCase, invoke an
authoritative gate, or change a release state.

## Fixed non-promotion boundary

Every campaign and nested case retains exactly:

- Release 2: `CLOSED_INCOMPLETE_EXPERIMENTAL_CHECKPOINT`
- QCP-001: `EXPERIMENTAL` / `CONTRACT_ONLY`
- runtime: `PARTIAL_NONPORTABLE_PROTOTYPE`
- Release 3: `DISCOVERY_PLANNING_ONLY`

Every campaign result also fixes:

```text
R3 SYNTHETIC CAMPAIGN — NON-AUTHORITATIVE
authoritative=false
authoritative_gate=null
decision_effect=NONE
qualification_state=EXPERIMENTAL
promotion_eligible=false
feasibility_verdict=null
selected_candidate=null
translation_checked=false
translation_state=TRANSLATION_NOT_ESTABLISHED
preview_eligible=false
next_observation=null
```

Campaign aggregation and successful replay do not add evidence, establish support, or authorize an
external observation. An all-abstention campaign is not a safe or positive result. A campaign with
counterexamples proves only that those exact synthetic observed-discard witnesses reproduced.

## Why this bounded item

The merged v1 adapter already owns the difficult fail-closed projection from raw simulator output
to replayable counterexample or abstention. The remaining operator gap was orchestration:

- only one tracked case existed;
- replay was library-only;
- no campaign-wide totality or replay ledger existed; and
- operators had to inspect canonical JSON to reconcile limitations.

A separate capsule preserves the v1 single-case contract and avoids a second simulation model.
Direct Master Reference integration is held: its labs are static definition-only walkthroughs and
its curated content has a broader consequential-claim and release-census surface.

## Campaign input

The machine schema is
`docs/schemas/atlas-r3-break-this-plan-campaign-input-v1.schema.json`. It delegates each `cases[]`
item to `atlas.r3-break-this-plan-discovery-input/1`; schema consumers register that existing
resource under `urn:atlas:r3:break-this-plan:discovery-input:1`.

The capsule additionally enforces exact canonical JSON, exact keys, sorted unique case identities,
the complete `R3-DEP-001` through `R3-DEP-011` census, and null-only placeholders for
`R2-AUTH-001`, `R2-AUTH-002`, and `R2-AUTH-004`. Every nested case is revalidated by the existing
adapter. One invalid case refuses the whole campaign; cases and results are never truncated or
silently omitted.

The tracked campaign fixture is
`tests/fixtures/atlas-r3-break-this-plan/campaign.synthetic.json`. It contains four wholly
synthetic cases and six candidates:

1. baseline conflict;
2. an explicitly human-only requirement;
3. absence-derived path loss; and
4. the unsafe-middle case with unresolved, invalid/no-op, and observed-discard candidates.

The expected campaign outcome is five abstentions, one counterexample candidate, one emitted
counterexample, and one successful automatic replay. Those counts describe this fixture only; they
are not a quality score or population estimate.

## Semantic and replay custody

The original v1 semantics digest omitted repository modules that influence `cutover_sim` through
transitive calls. The strengthened discovery semantics profile `/2` now binds exact bytes for:

- the discovery adapter;
- `cutover_sim.py`, `fib.py`, `failover.py`, and `whatif.py`;
- `transition_contract.py`;
- both discovery schemas;
- the fixed discovery limit profile; and
- the Python implementation and exact interpreter version.

Changing any bound source or schema changes the child `semantics_digest`; an earlier witness then
fails exact replay. This is source/runtime identity, not installed-distribution, memory-image,
platform, provenance, or authority proof.

The campaign adds a stronger result-custody layer. `case_set_digest` binds the ordered set of each
exact case input digest and full child discovery-result digest. The latter includes every candidate,
result kind, reason, limitation, witness, checked count, and simulation-projection digest.
Each replay envelope then carries `campaign_replay_binding_digest` over:

- campaign ID and exact campaign-input digest;
- complete `case_set_digest`; and
- the exact replay-receipt digest.

Therefore narrowing a campaign or changing only an operator-visible limitation changes the campaign
replay binding even if the narrow v1 witness itself remains byte-identical. This digest is not a
signature, authenticated receipt, independent review, trusted time, revocation proof, or custody
attestation.

## Result and operator report

The canonical result schema is
`docs/schemas/atlas-r3-break-this-plan-campaign-result-v1.schema.json`. It delegates nested discovery
results to `atlas.r3-break-this-plan-discovery-result/1`, registered by schema consumers under
`urn:atlas:r3:break-this-plan:discovery-result:1`.

The result includes:

- exact totals for cases, candidates, abstentions, counterexample candidates, emitted witnesses,
  successful replays, and replay failures;
- the complete unchanged child result for every case;
- the exact replay receipt and campaign replay binding for every witness;
- closed observed limitation and abstention reason counts; and
- the union of unresolved next-evidence identifiers.

`--operator-report` renders the same freshly computed result as deterministic UTF-8 Markdown. It
shows every case and candidate, result kind, reason, checked-step count, replay count, and applicable
limitation. It never renders raw simulator paths, narratives, election objects, readiness output, or
a green/pass/safe state.

## Bounds

- campaign input: 9,437,184 bytes;
- canonical campaign result: 8,388,608 bytes;
- Markdown operator report: 1,048,576 bytes;
- cases: 8;
- nested case/candidate/step/witness bounds: unchanged from the v1 discovery adapter.

Any exceeded bound refuses the whole campaign. No row, limitation, witness, or case is silently
truncated.

## R2 closure-ready handoffs remain unresolved

The campaign copies the byte-semantic handoff object only after every child result agrees exactly:

- `R2-AUTH-001`: selection receipt remains `null`; evidence collection remains not started.
- `R2-AUTH-002`: Stage A plan and Stage B adequacy receipts remain `null`; workload evidence
  collection remains not started. Synthetic campaign cases are not a target population, sampling
  frame, representative-workload denominator, corpus, adequacy decision, or authorization.
- `R2-AUTH-004`: Profile P1 remains `PROPOSED_UNAPPROVED`; implementation and operational receipts
  remain `null`; no real key or signature is created. Digests and replay do not establish policy
  succession, custody, trusted time, revocation, separation, or authority.

Every missing authority value remains an unresolved placeholder for a future authenticated external
update. The capsule accepts none of those values and cannot start runtime or workload evidence
collection. A currently valid externally effective
`SELECT_CANDIDATE_FOR_EVIDENCE_COLLECTION` receipt remains a separate precondition.

## Threat model and tests

`tests/test_atlas_r3_break_this_plan_campaign.py` and the strengthened single-case tests cover:

- canonical and schema-valid input/result;
- exact case, candidate, limitation, abstention, counterexample, and replay accounting;
- all-abstention rendering that explicitly forbids a support inference;
- campaign narrowing and cross-campaign replay-binding changes;
- full child-result binding when only limitations change;
- complete repository semantic dependency binding;
- invalid, duplicate, unsorted, noncanonical, oversized, and authority-bearing inputs;
- N−1/N/N+1 case bounds and output/report refusal without truncation;
- whole-campaign refusal on replay failure or mixed child semantics; and
- stdout-only operation from an arbitrary directory.

The most consequential preserved negative result is the prior replay-binding gap. The v1 witness
bound adapter, FIB, and simulator source but not all transitive repository behavior or the full
candidate limitation projection. The strengthened semantic profile and campaign result binding close
those two bounded seams. They do not make the simulator qualified or complete.

## Reproduce locally

```powershell
py -3.12 -B tools/run_atlas_r3_break_this_plan_campaign.py --fixture
py -3.12 -B tools/run_atlas_r3_break_this_plan_campaign.py --fixture --operator-report
py -3.12 -m pytest -q tests/test_atlas_r3_break_this_plan_campaign.py tests/test_atlas_r3_break_this_plan_discovery.py
```

All commands are offline and synthetic-only. None authorizes a real observation, workload, runtime
collection, device action, qualification, promotion, publication, release, or GA.

## Next genuine boundary

Use the campaign output in a bounded operator study: can an architect distinguish a replayed
counterexample from abstention and explain the retained limitations without raw simulator JSON?
That study may justify a separately scoped information-model or generated viewer. It cannot supply
R2 workload adequacy, trust/custody authority, QCP-001 qualification, R3 preview, promotion,
publication, shipment, or GA.
