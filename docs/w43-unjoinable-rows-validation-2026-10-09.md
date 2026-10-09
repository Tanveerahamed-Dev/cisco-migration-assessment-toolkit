# W43 unjoinable rows on device pages and in collection completeness (F6) validation

Branch `claude/f6-unjoinable-rows`, started from main `a06d1d27`. This record covers the owner
item F6. It is a source checkpoint: no local test, build, OpenAPI export, projection or browser
run was made, because the owner's rule is GitHub-hosted only. Every runtime verdict is pending
hosted evidence and independent refutation.

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
  roster names this device". The page stays bare, so the reason carries the count.
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
- `__all__` is unchanged.
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
- **A blind-spot list that is not a list, or is `null`.** This is the collection record's own
  state (`unverified` or `not_collected`). It is not a per-device doubt, so device values are not
  withheld for it.
- **A blank or whitespace-only host** is text. It joins no device and is not treated as
  unreadable.
- **VLAN-keyed selections** (`selections.stp_roots`, `gateways` and `endpoints`) are bare
  pointer lists with no fact envelope to carry a doubt. A row with an unreadable VLAN key is
  passed over there. This is a VLAN-page join, outside F6, and is adjacent to G15's residual.
- **Withheld lists drop the fleet qualifier** (W23's recorded residual). An `unverified`
  selection does not carry `fleet_lists_exclude_blind_devices`.
