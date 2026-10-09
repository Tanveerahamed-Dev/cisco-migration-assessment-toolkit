# W28 Trust analysis-input gap summary (G08) validation

Started from main `a97fdfc9` on `claude/trust-inputs`. This is a source checkpoint:
no local test, build, OpenAPI export, type check, browser or performance run was made
(GitHub-only doctrine). Every runtime verdict below is **pending hosted evidence**.

## What is published

`trust.inputs` is an ordered array with one row per analysis input:
`{input, sections, n: CountFact, of: CountFact, hosts: TrustInputHostList}`. Each host
item is `{host, custody, label, pointer}`. There is no stored engine section, sample,
golden or new toolkit module, and none was regenerated.

- **Registry.** The inputs are `analyze.DOSSIER_AXIS_INPUTS`, imported rather than
  copied (`ui_projection.TRUST_INPUTS`). This is the engine's closed per-device axis
  registry and their input sections, in owner order.
- **Custody.** For every device row, `analyze.compute_device_dossiers` writes exactly
  one exposure per registered axis. Its `ax()` forces state `na` whenever the input was
  not published, so a device is listed exactly where its single exposure for the axis is
  `na`. Its custody keeps the engine's `input_state`: not collected, analysis
  unavailable, or collected but empty (for example, no authoritative lifecycle band).
- **Blind spots.** A `collection_completeness` device marked "not collected", matched by
  its owner's device scope, is listed under every input whatever its register row says.
  The witness pointer is its blind-spot row.
- **Missing or malformed rows.** A missing, duplicated or malformed register row or
  exposure makes the input `unverified` and lists the device with `custody: unverified`.
  `na` over published custody contradicts the producer and is also `unverified`. A
  missing row becomes `analysis_unavailable` instead when the lifecycle phase that
  guarantees every device a row failed, and the row carries that failure record.
- **Denominator.** `of` is the inventory count that the device rows reconcile to. The
  inventory screen's total uses the same helper, `_inventory_universe` /
  `_inventory_total`, refactored out of `_device_rows` without changing behaviour. A
  withheld denominator withholds `n` and `hosts`.
- **Failures.** A failed register or input phase makes the row `analysis_unavailable`
  with its failure record. A missing `collection_completeness` makes the list
  `not_collected` ("may be incomplete"). A missing register lists only blind spots,
  as `not_collected`.

## Owner evidence (line numbers at `a97fdfc9`; they will drift)

- Registry: `cisco_toolkit/analyze.py:12522` (`DOSSIER_AXIS_INPUTS`) and `:12535`
  (`DOSSIER_EMPTY_IS_CLEAN`).
- One exposure per axis, `na` off published custody: `analyze.py:12704-12714` (`ax`).
  Every axis literal in the producer equals the registry, which the new test checks
  through the AST.
- Every devices-map device gets a register row:
  - The register host universe includes `lifecycle_risk.per_device` (`analyze.py:12696`).
  - `compute_lifecycle_risk` writes one row per device (`analyze.py:11852`).
  - Both its input and the devices map come from the same device-physical list:
    `COLLECT_PARSE_V3_23_0.py:4714-4716` and `cisco_toolkit/html.py:3352`.
  - The stored register is `snap_dict["device_dossiers"]` (`COLLECT_PARSE_V3_23_0.py:5371`).
- Blind spots and the inventory count: `analyze.py:1839-1876`. The owner lists only
  partial and not-collected devices (`:1872`), and its device scope is
  `ssot._device_not_collected`.

## Sparse and findings-only sections: excluded, with proof

The fold never reads these sections to decide that a device is absent. Absence in them is
neither a gap nor clean. Instead, the register's own custody decides: G49 receipts, the
capture-precedence rule and failure marking.

- **`security` and `config_hygiene`** are per-device stores with `keep_always=False`, so
  a device whose builder returns nothing gets no row (`COLLECT_PARSE_V3_23_0.py:3343-3349`
  and `:3422`).
- **`physical_health`, `protocol_health`, software findings and syslog detections** are
  findings lists, which the register indexes as findings (`analyze.py:12665-12687`).
- **`cross_layer` and `l3_forwarding`** are no input at all.

The test empties every sparse section and requires an identical `trust.inputs`.

## Closed schema and native review

The delta adds `TrustInput`, `TrustInputHost` and `TrustInputHostList`. It adds the
required `Trust.inputs` property (`minItems` = `maxItems` = 11) and one limitation,
`trust_inputs_scope`. `one_hop_failure_attribution` and `measured_zero_mapping` now also
address `/trust/inputs`. No definition is removed.

The new definitions use only these keywords, all already present in the established view
and list profile: `$ref`, `additionalProperties`, `anyOf`, `const`, `dependentRequired`,
`enum`, `items`, `maxItems`, `minItems`, `minLength`, `oneOf`, `properties`, `required`,
`title`, `type` and `uniqueItems`.

The transport list catalog is unchanged, because `inputs` is an array and not a paged
FactList. Its nested `hosts` lists ride whole.

Literal audit pins use compact ensure-ASCII JSON plus LF, in owner key order. They were
computed statically with `ui_projection_api._native_schema_hash`:

- view: `081929d800e1da79a5e2d9234b433f6eba1924039a1eeaa8e013cb641b010e8e`
- list: `66cd55b411e600618c40b975bf48a753c951391e7459c718c7ad63acaa1b7abd`

The W12b test's prospective pin pair moves with them. **Combined re-pin:** #616 (W23)
and #617 (W24) also change this schema. Whichever of #616, #617 and this branch merges
later must recompute both pins, and the prospective pair, on the combined schema. It
must also regenerate `openapi.ts` on that combined schema; none of the three pin sets
is valid for the combination.

## Generated types and fixtures

`webapp/frontend/src/generated/openapi.ts` was hand-edited to what openapi-typescript
7.13.0 emits with `--array-length --alphabetize --immutable`.

- **Rule read from the installed generator source:** a tuple is emitted only while
  `(max*(max+1) - min*(min-1))/2 < 30`. When `min == max == n`, that means n < 30.
- **Effect of the 30th limitation:** the Trust limitation registry now has 30 entries,
  so all 27 of its 29-entry tuple copies become `readonly ...Limitation[]`. These
  copies sit in the Trust definition, the trust payload and every non-device
  view/list/path response.
- **Unchanged:** the device-document registry (15 entries).

An inverse transform reproduces the committed original byte-for-byte. The hosted
`api:generate --check` remains the authority.

`trustFixture` gains 11 withheld rows in the contract's shape. No receipt state is listed
there, and the static scan is clean.

## Frontend and distribution impact

No runtime frontend source changed. The Trust screen does not render `inputs` yet. That
requires a runtime change in `CoreSnapshot.tsx` and a hosted distribution rebuild, which
are left as a follow-up. `openapi.ts` is type-only and the fixture is test-only, so the
tracked `webapp/frontend/dist` is expected to be byte-identical. Hosted evidence must
confirm this.

## Combined with W23 (main `d0e10888`)

#616 (W23) merged as `d0e10888`. W23 added `DevicePage.failure_impact` and `structural_links`,
the impact holds, and device limitations growing from 15 to 18. This branch merged that main
with a merge commit and re-pinned on the combined schema. The W28-only pair above
(`081929d8…`/`66cd55b4…`) is superseded.

**Merge consistency.** `cisco_toolkit/ui_projection.py`, `openapi.ts` and the fixtures merged
without conflict, and each merged delta over main equals this branch's own delta. W23 adds no
limitation ID, so:
- `LIMITATIONS` has 30 entries, and the Trust registry and all 27 non-device copies stay
  `readonly Limitation[]` arrays.
- The device registry now has 18 entries, still rendered as tuples (18 < 30), in all 20 device
  copies. These include W23's two new device list variants.
- `trust_inputs_scope` is not device-cited, so the device document's order still equals W23's
  hand-written list.

**Delta over main.**
- Added definitions: `TrustInput`, `TrustInputHost` and `TrustInputHostList`.
- `Trust` gains the required `inputs` property.
- `LimitationId` grows from 33 to 34 IDs.
- Every Trust-limitation copy grows from 29 to 30 (`minItems` = `maxItems`).
- No definition is removed, and no device or topology definition changes.

The added parts use only keywords already in main's view and list profile: `$ref`,
`additionalProperties`, `allOf` (the existing payload wrapper), `anyOf`, `const`,
`dependentRequired`, `enum`, `items`, `maxItems`, `minItems`, `minLength`, `oneOf`,
`properties`, `required`, `title`, `type` and `uniqueItems`.

**Hashes.** These are compact `ensure_ascii` JSON plus LF, in owner key order. They were computed
statically with `ui_projection_api._native_schema_hash`, with the modules imported from this
worktree (`__file__` asserted). As a method check, an extract of main reproduces main's own
pins: view `a2fd2b99…` and list `c47a6cef…`.

The combined W23 + W28 pins are now in `_NATIVE_SCHEMA_HASHES` and in the W12b prospective pair:
- view: `59e4a53fbc475221a8368a25da0aea618b920bf2a4694657a61b56addffac7ec`
- list: `ef3906d3ae6793f589cf1b1bcbaaa433ff84865a16971a19252683a715852c33`

**Second merge (W24 or W28).** W24 (`claude/vocab-rank`, #617, G43) also moves these pins.
Whichever of W24 and W28 merges second must:
- re-pin again on top of the other;
- regenerate `openapi.ts` on that combined schema;
- classify `TrustInputHost.custody` in W24's vocab catalogue.

That custody enum's token set matches no G43 vocabulary, so `tests/test_ui_projection_vocab.py`
v1 would report it unclassified. `TrustInput.input` reuses the `dossier_axis` token set. Neither
pin set here is valid for that combination.

## Combined with W23+W24 (main `366d1ab3`)

#617 (W24, G43 vocab) merged as `366d1ab3` (parents `d0e10888`+`70e4f812`, tree `fbb644eb`). This
branch merged that main with a merge commit and re-pinned on the combined W23+W24+W28 schema. This
is the second merge described above. The W23+W28 pair (`59e4a53f…`/`ef3906d3…`) and main's W23+W24
pair (`732c68c3…`/`7f256f80…`) are both superseded.

**Conflicts.**
- `docs/NOW.md`: board rows and handoff lines.
- `docs/ssot.md`: both new registry rows are kept, G08 before G43.
- The pin pair in `webapp/backend/ui_projection_api.py` and the W12b prospective pair in
  `webapp/tests/test_ui_projection_api.py`: both are replaced by the combined pair below.

`cisco_toolkit/ui_projection.py`, `openapi.ts` and `projectionFixtures.ts` merged cleanly. Before
the cross-PR edits below, the merged `openapi.ts` delta over main equalled this branch's own delta
over `d0e10888`, line for line.

**Cross-PR classification (G43 x G08).** W24's catalogue requires every string enum the schema
publishes to be classified exactly once (`tests/test_ui_projection_vocab.py` v1).
- `TrustInput.input` has the `dossier_axis` token set, which it shares with
  `ExposureValue.axis`. That set is already classified unranked, so it needs no change.
- `TrustInputHost.custody` is a new token set (`TRUST_INPUT_CUSTODY`: collected but empty,
  not collected, analysis unavailable, unverified). It is named once, as the unranked
  `trust_input_custody`, after `withheld_state`. Its tokens are the owner tuple itself, so the
  catalogue entry names no state literal.
- **Why unranked, not ranked.**
  - Every token is an absence: it says why an input did not assess a device. Under W24's rule each
    one would class `undetermined`.
  - The catalogue refuses a ranked vocabulary whose every class is `undetermined`: v4 requires a
    ranked vocabulary to determine some level.
  - No engine owner orders these tokens apart, so a rank would be a presentation order that draws
    no level.
  - W24's own precedent: the superset `withheld_state` and `abstention_state` are unranked
    evidence states, which name why a value is absent and never how severe it is.
  - A gap's weight is its count, `n` out of `of`, not its custody token. An unranked entry carries
    no class, so no custody token can draw `pass`.
- A new test in `tests/test_ui_projection_trust_inputs.py` pins this choice. It requires the tokens
  to equal the owner tuple, the vocabulary not to be ranked, the tokens to be a strict subset of the
  withheld states, and the catalogue entry to name `TRUST_INPUT_CUSTODY` (read by AST).
- **Counts.** The catalogue now holds 19 ranked and 30 unranked vocabularies (main: 19 and 29). A
  static sweep of the combined schema, mirroring v1, finds 57 string enums in 49 token sets. Each
  set is classified exactly once; none is doubled, unclassified or invented. No test pins the
  19/29 counts; only W24's dated note states them, and it stays as its record.

**Delta over main.**
- Added definitions: `TrustInput`, `TrustInputHost` and `TrustInputHostList`.
- `Trust` gains the required `inputs` property, and its limitation copies grow from 29 to 30.
- `LimitationId` grows from 33 to 34 IDs.
- `VocabUnranked` gains the `trust_input_custody` member. Its `limitation_id` member gains
  `trust_inputs_scope`, because its tokens are `_ALL_LIMITATION_IDS`.
- No definition is removed, and the root is unchanged.

**`openapi.ts`.** Two edits go beyond the clean union, both in `UiProjection1_VocabUnranked`:
- The `limitation_id` tokens gain `"trust_inputs_scope"` after `"path_route_model_only"`, the
  same union as `UiProjection1_LimitationId`.
- `trust_input_custody` is inserted, alphabetized, between `topology_weight` and `withheld_state`,
  as a `readonly (...)[]` union of its four tokens.

The tuple rule is unchanged:
- the device registry is 18-item tuples in all 20 copies;
- the Trust registry copies are `readonly Limitation[]` arrays (27);
- `Trust.inputs` is an 11-item tuple.

A static cross-check, not the generator, found:
- every string enum of the combined schema appears in the file as its exact union;
- every `$defs` entry has its `UiProjection1_` component;
- the `VocabUnranked` (30) and `VocabRanked` (19) members are alphabetized and equal the catalogue,
  and each unranked entry is rendered exactly;
- `UiProjection1_LimitationId` equals `_ALL_LIMITATION_IDS` (34).

The hosted `api:check` remains the authority.

**Keywords.** The combined view and list schemas use exactly main's keyword set. No keyword falls
outside the established domain: `$defs`, `$ref`, `additionalProperties`, `allOf`, `anyOf`,
`const`, `dependentRequired`, `enum`, `items`, `maxItems`, `maximum`, `minItems`, `minLength`,
`minimum`, `oneOf`, `pattern`, `properties`, `required`, `title`, `type` and `uniqueItems`.

**Hashes.** These are compact `ensure_ascii` JSON plus LF, in owner key order. They were computed
statically with `ui_projection_api._native_schema_hash`, with the modules imported from this
worktree (`__file__` asserted). As a method check, a `git archive` extract of `366d1ab3`
reproduces main's own pins: view `732c68c3…` and list `7f256f80…`.

The combined W23 + W24 + W28 pins are now in `_NATIVE_SCHEMA_HASHES` and in the W12b prospective
pair:
- view: `6aa9a264cf5622d5eb905f5cace25aa612cbb46437a46eed63ae957baad23745`
- list: `a3021b672f785a76c3d88ae33db58ac487e5fa151d84de69af52949c1cc2df58`

**Local evidence for this merge:**
- `py_compile`;
- the static assessability helpers: the hand-list scan, its self-test, receipt-reader
  classification, and the section-dependency proof with its mutants;
- the static pin, enum and keyword computations.

No pytest, npm, build or snapshot projection ran.

## Verification boundary

Local evidence:

- `py_compile` of the projection.
- The static assessability scans: the hand-list scanner over every scanned file, the
  receipt-reader classification, and the section-dependency proof on `ui_projection.py`.
- JSON reads of the tracked sample and golden snapshots, confirming the producer
  invariants the fold relies on.
- The static pin computation.

The following were written for hosted execution and were **not run**:
`tests/test_ui_projection_trust_inputs.py` and the new native/stock parity test in
`webapp/tests/test_ui_projection_api.py`.

Still required before merge: all protected exact-head checks, the OpenAPI drift check,
Vitest/typecheck, including the stricter Scope-hub build, the unchanged hosted 300 ms
projection gate, and an independent refutation.

## W51 second refutation round (2026-10-09)

The trust inputs read the blind-spot record's one coverage verdict, `_cc_coverage` (read through `_Ctx.cc_coverage`, next to F6's `_cc_universe`) for the gaps their own `collection_completeness` rollup and the inventory total do
not report: a devices list absent from a section the snapshot carries (published clean before), and a summary that
counts an unlisted blind spot or cannot be read. Their witnesses are cited even when a device-scope doubt already
withholds the list; `_R_INPUTS_SCOPE` now names a failed or self-contradictory record among the doubts.
