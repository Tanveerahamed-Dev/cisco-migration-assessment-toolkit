# W50 execution-receipt failure-impact rows: bind the evidence, interpret it live (validation record)

Branch `claude/w50-receipt-impacts`, cut from the local branch `claude/w48-impact-consumers` at `e7c00e12`. The
stack is main ← #629 (W45, which adds the owner `cisco_toolkit/impact_assessability.py`) ← W48 ← W50. It is
committed locally and not pushed. This is round 3, a design pivot decided by the supervisor after the independent
re-verification of round 2 (`e04bb4a1`).

No local test, build, engine, pipeline, npm or vitest run happened (owner GitHub-only rule). The local checks were
static: `py_compile`, AST scans, and pure library functions called on the committed golden and sample JSON (see
"Static checks"). The hosted gates decide.

## The problem

`protocol_assurance.cutover_operator_evidence` copies every stored `failure_impact` row raw into
`rehearsal.impacts`. AssessHub's `ComparisonDecision` rendered those rows' `severity` and `detail` raw, so a lower
bound read as an exact count and a held zero as a measured zero. On the committed sample, core1 (one inter-switch link
with no trunk/STP evidence) was shown as an exact 45.

W48 stopped at this site because the payload is persisted inside every AssessHub execution comparison receipt, and
every read re-verifies a stored receipt by RECOMPUTING it from the bound snapshots
(`webapp/backend/storage.py`, `_execution_receipt_authority_locked`).

## Why rounds 1 and 2 were wrong, and the robust model

Rounds 1 and 2 put the owner's reading INTO the receipt (`cutover_operator_evidence/2`: verdict tokens, reason codes,
withheld markers). Round 2 removed the owner's prose so a rewording could not move a stored receipt, and pinned the
owner's decisions on a sampled corpus. The re-verification proved that is not enough:

- `_rehearsal_impacts_v2` called the live owner. Any change to what the owner decides changes `/2` bytes for some
  fleet, and every stored `/2` receipt for that fleet then reads as mismatched (409), so its execution history becomes
  unreadable. Renaming a frozen copy does not help while it still calls the live owner.
- The semantic pin covers only the sampled corpus. Removing `"endpoint"` from `IMPACT_EDGE_KINDS` passes every pin
  yet changes `/2` bytes on a real fleet.

The general rule for a recompute-on-read record: **anything it binds must be a pure function of the bound bytes and of
frozen code.** Evidence satisfies that; an interpretation by an evolving owner never can. So the record binds the
evidence, and the interpretation is computed live, at display time, and never stored:

- the receipt stays verifiable forever without migrations or version bumps when the owner improves;
- every receipt, old or new, shows the CURRENT best reading of its own evidence;
- the owner stays the single place where "measurement, lower bound or not assessed" is decided.

## 1. The receipt binds evidence only (`cisco_toolkit/protocol_assurance.py`)

- The contract stays `cutover_operator_evidence/1`. `/2`, its row builder `_rehearsal_impacts_v2`, its
  `IMPACT_CELL_WITHHELD` marker, its pins and its owner-semantics battery are removed. No `/2` receipt ever existed
  outside this unpushed branch.
- `rehearsal.impacts` is computed by one frozen binder, `_rehearsal_impact_evidence_v1(snap)`: every object row of
  `snap["failure_impact"]`, copied raw, in stored order. It is the pre-W50 comprehension byte for byte (it now reads
  the section itself rather than receiving it from a lambda, so the structural guard can name it). The module imports
  and names nothing of `impact_assessability`.
- Hardening kept from round 2:
  - an explicit, read-only dispatch `_REHEARSAL_IMPACTS_BY_CONTRACT` whose only entry is `/1`;
  - `cutover_operator_evidence(..., schema=...)` raises `ValueError` on any contract outside it (unknown, empty,
    non-string, prototype names);
  - `stored_operator_evidence_schema(comparison)` returns the declared contract only when it is a string in
    `CUTOVER_OPERATOR_EVIDENCE_SCHEMAS`; the storage read replay raises `ExecutionReceiptAuthorityError`
    ("operator-evidence contract is missing or unsupported") on `None` and otherwise recomputes the declared contract
    (`compare_bound_pair(..., operator_evidence_schema=...)`);
  - the append path recomputes with the current contract only, so an incoming receipt declaring anything else is
    refused as `comparison_mismatch`.
- `html.compute_cutover_gate` is back to its pre-W50 text (equality with `/1`); with one contract the set membership
  added in round 1 was redundant.
- Every receipt stored before W50 still verifies, with no migration and no new version: `/1` reproduces the frozen
  digests below, and the whole comparison is independent of the owner.

## 2. The interpretation is display-only and computed live (`webapp/backend/engine.py`, `app.py`)

`engine.rehearsal_impacts_view(snapshot, source_sha256=...)` (schema `rehearsal_impacts_view/1`) is the owner's
reading of a comparison's bound after snapshot, built only from `impact_assessability`:
`assess_failure_impact` (every stored row, unreadable ones included), `withholds` / `withheld_state`, `table_value`
(the floor text `≥ 45`, `High (lower bound)`), `ranks` / `ranking_floor`, `code_counts`, `section_state`,
`count_value`. Per row: `index`, `host` (null when the owner withholds it), `assessable`, the owner's `state`
(`not_collected`, `unverified`, `analysis_unavailable`), `reasons` `[{code, n}]`, `ranked`, and one cell per measure
plus `detail` as `{kind: published|floor|withheld|unreadable, text, state}`. Rows come in the owner's ranking order:
ranked rows by floor or measured count, largest first, then ranked rows with no readable count, then every row the
owner does not rank; stored order breaks ties. The census (`n_rows_total`, `n_rows_unreadable`, `counts`) covers
every stored row. `section_state` says whether the section itself could be read, so an absent or failed section never
reads as "no impact".

Where it is served, always BESIDE a comparison and never inside it:

- **Execution receipt rows** (`GET /api/executions/{id}` and every route that returns the execution view):
  `app._receipts_with_impacts_views` shallow-copies each stored row and adds `impacts_view`, computed by
  `engine.receipt_impacts_view(comparison, store.get_bound_snapshot)`. That loads the comparison's bound after snapshot
  by id and interprets it only when the stored bytes still carry the SHA-256 the comparison binds
  (`comparison_admission.source_binding.after`).
- **Campaign trend pairs** (`GET /api/campaigns/{id}/trend`): each `adjacent_comparisons` entry carries
  `impacts_view` next to `comparison`, from the same in-memory after snapshot and binding.

**Unavailable is explicit.** `engine.IMPACTS_VIEW_UNAVAILABLE` is the closed set of reasons: `binding_unreadable`,
`snapshot_missing`, `snapshot_unreadable`, `snapshot_mismatch`, `owner_fault`. An unavailable view carries no rows and
the UI never falls back to the raw rows.

**The boundary.** `impacts_view` is never stored, never hashed and never an input to verification:

- storage (writes and the replay), the comparison composer, the receipt contract, the execution state and the PIR
  export never name it (`tests/test_operator_evidence_contract.py`, an AST scan that admits only the engine view
  builders, the trend pair and the app's execution-view decorator);
- the PIR export reads `rec["comparisons"]` directly, not the decorated view;
- a comparison WITH the view inside it fails the detached envelope (`storage._comparison_envelope_valid` treats every
  non-additive key as delta), which is why it travels beside the comparison.

**`/api/compare` is unchanged.** It deliberately does not carry the view: two existing pins require its JSON to equal
the stored execution-receipt comparison and the trend pair's comparison exactly
(`test_compare_and_execution_receipt_are_exactly_parity_bound_to_stored_bytes`,
`test_campaign_trend_receipts`), and the envelope argument above applies. A dedicated display route would change the
OpenAPI document and therefore the generated `src/generated/openapi.ts`, which cannot be regenerated without npm under
the owner rule. The ad-hoc Compare panel therefore states that the interpretation is not supplied on that surface
(residual 1).

## 3. AssessHub UI (`webapp/frontend/src/components/ComparisonDecision.tsx`)

`ComparisonDecision` takes a new optional `impactsView` prop; the execution page, the cutover planner and the trend
pairs pass the sibling from the API. The raw `rehearsal.impacts` rows are no longer read at all (only their count, for
the evidence line).

- The view is shown only when its `source_sha256` equals the comparison's bound after-snapshot SHA-256; otherwise, or
  when no view or an unavailable view was supplied, the panel says "Failure-impact interpretation unavailable: …" with
  the reason, renders no row value and discloses `Rendered: 0`.
- One line replaces the old "/1 recorded before bounds were tracked" note: the interpretation is computed live by the
  engine owner from the bound evidence and is not part of the comparison or of any receipt.
- Each row: the verdict chip, the owner's state word (`not collected`, `unverified`, `analysis unavailable`), the
  reasons in the owner's words, `not ranked` where it applies, and every measure: a floor as the owner's text
  (`≥ 45`, `High (lower bound)`), a withheld value as `not assessed (<state>)`, a measurement as its value, and an
  unreadable value as `unavailable (the stored value cannot be read)`, never 0.
- The census says `every one of the N stored rows` only when no row is unreadable; otherwise `all N stored rows
  (U unreadable)`, and the unreadable rows are listed by position however far down the ranking they fall.
- An absent or failed section is shown as such and "not a finding of no impact"; an empty list reads "stores no
  failure-impact rows".
- Reason and verdict words come from two closed tables equal to the owner's `CODE_PHRASES` and `VERDICT_LABELS`
  (`webapp/tests/test_impacts_view_constants.py` parses the TS tables and requires exact, ordered equality, the W47
  constants-guard pattern). State words come with the view itself (`state_words`, the owner's `STATE_WORD`
  verbatim): a TS literal naming `not_collected` and `analysis_unavailable` is flagged by the protocol hand-list guard
  (`tests/test_protocol_assessability.py`) as a copy of the protocol receipt's vocabulary, and this way the SPA holds
  no copy at all. An unknown code renders `unrecognised reason code (…)`, an unknown verdict `UNRECOGNISED VERDICT
  (…)` with every value withheld, a state without a word `unrecognised state (…)`. Lookups are own-property only
  (`constructor`, `toString` never match).
- `webapp/frontend/dist` is untouched (owner rule); the hosted dist import belongs to the UI train.

## 4. W48 guard interplay (`tests/test_impact_consumers.py`)

- The `protocol_assurance` ratchet entry is back, keyed to the binder alone:
  `("cisco_toolkit.protocol_assurance", "_rehearsal_impact_evidence_v1")`, reason "binds raw evidence for
  recompute-on-read receipts; presentation goes through the owner at display time (W50)".
- `test_only_the_frozen_binder_reads_the_rows_raw_and_the_display_path_reaches_the_owner` requires the binder to be
  the module's only reader of the section, the ratchet to name only it, and the engine view builders and trend pair to
  be routed to the owner.
- `test_the_guard_still_flags_a_second_raw_presenter_beside_the_binder` is the non-vacuity case on a synthetic tree.
- The former strict xfail is now `test_receipt_impact_rows_are_bound_raw_and_presented_only_through_the_owner`
  (bounded and held core1): the receipt binds core1's row raw, and the view presents it through the owner (`≥ 45`
  floor leading the ranking; held: `not_assessed`, `legacy_row`, `not_collected`, unranked).
- A presenter of the binder's OUTPUT is not a section read, so `test_impacts_view_constants.py` also scans every
  non-test SPA source (comments stripped) for `.impacts` / `["impacts"]` reads; the pre-W50 component is the
  non-vacuity case.
- W48-owned edits are limited to these; W48's fix round (`a78d85ed`) merges into W50 later.

## Frozen `/1` digests

Canonical encoding `protocol_assurance.canonical_json_bytes` (sorted keys, ASCII, compact), SHA-256, over
`cutover_operator_evidence(snap, prior_snapshot=snap)` and over `compare_bound_pair(snap, snap, ...)` with the fixed
persisted-source bindings of `_binding` (snapshot ids 1 and 2, campaign 1, engagement `E`, the file's own SHA-256 and
length), `snap` being `bind_snapshot_json_bytes` of the committed file bytes. Measured at `e7c00e12`; constants, never
recomputed from current code.

| Snapshot | operator evidence | full comparison |
| --- | --- | --- |
| golden | `9da4d736cb8c1bfbe6ed4fe69c4ea01bacfd40ed2a353b50fa7368e8d3f75557` | `56b1c51c69a0fe79c0ad193d78479aecee228c3acc4d7a1c8eab28a506cd0ce2` |
| sample | `ab1f6d468e57cba53658dff2af81baa25498fcf674f805d3a783dcd83c7c7b32` | `0c81ec1949fe4af0344dd5953f6a7306832e1c4497a757a9ee92563870d53744` |

If one moves, never re-pin: a payload change needs a new contract with its own frozen binder added beside `/1`; a
comparison-only change breaks every stored receipt alike and needs its own receipt-versioning decision.

## Owner additions (`cisco_toolkit/impact_assessability.py`, additive)

`RowVerdict.state` and `RowVerdict.withheld_state(field)` expose the owner's existing withheld states (from the hold,
doubt, bounds or section it already computes), `section_state(snap)` reads the section as a whole, and
`count_value(raw)` exposes its count rule. `code_counts` stays (round 2) with a display-only docstring. No decision,
reason or wording changed, and the comment that tied `SCHEMA` to a receipt is removed.

## Tests (written, not run)

- `tests/test_operator_evidence_contract.py` (rewritten): the frozen `/1` digests, by default and declared;
  `test_no_owner_change_can_move_a_stored_receipt` (every owner entry point sabotaged, `IMPACT_EDGE_KINDS` without
  `endpoint`, every phrase reworded: the digests do not move); the raw binder; the one-entry dispatch; unknown
  contracts raise; stored declarations fail closed; the binder's single reference; protocol_assurance never reaching
  the owner; the display boundary AST scan; a comparison byte-identical with and without its view, and invalid with
  the view inside it.
- `webapp/tests/test_compare_execution_receipts.py` (round 2's `/2` tests replaced): the receipt binds the raw rows
  beside a live view equal to a fresh owner reading of the bound bytes; the stored receipt's persisted bytes,
  `receipt_sha256` column and envelope are identical whether the view is present, reinterpreted by a changed owner
  (every row held) or unavailable, and no read writes it back; every unavailable code; unreadable rows counted and
  shown, absent / malformed / failed sections; trend pairs carry the view beside a comparison equal to `/api/compare`.
- `webapp/tests/test_impacts_view_constants.py` (new): the two phrase tables equal their owners in order, the view's
  `state_words` equal `STATE_WORD` and the SPA holds no state table, the parser's non-vacuity, and the raw-row read
  scan of the SPA.
- `ComparisonDecision.impacts.test.tsx` (rewritten, vitest): fixtures copied from the engine's real view output on
  the committed sample (bounded and held core1, published access1, an unreadable row); floors, states, reasons, the
  census wording, unreadable rows, unknown code/verdict/state, an unreadable cell, no view, an unavailable view, a SHA
  mismatch, absent and empty sections, and the cap.
- `tests/test_protocol_assurance_contracts.py` and `webapp/tests/test_backend.py` are back to their pre-W50 `/1`
  expectations.

## Static checks (this round)

- `py_compile` on every changed Python file.
- Pure functions on the committed golden and sample: all four `/1` digests reproduce, both by default and with `/1`
  declared; with every owner entry point replaced by a raising stub and `IMPACT_EDGE_KINDS` reduced, both comparisons
  still reproduce their frozen digests; unknown contracts raise; `stored_operator_evidence_schema` returns `/1` or
  `None` as above.
- The view on the sample: 23 rows, 20 published and 3 lower bound; core1 first with `≥ 45`, `High (lower bound)`,
  backup and FHRP withheld (`not_collected`); held core1 `not_assessed` / `legacy_row`; an appended non-object row is
  row 24 with `row_unreadable`, `unverified`, unranked.
- The guard's own scan helpers (copied from the test module, no test function executed): the raw readers are exactly
  the two ratchet entries, `protocol_assurance`'s only reader is the binder, the view builders are routed, and the
  synthetic second presenter is flagged.
- The display-boundary AST scan, the TS table parser, the SPA raw-read scan and the protocol hand-list scanner,
  replicated in scratch scripts from the test modules' helpers (no test function executed), pass on this tree;
  the pre-W50 component is flagged by the raw-read scan.

## Residuals

1. **The ad-hoc Compare panel shows no interpretation.** `/api/compare` must stay byte-equal to the stored
   comparison, and a display route needs regenerated OpenAPI types. Follow-up for the UI train: a read-only
   `GET /api/snapshots/{id}/impacts-view` (or similar) with the types regenerated; the panel then passes it, and the
   SHA check in `ComparisonDecision` already guards it.
2. **The reading is live, not a record of what was shown.** A receipt displayed today and next month may read
   differently if the owner improved. That is the intent; the panel says so. Preserving "what the operator saw at
   decision time" would need its own signed, separately stored display record, outside this contract.
3. **Display cost.** An execution view loads each distinct bound after snapshot once more (the receipt replay already
   loads it); the trend runs the owner once per pair.
4. **Trend JSON export** now contains the display sibling next to each comparison. It is labelled `display_only` and
   never verified; the comparison inside the pair is unchanged.
5. **Merge with W48's fix round.** It touches `tests/test_impact_consumers.py` and possibly the owner; the additive
   owner methods and the ratchet entry need a merge check, but no receipt can move because the receipt never reads
   the owner.

## Not verified here

- No pytest, vitest, typecheck or build ran: the webapp receipt tests (FastAPI client and SQLite store), the vitest
  file, and the SPA `tsc` typecheck (the TypeScript was checked by hand against the ES2021 lib, strict mode,
  `noUnusedLocals`).
- That the OpenAPI document is unchanged: every changed route returns `Dict[str, Any]`, so no schema should move, but
  `api:check` was not run.
- Whether an AssessHub database with real stored receipts exists anywhere; the read path is exercised only through
  the tests' own writers.
- The hosted SPA dist is not rebuilt.
