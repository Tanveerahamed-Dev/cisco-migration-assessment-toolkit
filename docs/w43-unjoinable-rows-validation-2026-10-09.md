# W43 unjoinable rows on device pages and in collection completeness (F6) validation

Branch `claude/f6-unjoinable-rows`, started from main `a06d1d27` and merged with main `7d547890`
(#620) for the refutation round below. This record covers the owner item F6. It is a source
checkpoint: no local test, build, OpenAPI export, projection or browser run was made, because the
owner's rule is GitHub-hosted only. Every runtime verdict is pending hosted evidence and
independent refutation.

The first round is described from "What F6 found" to "Residuals". The independent review of
`ee71a03a` and the fixes it led to are in "Refutation round (2026-10-09)" at the end; where the two
differ, the later section is current.

## What F6 found

A device page joins rows to one device by key. Three kinds of join passed over a row they could
not read:

- **`_resolve`'s list join** (`key_field`). This covers the health (`switch`), lifecycle,
  dossier and blind-spot (`collection_completeness.devices`, without case or surrounding space)
  rows.
  - A row that is not an object, or whose key is missing or not text, was skipped.
  - If the device's own row sat beside it, that row was published as the only one.
  - If not, the page read the clean absence "carries no row for this device". For the blind-spot
    record that reads "not a blind spot".
- **The owner's device scope** (`ssot._device_not_collected`, read through
  `ssot.abstention_reason(device=...)` and `_Ctx.cc_row`). It reads only the first readable row
  naming a device and passes over every row it cannot read.
  - A second row naming the device, such as "Core1" and "core1", was never read. The real
    producer writes one row per exact host, so this input is reachable.
  - A row with an unreadable host was never read.
  - A row whose status is outside the owner's vocabulary read as "collected".
  - The page then published the device's values as if its collection were known. It took the
    first row's partial `missing` list as the device's own, which can be another device's list.
- **The inventory universe and the fleet qualifier.** Main has no function named
  `_inventory_universe`; the inventory universe is the devices map plus the blind spots, built
  in `_device_rows`.
  - A blind-spot row whose host cannot be joined vanished from that universe.
  - `_fleet_qualify` counted only rows with a readable status, so a malformed blind-spot row left
    the fleet lists unqualified.

The selections (`_selection_rows`) had the same rule only as an opt-in flag (`strict=True`).
W23 set it on two of the six device-page selections. That is a hand-kept list standing in for
the class.

## The one rule and where it lives

**A key join reads one unique row, or none, from a list it can read in full. Otherwise it is
`unverified`, with a witness to each row it cannot read and to each row that does name the key.
No row is picked, and no absence is claimed.**

- **`_resolve` (`key_field`).** The rule lives inside the join, so every list join follows it.
  The class test reads the members from the projection's own source. There are four today, all
  in `_joins`, and a join added elsewhere fails that test.
- **`_selection_rows`.** The `strict` flag is removed. Every selection applies
  `_unjoinable_rows`, which now also reads a `multi` key list: a key list holding anything but
  text cannot be read in full.
  - So `links`, `native_vlan_mismatches`, `findings` and `endpoints` follow the rule, as
    `failure_impact` and `structural_links` already did.
  - A punch-list row whose `devices` is `[]` names no device. It is readable, not doubted.
- **NRFU device entries.** `_nrfu_block` joins each wave's device entries by exact host. An
  entry it cannot read is witnessed, and the device's case list is `unverified`.
- **The device scope.** `_Ctx.device_scope(section, host)` is now the only reader of the
  owner's answer. A source test pins `device_blind` to that one caller, and `cc_row` to
  `partial_row`, `cc_witness` and the roster check.
  - `device_scope` returns `not_collected` when the owner calls the device a blind spot.
  - It returns `unverified` (`_Ctx.scope_doubt`) when the owner does not, but cannot be trusted
    to say so. That is the case when `collection_completeness.devices` holds:
    - a row the host join cannot read;
    - two or more rows naming the device under the owner's key rule; or
    - a row naming the device whose status is not one of `CC_STATUSES`.
  - Otherwise it returns `None`.
  - Its consumers are `_resolve`, `_device_gap`, `_selection_rows`, `_device_finding_rollup`,
    `_nrfu_block` and `_address_observations`. A source test requires at least five.
  - `_Ctx.partial_row` reads the device's partial row only when the scope is not in doubt.
    `_device_gap` and `_health_caveat` take it from there, so no page reads another device's
    `missing` list.
- **The inventory universe.** A blind-spot row the host join cannot read makes the inventory
  rows `unverified`, with a witness to it. The rows already listed stay. The reconciled
  inventory count (`_matches_rows`) is `unverified` with the same witness, because the rows
  cannot be reconciled with the owner's count.
- **The fleet qualifier.** `_Ctx.unread_blind_rows` lists every blind-spot row that
  `blind_rows` cannot read as a partial or not-collected device. Each such row qualifies the
  fleet lists under the existing limitation `fleet_lists_exclude_blind_devices`, with a witness,
  so an empty list is `not_collected`. The existing qualification text (`_R_FLEET_BLIND`) is
  unchanged.
- **An unknown host.** The roster lists (blind spots, cable-map nodes) are key joins too. While
  either holds a row it cannot join, a host no readable roster names is `unverified`, not "no
  roster names this device". The page stays bare, so the reason carries the count. *(Superseded:
  the forced page now also cites each such row; see the refutation round.)*
- **Path hop evidence.** `_path_hop_evidence` now carries its `_resolve` row's own witnesses
  (a blind-spot row, or the doubt's rows). Before, it dropped them.

### Precedence

The order follows `_resolve`, `_selection_rows` and W23:

1. Forced: an unknown or non-text host.
2. The owner's blind spot, `not_collected` in owner order, ahead of failures.
3. A failed or faulted section.
4. An uncollected section.
5. A wrong container.
6. The device-scope doubt, `unverified`.
7. The join itself: unreadable, absent or ambiguous.

The doubt qualifies only the owner's negative answer. A device the owner calls not collected
keeps `not_collected` on every value the scope governs. Its own blind-spot record is a key join
over the same list, so beside an unreadable row that record is `unverified`, with both witnesses.

In a selection or a finding rollup, `unverified` outranks a capture gap, and the gap's reason
and witness are carried beside it. That is the W23 rule.

## Effect on stored data

Read with `json.load`; nothing was projected.

- `webapp/sample_data/sample_fleet.snapshot.json`:
  - `collection_completeness.devices` is `[]`.
  - The health, lifecycle, dossier, cable, trunk-native, endpoint, punch-list, failure-impact,
    link-centrality, cable-node and NRFU device lists hold no row these joins cannot read.
  - Its one punch-list row with `devices: []` stays readable.
- `tests/golden/snapshot.json`: the same holds. It has no `lifecycle_risk.per_device`.

So no sample or golden value changes, apart from three limitation texts: `row_selection_by_exact_key`,
`fleet_lists_exclude_blind_devices` and `projection_owned_verdicts`. Texts are instance data. No
golden or sample regeneration is needed.

## Schema, pins and generated types

A static script imported `cisco_toolkit.ui_projection` and `webapp.backend.ui_projection_api`
from this worktree, with `__file__` asserted. It compared `ui_projection_schema()` with main's
module, loaded from a `git show origin/main` extract.

- **The schema is unchanged:** sha256 of its sorted JSON is `281230b0663a58dc…` on both.
- Limitation ids, every `applies_to` and `DEVICE_CITED_LIMITATIONS` are unchanged.
- `__all__` is unchanged. *(The refutation round adds one public function,
  `fleet_blind_spot_rows`.)*
- **The native pins still hold.** `_native_schema_hash` gives:
  - view: `732c68c3d762f2b3d4d0329582bd32f3842567feef9cab20960f6959eef07372`
  - list: `7f256f809f1d9e0754a2312579ee6afdfe3ae5e58c2b5dd7b44fbfd32b5369b5`

  Both equal `_NATIVE_SCHEMA_HASHES`.
- Therefore `webapp/frontend/src/generated/openapi.ts`, `projectionFixtures.ts`,
  `portable/build_atlas.py` and `tests/test_atlas_projection_smoke.py` need no change.
- No envelope key changed, so Atlas Scope's exact-key `load.ts` envelopes are unaffected. No
  Codex handoff is needed.
- No new `cisco_toolkit` or `webapp/backend` file was added, so the LF byte-custody receipt and
  the golden's module-count strings are unchanged.

## Tests (written, not run)

`tests/test_ui_projection_unjoinable_rows.py` reads the class from the projection's source: every
`key_field` join and every device-page `_selection_rows` call. Each withheld value is compared
with the same page over the unedited sample, which publishes it, so no precondition is made true
by a fixture.

- **(a) The `key_field` joins.** Each member is tested with seven shapes of unreadable row:
  - the joined facts are `unverified`, with a witness to that row and to the device's own row;
  - the inventory row's pointer is withdrawn;
  - a device whose own row is gone reads `unverified`, not "no row";
  - a duplicate beside an unreadable row names both doubts and every candidate.
- **(b) The device scope:**
  - With an unjoinable blind-spot row, every top-level value the sample publishes, or calls a
    clean absence, on core1's page and inventory row becomes `unverified`, with the witness. The
    one exception is the fleet-level remediation banner. The owner's own answer stays
    `published`, which shows it passes over the row.
  - A device the owner calls not collected stays `not_collected`.
  - The real producer, given captures for "Core1" and "core1", writes two partial rows. core1's
    page no longer takes Core1's row or its `missing` list.
  - An unreadable status, or a missing one, is never read as collected. The control is a
    readable partial row.
  - Address observations of a doubted host are `unverified`.
- **(c) Disclosure:**
  - The inventory discloses a blind-spot row it cannot join. The control is a readable ghost row.
  - The fleet qualifier covers four unreadable-row shapes, and an empty list is `not_collected`.
  - An unknown host beside an unreadable roster row is `unverified`.
- **(d) The selections:**
  - Each selection keeps its rows and turns `unverified`, with a witness.
  - A `devices: []` finding stays readable.
  - NRFU device entries the join cannot read are witnessed.
- **(e) Stored data and structure:**
  - The stored sample and golden raise no doubt.
  - A structural test pins the single door to the device scope.

**Existing tests, reviewed by reading.** Each of the following keeps its expectation:
- `test_ui_projection_inventory.py`: I9 duplicate health, I16 blind and partial devices and I19
  blind-spot key rule. In I19's two-row case, core1's values now also read `unverified`; the test
  asserts only the collection status, pointer and total, which are unchanged.
- The W23 `test_ui_projection_device_impact.py` cases.
- `test_ui_projection_topology.py`'s blind-address case.
- The decision and coverage rollup blind cases.

They use readable blind-spot rows, so no doubt fires. In the garbage case `g_ep_bad`, every
device's endpoint selection is now `unverified`. No test asserts that selection's state there,
and I2's envelope invariants still hold.

## Static checks run

- `py -3.12 -m py_compile` on both changed Python files.
- An AST shadow scan of `ui_projection.py`. Its only hits are in functions this change does not
  touch, and none is called while shadowed.
- `tests/test_protocol_assessability.py::_hand_listed_state_collections` on `ui_projection.py`:
  no hits.
- The schema, limitation and pin comparison above.
- The new test module's AST enumeration, evaluated statically: four `key_field` joins and six
  selections, matching the module-wide counts. `device_blind` is read only in `device_scope`.
- The repository privacy verifier and the client-marker scan, both before commit.

## Residuals (not changed here)

- **The owner itself.** `ssot._device_not_collected` and `ssot.abstention_reason(device=...)`
  are unchanged. Their codomain has no `unverified` token, and other engine consumers (for
  example `assertions.evaluate_pack`) still read the first match. The projection discloses the
  doubt; the owner does not.
- **A blind-spot list that is not a list, or is `null`.** *Superseded for the not-a-list case by
  the refutation round below:* a list (or section) carried as the wrong type now doubts every
  device. A missing or `null` list stays the collection record's own `not_collected`.
- **A blank or whitespace-only host** is text. It joins no device and is not treated as
  unreadable.
- **VLAN-keyed selections** (`selections.stp_roots`, `gateways` and `endpoints`) are bare
  pointer lists with no fact envelope to carry a doubt. A row with an unreadable VLAN key is
  passed over there. This is a VLAN-page join, outside F6, and is adjacent to G15's residual.
- **Withheld lists drop the fleet qualifier** (W23's recorded residual). An `unverified`
  selection does not carry `fleet_lists_exclude_blind_devices`.

## Refutation round (2026-10-09)

An independent review of `ee71a03a` raised two P2 and five P3 items. Each was checked against the
source before it was changed. All seven are real; none was rejected. The branch first took main
`7d547890` (#620) with a merge commit, because `docs/NOW.md` conflicted and the P3 on
`webapp/backend/summary.py` exists only on that merged source.

### P2: the exact-hostname join over `cable_map.nodes` did not follow the rule

`_topology_join` joined cable-map nodes with `ctx.index` and never read the rows it could not
join. The class test found only `_resolve(key_field=...)` and `_selection_rows` calls, so this
join was outside it. Beside a node row with no readable host, the join still published its single
node, or read "no cable-map node has this exact hostname". The unknown-host page treated that same
row as one that could name any host. One row had two contradictory readings.

**Fix.**

- `_topology_join` now reads `ctx.unjoinable(("cable_map", "nodes"), ("host",))`. A published or
  empty join beside such a row is `unverified` (`_R_UNJOINABLE`), with witnesses to the rows that
  carry the name and to every row it cannot read. Its items stay. This covers a cable's ends, a
  structural link's ends, a failure-impact row, an address observation and a path hop, on the
  device page and on the fleet topology.
- The other joins of the same kind were held to the same rule:
  - `_topology_structural`'s host-pair join over `cable_map.cables` now goes through `ctx.pairs`
    and reads `ctx.unjoinable(toks, ("a", "b"))` (`_R_PAIR_UNJOINABLE`). It is equivalent to the
    old comprehension on readable rows.
  - `_impact_peers`' far-end join over `cable_map.nodes` now reads the nodes it cannot join. Beside
    one, no far end joins exactly one node, so every neighbour fails closed (the existing
    duplicate-node rule), and the bound also cites the unreadable node rows. The W27 wording that
    `summary._IMPACT_PEERS_SAID` parses is unchanged.
  - `_selection_rows` and `_nrfu_block` now read through the cached `ctx.unjoinable` and
    `ctx.index`, so `_Ctx.unjoinable` is the only caller of `_unjoinable_rows`.
- **The class test is now the class.** `test_every_exact_key_join_reads_the_rows_it_cannot_join`
  reads every `.index(...)` / `.pairs(...)` join in the module by AST. Each must read the rows it
  cannot join over the same list and key, in the same function, or be one of five reviewed
  exemptions with their reasons:
  - `cc_row`, the owner's own first-match row, reached only through `partial_row`, `cc_witness` and
    the roster join;
  - the endpoint `ip` and `mac` selections, which are bare pointer lists keyed by endpoint, not by
    device;
  - two uniqueness checks inside fleet lists that show every row (`_structural_dup`,
    `_impact_dup`).

  Every function holding a held join must name its behavioural test in `JOIN_TESTS`, and that test
  must exist. A join added later fails until it is held and tested.

Stored data: the sample and golden `cable_map.nodes` and `cable_map.cables` hold no row these joins
cannot read (checked with `json.load`), so no stored value changes.

### P2: an unreadable blind-spot list still rendered as healthy

With `collection_completeness.devices` present but not a list, `ssot._as_list` reads it as `[]`,
so the owner calls every device collected. The device scope, the fleet qualifier and the inventory
passed over it; only the device's own `/collection/*` record turned `unverified`.

**Fix.** `_unreadable_container` finds the first hop the snapshot carries as the wrong type: the
section as something other than an object, or the list as something other than a list.
`_Ctx.cc_unreadable` applies it to the blind-spot list. Then:

- `scope_doubt` doubts every text host (`_R_SCOPE_LIST`), with a witness to that value, so every
  device value the scope does not call not collected is `unverified`;
- `_fleet_qualify` adds the `fleet_lists_exclude_blind_devices` qualifier
  (`_R_FLEET_UNREADABLE_LIST`), so an empty fleet list is `not_collected`;
- `_device_rows` makes the inventory rows and the reconciled count `unverified`
  (`_R_INVENTORY_UNREADABLE`);
- the unknown-host roster check treats any unreadable roster (devices map, blind-spot list,
  cable-map nodes) the same way.

A missing or `null` section or list is unchanged: the abstention core's `not_collected` on the
device's own record, and no doubt. A test pins that boundary.

### P3 items

- **`summary.py` called an unreadable row a blind device (fixed).** After the merge,
  `summary.impact_view` counted every `/collection_completeness/devices/` witness on the
  failure-impact list as a device "listed as partial or not collected". It now tells the two kinds
  apart by the projection's own classifier: `ui_projection.fleet_blind_spot_rows`, delegated by
  `engine.fleet_blind_spot_rows`. It never re-reads the stored rows.
  - A readable blind row keeps `_R_IMPACT_BLIND`.
  - Every other `/collection_completeness` witness (a row, list or section it cannot read) is
    counted in `blind_unread` and worded `_R_IMPACT_BLIND_UNREAD`.
  - `impact_blind_note` composes both, and `_keystones` and `cutover._worst_blast_radius` disclose
    either.
  - `KEYSTONE_CONTRACT_VERSION` is now 5, so cached summaries recompute.
  - New webapp test:
    `test_the_blind_spot_note_never_calls_a_record_the_engine_cannot_read_a_blind_device`.
- **`docs/NOW.md` conflicted with main (fixed).** Main `7d547890` is merged with a merge commit.
  Only the handoff log conflicted. Main's table is kept as main has it, with the W43 row beside it,
  and every handoff line from both sides is kept. The W43 diff over main stays its own files.
- **The unknown-host page cited nothing (fixed).** A forced page may now carry witnesses as a third
  element of `forced` (`_forced_wit`). A bare row or list cites only those, never a subject, basis
  or failure record. Existing forced pages carry none, so their refs stay `[]`. The doubted page
  (`_roster_join`) cites every roster row it cannot join and every roster it cannot read. The test
  requires those witnesses, and that each resolves.
- **The single-door test named methods, not the class (fixed).**
  `test_the_device_scope_is_read_only_through_its_doubt_aware_door` now also pins:
  - `abst_dev` to `device_blind`;
  - every `ssot.abstention_reason` call with a device argument (keyword, `**` or a third
    positional) to `abst_dev`;
  - every read of the blind-spot list itself (an `index`, `unjoinable`, `pairs`, `_get`,
    `_unreadable_container`, `_resolve` or `_unjoinable_rows` call naming `_CC_ROWS` or the literal
    path) to eight reviewed readers, each with its reason (`CC_LIST_READERS`).
- **The stored-snapshot test could not fail by over-withholding (fixed).**
  `test_the_real_producers_distinct_hosts_raise_no_scope_doubt` builds the blind-spot list with the
  real `analyze.compute_collection_completeness`, over the sample's hosts plus `Ghost-Edge`, with
  core1 and access2 partial.
  - No devices-map host is doubted.
  - core1's score stays published, with `health_scored_over_partial_collection` and a witness to
    its own `missing` list.
  - A complete host carries no partial caveat.
  - The uncollected ghost is `not_collected`.

### Schema, pins and stored data after the round

The same static script as the first round, with `cisco_toolkit` and `webapp/backend` imported from
this worktree and `__file__` asserted:

- `ui_projection_schema()` equals main's (sha256 of its sorted JSON `281230b0663a58dc…`).
- The limitation ids and every `applies_to` are unchanged. Five limitation texts (instance data)
  now differ from main: `projection_owned_verdicts`, `row_selection_by_exact_key`,
  `fleet_lists_exclude_blind_devices`, `topology_scanned_model` and `impact_scanned_scope`.
- `__all__` adds `fleet_blind_spot_rows`.
- `_native_schema_hash` over `_VIEW_SCHEMA` and `_LIST_SCHEMA` gives `732c68c3…07372` and
  `7f256f80…369b5`, both equal to `_NATIVE_SCHEMA_HASHES`.

So `openapi.ts`, `projectionFixtures.ts`, `portable/build_atlas.py` and
`tests/test_atlas_projection_smoke.py` need no change. No envelope key changed, so Atlas Scope's
exact-key loader is unaffected. No file was added under `cisco_toolkit/` or `webapp/backend/`. The
sample and golden are unchanged and need no regeneration.

### Existing tests, reviewed by reading

- `test_ui_projection_topology.py::test_malformed_rows_retained_and_address_partiality_disclosed`
  appends a bad node and a null cable. Its joins now read `unverified`. The test asserts only the
  rows' own cells and that refs resolve, and both still hold.
- The W23 `test_l_a_neighbour_the_join_cannot_resolve_fails_closed` modes add no unreadable node
  row. The W23 duplicate-pair test's joins over withheld ends keep the ends' reason, because that
  branch runs first.
- The W27 null-cable test adds no unreadable node and no blind spot.
- `test_i9_unknown_and_non_text_hosts_claim_nothing` and the device-impact unknown-host tests use
  the sample, which has no unreadable roster, so the pages stay bare `not_collected`.
- In the garbage case `g_devices_int` (`devices: 5`), an unknown host's page is now `unverified`
  and cites `/devices`. The I1/I2 invariants still hold (closed states, resolving refs, no "not a
  blind spot" outside `collected_but_empty`), and no test asserts that page's state.

### Static checks run in this round

- `py_compile`/`compile` of every changed Python file.
- `tests/test_protocol_assessability.py::_hand_listed_state_collections` on `ui_projection.py`,
  `summary.py`, `cutover.py` and `engine.py`: no hits.
- The schema, limitation, `__all__` and native-pin comparison above.
- An AST census mirroring the new tests:
  - the join census finds 15 joins: 10 paired across 9 functions, and 5 exempt, equal to
    `EXEMPT_JOINS` and `JOIN_TESTS`;
  - `_unjoinable_rows` is called only by `unjoinable`;
  - `device_blind` is called by `device_scope`, `abst_dev` by `device_blind`, and `cc_row` by
    `partial_row`, `cc_witness` and `_roster_join`;
  - the device-scoped `abstention_reason` call is made only in `abst_dev`;
  - the eight blind-spot list readers equal `CC_LIST_READERS`.
- An AST shadow scan (a local name that is also a called module-level function): no hits.
- The repository privacy verifier and the client-marker scan, before commit.

### Residuals after the round

- **The census sees joins made through `_Ctx.index` / `_Ctx.pairs`.** A join written as a
  hand-rolled comparison loop is invisible to it. None is left in the device or topology joins:
  the NRFU loop now uses `ctx.index`, and `_capture_record` already fails closed on an unreadable
  host.
- **The endpoint `ip` / `mac` selections** stay the recorded exemption, like the VLAN-keyed
  selections: bare pointer lists with no envelope that could carry a doubt.
- **The failure-impact neighbour wording** names "a cable end that does not join exactly one node"
  also for a far end beside an unreadable node row. It joins one readable node, but that cannot be
  shown to be the only one. The wording is kept because the W27 summary parser reads it.
