# W41 punch-list facet totals (G21)

Branch `claude/g21-punch-facets`, started from main `a06d1d27`. This record covers gap G21
(`docs/one-app-contract-gaps-2026-09-30.md`, entry 24). The Findings payload now carries
`findings.facets = {severity, category, device}`: the punch-list row counts by severity, by
category and by inventory device, each count a `CountFact` under the projection's evidence
states.

No local test, browser, SPA build, OpenAPI export, projection run or benchmark was made; the
owner's rule is GitHub-hosted only. Every runtime verdict below is pending hosted evidence.

## Contract

| Facet | Keys (owner order) | Count owner | Reconciles with |
|---|---|---|---|
| `severity` | `analyze.PUNCH_SEVERITIES` (5) | `analyze.compute_punchlist_facets` | every stored row exactly once; sum = row count = `findings.total` |
| `category` | `analyze.PUNCH_CATEGORIES` (24) | `analyze.compute_punchlist_facets` | every stored row exactly once; sum = row count = `findings.total` |
| `device` | the inventory roster (devices map plus `collection_completeness` blind spots), sorted | the G09 rollup `_device_finding_rollup` (fold `analyze.compute_device_findings`), summed | the device's own inventory row; not the row total (a multi-device row counts once per named device) |

- **Category vocabulary.** `analyze.PUNCH_CATEGORIES` is `tuple(_PUNCH_EVIDENCE_POLICY)`.
  `tests/test_punchlist_evidence_refs.py` already holds those keys equal to the set derived from
  the producer's AST, so the facet keys are that set, never a second hand list. The schema closes
  them (`CategoryFacetRow.k`) and the G43 catalogue classifies them as the unranked vocabulary
  `punch_category`.
- **The device facet reuses G09; it does not duplicate it.** Each device bucket is the device's
  `findings.by_severity` rollup summed, with the rollup's state, reason, refs and caveats kept. A
  configless, blind, unreadable or failed device is withheld exactly as its inventory row is.
- **Engine owner.** `analyze.compute_punchlist_facets` is a pure, unpersisted fold next to
  `compute_device_findings`. Each facet is a complete partition or nothing: a non-list, a row that
  is not a record, or a value outside the closed vocabulary refuses that facet. A legacy category
  spelling refuses the category facet only; the severity counts stay.

### Evidence states

| Input | Severity and category buckets | Device buckets |
|---|---|---|
| Punch list absent | `not_collected` | G09: `not_collected` |
| Punch list `[]` | `collected_but_empty` ("carries no row") | G09: measured `0` for a captured device |
| Punch-list phase or a punch-list input failed | `analysis_unavailable`, with the failure record | G09: `analysis_unavailable` |
| Owner fold refuses, or its buckets do not place every row exactly once in the bucket its own field names, or disagree with the row list or its published total | `unverified` | G09 rules |
| Published list, no fleet qualification | the count; `0` is a measured zero over a complete list | G09 |
| Published list, a blind device or a device without a captured running-config | positive: a lower bound carrying the qualification caveat and witnesses; zero: `not_collected`, never a clean result | G09 per device |

A severity or category bucket cites `/punchlist` as its basis, then the row list's qualification
witnesses and failure records. It does not repeat the sixteen per-input basis refs or a witness
per row; each row's own severity and category cells carry those. A device bucket keeps G09's
per-row witnesses.

## Native transport schema re-pin

**Method check.** An extract of main `a06d1d27` reproduces main's own pins:
- view: `732c68c3d762f2b3d4d0329582bd32f3842567feef9cab20960f6959eef07372`
- list: `7f256f809f1d9e0754a2312579ee6afdfe3ae5e58c2b5dd7b44fbfd32b5369b5`

### Reviewed structural delta

1. **Four added definitions:** `SeverityFacetRow`, `CategoryFacetRow`, `DeviceFacetRow` and
   `FindingFacets`. No definition is removed, and the existing `$defs` keep their order.
2. **Two changed definitions:**
   - `Findings` gains the required property `facets` (a `$ref` to `FindingFacets`);
   - `VocabUnranked` gains `punch_category`.
3. **Branches.** Only the findings view branch changes: its payload gains `facets`. Every list
   branch is byte-equal to main's, and `LIST_CATALOG` is unchanged. The facets are whole owner
   arrays, never transport pages.
4. **Reachability.** The view schema reaches 207 of 290 definitions (main: 203 of 286), the four
   new ones included. The list schema reaches 180 of 290 (main: 180 of 286). No `Vocab*`
   definition is reachable from any branch.
5. **Keywords.** The changed definitions and the changed branch use only keywords already in
   main's view and list profile. A static sweep found none outside it.
6. **Instance domain.** Facet counts are JSON integers, so `_native_instance_allowed`, the
   provider version (`jsonschema-rs` 0.58.5), the private resolver guard and the offline Python
   fallback are unchanged.

### Hashes

Compact `ensure_ascii` JSON plus LF, in owner key order. They were computed statically with
`ui_projection_api._native_schema_hash`, with `backend.ui_projection_api` and
`cisco_toolkit.ui_projection` imported from this worktree (`__file__` asserted). They are now in
`_NATIVE_SCHEMA_HASHES` and in the W12b prospective pair:
- view: `4643eba4c8eaf44fd4c3b9905da2b8439f0c5375cf944a24be40e0f7fd27c580`
- list: `3fdc738d246a42ad3789bd9ede7353b9ddc4c0bdcd8dcd522bdd55aaf7845f16`

Any other schema change that merges first moves the same pins. This branch must then merge that
main, re-pin on the combined schema and regenerate `openapi.ts` on it.

## G43 catalogue

A static sweep of the owner schema finds 57 string enums in 49 token sets outside the `Vocab*`
closure. Each token set is classified exactly once (19 ranked, 30 unranked): none is
unclassified and none is invented.
- `SeverityFacetRow.k` reuses the ranked `severity` token set.
- `CategoryFacetRow.k` is the new unranked `punch_category`. A category names what a finding is
  about; its severity carries its level.

## Generated types and fixtures

`webapp/frontend/src/generated/openapi.ts` is hand-edited to the openapi-typescript 7.13.0 shape:
`--immutable --alphabetize --array-length`, case-insensitive component order, tuples below 30
estimated elements, and `readonly T[]` for the unbounded device array. Hosted `api:check` remains
the authority.

The edits are:
- the four new components;
- `facets` on `UiProjection1_Findings` and on the findings view payload;
- `punch_category` in `UiProjection1_VocabUnranked`.

`findingsFixture` in `webapp/frontend/src/test/projectionFixtures.ts` now carries `facets`. The
new `findingFacetsFixture` reads the severity and category keys from the generated contract, the
same way `vocabFixture` does, so the fixture holds no second copy of an engine vocabulary.

## Limitations

No limitation ID is added, so the 29-item Trust limitation tuples and the device limitation
tuples in `openapi.ts` are unchanged. Five existing limitations gain `/findings/facets` (or
`/findings/facets/device`) in `applies_to`:
- `one_hop_failure_attribution`;
- `fleet_lists_exclude_blind_devices` and `findings_without_running_config`, whose texts now state
  the lower-bound and zero rule;
- `projection_owned_verdicts`, whose text now names the partition check;
- `device_findings_scope`, whose text now states the device facet's roster and why its counts
  never sum to the row total.

## Unchanged

- The bytes of `tests/golden/*` and `webapp/sample_data/sample_fleet.snapshot.json`. Both are
  read by the new tests as they are.
- `atlas-scope/`. Atlas Scope's `envelope()` exact key sets cover the transport envelope, which
  is unchanged. The topology and path payloads are unchanged.
- The LF byte-custody receipt. No tracked file was added under `cisco_toolkit/`,
  `webapp/backend/` or the other policy domains, and no `cisco_toolkit` module was added.
- `tests/test_protocol_assessability.py`'s section-dependency proof. The facet code names no
  `PUNCHLIST_INPUTS` and no receipt state. It takes the row list's own final state, and its
  allow-list is unchanged.

## Tests authored (not run locally)

- `tests/test_punchlist_facets.py`. The fold over the stored sample and golden punch lists,
  checked against independent `Counter` recounts. Also: real producer rows, per-facet refusals,
  purity, and the category vocabulary held equal to the producer's AST-derived emittable set.
- `tests/test_ui_projection_finding_facets.py`. Also over the stored sample and golden:
  - recounts and reconciliation with the row total;
  - the configless-device qualification, and device buckets equal to their inventory rows;
  - the complete-capture control, where zeros publish;
  - missing, empty, failed-phase and failed-input states;
  - blind and configless qualifications;
  - legacy categories, owner faults, eleven non-reconciling partitions, and row-count and
    published-total disagreement;
  - closed-schema forgeries, purity and container independence.
- `tests/test_ui_projection_inventory.py::test_i13_every_published_number_is_the_owners`. Every
  published facet count is recounted independently from the snapshot.
- `tests/test_ui_projection.py`. The import allowlist admits `PUNCH_CATEGORIES` and
  `compute_punchlist_facets` by exact name.
- `webapp/tests/test_ui_projection_api.py`. Native and stock agree on the real findings view and
  on fourteen refusals. The W12b prospective pins are updated.

## Follow-up (not in this slice)

The AssessHub Findings screen (`webapp/frontend/src/pages/CoreSnapshot.tsx`, `Findings`) still
renders no facet counts. Its disclosure says "Severity and category facet totals are not
published by this contract", which becomes stale when this merges. Rendering the facets changes
the tracked SPA bundle, so it needs the hosted SPA build handoff. It is a separate frontend slice
and is deliberately not mixed into this contract change.

## Verification boundary

Local evidence:
- `py_compile` of every touched Python file;
- the static assessability guard helpers from `tests/test_protocol_assessability.py`;
- an AST scan for locals shadowing called module helpers;
- the static pin, delta, reachability, keyword and enum-sweep computations above;
- the rule-7 privacy and marker scans.

Still required before merge:
- every protected exact-head hosted check, including the native-parity group and `api:check`;
- independent refutation;
- the supervisor's merge.
