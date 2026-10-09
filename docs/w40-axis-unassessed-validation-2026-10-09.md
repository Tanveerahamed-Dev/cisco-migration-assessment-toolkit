# W40 per-axis could-not-assess denominators (G05) validation

Branch `claude/g05-axis-denominators`, started from main `a06d1d27` and since merged with main `7d547890`
(#620). This record covers gap G05 of `docs/one-app-contract-gaps-2026-09-30.md` (section 18): for each
executive axis, how many devices it could not assess, out of how many.

Each `overview.axes.items[]` row now carries `unassessed = {n: CountFact, of: CountFact}`. Both facts are
read from the axis's producer, never from the brief's headline text. No engine section, sample or golden
changes, and no new toolkit module or limitation ID is added.

This is a source checkpoint. No local test, build, OpenAPI export, type check, projection or browser run
was made, because the owner's rule is GitHub-hosted only. Every runtime verdict is pending hosted evidence.

## What each axis reads

The table is `cisco_toolkit.ui_projection.AXIS_UNASSESSED` (stored counts),
`AXIS_UNASSESSED_LIVE` (Fleet health) and `AXIS_UNASSESSED_ABSENT` (no stored count). The three tables
partition the registered brief axes exactly once. `AXIS_UNASSESSED_LAYERS` names the further layers a
stored count does not cover.

| Axis | `n`: could not assess | `of` | Raw basis the count is held against |
|---|---|---|---|
| Hardware lifecycle (EoL) | `lifecycle_risk.summary.n_unknown` | `lifecycle_risk.summary.n_devices` | `lifecycle_risk.per_device[].band == "Unknown"` |
| Operational logs | `syslog_intelligence.summary.n_not_collected` | `syslog_intelligence.summary.n_devices` | `per_device[].collected == false` |
| QoS posture | `qos_audit.summary.n_not_assessable` | `qos_audit.summary.n_devices` | `per_device[].assessable == false` |
| Software risk | `software_risk.summary.n_config_not_assessable`, withheld while the release-train layer (`n_version_known`) shows a gap | `software_risk.summary.n_devices` | `per_device[].config_assessable == false` |
| Platform capacity | `platform_health.summary.bands.Unknown` | `platform_health.summary.n_devices` | `per_device[].band == "Unknown"` |
| Asset risk register | `device_dossiers.summary.bands.Unassessed` | `device_dossiers.summary.n_devices` | `per_device[].risk_band == "Unassessed"` |
| Fleet health | `ssot.fleet_avg_health` `n_rows` minus `n_scored` (live) | `n_rows` (live) | the owner counts the health rows itself |
| Migration punch-list, Application domains, Cutover sequence, Segmentation, Multicast / timing, Remediation | `not_collected`, never 0 | `not_collected` | the producer stores no per-device count |

## Coverage-honesty rules

- **Failed input.** The block follows its row. When a failed phase makes the row's fact
  `analysis_unavailable`, both cells are `analysis_unavailable` with the same `failure_record` references.
  That covers the brief itself and any section of the row's basis. For an unregistered label the basis is
  every brief input. A count whose producer did write a value keeps that owner's token in `engine_state`.
- **Contradicted count.** Both facts are `unverified`, with witness references, when:
  - the count exceeds its denominator;
  - a further layer's stored count exceeds the denominator;
  - the producer's per-device rows disagree with the count or the denominator;
  - the rows cannot be read (not a list of records, each carrying the field with the right type).
- **No raw basis.** When a snapshot carries no rows, the stored summary is published as it stands. This
  follows the `reconcile_checks_only_with_raw_basis` precedent.
- **Missing count.** A count missing from a summary its producer wrote is `not_collected`, never 0. The
  reason gives examples of a cause (an older snapshot, an edited summary) and claims neither.
- **Sparse counter.** One counter omits a zero entry: `platform_health.summary.bands` is a `Counter`.
  `AXIS_UNASSESSED_SPARSE` names it, and a test holds that against the producer. Its missing `Unknown`
  entry is published as 0 only when the per-device rows and a published denominator confirm that no
  device holds the band. Otherwise it is:
  - `not_collected` when the rows are absent;
  - `unverified` when the rows contradict it or cannot be read.
- **Zero over zero.** A zero count over a zero denominator is `collected_but_empty`, never a measurement.
- **Measured zero.** A stored measured zero (for example the sample's `Unassessed: 0`) keeps the owner's
  `collected_but_empty` token in `engine_state`, with the `measured_zero_mapping` caveat. That caveat's
  `applies_to` now includes `/overview/axes`.
- **Further layer.** A count that covers one layer of an axis whose producer assesses another is that
  axis's count only while the other layer's stored count equals the device count. Otherwise `n` is
  `not_collected`. The reason names the stored value, the other layer's gap read from the owner
  (`n_devices - n_version_known`) and the stored layer count. A witness reference points at that count,
  and `engine_state` keeps the owner's token.
- **Blind spot.** No producer universe holds an inventory device the collection never reached. While
  `collection_completeness` lists any partial or not-collected device:
  - every published `n` and `of` carries `fleet_lists_exclude_blind_devices`, with a witness reference to
    each blind-spot row;
  - a zero `n`, a count over no device, and an empty `of` are `not_collected`, never "none left
    unassessed".
- **Unreadable label.** An axis row with no readable label is `unverified`. An unregistered label is
  `not_collected`.

## Design decisions

- **Platform capacity counts the `Unknown` band, not `n_not_collected`.** The producer also bands a
  device `Unknown` when its capacity output was collected but no figure was recognised. So
  `n_not_collected` would undercount the devices the axis could not assess. A real-producer test holds
  a fleet where the two differ.
- **Operational logs counts a captured buffer as assessed.** This holds even when no line in the buffer
  was recognised: `compute_syslog_intelligence` stores no count of unrecognised buffers. The limitation
  text says so (review P3, accepted as documented).
- **Software risk's count is its running-config layer, withheld while the release-train layer has a
  gap.** No stored count spans both layers. A bare configuration-layer count beside a version gap would
  read "could not assess 0" for a fleet in which no release was assessed. The reason keeps the value,
  so nothing is lost.
- **Further layers are a table, held as a class.** A test scans every registered producer's real summary
  for per-layer coverage counts (`n_*_known`, `n_*_assessable`, `n_*_collected`). Each one must be a
  registered further layer of that axis, or the registered count's own complement. A complement must
  leave no device outside the registered count. Today the only further layer is `n_version_known`.
- **Blind spots reuse the fleet-list rule.** `_fleet_qualify` is the one owner of the blind-spot witness
  set. `fleet_lists_exclude_blind_devices` gains `/overview/axes` in its `applies_to`, and its text gains
  one sentence for the counts. Both partial and not-collected rows qualify, as for every fleet list.
  Over-withholding a zero beside a partial device is the safe direction.
- **Fleet health reuses the fleet-health block's live counts.** `_fleet_health_count` is extracted
  unchanged from `_fleet_health`. So the axis's `of` is the same owner value as
  `overview.fleet_health.n_rows`, and `n` is the brief's own unscored rows.
- **The lifecycle count is the canonical fact.** `n_unknown` is also `overview.facts.n_unknown`, and the
  test holds the two equal on the sample. `ssot.reconcile` still applies to both. A blind spot qualifies
  only the axis cell. The canonical headline fact is owned by `ssot.canonical_facts` and is outside G05.
- **No new limitation ID.**
  - The existing `axis_basis_owned_by_projection` limitation states the G05 table, its checks, the
    further-layer rule and the failure rule. The existing `fleet_lists_exclude_blind_devices` limitation
    states the blind-spot rule.
  - A 30th payload limitation would turn every 29-item limitation tuple in `openapi.ts` into an array.
    W28 makes exactly that change, so adding one here would double the conflict. The P2 fix therefore
    withholds rather than adding a cell-level ID, one of the two fixes the review offered.
  - The texts and `applies_to` lists are instance data, not schema.
- **No transport envelope change.** The block sits inside the owner `AxisItem` definition. Atlas Scope
  reads only the topology and path envelopes, and neither changes.

## Review fixes (independent review of `9097af0e`)

| Item | Verdict | Change |
|---|---|---|
| P1: five stored axes could publish a measured 0 while `collection_completeness` listed an unreached device | Real. `COLLECT_PARSE_V3_23_0.py` skips an unreached device from `all_devices_meta`, and every producer universe derives from that list. The health rows (Fleet health, Asset risk register) do as well, so all seven counted axes are in the class. | `_qualify_unassessed`: caveat plus a witness reference to each blind-spot row on published cells, and `not_collected` for a zero, a count over no device or an empty denominator. `/overview/axes` is added to the limitation. |
| P2: Software risk's `n` counted the configuration layer only | Real. `compute_software_risk` with every config and no version gives `n_config_not_assessable` 0 and `n_version_known` 0. | `AXIS_UNASSESSED_LAYERS` plus `_layer_gaps`: `n` is withheld as `not_collected` while the layer gap stands. A layer count above `n_devices` makes both cells `unverified`. |
| P3: failure precedence differed between the row's fact and the block | Real. An unregistered label used `AXIS_BASIS.get(label, ())` rather than the row's fail-closed `BRIEF_INPUTS`. | `_axis_unassessed` takes the row's `basis` and `base`. `_failed_unassessed` applies "a failed input always wins" before any other path. Decision: a failed brief withholds the producer counts too. |
| P3: missing-count reason stated a cause it cannot know | Real. | Neutral wording: "for example a snapshot that predates this count, or a summary edited after it was written". |
| P3: Operational logs and Platform capacity apply different could-not-assess rules | Real, and bounded by the producer: no count of unrecognised buffers is stored. | Accepted as documented in `axis_basis_owned_by_projection`. |
| P3: `docs/NOW.md` conflicted with main `7d547890` | Real. | Merge commit `fb65a0b2`: main's board kept (W26 retired, W27 added, every handoff line), W40's row and handoff line restored. Every other incoming file is main's bytes. Main's new webapp code does not read the overview axes. |

**Residuals.** Both are recorded here and not fixed in W40.
- A snapshot whose `collection_completeness` is absent, failed or unreadable lists no blind spot, so no
  blind-spot qualification applies. Every fleet list has the same limit. A failed completeness phase
  still puts `one_hop_failure_attribution` on every published brief value.
- The device page's `fleet_lists_exclude_blind_devices` text now also mentions the executive axes,
  because the text is shared.

## Reviewed transport-schema delta

A structural diff of the owner, view and list schemas against an extract of main `a06d1d27` finds three
changes each, and nothing else:

1. One added definition, `AxisUnassessed`: a closed `{n, of}` record, both members `$ref`s to the
   existing `CountFact`. It is added to the owner `$defs` and to the view and list `$defs`.
2. `AxisItem` gains the required property `unassessed`, a `$ref` to `AxisUnassessed`.
3. No `oneOf` view or list branch changes. No definition is removed or reordered.

The review fixes change no schema: limitation texts and `applies_to` lists are instance data, and no
enum, definition or tuple length moves.

**Keywords.** The added definition uses only `$ref`, `additionalProperties`, `properties`, `required`,
`title` and `type`. Every one of them is already in main's view and list profile.

**Instance domain.** Every new value is an integer count, a string or null. So
`_native_instance_allowed`, the provider version (`jsonschema-rs` 0.58.5), the private resolver guard and
the Python fallback are unchanged.

**Hashes.** The hashes are compact `ensure_ascii` JSON plus LF, in owner key order. They were computed
statically with `ui_projection_api._native_schema_hash` on `_VIEW_SCHEMA` and `_LIST_SCHEMA`. Both
`backend.ui_projection_api` and `cisco_toolkit.ui_projection` were imported from this worktree, with
`__file__` asserted. No test, validator or projection ran.

- **Method check.** The same script on a `git archive` extract of main `a06d1d27` reproduces main's
  pins:
  - view: `732c68c3d762f2b3d4d0329582bd32f3842567feef9cab20960f6959eef07372`
  - list: `7f256f809f1d9e0754a2312579ee6afdfe3ae5e58c2b5dd7b44fbfd32b5369b5`
- **W40.** These are in `_NATIVE_SCHEMA_HASHES` and in the W12b prospective pair. After the review fixes
  the same script on the fixed worktree computes them again, unchanged:
  - view: `f782eaa0f1f76a760b770a3390d4e7cbd4fbcfea92c3b42ab087f548c42d30ae`
  - list: `346c838a509ef681f825f8dfd3f38fa1302ad2286550d99502e514cf8f5e2552`

**`openapi.ts`.** It has two hand edits, following openapi-typescript 7.13.0's `--alphabetize`,
`--immutable` output:
- `UiProjection1_AxisItem` gains `readonly unassessed: components["schemas"]["UiProjection1_AxisUnassessed"];`
  after `index`.
- The new `UiProjection1_AxisUnassessed` component (`n`, `of`) sits between `UiProjection1_AxisList` and
  `UiProjection1_AxisValue`.

No enum, limitation tuple or response type changes. The hosted `api:check` decides exactness.

## Overlap with W28 (G08, `claude/trust-inputs`, not merged)

W28 touches the same shared surfaces:
- it moves both native pins;
- it rewrites `openapi.ts`: its 30th payload limitation turns the limitation tuples into arrays;
- it edits the same `measured_zero_mapping` `applies_to` list;
- it adds an `ssot.md` row two rows above this one;
- it edits `docs/NOW.md`.

W40's review fixes also edit `fleet_lists_exclude_blind_devices` (text and `applies_to`) and the
`axis_basis_owned_by_projection` text.

Whichever of W40 and W28 merges second must:
- re-pin on the combined schema;
- regenerate `openapi.ts` from the combined hosted export;
- keep both `applies_to` additions.

The two gaps count different universes and neither restates the other. G08 counts inventory devices whose
risk-register axis is `na`. G05 counts each axis producer's own devices, out of that producer's count.

## Tests written (not run)

**`tests/test_ui_projection_axis_unassessed.py`:**
- **The tables.** They partition the brief axes exactly once and are read-only. Each further layer sits
  in its axis's own producer section.
- **Each entry against its real producer.** The real producer runs on small inputs with an unassessed
  device. The registered count equals the rows carrying the registered value, and the denominator equals
  the row count.
- **Further-layer class guard.** Every per-layer coverage count in a registered producer's real summary
  is a registered further layer or the registered count's complement. A complement's uncovered devices
  stay inside the registered count. The guard must reach `n_version_known`.
- **Sparse counters.** They are exactly the producers that omit a zero entry. A producer run on empty
  input writes every other count as 0.
- **Real producer output through the projection.** Platform capacity's `n` exceeds `n_not_collected`.
  Fleet health equals the owner's unscored rows.
- **Engine-built snapshots.** The shipped sample, with its stored brief, and the golden producer sections,
  with the brief recomputed by the real producer. Neither lists a blind spot.
  - Stored counts are published and agree with the rows, except a count whose further layer shows a
    gap. That count is withheld, with the gap read from the snapshot: both store fewer known versions
    than devices.
  - A measured zero keeps its token.
  - The lifecycle count equals the canonical `n_unknown`.
  - Every other axis is `not_collected`.
- **Further layer, real producer** (`compute_software_risk`), covering the review's P2 fleet:
  - every config and no version: `n` is `not_collected`, the reason names both counts, and a witness
    reference points at `n_version_known`;
  - one version captured: a positive count is withheld too;
  - an unreadable layer count;
  - control: every version captured publishes the measured zero.
- **Blind spot, real producers** with the real `compute_collection_completeness` over files in
  `tmp_path`, covering the review's P1 fleet:
  - an unreached device and, separately, a partial one. No counted axis publishes 0. Every cell carries
    the witness reference. A published cell carries the caveat, and the lifecycle count stays published.
    The whole payload validates.
  - control: the same fleet fully collected publishes the zero, with no caveat;
  - every inventory device unreached: 0 of 0 becomes `not_collected` in both cells. Its control is
    `collected_but_empty`.
- **Failed input.** The review's unregistered-label case, and a failed brief over the sample: block and
  fact are both `analysis_unavailable` with the failure record, and the producer's token stays visible.
- **Closed schema, with forgeries.** The payload validates, and forgeries are rejected.
- **States.**
  - Headline independence.
  - A failed input is `analysis_unavailable` with its failure record.
  - A missing count or section is `not_collected`, with neutral wording.
  - A sparse zero needs its rows.
  - Contradictions are `unverified`: a count above its denominator, a layer count above it, a flipped
    row, an unreadable row or a dropped row.
  - No rows: published as stored.
  - Zero over zero: `collected_but_empty`.
  - An unscored fleet counts every row.
  - An unreadable label is `unverified`; an unregistered label is `not_collected`.

**`webapp/tests/test_ui_projection_api.py`:**
- A native/stock parity test covers the overview transport. It checks the real sample's rows, including
  published and `not_collected` blocks, against seven rejected shapes.
- The updated W12b prospective pins.

Existing guards cover the extended limitation `applies_to`: payload-wide caveat coverage and pointer
resolution.

## Static evidence

- `py -3.12 -m py_compile` of every touched Python file.
- `ruff check` (the repository's `ruff.toml`) on `cisco_toolkit/ui_projection.py` and the test file.
- The static helpers of `tests/test_protocol_assessability.py`, with this worktree pinned at
  `sys.path[0]`:
  - `_hand_listed_state_collections` finds no site in `cisco_toolkit/ui_projection.py`;
  - `_assert_section_dependency_reader` passes on `cisco_toolkit/ui_projection.py`.
- An AST scan finds no local binding shadowing a module-level name in any new or changed function. The
  three remaining whole-module hits (`_typed`, `_tokens` parameters) are on main unchanged.
- The pin computation above, unchanged by the review fixes.
- `.github/scripts/verify_repository_privacy.py --root <worktree>` passes. A marker scan over
  `git log -p -m origin/main..HEAD` and the staged diff, with
  `distribution_verify._client_marker_patterns()` imported from this worktree, finds nothing.

## Not done here

- **UI rendering.** No page renders the counts yet. The Overview axis panel needs a later slice with a
  hosted SPA build.
- **The dated status record.** `docs/one-app-contract-gaps-status-2026-10-08.md` is unchanged. It records
  `a816bfca`, and earlier slices left it as written.

## Verification boundary

Still required before merge:
- every protected exact-head hosted check, including the native-parity group and `api:check`;
- independent refutation;
- the supervisor's merge.
