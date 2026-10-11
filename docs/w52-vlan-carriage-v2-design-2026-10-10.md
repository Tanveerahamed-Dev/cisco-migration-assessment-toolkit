# W52 / G14 carriage v2 design (2026-10-10)

Answers the PR #646 refutation; line numbers at head `b318237a`.

## (a) Bundle PVST

**Defect.** `_Inputs.end` joins PVST roles on the physical member (`cisco_toolkit/vlan_carriage.py:310-312`).
IOS and NX-OS report the logical PoN, so a blocked LAG falls through to member allowance (`:326-334`) and is
published as `forwarding`.

**v2 rule in `end`:**

1. `channel = _channel(port_channel)` (`:114-121`). An unparsable, non-blank `port_channel` holds
   `interface_unreadable`; today it is only censused (`:461`).
2. A bundled member supplies identity only (`:289-294`).
   - PVST rows are those where `_channel(row.interface) == channel`.
   - `_channel` on both sides, never `_port` (a probe: `_port("port-channel015")` is `Po015`).
   - Allowance and `switchport_mode` come from the unique channel record.
3. Hold, and never fall back to member allowance, in these cases:
   - a role row exists for the physical member as well as for the channel (`role_ambiguous`);
   - the channel row is incompatible (`:318-321`);
   - the observation is unpublished (`:308-309`).
4. With no channel row, use the channel's allowance. With no channel record, hold `no_evidence` (not_collected).
5. Cite the observation only as basis or absence witness.
6. Index roles once per host by `(namespace, instance, joined interface)`. Today's scan per end is
   O(V×ends×roles) (`:310`).

**Projection.** `_carriage_basis_gaps` (`cisco_toolkit/ui_projection.py:4853-4863`) matches the stored
`stp_interface`: the end port or the cited record's channel.

**Folded P3.** The local code list (`vlan_carriage.py:213-216`) becomes a `stp_topology`-owned
`ROLE_EVIDENCE_INTEGRITY_CODES`. It adds `role_evidence_missing` and `state_instance_missing`
(`cisco_toolkit/stp_topology.py:89-99`), and a test classifies every code.

**Controls**, through `parse_show_interface_trunk_table`, `cisco_toolkit/build.py:1339-1349` and
`compute_cable_map` (`cisco_toolkit/analyze.py:443`):
- NX-OS members with the Po in BLK give stp_blocked or held.
- IOS members with the Po in FWD on both ends give typed forwarding.
- An NX-OS Po allowing 10,20, with members allowing 1-4094 and no row for VLAN 30, gives not_carried.

## (b) Bounded stored model `vlan_carriage/2`

`origin/main` has no carriage; the bump touches only `docs/ssot.md:47` and
`tests/test_ssot_failed_phase_abstention.py:80,91`.

```
{schema, state, reason, basis, limitations,
 code_tables: {verdict: VERDICT_CODES, end: END_CODES},  # = owner tuples
 coverage: {vlan_rows, cable_rows, assessed_cables, edge_cables, unreadable_cables,
            requested_pairs = vlan_rows*assessed_cables, emitted_pairs, by_state,
            input_census_complete, capture_completeness_claim: false},
 issues: [{state, reason, pointer}],                           # VLAN-independent
 cables: [{index, pointer, scope: assessed|edge|unreadable, hold, ends,
           members: [{index, pointer, a: END, b: END}]}],      # once per cable
 rows:   [{vlan_index, vlan, vlan_pointer, hold, state, reason, codes}]}
END = {host, port, interface_pointer, stp_interface, stp_pointer, allowance_pointer, refs, hold}
```

**Codes.**
- `codes` is one string per VLAN. For each assessed cable in order, it holds one cable character, then three
  characters per member: member, a-end, b-end.
- Each character indexes a closed owner alphabet:
  - `VERDICT_CODES`: the 7 published relation×basis pairs, plus the held reasons.
  - `END_CODES`: the 4 signals, plus the held reasons.
- State and evidence shape are functions of the code, as the `_ISSUES` prefixes are today (`:41-74`).
- One line under the sample's `indent=2` (`webapp/sample_data/build_sample.py:701`).
- Typed role refs are not stored per VLAN. Producer and projection share one owner join,
  `carriage_role_rows(observation, stp_interface, vid)`.

**Scopes.**
- **Edge.** A cable with an end host that is not a scanned `interfaces` key, as in the cable map's own `collected` test
  (`analyze.py:573`).
  - The far port is kept as text. This fixes P3 `vlan_carriage.py:410`: AP `Gi0` and phone `Port` fail `_port`.
  - An edge cable gets no codes. It is counted in `coverage.edge_cables`.
- **Unreadable.** The cable carries one verdict and no codes.
- **Held rows.** An invalid VLAN row, or a failed `cable_map` or `vlan_cutover` source, sets `hold` and stores
  `codes == ""`.

**Coverage honesty.**
1. Absent is not healthy. A missing or failed source holds every row (`vlan_carriage.py:436-451`).
2. Edge cables are blind spots. They are not_collected: counted, never omitted, never published.
3. A VLAN's `state` is the `_HOLD_PRECEDENCE` (`:28`) over:
   - source-level issues;
   - unreadable cables;
   - its own hold and codes.

   It is never inherited from an unrelated cable. This fixes P3 `ui_projection.py:4994-5003`.
4. The section state stays the precedence over everything (`vlan_carriage.py:556-560`).

**Validator.** `validate_vlan_carriage` (`:573-734`) runs in O(V×C′) characters. It checks:
- the closed keys and code tables;
- index alignment;
- code length `Σ(1+3·m)` and the alphabet;
- cable ⇐ member ⇐ end consistency (as at `:680-707`);
- the census and the state precedence.

**Readers.**
- Producer: `COLLECT_PARSE_V3_23_0.py:5126-5129,5369`.
- Phase map: `cisco_toolkit/ssot.py:444,505-506`.
- Projection: `ui_projection.py:4787-5004,5843,5913`.
- Module census: `master-reference/governance/architecture.json:98`.
- Tests: `tests/test_vlan_carriage.py`, `tests/test_ui_projection_vlan_carriage.py`,
  `tests/test_pipeline_{failopen,inprocess}.py`, `webapp/tests/test_ui_projection_api.py`,
  `webapp/frontend/src/test/projectionFixtures.ts`.
- Scope: none (f).

## (c) Projection

`selections.carriage` cannot be paged in place: `_list_catalog` never enters row items
(`webapp/backend/ui_projection_api.py:699-711`), and a top-level V×C′ list still caches V×C′ facts. Hence a cached
summary plus a lazy page.

- **Summary.** `VlanSelections.carriage` (`ui_projection.py:8634-8637`) becomes a closed `CarriageSummary`:
  `{state, reason, refs, caveats, qualify, vlan_index, assessed, forwarding, stp_blocked, not_carried, held,
  edge_not_collected}` (CountFacts).
  - Counts publish only when the section validates and joins; otherwise they carry the source state, never zero.
  - Its refs are O(1): `/vlan_carriage/rows/<vi>` and `/vlan_carriage/coverage`.
- **Lazy page.** `GET /api/snapshots/{id}/ui-projection/inventory/carriage?vlan_index&offset&limit`, with limit at
  most `MAX_PAGE_SIZE` = 200 (`ui_projection_api.py:35`). It mirrors the path route (`:886-910`):
  - `project_vlan_carriage` sits beside `project_path` (`ui_projection.py:8099`).
  - `CarriageDocument` sits beside `PathDocument` (`:8864`).
  - The wrapper sits beside `webapp/backend/engine.py:43`.
  - It is Python-validated, like `_PATH_VALIDATOR` (`ui_projection_api.py:779-780`). There is no native profile.
  - Items reuse `CarriageRow/Member/End` (`ui_projection.py:8623-8633`).
  - It echoes the summary; the client refuses drift.
  - It reads the cached snapshot read-only and deep-copies only the result; a test proves no mutation.
  - Basis-gap checks run once per digest.
- **Native pins.** Both pins (`ui_projection_api.py:484-489`) move, because `$defs` feed both schemas (`:769-771`).
- **openapi.ts.** Drop `CarriageList` from VlanSelections (`webapp/frontend/src/generated/openapi.ts:6601`). Add
  `CarriageSummary`, `CarriageDocument`, the route and the operation.
- **CoreSnapshot.** `webapp/frontend/src/pages/CoreSnapshot.tsx:260-276` shows the summary and a pager.
  - The pager uses a new `loadCarriagePage`, beside `loadPathProjection` (`webapp/frontend/src/projection.ts:98-116`).
  - It applies the same identity, engine and limitations guards.
- **Vocab bijection.** No new token set: values decode to `_VOCAB_UNRANKED` (`ui_projection.py:8298-8301`). The test
  walks every `$def` (`tests/test_ui_projection_vocab.py:72-80,166-171`).

## (d) Blank allowance and literal none

- **P2.** Delete `allowed = True` (`vlan_carriage.py:301-304`). A native match only witnesses `evidence_conflict`.
  A blank list falls through to `no_evidence` (`:335`).
- **Parser.** `allowed_vlans` stays `''` (`cisco_toolkit/parse.py:2838`), and the parser adds
  `allowed_literal = "none"`. `build.py:1347` stores it in a new `InterfaceData.trunk_allowed_none`
  (`cisco_toolkit/model.py:40`).
  - Sparse persistence drops blanks (`cisco_toolkit/html.py:3371-3372`).
  - The field censuses are subset checks (`tests/test_parsers.py:676-677`, `tests/test_ui_projection_inventory.py:1304`).
  - Carriage adds the field to `_INTERFACE_FIELDS` (`vlan_carriage.py:77-78`) as an exclusion. Two non-blank
    fields hold `range_unreadable`.
  - `record_readable` imports that tuple. This fixes P3 `ui_projection.py:4843-4845`.
- **Folded P3** (`parse.py:2802`). A `Port …` header whose first token is not an interface closes the allowed
  section. A probe at head showed NX-OS `STP Forwarding` rows overwriting a literal `none` with `1,20`.

## (e) Budgets

The new file is `tests/test_vlan_carriage_budget.py`.
- **Fleet:** 300 devices, 200 VLANs and 1,500 cables (600 assessed, including 150 two-member bundles; 900 edge).
  It is built through the real producers from synthetic text.
- **Probe:** a scratch encoding probe (no repository code) measured 3.0 MB; v1 at 2,016 B/pair: ~605 MB.

| Measure | Budget |
|---|---|
| Stored section, compact JSON | ≤ 6,000,000 B |
| Section bytes, V=200 minus V=100 | ≤ 600,000 B |
| One `CarriageSummary` | ≤ 4,096 B, identical for C′=300 and 600 |
| Inventory document growth | ≤ 1,000,000 B |
| `compute_vlan_carriage` | ≤ 3,000 ms |
| `validate_vlan_carriage` | ≤ 1,500 ms |
| First document build and validation, growth | ≤ 2,000 ms |
| One 200-row page | ≤ 300 ms and ≤ 3,000,000 B |

Bytes are exact; milliseconds are hosted Linux 3.12 ceilings; the first hosted run is findings.

## (f) Atlas Scope

Scope does not consume carriage:
- `SECTIONS_READ` (`atlas-scope/tools/lib/compile-model.mjs:163-184`) lacks it.
- Interface fields are read by name (`:1406-1407`).
- No fixture prints `none` (`build_sample.py:215,277`).

Re-bind only, from `scope-compiler-handoff` (`docs/engine-output-handoff.md:114-119`):
- `GOLDEN_SHA` (`atlas-scope/src/test-support/golden-sample.ts:23`);
- the bindings in `atlas-scope/src/panels/producer-emission.json:6-9`, `atlas-scope/src/data/fabric.json` and
  `atlas-scope/src/forwarding/{acl-bindings,rib-evidence}.json`.

## (g) Route P3s

- **Skip.** Drop `BOUND_POLICY` (`tests/test_engine_output_handoff.py:54-55`; seven uses at `:1068-1150`). Rewrite
  `docs/engine-output-handoff.md:319-320`.
- **Filter ordering.** Add tests with a clean filter that writes a sentinel, on a stat-dirty file. They expect
  `unsupported filter`, no sentinel and `api.calls == []` (`.github/scripts/engine_output_handoff.py:847-848,1403-1404`).
- **Replace refs.** For `--no-replace-objects` (`:339`), plant `git replace HEAD <other>` and assert that the real
  tree binds.
- **Closing status.** Call `source_index` before the closing status (`:1452-1453`), as `_closed_effect` does (`:899`).
- **Escapes.** `check_output_bytes` (`:812-821`) also scans `json.dumps(value, ensure_ascii=False)`.
  `.github/scripts/verify_repository_privacy.py:1283-1292,1447-1457` adds a `\uXXXX`-decoded pass.
- **Custody.** Record the held sample's custody as history in `docs/w52-vlan-carriage-validation-2026-10-09.md:302-319`:
  run `37925393797`, artifact `11613324695`, a pre-W54 download bound at content level.

## (h) Regeneration

**2026-10-11 continuation:** the full #646 findings also require resolved third-party producer
dependencies to be bound. The source continuation records canonical name/version/ordinary RECORD
digests before and after generation and carries their equal, closed ledger into the hosted receipt.
This is metadata observation, not authenticated package or recursive installed-file custody. The
stdlib-only receiver verifies the producer ledger; its different environment is not compared.
Current hosted execution and receipt/import verification remain mandatory. Detailed outcomes are
recorded in `w52-v2-validation-2026-10-11.md`.

1. Commit; pass the privacy and marker gates; push (owner authority).
2. Adopt `openapi.ts` (`api:check`, `.github/workflows/webapp-ci.yml:307`) and the pins from `ui-projection-contract`
   (`:296-303`).
3. Run the producer, then the receipt (`docs/engine-output-handoff.md:46-81`). Expect changes to `vlan_carriage`,
   two module counts and `generated_at`.
4. Import with Git and check the blobs (`:83-99`).
5. Run `verify_import` (`:101-112`). This is its first hosted execution, so treat it as findings.
6. Re-measure the W50 pairs (`tests/test_operator_evidence_contract.py:121-132`) from the hosted output. Re-measure
   the LF scope (`tests/fixtures/atlas-r2-byte-custody-policy.v1.json:32-34`) if the scope changes.
7. Re-bind Scope (f) and import the hosted SPA (`webapp-ci.yml:320-324`).
8. Update `docs/ssot.md:47` and the W52 record.

Out of scope: legacy native inference in `analyze.py:980-983`.
