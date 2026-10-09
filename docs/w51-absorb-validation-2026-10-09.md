# W51 absorb: W48, W50 and W47 on the contract train, plus the pending review findings (validation record)

Branch `claude/w51-absorb`, cut from the W51 contract-train head `6ad57ed9` (pushed as `origin/claude/train-contract`).
It is committed locally and not pushed. Three local branches are merged with `--no-ff`, then one commit applies the
independently reviewed findings (a) to (e) below.

No local test, build, npm, vitest, tsc, engine or pipeline run happened (owner GitHub-only rule). The local checks were
static: `py_compile`, `ruff`, AST scans, and pure library functions called on the committed sample and golden and on
synthetic JSON. Wherever a check needed a test module's helper, its source was copied as text and executed on its
own. No test module was imported and no test function ran. The hosted gates decide.

## Merges

| Row | Branch tip | Merge commit | Conflicts |
| --- | --- | --- | --- |
| W48 | `claude/w48-impact-consumers` `a78d85ed` | `5ecad5be` | `webapp/backend/{engine,summary,cutover}.py`, `webapp/tests/test_impact_surfaces.py`, `docs/ssot.md`, `docs/NOW.md` |
| W50 | `claude/w50-receipt-impacts` `add4b377` | `44ce0b75` | `cisco_toolkit/impact_assessability.py` (`__all__`), `webapp/backend/engine.py`, `tests/test_impact_consumers.py`, `docs/ssot.md`, `docs/NOW.md` |
| W47 | `claude/f8-bound-styling` `db93b265` | `6fa6cc35` | `docs/NOW.md` only |

**W48 against W51.** W51 had split the projection's fleet qualifier into two kinds: blind devices, and records the
projection cannot read as one (`summary.impact_blind_counts`, `_R_IMPACT_BLIND_UNREAD`). W48 had moved a one-kind count
into the owner (`impact_assessability.fleet_blind`). The resolution keeps the owner as the one place for the rule and
gives it W51's semantics:

- `fleet_blind(listing, blind_rows)` returns `(blind, unread)`. `blind_rows` is the projection's classifier
  (`ui_projection.fleet_blind_spot_rows`); the owner still never imports the projection.
- `FLEET_BLIND_WITNESS` is W51's `/collection_completeness` prefix.
- Both phrases are the owner's (`R_WAVE_FLEET_BLIND`; `R_WAVE_FLEET_BLIND_UNREAD`, W51's wording verbatim).
- `WaveBlast` gains `blind_unread`. `wave_blast` is exact only when both counts are readable zeros, and `wave_why`
  words both in the order AssessHub's blind-spot note uses.
- `summary.impact_blind_counts` supplies the classifier and reads the owner. `mop._fleet_blind` returns the owner's
  pair, and `cutover._worst_blast_radius` passes both counts.
- The tests follow: the fleet tests bump the inventory count (W51 reconciles it with the roster, so an uncounted
  outside device would add an unread record), and a `fleet_unread` agreement variant was added.

**W50 against W48's fix round.** W50 (stacked on `e7c00e12`) had refactored the first guard's resolver into `_graph`.
The fix round `a78d85ed` replaced that guard (`_Scan`: unit granularity, call-only routes, a line check). The merge
keeps the fix round's guard as THE guard. W50's resolver is kept as the separate, conservative receipt-recompute
closure resolver its contract test reads (`_Graph` / `_graph` / `_closure` / `_path`), over its own top-level unit
split (`_graph_units`, copied from `e7c00e12`). W50's tests unpack the guard's four-tuple.

The stricter guard does not resolve a local alias of a module, so `engine.rehearsal_impacts_view` (`ia =
_impact_assessability`) read as unrouted. It now calls the owner through the module alias: the same calls and the
same output.

## The pending findings

**(a) A bound always cites a witness that resolves.** This was the W48 re-verification's P2, raised three times. With
no `cable_map` at all, the owner bounds every row: whether a switch faces an uncollected neighbour cannot be checked.
The MOP printed `≥ N`. But the projection's bound cited `/cable_map`, `_Ctx.refs` dropped the unresolvable pointer, and
AssessHub's `summary._impact_bounds` and the cutover plan read the row as exact. Measured on the published sample
with the cable map removed: the core1 wave was `complete: true, 45` on the plan and `≥ 45` in the MOP.

- `ui_projection._impact_witnessed` (called by `_topology_impact`) cites an absent witness record by the nearest record
  that exists, the longest prefix of its address that resolves. Without a cable map that is the snapshot root `""`;
  without the cable list it is `/cable_map`. Present records and failure records are cited as given. The
  `impact_scanned_scope` limitation states the rule; the schema is unchanged.
- `summary` words the root witness (`_R_BOUND_ROOT`) and moves `KEYSTONE_CONTRACT_VERSION` to 7, so a cached
  summary is recomputed.
- The SPA already words `""` as "the snapshot as a whole" (W47).
- Why the nearest record and not the row's own pointer: the summary reads a row-self witness as the blind-links legacy
  bound (`_R_BOUND_BLIND_LEGACY`), so citing the row would mis-word the cable-map bound.
- Tests: a `no_cable_map` variant of `test_the_mop_and_the_cutover_plan_agree_on_every_wave`, and
  `test_a_bound_whose_witness_is_absent_cites_the_nearest_record_that_exists` (absent map, map without a list, a list
  of the wrong type).
- Non-vacuity: with `_impact_witnessed` replaced by the identity, the agreement probe reproduces the mismatch.
- **This supersedes open PR #626 (W35, `claude/impact-cable-witness` `64667568`).** It applies the same
  nearest-record rule, now on the owner's `Bound` after W33, and adds the summary wording and the contract bump.
  #626 can close unmerged.

**(b) "Cannot disagree" corrected.** The owner docstring, `docs/ssot.md` and the guard test's docstring now say what is
true. The MOP applies the wave rule to the owner's verdicts, and the cutover plan applies it to the projection's rows
(built from those verdicts, every bound now witnessed). Their agreement is pinned per variant, not guaranteed by
construction.

**(c) W48 P3s.**

- `wave_blast(..., blind, blind_unread)` has no defaults: a missing fleet is a `TypeError`, and `None` is unknown,
  never exact.
- `WaveBlast.observed` includes rows that name no readable host, so the MOP never prints `[NOT OBSERVED]` for a wave
  the cutover plan names such a row for.
- The cutover plan honours `zero_bound` (and ranked rows with no readable count): NOT ASSESSED with no counts, led by
  the owner's `R_WAVE_ZERO`, never "0 endpoint(s) stranded". Its `complete` is `wave.complete` with a value, which
  equals the MOP's PUBLISHED.
  - On the committed sample this changes one live AssessHub output: the dist wave (dist1 withheld, dist2, podacc1 and
    podacc2 publishing 0) read "0 endpoint(s) stranded — LOWER BOUND" and now reads NOT ASSESSED, as the MOP
    already did. The plan is computed on request and is not persisted in the sample or the golden.
  - `test_the_sample_plan_keeps_its_worst_cases_and_a_duplicate_is_never_picked` now expects that wave as NOT
    ASSESSED and requires at least one such wave. `test_the_cutover_plan_reads_a_zero_lower_bound_as_not_assessed`
    pins the rule, with an exact zero kept as its control.
- The guard's twelve key-folding holes are pinned in `_KNOWN_LIMITS`: tuple-unpack, re-assignment, a local literal
  table, `KEY.strip()`, `KEY[:]`, `KEY or ''`, a conditional expression, `globals()['KEY']`, `f'{KEY!s}'`, a star
  import, `importlib` and `b''.decode()`. The known-limit test now writes the `keys.py` helper the star-import and
  importlib cases need.
- The docstring now states exactly what is folded. It also says that the line check does NOT close these holes: each
  one places the literal in a closed position, or nowhere at all.
- A copy of the scanner flags none of the 12 cases, and the line check stays clean on each. All 26 evasions stay
  flagged.

**(d) G21 facets rendered.** `CoreSnapshot.tsx` said facet totals are not published, but W41/G21 publishes
`findings.facets`. The Findings view now renders the severity and category totals (`FactView`, each with its own
state and reason) and the paged per-inventory-device list (`ProjectionList` over `/facets/device`), and the
disclosure is reworded. A vitest case pins it: withheld totals show their reason and never a 0, and the device count is
shown. This also answers the W51 row's "paired SPA slice" item.

**(e) Carried records.**

- The W45 record on #629's head (`40ca4d96`, `docs/w45-engine-sample-train-2026-10-09.md` and the W45 board row)
  calls webapp-ci run `37897012004` succeeded. All six of its jobs passed, but the run's conclusion is `cancelled`, by
  concurrency.
- The dist handoff evidence that holds is artifact `11600639221`
  (`frontend-dist-handoff-40ca4d96…-37897790220-1`), from run `37897790220`, which concluded `success` on `40ca4d96`.
  `40ca4d96` differs from `31d9b5b9` only in two docs, so its frontend inputs are the same.
- Those `40ca4d96` lines are not on this train yet: #629's head merges here later. The correction is therefore recorded
  in the W45 record's tail and in the board handoff line, for the supervisor to apply when merging.
- W28, W29, W30 and W46 are carried by W45 (#629: `bc37c587` merges #628 `30e425bb`). W34 (#627) merged as `f797444e`.
  Codex's W34 row text is kept and a handoff line records the merge.

## Static checks

- **Guard copy** (`_scan` source extracted as text): 23 readers on this tree. Exactly the two ratchet units are raw:
  `design_advisor._signals` and the frozen binder. The line check is clean.
- **W50's guard and closure assertions:** `protocol_assurance`'s only reader is the binder, and the three engine
  display units are routed. The synthetic second presenter is flagged. The receipt-recompute closure spans 891 units
  in 29 modules with 0 owner hits (W50's figure), and the synthetic closure tree gives the four expected units.
- **W50's frozen and live `/1` digests:** every frozen-corpus pair (default and declared) and the live golden and
  sample pairs reproduce on this tree.
- **W47's SPA constants** equal their Python owners. No SPA source reads the raw receipt rows.
- **MOP/cutover agreement**, mirrored with library calls on the published, hostless, fleet_caveat, fleet_unread and
  no_cable_map variants: 0 mismatches. The zero-bound wave is NOT ASSESSED on both.
- **Root witness:** the expectations of the absent-map, list-less and wrong-type cases hold.
- AST collection sanity of every changed test file (argnames, fixtures, duplicates, imports), `py_compile`, `ruff`.

## Pins, OpenAPI, LF receipts, golden and sample

- **Native pins unchanged.** `_native_schema_hash` on this tree reproduces view `55bc576f…` and list `ce6e9c45…`;
  no schema changed, so no re-pin.
- **OpenAPI unchanged.** The app's OpenAPI document is byte-identical to the W51 head's (40 paths), so
  `src/generated/openapi.ts` is untouched.
- **LF receipts unchanged.** Recomputed with the test module's pure helper logic on the index: LF scope 183 (digest
  equal), publisher scope equal, the effective LF set equal, and the marked `.gitattributes` rules equal.
  `.gitattributes`'s new W50 fixture rule lies outside every policy domain.
- **Golden, sample, `atlas-scope/` and `webapp/frontend/dist` untouched.** No persisted engine output changes. The
  witness fix changes projection output only for a snapshot with no cable map, and the committed sample and golden
  carry one. The `impact_scanned_scope` limitation text (instance data) changes. AssessHub's live cutover plan
  changes for the sample's dist wave, per (c).

## Frontend source changed (needs the integrator's hosted dist import)

- W50: `api.ts`, `components/ComparisonDecision.tsx` (+ `.impacts.test.tsx`), `components/CutoverPlanner.tsx`,
  `pages/Campaign.tsx`, `pages/Execution.tsx`.
- W47: `api.ts`, `components/ImpactValue.tsx` (+ test), `components/CutoverPlanner.tsx` (+ test),
  `pages/CoreSnapshot.tsx` (+ test), `pages/Snapshot.tsx` (+ test), `pages/core/ProjectionEvidence.tsx`,
  `pages/core/ProjectionList.tsx` (+ test), `pages/core/TopologyPaths.tsx` (+ test), `pages/coreSnapshot.css`,
  `styles.css`.
- This commit: `pages/CoreSnapshot.tsx` and its test.

## Not verified

- No pytest, vitest, `tsc`, build or browser run. Every new and merged test is unexecuted, including the MOP and
  runbook docx tests, the receipt API tests and every vitest file.
- The TSX in W47, W50 and (d) was checked by reading only. It is untyped against W51's regenerated `openapi.ts`
  except by inspection.
- The hosted dist import for the combined frontend source.
- The W45 CI fix `f6323759` (two W28 tests on the combined tree) is on #629's head, not on this train. The
  parallel CI agent on `claude/train-contract` owns that class.
- Atlas Scope's raw reader (`compile-model.mjs`) is still a Codex handoff (W48).
- Whether the cutover plan and the MOP agree on inputs the agreement variants do not cover. Finding (b) states this
  limit.
