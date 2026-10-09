# W45 engine/sample integration train (W36 + W33 + W32)

Branch `claude/train-engine-sample`, cut from `origin/main` `a06d1d27` (#622, W31). It carries three open
Claude pull requests, merged with merge commits in this order, so the goldens and the demo sample are regenerated
**once** on the hosted runners for the combined engine:

| Order | PR | Row | Branch head | Merge commit |
|---|---|---|---|---|
| 1 | #625 | W36 | `claude/sample-collected-at-utc` `44908e59` | `9c6e75a7` |
| 2 | #624 | W33 | `claude/impact-assessability-owner` `c036b844` | `ee49e8cb` |
| 3 | #623 | W32 | `claude/impact-blind-links` `0f4455fe` | `f7b890d5` |
| 4 | main after #620 | (W27, merged) | `origin/main` `7d547890` | the main merge on top of `0883db45` |

No local test, build, engine, pipeline or sample/golden writer ran (owner GitHub-only rule). The local checks
were static: compilation, an AST shadow scan, the static helpers of `tests/test_protocol_assessability.py`, the
native schema pins, the byte-custody LF receipts, `ruff check` on the changed files, and `json.load` of tracked
snapshots. The hosted gates decide.

## Conflicts and how each was resolved

1. **`docs/NOW.md`** (merges 2 and 3). Every row and every handoff line from both sides is kept. The W31 row
   stays deleted: W33's side retired it under rule 8 (#622 merged as `a06d1d27`), and that retirement line is
   kept. W45 has its own row and handoff line.
2. **`cisco_toolkit/ui_projection.py`** (merge 3, authorial). W33 moved every failure-impact row-level rule into
   the engine owner `cisco_toolkit/impact_assessability.py`, and the projection's `_topology_impact` now reads
   `ctx.impact.row(i, raw)`. W32 added its blind-link hold and bound to the projection's private rule functions
   (`_impact_hold`, `_impact_blind`, the `_impact_bound` detail tail), which W33 had deleted. Keeping W32's code
   would have been a second, parallel hold path that no deliverable reads. So:
   - the projection keeps W33's code exactly, plus W32's `LIMITATIONS` text and two comment lines;
   - W32's rule is expressed **in the owner**, so the projection, the Failure Impact and Executive Summary
     sheets, RES-4, the design document, the deck, the dossier and the explorer embed all read it from one place.
   No webapp module consumes the owner directly: AssessHub reads the projection. For W27's surfaces, see the main
   merge below.
3. **`docs/ssot.md`** (merged textually, then corrected). W32's registry row cited `ui_projection.py ::
   _impact_hold / _impact_blind / _impact_peers`, which no longer exist, and `tests/test_ssot_registry.py`
   requires every cited symbol to resolve. The row now cites the owner (`row_hold / off_scan_bound /
   blind_bound`) and `_topology_impact`. W33's row names the blind-link rule.
4. **`tests/fixtures/atlas-r2-byte-custody-policy.v1.json`**: no change needed. The combined tree's LF-scope
   receipts, recomputed at `f7b890d5` with the test module's own helpers (`_head_paths_matching`,
   `_transition_byte_owner_paths`, `_path_set_receipt`), equal W33's fixture:
   - `lf_scope` 182 `68493206…`;
   - `derived_byte_owner_scope` 38 `ad1a4aa6…`;
   - `broader_declared_lf_scope` 144 `a5cb2b74…`;
   - `publisher_byte_scope` 1 `5738a353…`.

   W32 and W36 add no file under an LF rule, and `docs/*.md` is outside it.

`COLLECT_PARSE_V3_23_0.py`, `cisco_toolkit/analyze.py`, `tests/test_pipeline_golden.py`,
`tests/test_sample_fleet.py` and `tests/golden/snapshot.json` merged cleanly:

- W36 changed `_derive_collected_at`, W33 changed `main()` phase order, and W32 changed `compute_failure_impact`.
- The merged golden equals W33's golden plus W32's three `blind_links: 0`, leaf for leaf.

## Main after #620 (W27): the AssessHub failure-impact surfaces

Main moved to `7d547890` (#620, W27) after the first push. At the coordinator's request it is merged into the train
with a merge commit, and the regeneration is dispatched again on the final head. The first hosted run,
`37879944000` on `0883db45`, succeeded but was **not imported**.

- **`docs/NOW.md`:**
  - every active row is kept: W33, W32, W36, W45 and main's W27;
  - main's retirement of W26 (#618 merged) stands, and so does W31's (#622);
  - #620 has merged as `7d547890`, so W27's row is ready for rule-8 retirement by the supervisor.
- **Agreement with the owner.** W27's surfaces never read the stored rows. `summary.impact_view` reads
  `engine.failure_impact_projection` (the projection's shared row builder, which reads W33's owner), and the keystones,
  `cutover._worst_blast_radius`, the Failure impact tab and the /graph badge all read `impact_view`. Its one
  lower-bound rule is structural: a published measure that cites a witness is "at least" its value. W32's bound
  puts exactly such a witness on the published measures. So W27 already flags a blind-link bound and withholds what
  it withholds, with no second rule. What changed:
  - **Wording, `summary._impact_bounds`.** A blind-link witness was worded generically ("the engine cites … as a
    bound on this row"). It is now worded by the owner's two witnesses, as the off-scan witness already was: the
    row's `blind_links` count (`_R_BOUND_BLIND`), or the row itself (`_R_BOUND_BLIND_LEGACY`). Only `blind_bound`
    cites the row itself on a published measure: holds are not cited, and a doubted row publishes no measure.
  - **`summary.KEYSTONE_CONTRACT_VERSION` 4 → 5.** A dashboard summary cached before the blind-link bound existed
    is recomputed on read (`app._summary_freshened`), so a stale keystone list cannot outlive the change.
  - **`webapp/tests/test_impact_surfaces.py`**, two changes, neither weaker:
    - **Removed projection names.** The file read names W33 removed from the projection (`ui._R_IMPACT_PEERS`,
      `ui._R_IMPACT_PEERS_CLOSED`, `ui._impact_bound`, `ui._IMPACT_EDGE_KINDS`). It now reads the owner's
      (`ia.R_PEERS`, `ia.R_PEERS_CLOSED`, `ia.make_bound`, `ia.IMPACT_EDGE_KINDS`), and it pins that `blind_bound`
      cites exactly the two witnesses summary words.
    - **Sample bounds are derived.** Its sample tests hard-coded "core2 is the sample's only bound", which W32's
      per-row count ends: the regenerated sample also bounds core1 and dist1. Every expectation is now derived from
      each stored row's own evidence (`_sample_bounds`: core2's router, a positive or absent `blind_links`). Each
      test still pins core2 explicitly, and a bounded band below High or a bounded zero is required to be unranked
      and disclosed.
- **Not changed.** The AssessHub dossier recompute (`webapp/backend/app.py`) still does not pass
  `failure_impact_assessability`. W27 kept it on the stored rows on purpose and pinned that, and W33's ratchet in
  `tests/test_dossier_input_state.py` records the missing argument. Passing the owner's document there is the
  one-line follow-up W33 named.

## The one structural rule (W32 inside the W33 owner)

`cisco_toolkit/impact_assessability.py`:

- **`row_hold`** has two more holds, in W32's first-match positions:
  - A `blind_links` that is present but not a count holds the row (`unverified`, code
    `blind_links_unreadable`). It is checked after the off-scan count and before the host.
  - A positive count with no VLAN simulated holds the row (`not collected`, code `blind_links_only`). It is
    checked after off-scan-only.
- **`blind_bound`** is new. It returns no bound for a zero count. A positive count bounds the row (code
  `blind_links`) and cites the count. A row with no `blind_links` predates the count and is bounded citing the
  row itself (code `blind_links_legacy`). `ImpactSnapshot.row` keeps W32's bound order: off-scan, blind links,
  uncollected neighbours. As before, both of the first two are stated beside a hold, so every measure cites them.
- **`make_bound`** gains W32's detail `tail`. The neighbour detail renders the same text as before.
- **Reason texts.** Every W32 reason text (`_R_IMPACT_BLIND*`, `_R_IMPACT_PEER_DETAIL/TAIL`) equals the
  owner's constant byte for byte, as do the earlier W23 texts (a static AST comparison of 21 constants).
  The projection's cells therefore carry W32's states, reasons and witnesses.
- **Phrases.** `CODE_PHRASES` gains a reader-facing phrase for each new code, with no engine internal named.

## Tests: what changed and why each is at least as strict

- **Hand-built current-producer rows carry `blind_links: 0`, as a producer row does:**
  `tests/impact_fixtures.py :: assessable`, the `_rich_snap` rows and the clean-bill row in `tests/test_deck.py`,
  the `core9` row in `tests/test_design.py`, and `_many_rows` in `tests/test_impact_assessability.py`. Without
  the field the owner correctly reads a lower bound (the row predates the count). The subject of each of those
  tests is something else: a published keystone, a cap, the per-host memo.
- **New `tests/test_impact_assessability.py` section 4**, on W32's real-producer fleet, pins:
  - the bound;
  - the count-alone hold;
  - the unreadable hold, with six bad values;
  - the legacy bound;
  - precedence;
  - agreement across the projection, the Failure Impact sheet, RES-4, the dossier and the explorer embed.
- **`tests/test_r4_deliverable_writers.py :: test_archreview_res4_still_conforms_on_an_observed_zero`**:
  - **Bounded leg** additionally names every row the stored `blind_links` bounds (read from the row, never a
    host list) and the not-graded count.
  - **Conform control** is a fleet whose every inter-switch link carries VLAN evidence (`blind_links` 0) and
    whose every switch faces no uncollected infrastructure. On the regenerated sample, `core1` and `dist1` are
    bounded by their counts, so the old control would no longer describe "a genuinely redundant fleet".
- **`tests/test_ui_projection_device_impact.py :: test_n_two_rows_naming_one_host_are_unverified_and_agree_on_both_surfaces`**
  (the W23 test). Its bare check `"predates" not in <first row reason>` was meant to show that the held copy's
  off-scan-marker hold never leaks into the producer's own row. It also fired on W32's legitimate blind-link
  legacy reason ("…predates the producer's per-row count…"), which is the first row's own bound on a stale
  sample. It is replaced by two checks that are more precise and never weaker:
  - the marker phrase itself is banned on the first row;
  - each first-row cell must equal exactly the doubt, or the doubt + `"; "` + the reason the same cell carries
    on the un-duplicated sample.

  So nothing from the copy, and nothing else, can enter the first row. Only the row's own bound is admitted,
  verbatim. The test then holds on both the stale and the regenerated sample.

## Static checks on `f7b890d5`

| Check | Result |
|---|---|
| `compile()` of all 30 changed `.py` files | pass |
| AST scan (a name assigned and called in one function that shadows a module or enclosing callable), new versus `origin/main` | 0 findings. Non-vacuous: it reports `('write_executive_deck_pptx', 'stat')` on `43f41c80`'s `deck.py` |
| `tests/test_protocol_assessability.py` static helpers on the changed non-test files | 0 hand-listed state sites; 18 receipt readers, none unclassified or gone; carrier, derives, rendered and section-dependency proofs pass |
| Native pins through `_native_schema_hash` | view `732c68c3…`, list `7f256f80…`, equal to main, W33 and W32. The transport schema is unchanged, so `webapp/frontend/src/generated/openapi.ts` needs no change |
| LF receipts | equal to the fixture (above) |
| `ruff check` on the changed files | pass |

## Regeneration declaration (written before the hosted run)

**Golden** (`tests/golden/snapshot.json`). The regenerated golden must be byte-identical to the merged committed
golden: W33's 13 leaves plus W32's 3 `blind_links: 0`. `sheet_schema.json` must be byte-identical.

**Sample** (`webapp/sample_data/sample_fleet.snapshot.json`) versus `origin/main`. Every changed leaf must be in
one of these classes:

1. **W36** (#625): the wall-clock pair `generated_at` / `attestation.generated_at`; `collected_at`
   `+03:00` → `+00:00`; the 150 receipt-hash and 71 receipt-byte leaves in the five named evidence sections.
   Each must equal W36's committed sample exactly.
2. **W32** (#623): `failure_impact[*].blind_links` added on all 23 rows. W32's own run observed core1 1, dist1 1
   and the rest 0.
3. **W33** (#624):
   - the two attestation module counts (+1);
   - `impact_assessability` added on all 23 dossiers;
   - core2's dossier verdict;
   - core2's RES-4 clause, `≥ 42 … (lower bound — it faces 1 uncollected neighbour(s) …)`.
4. **W45 interaction** (W33's mechanism applied to W32's bound, for each row whose regenerated `blind_links` is
   positive; predicted for core1 and dist1, with `why` = `CODE_PHRASES["blind_links"]` for the count):
   - **Dossier `impact_assessability`:** `{lower_bound, why, /failure_impact/<i>}` for those rows.
   - **core1** (Severe; CR-01, CR-04 and CR-06 quote the impact):
     - the measured phrase `removal strands 45 endpoint(s) across 3 VLAN(s)` becomes `removal strands at least
       45 endpoint(s) across at least 3 VLAN(s); the blast radius is only a lower bound (<why>)`;
     - this applies in its verdict and in those three `compound[*].basis` strings;
     - it applies also in the three `punchlist[*].detail` copies of those bases.
   - **dist1** (Low, single red axis): `removal impacts 2 VLAN(s)` becomes `removal impacts at least 2 VLAN(s);
     the blast radius is only a lower bound (<why>)` in its verdict.
   - **RES-4 `observed`:**
     - core1's clause becomes `core1 strands ≥ 45 endpoint(s) (lower bound — <why>)`;
     - the text gains ` 1 simulated device(s) are not graded, because their blast radius is not a measurement
       on this evidence: dist1 (lower bound — <why>).`;
     - the order, the 14-device 30-39 tail, the verdict (advisory) and the 19-host evidence are unchanged.
   - **Unchanged:** every score, band, compound code and ordering.

Any leaf outside these classes is a STOP: it is not imported. The main merge (#620, W27) touches only `webapp/` and
the board. Neither regeneration command reads either, so the declaration is unchanged by it.

## Regeneration evidence

**The run.** `engine-output-handoff.yml` ran 37881624224 (attempt 1, success) on the final source
`7d8f02a2ca810055e81d1c7d4ddce6418b89ad90` (tree `498e6d30`). Artifact 11594811864 has archive sha256
`ac7e4401a6e8a4723be6b7251870b57b7dc47bfec2b1a908b5525e9b6881ed2b`. `receive` admitted it, and it is committed as
`3d9b9831`. The earlier run 37879944000 on `0883db45` predates the main merge and was not imported.

**Golden.** `tests/golden/snapshot.json` and `sheet_schema.json` are byte-identical to the merged tree. A leaf diff
against main gives 16 leaves:

- 13 are equal to W33's own regenerated golden;
- 3 are W32's `blind_links: 0`;
- none is undeclared.

**Sample.** The new `webapp/sample_data/sample_fleet.snapshot.json` is sha256
`dbc229cfdcd676bb07e99bdace7e26ea429de087715ebf1727064b4e373a26c1`, blob
`ba869c0efe012af3c74c34162583834325f476b8`, 3,339,333 bytes. A leaf diff against `origin/main` gives 328 changed
leaves, which is the predicted count. Every leaf is in a declared class, and none is undeclared:

| Class | Leaves |
|---|---|
| W36 wall-clock `generated_at` pair | 2 |
| W36 `collected_at` `+03:00` → `+00:00` | 1 |
| W36 LF receipt hashes, each equal to W36's committed sample | 150 |
| W36 LF receipt byte counts, each equal to W36's committed sample and shrunk | 71 |
| W32 `failure_impact[*].blind_links` added (core1 1, dist1 1, the other 21 rows 0) | 23 |
| W33 attestation module counts, each +1 | 2 |
| W33 dossier `impact_assessability`, published | 60 |
| W33 dossier `impact_assessability`, core2 `lower_bound` (uncollected neighbour) | 3 |
| W33 core2 dossier verdict | 1 |
| W33 + W45 interaction: RES-4 `observed`, equal to the exact predicted text | 1 |
| W45 interaction: core1/dist1 `impact_assessability` `lower_bound` (`blind_links`) | 6 |
| W45 interaction: core1 verdict, CR-01/04/06 bases and dist1 verdict, each the exact predicted phrase substitution | 5 |
| W45 interaction: `punchlist` copies of core1's CR bases, each the exact predicted substitution | 3 |

The classifier compared each W36 leaf with W36's committed sample. For each interaction string it checked the old
text with the measured phrase replaced by the lower-bound phrase. It used the owner's `CODE_PHRASES`, read as
constants.

## Carrying main `f797444e` (#627) and #628 (W46)

On 2026-10-09 this train merged main `f797444e` (#627, Codex W34/G15: per-device VLAN STP root facts in
`selections.stp_roots`) as `1c10bd8d`, then #628 (`origin/claude/train-ui` at `30e425bb`: W28 `trust.inputs`, W29,
W30 and a dist import) as `bc37c587`. Both are merge commits, so the two trains re-test once together.

**Conflicts and resolutions.**
- `docs/NOW.md` (both merges): every active row and handoff line is kept, except the W27 and W31 rows, which main
  retired under rule 8 (#620 and #622 merged).
- `docs/ssot.md` (main): both new registry rows are kept, W33's failure-impact assessability owner first, then G15's
  stored STP observations.
- `tests/fixtures/atlas-r2-byte-custody-policy.v1.json` (main): both sides added one LF-scoped path, so the receipts
  are recomputed (below).
- `tests/test_ui_projection.py` (#628): both admission comments are kept. The auto-merged `allowed` set already holds
  both `cisco_toolkit:impact_assessability` and `cisco_toolkit.analyze:DOSSIER_AXIS_INPUTS`.
- `webapp/backend/ui_projection_api.py` and the W12b prospective pair in `webapp/tests/test_ui_projection_api.py`
  (#628): both replaced by the combined pair.

`cisco_toolkit/ui_projection.py`, `openapi.ts`, `projectionFixtures.ts` and `CoreSnapshot.tsx` merged cleanly.

**Combined schema.** HEAD's owner schema equals the merge base. Main changes `StpRootObservation`,
`StpRootObservationList` and `VlanSelections`; #628 changes `LimitationId`, `Trust`, `TrustInput`, `TrustInputHost`,
`TrustInputHostList` and `VocabUnranked`. No definition is changed by both, the root is unchanged, and every combined
definition equals the one parent that changed it. The view/list keyword set is unchanged (`$defs`, `$ref`,
`additionalProperties`, `allOf`, `anyOf`, `const`, `dependentRequired`, `enum`, `items`, `maxItems`, `maximum`,
`minItems`, `minLength`, `minimum`, `oneOf`, `pattern`, `properties`, `required`, `title`, `type`, `uniqueItems`).

**Native pins.** Computed once, statically, with `ui_projection_api._native_schema_hash` on `_VIEW_SCHEMA` and
`_LIST_SCHEMA`, with the worktree's modules imported (`__file__` asserted):
- view: `0553957c7d4e6e535420488d0aec799db5e319c0942154e6729ab7b5d45fccb4`
- list: `3ee0af7f1686050821ed29878b1785eac3a5ca3ee482b35af55561c770a659df`

Method check: `git archive` extracts reproduce each parent's committed pins: `01720e5b` and `7d547890` give view
`732c68c3…` / list `7f256f80…`, `f797444e` gives `16b80957…` / `bca688bd…`, and `30e425bb` gives `6aa9a264…` /
`a3021b67…`. The pair is in `_NATIVE_SCHEMA_HASHES` and in the W12b prospective pair.

**`openapi.ts`.** The merged file is the union of the two hand edits. A py -3.12 cross-check exported the app's
OpenAPI offline (`export_ui_projection_openapi.export_schema`) for the combined tree and for each parent. It relies on
openapi-typescript 7.13.0 (`--immutable --alphabetize --array-length`) emitting each component as a function of that
component's JSON alone, with references kept by name. It found 0 problems:
- all 313 components are present, and each TS block equals the hosted-checked block of a parent whose component JSON
  is identical (304 from main, 9 from #628);
- the paths, operations and other non-component JSON is identical in every export, and so is each non-component TS
  section;
- the component order agrees with every parent's generator order;
- the members and optionality of all 282 `UiProjection1_` object components match the combined JSON;
- all 51 distinct string-enum unions are present.

The tuple/array rule is therefore inherited unchanged. The hosted `api:check` remains the authority.

**Vocab.** A static mirror of `tests/test_ui_projection_vocab.py` v1 (re-implemented; no test function called) on
the combined `ui_projection_schema()` and `_vocab()` finds 57 string enums in 49 token sets, 19 ranked and 30
unranked. None is doubled, unclassified or invented. G15 adds no string enum; W28's `trust_input_custody` is already
classified.

**Fixtures.** `projectionFixtures.ts` is #628's blob (`b0c125dc`), which carries W28's `trust.inputs`. G15 needs no
fixture change: main did not touch the file, and the inventory fixture's `vlans.rows` page is empty, so
`selections.stp_roots` is never instantiated.

**LF receipts** (`tests/fixtures/atlas-r2-byte-custody-policy.v1.json`), recomputed for the merged tree with the
pure helper logic of `test_byte_bound_checkout_owners_are_lf_exactly_attributed`:

| Scope | `01720e5b` | `f797444e` | Combined |
|---|---|---|---|
| `lf_scope` | 182 `68493206…` | 182 `3dfb75b9…` | 183 `57245ec1b063200468a0234602a114660aa38ee2e00e0bdfaf368611a8254a93` |
| `derived_byte_owner_scope` | 38 `ad1a4aa6…` | 38 | 38 (unchanged) |
| `broader_declared_lf_scope` | 144 `a5cb2b74…` | 144 `1d005cc1…` | 145 `01f4dc994f7750e727a3f7dc06c1e56df19e1fdf83c013fb1baa0753017e1929` |
| `publisher_byte_scope` | 1 `5738a353…` | 1 | 1 (unchanged) |

The added paths over the base are `cisco_toolkit/impact_assessability.py` (W33) and
`webapp/backend/observe_ui_projection_contract.py` (#627). The same helper reproduces the committed receipts of
`7d547890`, `01720e5b`, `f797444e` and `30e425bb`.

**Sample and Atlas Scope.** Neither #627 nor #628 changes snapshot-producing code. Their only engine file is
`cisco_toolkit/ui_projection.py`, which no producer imports: neither `COLLECT_PARSE_V3_23_0.py`,
`webapp/sample_data/` nor any other `cisco_toolkit` module; `impact_assessability.py` imports only `ssot`. The merged
tree's sample (blob `ba869c0e…`, sha256 `dbc229cf…a26c1`), `tests/golden/`, `atlas-scope/` and every engine file
other than `ui_projection.py` are byte-identical to `01720e5b`.

**Dist.** The tracked dist is #628's import, built from `f309ed61`. `frontend_build_handoff.py` binds
`webapp/frontend/**` (excluding `dist/`) plus its five processing inputs. Against `30e425bb` the merged tree differs in
six of them:
- `webapp/frontend/src/generated/openapi.ts` (types only);
- `webapp/frontend/scripts/generate-api-types.mjs`, `generation-policy.mjs` and `generation-policy.test.mjs` (not
  in the Vite graph);
- `.github/workflows/webapp-ci.yml` and `.github/scripts/classify_webapp_ci_scope.py`.

No bundled source changes, so the rebuild was expected to be byte-identical, but the binding is input-based. The
hosted `frontend-dist-handoff-<sha>-<run>-<attempt>` of the pushed head decided it.

**Dist handoff evidence (no import).** After the rule-7 scans, `31d9b5b9` was pushed. Webapp-ci run `37897012004`
(pull_request, attempt 1) and its frontend job `113710626305` succeeded. That job ran api:check ("Generated API types
match the actual app schema"), Vitest (32 files) and the build. The handoff was verified as the W29/W46 precedent
requires:
- **Expected record, selected from Git before the archive was read.** It is the tested merge `7eb1868a` (parents
  `f797444e` + `31d9b5b9`), whose tree `bcf4ff84` equals the head tree, with 146 committed inputs. Six inputs
  differ from `f309ed61`'s.
- **Archive.** Artifact `11601230589`, `frontend-dist-handoff-31d9b5b938c291a62b8276a65890d1fe1e00c6c3-37897012004-1`,
  562,004 bytes, sha256 `4f4f2aa223a03d3595bb6b040df9e53a8ac7779c67556f82c55e7d9ca4b603a7`. This equals the API
  digest and the job-log upload digest.
- **Closed seven-file inventory:** `source-before.json`, `handoff.json` and 5 dist members. There are no directory,
  duplicate, absolute or parent paths, and `handoff.json` has a closed key set.
- **Source records.** Both equal the expected record. `github_head` is `31d9b5b9`, with run `37897012004`, attempt 1.
- **Non-promoting fields hold:** `GENERATED_INPUT_FOR_REVIEW_ONLY`, `release_authority` false,
  `final_source_rebuild_required` true.
- **Toolchain.** Node v24.19.0 and npm 11.17.0 equal the job log's environment details, and the member census
  equals the vite build log.
- **Members.** The 5 member hashes and sizes pass, as do the canonical path-aware marker policy and the index asset
  links. Every asset is reachable from `index.html`.
- **Negative controls are refused:** one altered input hash, a wrong npm version, and `f309ed61`'s tested-merge
  record.

All 5 members (`index.html`, `index-Cd6jS7wb.css`, `index-Cxzz7hwX.js`, `Topology3D-DpMNQuyH.js`,
`react-force-graph-3d-DarJyKca.js`) are byte-identical to the tracked dist, which is #628's import. No dist path
changes and nothing is imported. The handoff is review input; the final head must still reproduce these bytes in
fresh hosted gates.

**Static checks on `bc37c587`:**
- every changed `.py` compiles;
- an AST shadow scan finds no nested `def` rebound in its scope and no shadowed name read before its local binding.
  On the pre-`a38d11b1` deck, the scan does flag W33's `stat`;
- the protocol-assessability static helpers: the hand-list scan finds no site, 18 receipt readers are all classified,
  and the reader-class proofs hold, including the section-dependency proof on `ui_projection.py`;
- the pin, schema-union, OpenAPI, vocab and LF computations above.

No pytest, Vitest, npm, build or engine run.

## Not done here

- **Atlas Scope re-bind.** The regenerated sample stales Scope's compiled outputs and `GOLDEN_SHA`;
  `atlas-scope/` is Codex-held. The supervisor requests it.
- **Remaining W33 F6 raw-row sites: follow-up row W48** ("move remaining failure-impact consumers onto the
  `impact_assessability` owner"). These consumers read the stored `failure_impact` rows directly, so they see neither
  the blind-link bound nor the owner's other holds and bounds. They show core1's 45 stranded endpoints, which is only
  a lower bound (`blind_links` 1), as an exact figure:
  - `cisco_toolkit/mop.py:517`: `fi_by_host`, read by `_blast_for` (line 281) for each wave's "Max blast" figure and
    its rollback trigger;
  - `cisco_toolkit/runbook.py:302`: the row list, which §10 Risk Register ranks and tabulates at line 2267;
  - `cisco_toolkit/ops.py:33`: the handbook's keystones, ranked and tabulated by raw `stranded`;
  - `cisco_toolkit/mcp_server.py:191`: the `failure_impact` tool, which returns the raw cells;
  - `cisco_toolkit/protocol_assurance.py:2204`: copies the raw rows into the failure-rehearsal `impacts` list.

  Two further consumers read the same rows in a different way:
  - `cisco_toolkit/design_advisor.py:1244` counts High rows whose `backup` is 0 as `nobackup_high`, so it reads a
    bounded zero, such as core1's, as a measured "no backup path";
  - `atlas-scope/tools/lib/compile-model.mjs:988` builds `impactByHost` from the raw rows. Atlas Scope is held by
    Codex, so its part of W48 belongs to the Scope holder.

  A correction to this record: AssessHub `summary` and `cutover` are **not** raw-row readers. Since W27 (#620) they
  read the engine projection: `webapp/backend/summary.py:257` calls `engine.failure_impact_projection` in
  `impact_view`, and `webapp/backend/cutover.py` reads `summary.impact_view`. This train carries them onto the owner's
  blind-link rule, and `webapp/tests/test_impact_surfaces.py` pins that.
- **W32's F2–F4 producer follow-ups.**
