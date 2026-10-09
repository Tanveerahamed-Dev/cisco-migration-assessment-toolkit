# W50 failure-impact rows in execution receipts read the engine owner (validation record)

Branch `claude/w50-receipt-impacts`, cut from the local branch `claude/w48-impact-consumers` at `e7c00e12`. The
stack is main ← #629 (W45, which adds the owner `cisco_toolkit/impact_assessability.py`) ← W48 ← W50. It is
committed locally and not pushed.

No local test, build, engine, pipeline, npm or vitest run happened (owner GitHub-only rule). The checks run locally
were static: in-memory compilation and `ruff check` of every changed Python file, W48's guard scanner and the
hand-list scanner from `tests/test_protocol_assessability.py` executed on their own, and pure engine functions called
on the committed golden and sample JSON (the digests below; see "Static checks"). The hosted gates decide.

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

- New receipts carry v2 impacts decided by the owner.
- Stored v1 receipts keep verifying against the legacy v1 recomputation, preserved verbatim as a named function.
- The version is explicit in the receipt. A missing or unknown version fails closed.
- The AssessHub UI renders v2 honestly and marks v1 rows as recorded before bounds were tracked.

**Fix round (supervisor decision on the independent review's P2).** The first `/2` embedded the owner's free-text
prose (`why`, `table_detail`, `CODE_PHRASES`) and its rendering rules (`≥ 45`, `High (lower bound)`, `not assessed`).
A stored receipt is re-verified by recomputation on every read, so any later owner rewording (W48's fix round is the
next one) would have turned every stored `/2` receipt into a 409 and made its execution history unreadable. `/2` now
binds only stable semantics; see "Bound versus display".

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

**Dispatch.** `_REHEARSAL_IMPACTS_BY_CONTRACT` is a read-only `{V1: …, V2: …}` table and the one place a contract
selects its computation. Each entry returns the rows and the keys that contract adds to `rehearsal` (none for /1).
`cutover_operator_evidence` raises `ValueError` for any contract outside the table, before computing anything. The
earlier open-ended "anything but /1 is /2" branch is gone.

**v2 rows (bound semantics only).** `_rehearsal_impacts_v2` emits one row per stored `failure_impact` object, read
through `impact_assessability.rows_with_verdicts`:

- `index`: the stored row's position; `host`: the stored host, which names the row as the MCP tool and workbook do;
- `assessable`: the owner's verdict token (`published`, `lower_bound`, `not_assessed`, `ambiguous`);
- `reason_codes`: `[{code, n}]` in the owner's order, from the new additive `RowVerdict.code_counts`. Each code is
  a stable key of `CODE_PHRASES` with the count its phrase quotes. The owner already had these codes (`Hold.code`,
  `Bound.code`, `RowVerdict.codes`); only the public accessor for the counts is new, and no prose changed;
- `severity`, `vlans_impacted`, `stranded`, `hard`, `backup`, `fhrp` and `detail`: the stored value exactly when the
  owner publishes it, else the explicit marker `IMPACT_CELL_WITHHELD` (`{"withheld": true}`). It is never `null`,
  because a published row may itself store a null. On a lower-bound row a published band or count is the floor it
  is: the verdict says so, and the cell carries the stored value.

Order (P3): the rows the owner ranks (`ranks`) come first, by their stranded floor (`ranking_floor`) or measured
count, largest first, with ties in stored order. Every row it does not rank follows in stored order. The capped view
therefore leads with the largest floors, not producer order. On the golden this moves the bounded core2 (no positive
floor) after access1.

The v2 `rehearsal` block also carries `impacts_owner`, the owner's declared version (`failure_impact_assessability/1`),
and `n_impacts_by_assessable`, a verdict census over every row, including rows a capped view does not render. Every
other key is shared by /1 and /2: status, note, L2 projection, observed trial, rollback and blocker export.

Measured on the committed sample: core1 is
`{index 0, lower_bound, [{blind_links, 1}], severity "High", stranded 45, backup/fhrp withheld, detail = the stored
per-VLAN list}`, and the census is 20 published and 3 lower bound. On the golden, core2 is a lower bound
(`uncollected_neighbours` ×1) whose Low band and zeros are withheld.

**Legacy function.** `_rehearsal_impacts_v1_legacy(raw_impacts)` holds the v1 comprehension verbatim. Its one call
site is the /1 dispatch entry, which passes it the same `snap.get("failure_impact")` value v1 read. /1 adds none of
/2's keys, so a /1 recomputation is byte-identical to what /1 stored, and its digests are frozen (see "Pins").

**Gate.** `html.compute_cutover_gate` accepts any schema in `CUTOVER_OPERATOR_EVIDENCE_SCHEMAS`, where it used to
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
- **Writes take only the current contract.** The append path recomputes with no contract (the current one), so an
  incoming /1 or unknown-contract receipt cannot match it and is refused as `comparison_mismatch`. Only the
  stored-history replay recomputes a declared legacy contract. An execution may therefore hold /1 receipts written
  before W50 followed by /2 receipts written after it.

## Bound versus display

Two designs were open: a `bound` sub-object beside a display part that verification ignores, or prose removed from
the receipt entirely and resolved at render time. The first was rejected. The receipt envelope, the outer
`receipt_sha256`, the INTEGER authority limbs and the decision-input authority all hash the whole comparison, so an
ignored display part would mean excluding it from four digests and from the identity check. A display stored that
way would also be frozen at write time, so it would show stale prose anyway.

**Chosen: no prose in the receipt.** The bound record is the whole `/2` row above, and nothing else is stored. The
boundary is in code: `_rehearsal_impacts_v2` reads only verdict tokens, codes, counts, withholding decisions and
stored values from the owner. It never calls `why`, `summary`, `table_value`, `table_detail`, `ranked_value` or
`disclose`. `tests/test_operator_evidence_contract.py` rewords every owner string (all `CODE_PHRASES`,
`VERDICT_LABELS`, `STATE_WORD`, every `R_*` reason, `NOT_ASSESSED_CELL`, `LOWER_BOUND_MARK`). It then requires the
`/2` evidence, both pinned digests and the owner-semantics digest to stay unchanged, and no reworded byte to appear.

**Render time (`ComparisonDecision.tsx`).** The view resolves the words itself, from the bound tokens only:

- the verdict token becomes a chip;
- a withheld cell reads `not assessed`;
- on a lower-bound row the band reads `High (lower bound)` and a count reads `≥ N`;
- a published row prints its value;
- each reason code reads as itself with its count (`blind links ×1`, `uncollected neighbours ×1`, `legacy row`);
- the stored detail is shown as `Producer detail: …` when published.

The view holds no copy of the owner's phrase table, so there is one truth (the codes) and nothing to drift. The
trade-off is deliberate: the comparison view shows the stable code, not the owner's full sentence. The engine
deliverables that render failure-impact rows (for example the workbook's Failure Impact sheet and the MCP tool, through
`table_detail`) still print the owner's live phrase for the same code. Computing the owner's prose server-side at serve time was also considered and rejected. Comparisons reach the
UI through `/api/compare`, every execution view, campaign trend entries and four page call sites, so a server-side
display sidecar would add four untested exits for a presentation gain.

## Pins (`tests/test_operator_evidence_contract.py`)

Canonical encoding: `protocol_assurance.canonical_json_bytes` (sorted keys, ASCII, compact), SHA-256. The
operator-evidence digest is over `cutover_operator_evidence(snap, prior_snapshot=snap, schema=…)`. The comparison
digest is over `compare_bound_pair(snap, snap, ...)`, with the fixed persisted-source bindings in `_binding`
(snapshot ids 1 and 2, campaign 1, engagement `E`, the file's own SHA-256 and length). Here `snap` is
`bind_snapshot_json_bytes` of the committed file bytes.

| Contract | Snapshot | operator evidence | full comparison |
| --- | --- | --- | --- |
| /1 (frozen, measured at `e7c00e12` by the independent reviewer) | golden | `9da4d736cb8c1bfbe6ed4fe69c4ea01bacfd40ed2a353b50fa7368e8d3f75557` | `56b1c51c69a0fe79c0ad193d78479aecee228c3acc4d7a1c8eab28a506cd0ce2` |
| /1 (frozen) | sample | `ab1f6d468e57cba53658dff2af81baa25498fcf674f805d3a783dcd83c7c7b32` | `0c81ec1949fe4af0344dd5953f6a7306832e1c4497a757a9ee92563870d53744` |
| /2 (pinned) | golden | `e9aedbb835090df570132111f698e388343d48739fe4375b07dc501d5c97c713` | `30ed44b2ac4fbda336e9739e3ccecef7900022a96749e2bb85b53b85b9e56e83` |
| /2 (pinned) | sample | `cb916b4ead4448cb53c59bb64e91c1a21a834642954ac62b9abf0c512b818aea` | `a1d9a5040ac4789f5a71b9e673f66103c367ba3936bdb3c2a488aea417694d1f` |

The /1 values are constants, never recomputed from current code (P3: the earlier /1 check built its expectation from
the current comparison, so it could drift together with the code). This tree reproduces all four /1 values
statically. The module docstring states the rule:

- a `/2` digest change means `/2` changed: add `/3` as the current contract, freeze today's computation as
  `_rehearsal_impacts_v2_legacy` selected by the /2 dispatch entry, and pin `/3`;
- a comparison-only change, with the operator-evidence digest holding, is outside this contract and breaks every
  stored receipt alike: it needs its own receipt-versioning decision, not a re-pin;
- until W50 reaches `main` no `/2` receipt can exist anywhere, so the supervisor may re-pin `/2` once, deliberately,
  in the merge that changes it (for example W48's fix round), and must say so in the handoff log.

**Owner semantic version.** `impact_assessability.SCHEMA` (`failure_impact_assessability/1`) already existed as the
owner's document schema. It is now declared, in a comment on the owner, as the version of what the owner decides, and
`/2` binds it in `impacts_owner`. `test_the_owner_bound_semantics_change_only_with_a_schema_bump` pins, per declared
version, digests of the owner's decisions: per row the verdict, codes with counts, withheld cells, `ranks` and
`ranking_floor`. The digests cover three corpora:

| Corpus | digest |
| --- | --- |
| golden | `7f06243ce235412e0ae0dcb1d3577f196496fd1eda5139f5c12a5ad4dfd8f9de` |
| sample | `329e7bfbc4f7c54c97e90a355d0ac9cb1e91113436e9752e38b1819ea6ea228b` |
| battery | `a98056a2099f4a6465feb0a1c6b0d2548d55bad9f725b2553c95e3c46d24e83d` |

The battery is 15 golden variants, one per reason code the golden does not carry. Together with the golden (whose
core2 carries `uncollected_neighbours`) they exercise all 16 owner codes; a separate test requires that. A semantic
change under an unchanged `SCHEMA` fails. Bumping `SCHEMA` moves every `/2` digest because `impacts_owner` is bound,
so it also forces `/3`. Non-vacuity: dropping every hold (`row_hold` returns `None`) moves the battery digest, and
rewording every phrase does not.

## Residual: a database writer can downgrade a `/2` receipt to `/1`

Recorded, not fixed here (supervisor instruction). Someone who can write the AssessHub SQLite file can replace a
stored `/2` receipt with a self-consistent `/1` receipt for the same pair. That receipt has the raw rows and the `/1`
schema. The writer recomputes the detached envelope, the outer `receipt_sha256` and the four INTEGER authority limbs,
which are unkeyed SHA-256 over public content (`storage._comparison_authority_limbs`). The read replay then recomputes
the declared `/1`, which matches, so the receipt verifies.

What the downgrade can and cannot change:

- It cannot change the cutover gate: both contracts share every input the gate reads.
- It replaces owner-decided rows with raw rows. The UI marks those `NOT BOUND-CHECKED` and "recorded before bounds were
  tracked", so it never presents them as exact.

Closing it needs keyed authority (an HMAC or a signature whose key the database writer does not hold), or a trusted
per-execution contract floor. Both are out of scope for W50; any database write is outside the current trust model
anyway.

## AssessHub UI

`webapp/frontend/src/components/` has no shared failure-impact renderer on this base, so `ComparisonDecision.tsx`
keeps a local `RehearsalImpacts`:

- **/2.** Each row shows:
  - the owner's verdict chip (`PUBLISHED`, `LOWER BOUND`, `NOT ASSESSED`, `AMBIGUOUS`);
  - for a row that is not a measurement, its reason codes;
  - every measure resolved at render time, as described above;
  - the producer detail, or a note that the owner withholds it.

  A row with a missing, unknown or prototype-named verdict (`constructor`, `toString`) shows `VERDICT UNAVAILABLE`,
  and every value reads `unavailable`. The lookup uses an own-property check (P3). `Object.hasOwn` itself is ES2022,
  and the SPA's TypeScript `lib` is ES2021, so it would not typecheck; the code therefore uses
  `Object.prototype.hasOwnProperty.call`, which is the same check. A missing or mistyped cell reads `unavailable`,
  never 0. The verdict census and a ranking note precede the rows.
- **/1.** A visible note says "Recorded before bounds were tracked: … none of these values is an exact
  measurement." Each row carries a `NOT BOUND-CHECKED` chip and an "as recorded" label. A /1 receipt with no rows
  shows no note.
- **Any other contract.** No row values are rendered, and the cap disclosure now reports `Rendered: 0` (P3: it used to
  count the withheld rows as rendered). A notice points to the complete JSON export.

`api.ts` documents the v2 row (`index, host, assessable, reason_codes`, cells or `{withheld: true}`), its ranking and
the two v2-only keys.

**Follow-up.** When a shared impact renderer lands in the SPA, `RehearsalImpacts` should adopt it.
`webapp/frontend/dist` is untouched (owner rule). The `Rebuild the bundled AssessHub SPA` step rebuilds and
byte-compares the committed bundle, so it will report the tracked dist as modified until the later UI train imports a
hosted dist.

## Guard (`tests/test_impact_consumers.py`)

The `protocol_assurance` ratchet entry stays removed. Measured statically with the guard's own scanner on this tree:

- the only raw unit is `design_advisor._signals`, the remaining ratchet entry;
- in `protocol_assurance` the section is now read only inside the dispatch table, which the guard admits;
- the dispatch table reaches the owner through its /2 entry;
- `_rehearsal_impacts_v1_legacy` is not a reader, because it receives the rows;
- the textual cross-check finds no missed module.

The guard works per unit, so it admits the table even though its /1 entry copies raw rows. That entry is pinned
behaviourally instead:

- the frozen /1 digests;
- the AST test that `_rehearsal_impacts_v1_legacy` has exactly one reference and one call in production code
  (`cisco_toolkit/`, `webapp/backend/`, `portable/` and the pipeline), and that it sits in the /1 dispatch entry (P3).

`test_cutover_operator_evidence_carries_the_owner_values_for_core1[bounded|held]` (W48's former strict xfail) now
checks the bound semantics. It checks the verdict and the codes, and that each of severity, stranded and backup is
the stored value or the withheld marker exactly as the owner decides. W50's other tests moved out of this W48-owned
file into `tests/test_operator_evidence_contract.py`, which shrinks the merge surface with W48's fix round.

## Tests (written, not run)

`tests/test_operator_evidence_contract.py` (new):

- **Frozen and pinned digests.** Two tests carry the pin tables above:
  - `test_v1_recomputes_the_frozen_pre_w50_bytes[golden|sample]`;
  - `test_v2_recomputes_its_pinned_bytes[golden|sample]`.

  `test_the_current_contract_is_v2_and_its_default_is_the_pinned_one` checks that the default contract is /2 and
  produces the pinned bytes.
- **Rewording.** `test_rewording_the_owner_never_moves_a_stored_v2_receipt[golden|sample]`.
- **Owner version.** Four tests:
  - `test_the_battery_exercises_every_reason_code_the_owner_declares`;
  - `test_the_owner_bound_semantics_change_only_with_a_schema_bump`;
  - `test_the_semantic_pin_moves_when_the_owner_decides_differently`;
  - `test_v2_binds_the_owner_version_and_census`.
- **Row content on the sample.** Three tests:
  - `test_v2_binds_core1_as_a_lower_bound_by_code_and_stored_values`;
  - `test_v2_binds_a_held_core1_as_not_assessed_with_every_cell_withheld`;
  - `test_v2_ranks_rows_by_the_owner_floor_then_discloses_the_rest`.

  Each also checks that no owner phrase, verdict word or rendering mark appears in the bound rows.
- **Moved here from `test_impact_consumers.py`.** These were extended:
  - `test_the_legacy_v1_recomputation_is_the_verbatim_raw_row_copy_and_only_on_request[held]` now also refuses the
    prototype-ish contracts `__class__` and `get`;
  - `test_a_stored_comparison_names_its_contract_or_reads_as_unverified`.
- **Dispatch.** `test_the_dispatch_is_exactly_the_recomputable_contracts` checks that the table keys equal
  `CUTOVER_OPERATOR_EVIDENCE_SCHEMAS`, and that the table is read-only.
- **Single call site.** `test_the_frozen_v1_function_has_exactly_one_call_site_the_v1_dispatch_entry`.

`webapp/tests/test_compare_execution_receipts.py` (golden snapshot through the public routes and `Store`), adjusted
to the bound row:

- the /2 receipt test checks the exact `/2` key set, that every `index` names its stored host, and that the codes
  are well-formed;
- the tamper tests rewrite `reason_codes` instead of `why`, and find each stored row by `index`, because the rows are
  ranked;
- the /1 test keeps its hand-built structural check, with a comment that the byte anchor is the frozen engine-level
  digests.

The unknown/missing-contract and tampered-/2 fail-closed tests and the rewrite control are unchanged.

`tests/test_protocol_assurance_contracts.py` now expects the held row's `reason_codes` (`legacy_row`) and withheld
markers. `webapp/tests/test_backend.py` expects /2 from `/api/compare` (unchanged by this round).

`webapp/frontend/src/components/ComparisonDecision.impacts.test.tsx` (vitest) now uses fixtures copied verbatim
from the engine's real `/2` output (P3: the earlier fixtures were invented strings):

- sample core1 bounded and held;
- sample access1 published;
- golden core2 lower bound;
- the raw sample core1 row for `/1`;
- the sample census.

It checks that:

- a lower bound shows `LOWER BOUND`, `blind links ×1`, `≥ 45`, `High (lower bound)` and never `45` or `: 0`;
- a band below the worst reads `not assessed`;
- a held row shows `NOT ASSESSED`, `legacy row` and no digit;
- a missing or prototype-key verdict (`constructor`, `toString`) shows `VERDICT UNAVAILABLE`;
- `/1` keeps its note and reports `Rendered: 1`;
- an unknown contract renders nothing and reports `Rendered: 0 · Total: 1 · Omitted: 1`.

## Persisted-snapshot impact

None:

- No snapshot section carries `operator_evidence`. A tracked-file search finds it only in the pinned Release 1
  retrospective comparison, which is replayed by pinned Release 1 source and not by current code.
- The golden and the sample are not regenerated or touched.
- No new `cisco_toolkit` module was added, so the golden attestation module count and the LF byte-custody receipt
  are unchanged. The owner gains one additive property (`RowVerdict.code_counts`) and a comment on `SCHEMA`; no prose
  or decision changed.
- CLI `--compare` writes its `.comparison.json` at /2 from now on. It is output only and never re-verified.

## Static checks (this round)

- Every changed Python file compiles and passes `ruff check`.
- The guard scanner and the hand-list scanner are clean on the changed sources.
- The pure engine functions were called on the committed golden and sample JSON, outside any test runner:
  - every /1 digest reproduces the frozen `e7c00e12` values;
  - the /2 and owner-semantics digests above were measured;
  - rewording every owner string leaves them unchanged;
  - dropping every hold moves the battery digest;
  - every reason code is exercised.
- The new test module's functions were called directly as plain functions with the stored JSON (no pytest runner):
  19 of 19 cases held.

## Not verified here

- No pytest, vitest, typecheck or build ran. In particular:
  - the `webapp/tests` receipt tests (they need the FastAPI client and a SQLite store);
  - the new vitest file;
  - the SPA typecheck. The TypeScript was reviewed by hand against the ES2021 lib.
- That `/api/compare`'s JSON round trip is byte-identical to the stored comparison (the existing tamper tests rely on
  the same property).
- Whether an AssessHub database with real stored /1 receipts exists anywhere. The read path is exercised only by
  the simulated pre-W50 writer.
- How W48's fix round interacts with the pins: if it changes what the owner decides, the owner-semantics and `/2` pins
  move at the merge, and the rule above applies.
- The hosted SPA dist is not rebuilt.
