# W40 per-axis could-not-assess denominators (G05) validation

Branch `claude/g05-axis-denominators`, started from main `a06d1d27`. This record covers gap G05 of
`docs/one-app-contract-gaps-2026-09-30.md` (section 18): for each executive axis, how many devices it
could not assess, out of how many.

Each `overview.axes.items[]` row now carries `unassessed = {n: CountFact, of: CountFact}`. Both facts are
read from the axis's producer, never from the brief's headline text. No engine section, sample or golden
changes, and no new toolkit module or limitation ID is added.

This is a source checkpoint. No local test, build, OpenAPI export, type check, projection or browser run
was made, because the owner's rule is GitHub-hosted only. Every runtime verdict is pending hosted evidence.

## What each axis reads

The table is `cisco_toolkit.ui_projection.AXIS_UNASSESSED` (stored counts),
`AXIS_UNASSESSED_LIVE` (Fleet health) and `AXIS_UNASSESSED_ABSENT` (no stored count). The three tables
partition the registered brief axes exactly once.

| Axis | `n`: could not assess | `of` | Raw basis the count is held against |
|---|---|---|---|
| Hardware lifecycle (EoL) | `lifecycle_risk.summary.n_unknown` | `lifecycle_risk.summary.n_devices` | `lifecycle_risk.per_device[].band == "Unknown"` |
| Operational logs | `syslog_intelligence.summary.n_not_collected` | `syslog_intelligence.summary.n_devices` | `per_device[].collected == false` |
| QoS posture | `qos_audit.summary.n_not_assessable` | `qos_audit.summary.n_devices` | `per_device[].assessable == false` |
| Software risk | `software_risk.summary.n_config_not_assessable` | `software_risk.summary.n_devices` | `per_device[].config_assessable == false` |
| Platform capacity | `platform_health.summary.bands.Unknown` | `platform_health.summary.n_devices` | `per_device[].band == "Unknown"` |
| Asset risk register | `device_dossiers.summary.bands.Unassessed` | `device_dossiers.summary.n_devices` | `per_device[].risk_band == "Unassessed"` |
| Fleet health | `ssot.fleet_avg_health` `n_rows` minus `n_scored` (live) | `n_rows` (live) | the owner counts the health rows itself |
| Migration punch-list, Application domains, Cutover sequence, Segmentation, Multicast / timing, Remediation | `not_collected`, never 0 | `not_collected` | the producer stores no per-device count |

## Coverage-honesty rules

- **Failed input.** A failed producer phase makes both facts `analysis_unavailable`, with a
  `failure_record` reference. This also applies to an axis with no stored count when its input failed.
- **Contradicted count.** Both facts are `unverified`, with witness references, when:
  - the count exceeds its denominator;
  - the producer's per-device rows disagree with the count or the denominator;
  - the rows cannot be read (not a list of records, each carrying the field with the right type).
- **No raw basis.** When a snapshot carries no rows, the stored summary is published as it stands. This
  follows the `reconcile_checks_only_with_raw_basis` precedent.
- **Missing count.** A count missing from a summary its producer wrote is `not_collected`, never 0.
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
- **Unreadable label.** An axis row with no readable label is `unverified`. An unregistered label is
  `not_collected`.

## Design decisions

- **Platform capacity counts the `Unknown` band, not `n_not_collected`.** The producer also bands a
  device `Unknown` when its capacity output was collected but no figure was recognised. So
  `n_not_collected` would undercount the devices the axis could not assess. A real-producer test holds
  a fleet where the two differ.
- **Software risk counts its running-config layer only.** The producer stores that layer's
  not-assessable count. The software-version layer is counted apart (`n_version_known`), and no single
  stored count spans both layers. The limitation text says so.
- **Fleet health reuses the fleet-health block's live counts.** `_fleet_health_count` is extracted
  unchanged from `_fleet_health`. So the axis's `of` is the same owner value as
  `overview.fleet_health.n_rows`, and `n` is the brief's own unscored rows.
- **The lifecycle count is the canonical fact.** `n_unknown` is also `overview.facts.n_unknown`, and the
  test holds the two equal. `ssot.reconcile` still applies to both.
- **No new limitation ID.** The existing `axis_basis_owned_by_projection` limitation now states the G05
  table, its checks and its scope. Its `owner` names `AXIS_UNASSESSED` as well.
  - A 30th payload limitation would turn every 29-item limitation tuple in `openapi.ts` into an array.
    W28 makes exactly that change, so adding one here would double the conflict.
  - The texts are instance data, not schema.
- **No transport envelope change.** The block sits inside the owner `AxisItem` definition. Atlas Scope
  reads only the topology and path envelopes, and neither changes.

## Reviewed transport-schema delta

A structural diff of the owner, view and list schemas against an extract of main `a06d1d27` finds three
changes each, and nothing else:

1. One added definition, `AxisUnassessed`: a closed `{n, of}` record, both members `$ref`s to the
   existing `CountFact`. It is added to the owner `$defs` and to the view and list `$defs`.
2. `AxisItem` gains the required property `unassessed`, a `$ref` to `AxisUnassessed`.
3. No `oneOf` view or list branch changes. No definition is removed or reordered.

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
- **W40.** These are now in `_NATIVE_SCHEMA_HASHES` and in the W12b prospective pair:
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

Whichever of W40 and W28 merges second must:
- re-pin on the combined schema;
- regenerate `openapi.ts` from the combined hosted export;
- keep both `applies_to` additions.

The two gaps count different universes and neither restates the other. G08 counts inventory devices whose
risk-register axis is `na`. G05 counts each axis producer's own devices, out of that producer's count.

## Tests written (not run)

**`tests/test_ui_projection_axis_unassessed.py`:**
- **The table.** It partitions the brief axes exactly once and is read-only.
- **Each entry against its real producer.** The real producer runs on small inputs with an unassessed
  device. The registered count equals the rows carrying the registered value, and the denominator equals
  the row count.
- **Sparse counters.** They are exactly the producers that omit a zero entry. A producer run on empty
  input writes every other count as 0.
- **Real producer output through the projection.** Platform capacity's `n` exceeds `n_not_collected`.
  Fleet health equals the owner's unscored rows.
- **Engine-built snapshots.** The shipped sample, with its stored brief, and the golden producer sections,
  with the brief recomputed by the real producer:
  - stored counts are published, and agree with the rows;
  - a measured zero keeps its token;
  - the lifecycle count equals the canonical `n_unknown`;
  - every other axis is `not_collected`.
- **Closed schema, with forgeries.** The payload validates, and forgeries are rejected.
- **States.**
  - Headline independence.
  - A failed input is `analysis_unavailable` with its failure record.
  - A missing count or section is `not_collected`.
  - A sparse zero needs its rows.
  - Contradictions are `unverified`: a count above its denominator, a flipped row, an unreadable row or a
    dropped row.
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
- The static helpers of `tests/test_protocol_assessability.py`, with this worktree pinned at
  `sys.path[0]`:
  - `_hand_listed_state_collections` finds no site, in `cisco_toolkit/ui_projection.py` or in any
    scanned file;
  - `_assert_section_dependency_reader` passes on `cisco_toolkit/ui_projection.py`.
- An AST scan finds no local binding shadowing a module-level name in the new code. The four remaining
  hits (`_typed`, `_tokens` parameters) are on main.
- The pin, method-check and structural-delta computations above.
- `.github/scripts/verify_repository_privacy.py --root <worktree>` passes. A marker scan over the commit
  patch and message, with `distribution_verify._client_marker_patterns()` imported from this worktree,
  finds nothing.

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
