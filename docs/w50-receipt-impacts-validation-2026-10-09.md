# W50 failure-impact rows in execution receipts read the engine owner (validation record)

Branch `claude/w50-receipt-impacts`, cut from the local branch `claude/w48-impact-consumers` at `e7c00e12`. The
stack is main ← #629 (W45, which adds the owner `cisco_toolkit/impact_assessability.py`) ← W48 ← W50. It is
committed locally and not pushed.

No local test, build, engine, pipeline, npm or vitest run happened (owner GitHub-only rule). The checks run locally
were static: in-memory compilation of every changed Python file, `ruff check` on them, an AST shadow scan of every
changed function, W48's guard scanner executed on its own (stdlib only, no package import), and the hand-list scanner
from `tests/test_protocol_assessability.py` executed the same way over every changed source file. The hosted gates
decide.

## The problem

`protocol_assurance.cutover_operator_evidence` copied every stored `failure_impact` row raw into
`rehearsal.impacts`, so a lower bound read as an exact count and a held zero as a measured zero. On the committed
sample, core1 (one inter-switch link with no trunk/STP evidence) went into the payload as an exact 45. AssessHub's
`ComparisonDecision` rendered those rows' `severity` and `detail` raw.

W48 stopped at this site because the payload is persisted inside every AssessHub execution comparison receipt. Every
read re-verifies the receipt against an exact-source recomputation (`webapp/backend/storage.py`,
`_execution_receipt_authority_locked`). Changing the computation would have made every stored receipt with
failure-impact rows read as mismatched.

## The decision (supervisor, under delegated owner authority)

Version the receipt contract.

- New receipts carry v2 impacts computed through the owner.
- Stored v1 receipts keep verifying against the legacy v1 recomputation, preserved verbatim as a named function.
- The version is explicit in the receipt. A missing or unknown version fails closed.
- The AssessHub UI renders v2 honestly and marks v1 rows as recorded before bounds were tracked.

## The contract

**Version field.** The version is the existing `operator_evidence.schema` inside the stored comparison. Every
receipt stored before W50 already carries `cutover_operator_evidence/1` there, so no stored receipt lacks an explicit
version. The new contract is `cutover_operator_evidence/2`. The constants live in `protocol_assurance`:

- `CUTOVER_OPERATOR_EVIDENCE_SCHEMA_V1` and `CUTOVER_OPERATOR_EVIDENCE_SCHEMA_V2`;
- `CUTOVER_OPERATOR_EVIDENCE_SCHEMA`, the current contract (V2), which every new comparison carries;
- `CUTOVER_OPERATOR_EVIDENCE_SCHEMAS`, every contract the engine can recompute.

The outer `execution_comparison_receipt/1`, `source_bound_cutover_comparison/1` and `protocol_receipt_envelope/1`
schemas are unchanged. The admission's owner roster never named this contract and is unchanged too, so a v1
recomputation's admission is identical to what v1 stored.

**v2 rows.** `_rehearsal_impacts_v2` emits one row per stored `failure_impact` object, in stored order, read through
`impact_assessability.rows_with_verdicts`. Each row is `{host, assessable, why, severity, vlans_impacted, stranded,
hard, backup, fhrp, detail}`:

- `assessable` and `why` carry the owner's verdict.
- Each measure is `table_value`. That is the stored value on a published row. On a lower-bound row the worst band
  and each positive count are written as the lower bounds they are (`High (lower bound)`, `≥ 45`). A withheld value
  is written `not assessed`.
- `detail` is `table_detail`, which leads with the verdict on a row that is not a measurement.

This is the same shape the MCP tool hands the assistant since W48. The v2 `rehearsal` block also gains
`impacts_owner` (`failure_impact_assessability/1`) and `n_impacts_by_assessable`, a verdict census over every row,
including rows a capped view does not render. Every other key of the payload is shared by /1 and /2: status, note,
L2 projection, observed trial, rollback and blocker export.

**Legacy function.** `_rehearsal_impacts_v1_legacy(raw_impacts)` holds the v1 comprehension verbatim. Its caller
passes it the same `snap.get("failure_impact")` value v1 read. `cutover_operator_evidence(..., schema=V1)` selects it
and adds none of /2's keys, so a /1 recomputation is byte-identical to what /1 stored. Two tests pin this
independently of the function:

- In `tests/test_impact_consumers.py` the v1 rows must equal the stored object rows, and the v1 rehearsal must carry
  exactly the pre-W50 key set.
- In `webapp/tests/test_compare_execution_receipts.py` a stored v1 receipt must equal the legacy shape built by hand
  from the current comparison.

**Gate.** `html.compute_cutover_gate` now accepts any schema in `CUTOVER_OPERATOR_EVIDENCE_SCHEMAS`, where it used to
require /1 by equality. The gate reads only the L2 rehearsal and observed-trial wrappers, which both contracts share,
so a v1 recomputation reproduces the stored v1 gate exactly.

**Fail-closed rule.**

- `protocol_assurance.stored_operator_evidence_schema(comparison)` returns the declared contract only when it is a
  string in `CUTOVER_OPERATOR_EVIDENCE_SCHEMAS`. A missing `operator_evidence`, a missing or non-string `schema`, or
  an unknown contract returns `None`; `None` never means "current".
- The storage read replay calls it through `engine.stored_operator_evidence_contract`. On `None` it raises
  `ExecutionReceiptAuthorityError` (`operator-evidence contract is missing or unsupported`) before any recomputation.
  Otherwise it recomputes with `compare_bound_pair(..., operator_evidence_schema=<declared>)` and keeps the existing
  byte-identity check.
- `cutover_operator_evidence(schema=...)` raises `ValueError` on any value outside the set. An unknown contract is
  never computed as a known one.
- **Writes take only the current contract.** The append path recomputes with no contract (the current one), so an
  incoming /1 or unknown-contract receipt cannot match it and is refused as `comparison_mismatch`. Only the
  stored-history replay recomputes a declared legacy contract. An execution may therefore hold /1 receipts written
  before W50 followed by /2 receipts written after it.

## AssessHub UI

`webapp/frontend/src/components/` has no shared `ImpactValue` (or any other shared failure-impact renderer) on this
base. `pages/core/ProjectionEvidence.tsx` renders projection facts and needs the projection context, so it is not
reusable here. `ComparisonDecision.tsx` therefore renders conservatively, with a local `RehearsalImpacts`:

- **/2.** Each row shows the owner's verdict chip (`PUBLISHED`, `LOWER BOUND`, `NOT ASSESSED`, `AMBIGUOUS`), then
  every measure exactly as the owner wrote it (`≥ 45`, `High (lower bound)`, `not assessed`), then the owner's detail.
  A row with a missing or unknown verdict shows `VERDICT UNAVAILABLE`, and every value reads `unavailable`. A
  missing or non-numeric cell reads `unavailable`, never 0. The verdict census is printed above the rows.
- **/1.** A visible note says "Recorded before bounds were tracked: … none of these values is an exact
  measurement." Each row carries a `NOT BOUND-CHECKED` chip and an "as recorded" label. A /1 receipt with no rows
  shows no note.
- **Any other contract.** No row values are rendered. A notice points to the complete JSON export.

`api.ts` widens `CutoverOperatorEvidence.schema` to `/1 | /2` and documents the v2 row and the two v2-only keys. The
fallback notes no longer name `/1`.

**Follow-up.** When a shared impact renderer lands in the SPA, `RehearsalImpacts` should adopt it.
`webapp/frontend/dist` is untouched (owner rule). The `Rebuild the bundled AssessHub SPA` step rebuilds and
byte-compares the committed bundle, so it will report the tracked dist as modified until the later UI train imports a
hosted dist.

## Guard (`tests/test_impact_consumers.py`)

The `protocol_assurance` ratchet entry is removed and its strict `xfail` is now a passing expectation. Measured
statically with the guard's own scanner on this tree:

- 16 reader units;
- exactly one raw unit, `design_advisor._signals`, which is the remaining ratchet entry;
- `cutover_operator_evidence` is a reader and is routed to the owner;
- `_rehearsal_impacts_v1_legacy` is not a reader by the guard's definition, because it receives the rows;
- the textual cross-check finds no missed module.

The guard works per function, so it admits `cutover_operator_evidence` because it reaches the owner, even though one
of its branches selects the raw /1 copy. That branch is pinned behaviourally instead. It is reachable only by naming
/1 explicitly; the default is /2; an unknown contract raises.

## Tests (written, not run)

`tests/test_impact_consumers.py` (sample-based; every expectation read from the owner):

- `test_cutover_operator_evidence_carries_the_owner_values_for_core1[bounded|held]`: the former strict `xfail`,
  unchanged, now expected to pass.
- `test_v2_receipt_impacts_carry_core1_as_the_lower_bound_it_is` checks core1 on the committed sample:
  - `assessable` is `lower_bound`;
  - `stranded` is `≥ 45` and `severity` is `High (lower bound)`;
  - `backup` is `not assessed`;
  - the detail is the owner's, the row's key set is exact, and the census matches the owner.
- `test_v2_receipt_impacts_carry_a_held_core1_as_not_assessed`: with the off-scan marker removed, every measure
  reads `not assessed`.
- `test_the_legacy_v1_recomputation_is_the_verbatim_raw_row_copy_and_only_on_request[bounded|held]` checks four
  things:
  - the v1 rows equal the stored object rows;
  - the v1 rehearsal has exactly the pre-W50 key set;
  - every shared key equals v2's;
  - five unknown contracts raise.
- `test_a_stored_comparison_names_its_contract_or_reads_as_unverified`: /1 and /2 are returned, and ten malformed or
  unknown declarations read `None`.

`webapp/tests/test_compare_execution_receipts.py` (golden snapshot through the public routes and `Store`):

- **A v2 receipt verifies.** `test_v2_execution_receipt_carries_owner_valued_impacts_and_reverifies` checks that the
  stored receipt is /2 with owner rows, equals `/api/compare` for the same pair, and reads back 200.
- **A v1 receipt verifies.** `test_v1_execution_receipt_stored_before_w50_still_verifies` writes through the route
  with the writer pinned to /1. That simulates the pre-W50 writer exactly, because the legacy function is that
  writer's code. The test then restores /2 and checks that:
  - the stored /1 receipt equals the legacy shape built by hand from the current comparison;
  - it does NOT equal the current /2 recomputation (non-vacuity);
  - two execution read routes return 200.
- **A tampered v2 receipt fails at append.** `test_store_refuses_a_tampered_or_relabelled_v2_receipt_at_append`
  refuses three receipts, each with every digest rebuilt, as `comparison_mismatch`:
  - owner values rewritten to raw values and presented as published;
  - a complete, self-consistent /1 receipt;
  - an unknown-contract receipt.

  The untampered receipt is then accepted (control).
- **The rewrite helper is not the failure.** `test_pre_anchor_rewrite_control_reseals_a_valid_receipt_of_either_contract[/1|/2]`:
  the pre-anchor rewrite helper with no semantic change reseals cleanly. The refusals below are therefore the
  mutation's, not the helper's.
- **An unknown version fails closed on read.**
  `test_stored_receipt_with_an_unknown_or_missing_contract_fails_closed[unknown|missing|not_a_string]`: a stored
  receipt with every digest rebuilt is refused when the next store open seals it, with the new message.
- **A tampered v2 receipt fails on read.** `test_stored_v2_receipt_with_tampered_impacts_fails_closed`: a stored /2
  receipt whose first row is rewritten as a published measurement is refused by the replay
  (`does not match exact-source recomputation`).

Adjusted, not weakened:

- `tests/test_protocol_assurance_contracts.py` now expects /2 for a new comparison and checks that its marker-less
  row reads as not assessed.
- `webapp/tests/test_backend.py` now expects /2 from `/api/compare`.

`webapp/frontend/src/components/ComparisonDecision.impacts.test.tsx` (vitest, next to the existing
`ComparisonDecision.observed.test.tsx`) checks that:

- a /2 lower bound shows `LOWER BOUND` and `≥ 45`, never `45`;
- a /2 held row shows `NOT ASSESSED` and no digit;
- a /2 row with a missing verdict or value shows `unavailable`, never 0;
- a /1 receipt shows the "recorded before bounds were tracked" note and `NOT BOUND-CHECKED` rows;
- a /1 receipt with no rows shows no note;
- an unknown contract renders no values.

## Persisted-snapshot impact

None:

- No snapshot section carries `operator_evidence`. A tracked-file search finds it only in the pinned Release 1
  retrospective comparison, which is replayed by pinned Release 1 source and not by current code.
- The golden and the sample are not regenerated or touched.
- No new `cisco_toolkit` module was added, so the golden attestation module count and the LF byte-custody receipt
  are unchanged.
- CLI `--compare` writes its `.comparison.json` at /2 from now on. It is output only and never re-verified.

## Not verified here

- No test ran: every new and adjusted Python test, and the new vitest file.
- The SPA typecheck and build did not run.
- That the owner is total on the golden and sample snapshots inside the comparison (assumed from its documented
  totality).
- That `/api/compare`'s JSON round trip is byte-identical to the stored comparison (the existing tamper tests rely on
  the same property).
- That the pre-anchor reseal path behaves for a deliberately rewritten (rather than torn) receipt exactly as the
  existing migration tests show for valid and torn receipts.
- Whether an AssessHub database with real stored /1 receipts exists anywhere. The read path is exercised only by
  the simulated pre-W50 writer.
- The hosted SPA dist is not rebuilt.
