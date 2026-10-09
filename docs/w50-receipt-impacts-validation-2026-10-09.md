# W50 execution-receipt failure-impact rows: bind the evidence, interpret it live (validation record)

Branch `claude/w50-receipt-impacts`, cut from the local branch `claude/w48-impact-consumers` at `e7c00e12`. The
stack is main ← #629 (W45, which adds the owner `cisco_toolkit/impact_assessability.py`) ← W48 ← W50. It is
committed locally and not pushed. Round 3 was a design pivot decided by the supervisor after the independent
re-verification of round 2 (`e04bb4a1`); round 4 answers the three-lens review of round 3 (`096b2fd5`) and is
recorded in its own section below ("Round 4").

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
`cutover_operator_evidence(after, prior_snapshot=before)` and over `compare_bound_pair(before, after, ...)` with fixed
persisted-source bindings (snapshot ids 1 and 2, campaign 1, engagement `E`, the file's own SHA-256 and length),
each snapshot being `bind_snapshot_json_bytes` of the committed file bytes. Constants, never recomputed from current
code. Round 4 split them in two kinds (the review's P2-A: round 3 pinned only the LIVE corpus, which is regenerated,
so a routine regeneration would have moved a "never re-pin" digest with the binder untouched).

**Frozen corpus** (`tests/fixtures/operator_evidence_v1/`, LF-only, pinned LF by `.gitattributes`, each file's own
SHA-256 asserted before use). Bindings carry `script_version`, as AssessHub's stored binding does, so every pair is
admitted and the whole composer runs. Measured with the pure functions at the round-4 head, with the deployed
`main` code `f797444e` and with the pre-W50 code `e7c00e12` (each a `git archive` of `cisco_toolkit/` imported by
path, `__file__` asserted): identical.

| Fixture | SHA-256 |
| --- | --- |
| `before.json` | `0ec258031986450de951ccd9b5b7db5954036ca5a0886b7f124704e0bb7273a2` |
| `after-rows.json` | `08d520724aad77a78cb570837f5a168b586340572d560956dc24651ddb4d4d90` |
| `after-missing.json` | `d2853c90ec19519f2674d440e2ffa9cb387c8e4cd815e44b0dcc0eec50ab9876` |
| `after-non-list.json` | `f8e9c8eeccac3b7164edfdd9bcf47401632a37b4e154f82b7d5467782b347932` |

| Pair (before → after) | operator evidence | full comparison |
| --- | --- | --- |
| rows (`before` → `after-rows`) | `8914d60065a45a2ea78f160363c828d4c540d90b9c4a9a151e0bbaa5d746a600` | `8f998baaf7f79fa29f431c9f4d8d7319cc3bb363dc640ef7532e9dc4bbda4823` |
| missing (`before` → `after-missing`) | `5c7939b2b6aab6dc97724ffed99a122b05bd4cf55d0d63fa69302a6bff1190e7` | `4b05de8cb3a2f1e16f305b5bddfa57ab54e5712f18ab5dbb5398341d6c85a403` |
| non_list (`before` → `after-non-list`) | `5c7939b2b6aab6dc97724ffed99a122b05bd4cf55d0d63fa69302a6bff1190e7` | `bb2de4a7a65a2d0918d65253a9eb13bd41c3e9e20342547a3aed83999dcbe17d` |
| rows_self (`after-rows` → `after-rows`) | `8914d60065a45a2ea78f160363c828d4c540d90b9c4a9a151e0bbaa5d746a600` | `34ecb7e30cd4d77f425b34acc0858b636403021ca32602d5b435eae70fcb6cf1` |

`missing` and `non_list` share their operator-evidence digest by design: both bind no row and nothing else in the
evidence differs. `after-rows` holds 11 rows: six objects (a lower bound with a blind link, a legacy row, a row with
odd-typed values and extra keys including an integer past 2**53, an empty key and non-ASCII text, a second row for one
host, an empty object, a row with an empty host and a float count) and five non-objects (a string, an integer, null,
a list, a boolean). The binder binds exactly the six objects, raw.

**Live corpus** (the committed golden and sample, measured at `e7c00e12`), each an explicit pair:

| Snapshot | corpus SHA-256 | operator evidence | full comparison |
| --- | --- | --- | --- |
| golden | `c4f6a549299bd6494b9b0377a7a5be773d2322b3ace3b785701d2a57e7cc4643` | `9da4d736cb8c1bfbe6ed4fe69c4ea01bacfd40ed2a353b50fa7368e8d3f75557` | `56b1c51c69a0fe79c0ad193d78479aecee228c3acc4d7a1c8eab28a506cd0ce2` |
| sample | `dbc229cfdcd676bb07e99bdace7e26ea429de087715ebf1727064b4e373a26c1` | `ab1f6d468e57cba53658dff2af81baa25498fcf674f805d3a783dcd83c7c7b32` | `0c81ec1949fe4af0344dd5953f6a7306832e1c4497a757a9ee92563870d53744` |

The `f797444e` and `e7c00e12` code reproduce both live pairs on these corpus bytes too.

The rule (`tests/test_operator_evidence_contract.py` docstring): a frozen-corpus digest never moves, so if one does,
never re-pin: a payload change needs a new contract with its own frozen binder added beside `/1`, and a
comparison-only change breaks every stored receipt alike and needs its own receipt-versioning decision. A live pair
moves only AS A PAIR: a regeneration re-measures the corpus SHA-256 and its digests together, in its own commit, and
only while every frozen-corpus pin still holds; a moved digest with an unchanged corpus SHA-256 is a code change and
fails like a frozen one. Corpus bytes are read as committed: the golden has no `.gitattributes` EOL rule, so a
`core.autocrlf=true` checkout (Git for Windows' usual default; whether the hosted Windows image sets it was not
checked here) carries CRLF, which round 3's raw read would have hashed into the comparison's binding and so into the
pinned comparison digest; the reader undoes exactly CRLF → LF (lossless for JSON) and refuses any other CR.

## Round 4 (answers the three-lens review of `096b2fd5`)

- **P2-A, frozen digests measured corpus + code.** Fixed: the frozen corpus and the live pairs above
  (`tests/test_operator_evidence_contract.py`: `_FROZEN_FIXTURES`, `_V1_FROZEN_CORPUS`, `_V1_LIVE`,
  `_committed_bytes`; `.gitattributes` pins the fixtures LF). The sabotage test runs on both kinds. The new fixtures
  are outside every Atlas R1/R2 LF policy domain, so the byte-custody receipts in
  `tests/fixtures/atlas-r2-byte-custody-policy.v1.json` do not move (recomputed with the module's pure helpers on the
  committed tree, see "Static checks").
- **P2-B, unranked rows fell off the capped list.** Fixed: the view publishes `unranked` (every row the owner does not
  rank, in stored order, from the new owner accessor `unranked`), and `RehearsalImpacts` names each of them in its own
  block, whatever the cap (`comparison-rehearsal-impact-unranked`). Tests: the vitest case with ten ranked rows and
  three held ones; the Python case on the sample with three held rows past the cap.
- **P3-1, CapDisclosure wording.** Fixed: `CapDisclosure` takes an `exportNote`; the failure-impact block says the
  complete JSON export holds only the bound evidence (each stored row that is an object, raw and uninterpreted), never
  this interpretation nor a non-object row. Every other section keeps the original sentence.
- **P3-2, unreadable list vs census.** Fixed: one owner rule, `RowVerdict.readable` (the stored row is an object).
  The view publishes `unreadable` (stored positions) beside `n_rows_unreadable`, both from it; the SPA lists
  `view.unreadable`, never a reason code. Under a failed section a non-object row is worded `section_unavailable`, and
  the census and the list still agree (pinned in Python and vitest).
- **P3-3, second classifier.** Fixed: `_impacts_view_cell` and `_impacts_view_order` are gone from the engine. The
  owner publishes `cell_reading(verdict, field)` (`CellReading(kind, text, state)` with `CELL_KINDS` /
  `CELL_FIELDS`), `ranking_order(verdict)` and `unranked(verdicts)`; the engine only lays them out. On the golden, the
  sample and seven adversarial snapshots every pre-existing view field is byte-identical to round 3's output; the
  one reading change, by construction and checked on a published sample row, is that a detail holding a lone
  surrogate is now unreadable (the owner's `_is_text` slot rule) instead of a string the API could not encode.
- **P3-4, schema handling.** Fixed: `RehearsalImpacts` renders a view whose `schema` is not `IMPACTS_VIEW_SCHEMA` as
  unrecognised with no value, and a cell kind outside `IMPACT_CELL_KINDS` as `unrecognised value kind (…)`. Both SPA
  constants are held equal to `engine.REHEARSAL_IMPACTS_VIEW_SCHEMA` and `impact_assessability.CELL_KINDS`.
- **P3-5, no Python guard on presenting the bound rows.** Fixed: `webapp/tests/test_impacts_view_constants.py` now
  also scans every engine, AssessHub, Atlas and pipeline Python source for a read of the `impacts` key (subscript,
  call argument, attribute, `match` mapping key); the only admitted units are the frozen binder and the two storage
  verifiers, and the allowlist must name live units. Today no production code reads the key at all.
- **P3-6, the owner check covered `protocol_assurance.py` only.** Fixed: a static call-graph closure from
  `comparison.compare_bound_pair`, `engine.compare_bound_pair` and the two storage verifiers (resolved calls and
  references, `module.function`, `self.method`, dispatch tables, and every method of each project class a unit
  names) reaches no unit that is, imports or names the owner. It spans 891 units in 29 modules, including
  `html.compute_snapshot_delta`, `html.compute_cutover_gate`, `precert.compute_precert`, the protocol and L2 owners and
  52 analyze helpers; the display builder `engine.rehearsal_impacts_view` is outside it. A synthetic tree pins that a
  deep helper, a class method, an unaliased dotted import and a dispatch table are each seen. The graph is the W48
  guard's resolver, refactored into `_graph` with the W48 scan's result unchanged (readers and routed units identical
  on this tree).
- **P3-7, lock scope.** Fixed: `_mutate_execution` runs the read-modify-write under `MUTATION_LOCK`
  (`_mutate_execution_locked`) and builds the response view from the saved record after the lock is released;
  nothing stored or returned changes. Pinned by a test that observes the lock from inside `receipt_impacts_view`.

## Owner additions (`cisco_toolkit/impact_assessability.py`, additive)

`RowVerdict.state` and `RowVerdict.withheld_state(field)` expose the owner's existing withheld states (from the hold,
doubt, bounds or section it already computes), `section_state(snap)` reads the section as a whole, and
`count_value(raw)` exposes its count rule. `code_counts` stays (round 2) with a display-only docstring. No decision,
reason or wording changed, and the comment that tied `SCHEMA` to a receipt is removed. Round 4 adds the display
readings `cell_reading` / `CellReading` / `CELL_KINDS` / `CELL_FIELDS`, `ranking_order`, `unranked` and
`RowVerdict.readable` (which `rows_with_verdicts` now reads, with identical output); none of them is reachable from a
receipt recomputation.

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
- Round 4 additions (written, not run): in `tests/test_operator_evidence_contract.py` the frozen-corpus integrity
  test, the frozen-corpus digests by default and declared, the sabotage test on every frozen pair, the live pairs,
  the frozen binder over every row shape, the receipt-recompute closure check and its synthetic non-vacuity tree; in
  `tests/test_impact_consumers.py` the owner's display accessors against its own rules (sample, held row, frozen odd
  rows) and the display cells equal to `cell_reading`; in `webapp/tests/test_compare_execution_receipts.py` the
  unranked disclosure past the cap with every cell equal to the owner's reading, `unreadable` under a failed section,
  and the lock-scope probe; in `webapp/tests/test_impacts_view_constants.py` the schema and cell-kind constants and
  the Python presenter scan with its non-vacuity case; in `ComparisonDecision.impacts.test.tsx` the unranked block
  past the cap, the unreadable list from the view's own list under a failed section, an unknown schema, an unknown
  cell kind, and the export wording.

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

Round 4 (same rule: py_compile, AST scans, pure functions and the test modules' helpers; no test function run):

- The frozen-corpus and live digests above, at this head, at `f797444e` and at `e7c00e12` (module `__file__`
  asserted under each archive root): identical.
- The view before and after the owner-accessor refactor on the golden, the sample and seven adversarial snapshots:
  every round-3 field identical; the new `unreadable` and `unranked` fields as specified (a failed section with a
  non-object row: `unreadable` `[3]`, every row unranked).
- The refactored `_scan` against the round-3 copy on this tree: readers and routed units identical (17 readers, 218
  routed; the raw readers are still exactly the two ratchet entries). The receipt-recompute closure: 891 units, 0
  owner hits. The synthetic closure tree reports exactly the four expected owner-reaching units.
- The Python presenter scan: no read of the `impacts` key anywhere in production Python; the admitted units exist;
  the non-vacuity source yields its six reads. The SPA scan still finds no raw read. The TS schema and cell-kind
  constants equal their owners; the phrase tables still equal theirs.
- The new owner-accessor assertions, mirrored with library calls on the sample, the held sample and the frozen odd
  rows: no failure. The unranked-past-the-cap premise on the sample (19 ranked rows, three held rows outside the
  first eight): holds.
- The byte-custody receipts recomputed with the pure helpers of `tests/test_transition_schema_assets.py` on the
  committed head: unchanged.

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
- Round 4: none of the new or changed tests ran (pytest, vitest); the TSX was checked by hand (strict, ES2021 lib,
  `noUnusedLocals`), not by `tsc`. The closure check is static: a call through a local variable, a callback
  parameter or an attribute of an object the graph cannot type is not followed (the sabotage tests are the runtime
  half). That the hosted Windows checkout of the golden is CRLF was not checked; the reader is correct either way.
