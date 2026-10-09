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
| `severity` | `analyze.PUNCH_SEVERITIES` (5) | `analyze.compute_punchlist_facets` | every stored row exactly once; sum = row count = the published `findings.total` |
| `category` | `analyze.PUNCH_CATEGORIES` (24) | `analyze.compute_punchlist_facets` | every stored row exactly once; sum = row count = the published `findings.total` |
| `device` | the inventory roster (devices map plus `collection_completeness` blind spots), sorted, as a `DeviceFacetList` | the G09 rollup `_device_finding_rollup` (fold `analyze.compute_device_findings`), summed | the device's own inventory row; not the row total (a row naming no inventory device counts under none, a multi-device row under each) |

- **Category vocabulary.** `analyze.PUNCH_CATEGORIES` is `tuple(_PUNCH_EVIDENCE_POLICY)`.
  `tests/test_punchlist_evidence_refs.py` already holds those keys equal to the set derived from
  the producer's AST, so the facet keys are that set, never a second hand list. The schema closes
  them (`CategoryFacetRow.k`) and the G43 catalogue classifies them as the unranked vocabulary
  `punch_category`.
- **Category sources.** `analyze.PUNCH_CATEGORY_SECTION` is a new read-only public view
  (`MappingProxyType`) of the engine's `_PUNCH_CATEGORY_SECTION`: the published section each
  category is folded from. It is now total over `PUNCH_CATEGORIES`. The one entry added is
  Coverage -> `operational_drift`: `compute_operational_drift` writes the Coverage rows and the
  punch list folds them through `operational_drift`, as it does False-health. The map's only
  engine use is the `row_requires_ref` section fallback, which never applies to an absence row, so
  this entry changes no engine row.
- **The device facet reuses G09; it does not duplicate it.** Each device bucket is the device's
  `findings.by_severity` rollup summed, with the rollup's state, reason and caveats kept. A
  configless, blind, unreadable or failed device is withheld exactly as its inventory row is. Its
  refs are the rollup's basis, custody and qualification refs. The per-row witnesses (one per
  stored row naming the device) stay on the inventory row and the device page, so a bucket grows
  with the roster, not with rows times devices.
- **The device list takes the roster's own state.** `_roster_list` is shared with the inventory
  device rows: the devices map's state, then the `collection_completeness` rollup. An absent
  devices map is `not_collected` and an unreadable one `unverified`, never an empty published
  roster. The list is a primary FactList, so the transport pages it at `/facets/device` like every
  other one.
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
| The row list is published but its total is not (a census fault or an unreadable count) | `unverified`: nothing to reconcile with | G09 rules |
| A category's own source section not collected, failed, or unreadable by the abstention core | that category: zero takes the section's state (`not_collected`, `analysis_unavailable` with the failure record, `unverified` with the fault); positive is a lower bound with `finding_facet_source_incomplete`. Every severity bucket follows the same rule, the strongest held state first | G09 rules |
| Published list, no fleet qualification, every category source complete | the count; `0` is a measured zero over a complete list | G09 |
| Published list, a blind device or a device without a captured running-config | positive: a lower bound carrying the qualification caveat and witnesses; zero: `not_collected`, never a clean result | G09 per device |
| Devices map absent or unreadable | (per the rows above; the Inventory category's source is `devices`) | the list is `not_collected` or `unverified`, never an empty roster |

A severity or category bucket cites `/punchlist` as its basis, then the row list's qualification
witnesses and failure records, then, when its source hold applies, the held section and its
failure records. It does not repeat the sixteen per-input basis refs or a witness per row; each
row's own severity and category cells carry those.

## Review round 1 (2026-10-09)

The reviewer's findings were checked against the code before any change. Each was real.

### P1: a zero was published as clean over a missing or failed category source

The facet's zero gate was only the fleet qualification, and the row list it inherited rolls up
only over `PUNCHLIST_INPUTS`. Nine categories fold from sections outside that list:
`stp_roots`, `addressing_conflicts`, `fhrp`, `trunk_native`, `link_phy`, `devices`,
`operational_drift`, `service_map` and `multicast_intelligence`. A correction to the review: the
decision-rollup synthetic snapshot did carry `stp_roots` and `devices`. It lacked the other seven,
and the original synthetic test still asserted their zeros as published.

Fix, structural over the whole class: `_category_sources` reads every category's source from the
owner map, never a hand list, and `ctx.abst` decides whether it is complete.
`_severity_source_hold` applies the strongest held state to every severity bucket.
`PUNCHLIST_INPUTS` is unchanged, so `tests/test_protocol_assessability.py`'s pinned uses still
hold, and so does the static proof run on this tree. A category the map does not name fails
closed (`unverified`); the map is total today, and a test exercises that guard.

### P2: the device facet was a bare array

An absent or unreadable roster read as "no device has findings". The fix is a `DeviceFacetList`
in the roster's own state, as above. A test deletes `devices` and gets a withheld list. Because
`devices` is the Inventory category's own source, the P1 rule also withholds the Inventory zero
and every severity zero in that case. That closes the reviewer's scenario, where no qualification
applied because no devices map existed.

### P2: the AssessHub Findings disclosure becomes false on merge

`webapp/frontend/src/pages/CoreSnapshot.tsx` (`Findings`) says "Severity and category facet totals
are not published by this contract". Changing it changes the tracked SPA bundle, which only the
hosted SPA dist handoff may produce. That handoff is not a local action. The board row W41 now
carries it as a **merge precondition**, not a follow-up: W41 does not merge until the paired SPA
slice renders the facets and removes that sentence in the same merge train.

### P3 dispositions

| Item | Disposition |
|---|---|
| "device counts never sum to the row total" | Fixed. The text is now "need not sum to the row total", in `device_findings_scope` (also re-addressed into every `DeviceDocument`), `docs/ssot.md` and this record. |
| An unpublished total was replaced by `len(rows)` | Fixed. `_facet_partition` withholds the owner facets as `unverified` when the total is not published. Two tests cover it: a census fault and a count that is not a count. The `projection_owned_verdicts` text states the rule. |
| The complete-capture control was self-contradictory | Fixed. The control now sets `config_assessable` true for the patched hosts as well as copying security rows, and asserts their device buckets publish exact counts. |
| Unpaged device facet with per-row witnesses | Fixed. The per-row witnesses are dropped from the buckets, and the list is paged at `/facets/device` (`LIST_CATALOG["findings"]` is now `/rows`, `/facets/device`). |
| Stale base and a `docs/NOW.md` conflict with `origin/main` `7d547890` (#620) | Fixed locally. `7d547890` is merged with a merge commit after the fix commit. The board takes main's version (its W27 row and its retirement of the W26 row stand), the W41 row is added, and every handoff line from both sides is kept. #620 touches no projection, schema or OpenAPI file, so the pins below are unchanged on the merged tree; that was re-checked statically. No fetch was made, so a later main still needs the same merge. |

## Native transport schema re-pin

**Method check.** An extract of `98b27f72` (this branch before the fix) reproduces its pins:
- view: `4643eba4c8eaf44fd4c3b9905da2b8439f0c5375cf944a24be40e0f7fd27c580`
- list: `3fdc738d246a42ad3789bd9ede7353b9ddc4c0bdcd8dcd522bdd55aaf7845f16`

Those were themselves the static re-pin over main `a06d1d27`, whose own pins
(`732c68c3…`, `7f256f80…`) were reproduced first.

### Reviewed structural delta (against `98b27f72`)

1. **Three added definitions:** `DeviceFacetList` (a `_list_def` of `DeviceFacetRow`) and its
   transport pair `Page_DeviceFacetList` and `Source_DeviceFacetList`. No definition is removed,
   and the existing `$defs` keep their order.
2. **Four changed definitions:**
   - `FindingFacets.device` becomes a `$ref` to `DeviceFacetList`;
   - `LimitationId` gains `finding_facet_source_incomplete`;
   - `Trust.limitations` grows to 30 items;
   - `VocabUnranked.limitation_id` gains the new token.
3. **Branches.** The view schema keeps 6 branches; only the device branch is byte-equal, because
   every other envelope carries the 30-item limitation registry. The list schema gains one branch,
   findings `/facets/device`, for 37 in total; its 17 device branches are byte-equal.
4. **Reachability.** The view schema reaches 208 of 293 definitions (before: 207 of 290). The list
   schema reaches 183 of 293 (before: 180 of 290).
5. **Keywords.** A static sweep finds no keyword outside the previous view and list profiles.
6. **Instance domain.** Facet counts are JSON integers and the new list carries the usual list
   envelope. `_native_instance_allowed`, the provider version (`jsonschema-rs` 0.58.5), the private
   resolver guard and the offline Python fallback are unchanged.

### Hashes

Compact `ensure_ascii` JSON plus LF, in owner key order. They were computed statically with
`ui_projection_api._native_schema_hash`, with `backend.ui_projection_api` and
`cisco_toolkit.ui_projection` imported from this worktree (`__file__` asserted). They are now in
`_NATIVE_SCHEMA_HASHES` and in the W12b prospective pair:
- view: `9f59334b1e828c4dbc7be2597800799389a55fe8826a939c0d54585aff10e7fd`
- list: `7f7682f6edc67a141c926f721b5586de653fa11c35b2d3c9bc22e978e017760b`

Any other schema change that merges first moves the same pins. This branch must then merge that
main, re-pin on the combined schema and regenerate `openapi.ts` on it.

## G43 catalogue

A static sweep of the owner schema finds 57 string enums in 49 token sets outside the `Vocab*`
closure. Each token set is classified exactly once (19 ranked, 30 unranked): none is
unclassified and none is invented.
- `SeverityFacetRow.k` reuses the ranked `severity` token set.
- `CategoryFacetRow.k` is the new unranked `punch_category`. A category names what a finding is
  about; its severity carries its level.
- `finding_facet_source_incomplete` joins the existing unranked `limitation_id` set, which
  `_ALL_LIMITATION_IDS` derives; no new vocabulary is introduced.

## Generated types and fixtures

`webapp/frontend/src/generated/openapi.ts` is hand-edited to the openapi-typescript 7.13.0 shape:
`--immutable --alphabetize --array-length`, case-insensitive component order. The generator's
array rule was read from the 7.13.0 source: a fixed-length array becomes a tuple only while its
estimated size, `(max*(max+1) - min*(min-1))/2`, stays below 30. For `min = max = n` that is `n`,
so 29 limitations were a tuple and 30 are `readonly T[]`. Hosted `api:check` remains the
authority.

The edits, applied by one deterministic script:
- the new `UiProjection1_DeviceFacetList`, `UiProjection1_Page_DeviceFacetList` and
  `UiProjection1_Source_DeviceFacetList`, in alphabetical position and shaped like the
  `DeviceRowList` trio;
- `UiProjection1_FindingFacets.device` as the list;
- `finding_facet_source_incomplete` in `UiProjection1_LimitationId` and in the
  `limitation_id` vocabulary tokens;
- all 27 thirty-item limitation registries as `readonly ...["UiProjection1_Limitation"][]`.
  These are Trust, the five non-device view envelopes, the inline trust view payload, 19 list
  envelopes and the path envelope. The 20 eighteen-item device registries stay tuples;
- the findings view payload's `facets` inlined (its device list paged at `/facets/device`), and
  one new findings list-response branch for that pointer.

`findingsFixture` in `webapp/frontend/src/test/projectionFixtures.ts` carries `facets` with the
device list as a page (`ownerPage("/facets/device", ...)`). `findingFacetsFixture` reads the
severity and category keys from the generated contract, the same way `vocabFixture` does, so the
fixture holds no second copy of an engine vocabulary. No renderer reads the facets yet.

## Limitations

One limitation ID is added: `finding_facet_source_incomplete` (owner
`analyze.PUNCH_CATEGORY_SECTION`, applies to `/findings/facets/severity` and
`/findings/facets/category`). It is not device-cited, so the device-document registry is
unchanged. Existing limitations that gain `/findings/facets` (or `/findings/facets/device`) in
`applies_to`:
- `one_hop_failure_attribution`;
- `fleet_lists_exclude_blind_devices` and `findings_without_running_config`, whose texts state the
  lower-bound and zero rule;
- `projection_owned_verdicts`, whose text names the partition check, the unpublished-total rule
  and the source-section check;
- `device_findings_scope`, whose text states the device facet's roster and why its counts need not
  sum to the row total.

## Unchanged

- The bytes of `tests/golden/*` and `webapp/sample_data/sample_fleet.snapshot.json`. Both are
  read by the new tests as they are. The added Coverage map entry changes no engine row (above),
  so the pipeline golden's punch list is unchanged.
- `atlas-scope/`. Atlas Scope's `envelope()` exact key sets cover the transport envelope keys,
  which are unchanged. The topology and path payloads are unchanged; the path envelope's
  limitation registry grows by one item, as every non-device envelope's does.
- The LF byte-custody receipt. No tracked file was added under `cisco_toolkit/`,
  `webapp/backend/` or the other policy domains, and no `cisco_toolkit` module was added.
- `tests/test_protocol_assessability.py`'s section-dependency proof. The facet code names no
  `PUNCHLIST_INPUTS` and no receipt state. Its static helpers, run on this tree, pass.

## Tests authored (not run locally)

- `tests/test_punchlist_facets.py`. The fold over the stored sample and golden punch lists,
  checked against independent `Counter` recounts. Also: real producer rows, per-facet refusals,
  purity, and the category vocabulary held equal to the producer's AST-derived emittable set. New:
  the category-to-section map is total over that set, read-only and equal to the private table.
  Every source is a section the golden publishes, and Coverage's source is the producer that
  writes it.
- `tests/test_ui_projection_finding_facets.py`. Also over the stored sample and golden:
  - recounts and reconciliation with the row total;
  - the configless-device qualification, and device buckets equal to their inventory rows less
    the per-row witnesses;
  - the device list in the roster's own state;
  - the complete-capture control, where zeros publish and the patched devices publish too;
  - missing, empty, failed-phase and failed-input states;
  - blind and configless qualifications;
  - legacy categories, owner faults, eleven non-reconciling partitions, row-count and
    published-total disagreement, and two unpublished totals.

  New for the P1 and P2 fixes:
  - F6 deletes every source section in turn (parametrized from the owner map) from the fully
    captured stored sample. It also covers the reviewed `multicast_intelligence` case, a
    positive count over a missing source, a failed source phase with its failure record, and the
    unmapped-category guard;
  - F7 covers a missing or unreadable devices map;
  - closed-schema forgeries include a bare device array and an empty published list.

  The synthetic snapshot now carries every category source (empty, in the golden's shape), so its
  published zeros are earned rather than assumed.
- `tests/test_ui_projection_inventory.py::test_i13_every_published_number_is_the_owners`. Every
  published facet count is recounted independently from the snapshot, the device buckets at
  `/facets/device/items/<i>/n`.
- `tests/test_ui_projection.py`. The import allowlist admits `PUNCH_CATEGORIES`,
  `PUNCH_CATEGORY_SECTION` and `compute_punchlist_facets` by exact name.
- `webapp/tests/test_ui_projection_api.py`. Native and stock agree on the real findings view and
  on fifteen refusals, including a bare device array. Both admit the new caveat. The device
  facet's list route returns the owner roster's later page, and native and stock agree on it and
  on a refusal. The W12b prospective pins are updated.

## Verification boundary

Local evidence:
- `py_compile` of every touched Python file;
- the static assessability guard helpers from `tests/test_protocol_assessability.py`;
- an AST scan for locals shadowing module helpers;
- the registry citation checker from `tests/test_ssot_registry.py` on the G21 row;
- the static pin, delta, reachability, keyword and fixed-length-array counts above;
- the rule-7 privacy and marker scans.

Still required before merge:
- the paired SPA slice (merge precondition above);
- every protected exact-head hosted check, including the native-parity group and `api:check`;
- independent refutation;
- the supervisor's merge.

## Second refutation round on the W51 train (2026-10-09)

* **P1 (only directly attributed failures):** `_category_sources` reads the module's full failed-phase census:
  `ssot.abstention_reason` for a directly attributed section, and `ctx.unattributed` (an intermediate phase, a
  label nobody classified, or a failed-phase record that is not a list, from `ssot.failed_sections` over
  `ssot.PHASE_SECTIONS`) for every category it could feed, which is every category. Such a hold is
  analysis_unavailable with the unattributed failure records. Probe: the sample under `dependency map` published 17
  categories without the source caveat; now none.
* **P2 (wrong container):** `CATEGORY_SOURCE_KINDS` registers each source section's producer container (held by a
  test against the engine-built sample and golden); a section stored as anything else is unverified, a section with
  no registered container too. Probe: `multicast_intelligence` stored as a list, text or number published
  `Multicast/Media: 0`; now unverified.
* **Fleet qualification** now also fires on an absent, failed or self-contradictory blind-spot record
  (the blind-spot record's one coverage verdict, `_cc_coverage` (read through `_Ctx.cc_coverage`, next to F6's `_cc_universe`)).
