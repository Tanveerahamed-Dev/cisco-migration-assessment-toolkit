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
