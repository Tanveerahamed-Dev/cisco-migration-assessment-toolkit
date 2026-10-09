# W38 routing-neighbour peer host (G17) validation

Branch `claude/g17-peer-host`, started from main `a06d1d27`. This record covers gap G17 of
`docs/one-app-contract-gaps-2026-09-30.md`. Every routing-neighbour row on a device page now
carries `peer_host`: the collected device the neighbour's address belongs to, or "not resolved".
The contract home is the one the register named:
`device.routing_neighbors.items[].neighbors.items[].peer_host: TextFact`.

This is a source checkpoint. No local test, build, OpenAPI export, type check, projection or
browser run was made, because the owner's rule is GitHub-hosted only. Every runtime verdict is
pending hosted evidence.

## What resolves, and against what

**The one index.** The resolution reads the address index that `topology.source_addresses`
already publishes. It builds no second index.
- `_address_observations` was split in two. `_address_sources` builds the index once per
  projection context (`_Ctx.addresses`). `_address_observations` publishes it exactly as before:
  same rows, order, states, references and list state.
- The index is `fib._connected_index`'s exact-owner rule, carried with pointers. An owner is an
  interface address (`svi_ip`, `svi_ips`), a local host route, or an FHRP host route that names
  itself. A connected subnet is never an owner, because every router on a shared segment
  contains the address.
- More than one owning device is ambiguous, by `fib._hosts_owning_ip`'s rule. Every `peer_host`
  basis names both owners.

**Which field is the address.** `NEIGHBOR_ADDRESS_FIELDS` maps each protocol key of
`build.build_routing_neighbors` to its address field:
- OSPF uses `address`, the adjacency address. Its `neighbor` field is the Neighbor ID column, a
  router ID, which is never resolved.
- EIGRP and BGP use `neighbor`, which their parsers fill with the peer's address.

A test holds each entry to the real parser's output (`parse.parse_ospf_neighbors`,
`parse.parse_eigrp_neighbors` and `parse.parse_bgp_summary`). It also holds the keys to the
producer's own returned mapping, read from its source.

## States

First match wins, in the module's precedence: analysis unavailable, then unverified, then not
collected.

| Situation | State | Witnesses |
|---|---|---|
| The address cell is withheld | the cell's own state and reason; an empty address is `not_collected` | the cell's refs |
| The protocol has no registered address field | `not_collected` | the row |
| An index input (`interfaces`, `routes`) failed or its owner raised | `analysis_unavailable` / `unverified` | failure records |
| The address is not an IP | `unverified` | — |
| Two or more devices carry it, or only this device | `unverified` | every observation |
| A source record the index cannot read could carry it (for an owner: any record that is not the owner's own) | `unverified` | each such record |
| The index withholds the owner's observation (the owner is a collection blind spot) | that state, `not_collected` | its blind-spot row |
| An IPv6 address | `not_collected`: the index holds IPv4 interface addresses only | any observation |
| Exactly one other device carries it | `published`, the device name | every observation, and every device the index cannot hold |
| No owner, and an index input was not collected | `not_collected` | — |
| No owner, and some collected device's interface addresses were never captured | `not_collected` | each such device |
| No owner, over a readable and complete index | `collected_but_empty`: "not resolved" | — |

**What "complete" means.** Interface addresses come only from the scoped interface
running-config capture. `build.py` marks every interface that capture parsed with
`run_config_observed: true`. One predicate, `_run_config_captured`, now serves both the
failure-impact hold and this check, and its behaviour there is unchanged.

The roster is every host key of `devices`, `interfaces`, `routes` and `routing_neighbors`. A
roster device is a gap when `collection_completeness` calls it not collected, or when no
interface of it carries the marker. A blind-spot row that names no roster device is a gap, and
so is a devices map that cannot be read.

**VRF.** The interface source spans every VRF that a captured interface configures, so a miss
holds in every VRF. VRF selection itself is not modelled:
- an address carried by two devices in any VRFs is unverified;
- a published owner may carry the address in another VRF than the adjacency, where an
  uncollected device could reuse it.

The new device limitation `routing_peer_resolution_scope` says this and the other residuals
below. It is cited on every published and every "not resolved" value.

## Effect on the sample

`webapp/sample_data/sample_fleet.snapshot.json` was read with `json.load` and resolved by hand.
All 23 devices carry the capture marker, there are no blind spots, and no address record is
malformed.

| Device | Protocol | Address | `peer_host` |
|---|---|---|---|
| core1 | OSPF | 10.0.10.3 | published `core2` |
| core1 | OSPF | 10.0.40.9 (EXSTART) | not resolved |
| core1 | OSPF | 10.0.140.2 | published `dist1` |
| core1 | BGP | 10.0.10.254 | not resolved (the upstream peer, also core1's static default next hop) |
| dist1 | OSPF | 10.0.140.1 | published `core1` |
| dist1 | OSPF | 10.0.40.3 | published `dist2` |
| dist2 | OSPF | 10.0.40.2 | published `dist1` |

The OSPF router IDs (10.0.99.x) are on no device, which is why resolving `neighbor` instead of
`address` would be wrong. `topology.source_addresses` is unchanged. No engine section is
persisted, so the golden snapshot and the sample stay byte-identical.

## Reviewed transport-schema delta

A static structural diff of `ui_projection_schema()` against main's module finds four changes:
1. `NeighborRow` gains the required property `peer_host`, a `$ref` to the existing `TextFact`.
2. `LimitationId` gains `routing_peer_resolution_scope`, appended after the other device
   limitations.
3. The vocab block's unranked `limitation_id` token enum gains the same token.
4. `DevicePage.limitations` grows from 18 to 19 fixed items (`minItems` = `maxItems`).

The transport's `_common_schema("device")` copies that array into every device view and list
variant. No definition is added or removed (220 before and after). The delta uses only `$ref`,
`properties`, `required`, `additionalProperties`, `enum`, `minItems` and `maxItems`, all in the
established view and list profile.

The admitted native domain is unchanged. `peer_host` values are host names, and its reasons
carry no CR, LF, U+2028, U+2029 or surrogate.

**Hashes.** They are compact `ensure_ascii` JSON plus LF, in owner key order. They were computed
statically with `ui_projection_api._native_schema_hash` on `_VIEW_SCHEMA` and `_LIST_SCHEMA`.
Both `cisco_toolkit.ui_projection` and `backend.ui_projection_api` were imported from this
worktree, with `__file__` asserted. Before any edit, the same computation reproduced main's pins
exactly, as a method check:
- main view: `732c68c3d762f2b3d4d0329582bd32f3842567feef9cab20960f6959eef07372`
- main list: `7f256f809f1d9e0754a2312579ee6afdfe3ae5e58c2b5dd7b44fbfd32b5369b5`

These are now in `_NATIVE_SCHEMA_HASHES` and in the W12b prospective pair of
`webapp/tests/test_ui_projection_api.py`:
- view: `caa861ca820f16e9c3933d3b4b0d7e289d8cd1e8b803f41122bffdb6c15d8d8e`
- list: `c97c9b8f2c716fb14ee60c19cd3c0c1e66de8fe8baa5359e2494154cfabcddf8`

Any other branch that moves these pins must re-pin on top of the combined schema.

**`openapi.ts`.** The file was edited by hand to the openapi-typescript 7.13.0 shape:
- `UiProjection1_NeighborRow` gains `peer_host` in sorted property order, between `neighbor`
  and `pointer`;
- the `LimitationId` union and the `VocabLimitationId` token union each gain the new token at
  the end;
- all 20 device limitation tuples grow from 18 to 19 members. They stay tuples: the 29-member
  Trust tuples are unchanged and still under 30 items.

Hosted `api:check` decides exactness.

## Consumers checked

- **Atlas Scope** reads only topology and path envelopes. `source_addresses` rows are unchanged,
  so no Scope key set moves and no Codex handoff is needed.
- **`webapp/frontend/src/test/projectionFixtures.ts`** is unchanged. The device fixture's
  `routing_neighbors` is an empty page, so no neighbour row is built, and its envelope
  `limitations` is an empty array.
- **`portable/build_atlas.py`** and **`tests/test_atlas_projection_smoke.py`** use only the
  overview view and the Trust limitations, which are unchanged.
- **LF byte custody.** No file is added under `cisco_toolkit/` or `webapp/backend/`, so the
  receipt in `tests/fixtures/atlas-r2-byte-custody-policy.v1.json` does not move. No new
  `cisco_toolkit` module is added either, so the golden attestation counts do not move.
- **The rendered page.** `CoreSnapshot.tsx` still lists five neighbour cells and does not yet
  draw `peer_host`. The checked frontend distribution is gated, so a render change needs a
  hosted distribution regeneration. That is a recorded follow-up.

## Tests (written, not run)

New file: `tests/test_ui_projection_peer_host.py`.
- The schema and the device limitation.
- The address fields against the real parsers and the producer's keys.
- The sample's seven neighbours against three independent answers: the hand-resolved anchors
  above, an independent record lookup, and `fib._hosts_owning_ip(..., exact=True)` over
  `fib._connected_index`. Each published value cites exactly the records that carry the address.
- Agreement with the published `topology.source_addresses` rows.
- The index is built once per context and shared, with `_address_sources` counted under
  `project_devices` and `project_topology`.
- Controlled synthetic cases for each row of the states table. A connected subnet that contains
  the address names no owner, while the engine's own subnet rule would.
- Purity and container ownership.

Guards updated, never weakened:
- **`tests/test_ui_projection_device_impact.py`.** The hand-written device limitation list gains
  `routing_peer_resolution_scope`.
- **`tests/test_ui_projection_inventory.py` `CAP_SITES`** gains three reviewed exemptions.
  Citing `parse.parse_run_config_interfaces` as the owner of the IPv4-only interface source
  brings that parser and two of its helpers into the prefix-slice census. Each new slice is a
  first-character indentation test (`line[:1]`, `raw[:1]`), not a cap.

## Static checks run locally

- `py_compile` of every touched Python file.
- The receipt-vocabulary guards of `tests/test_protocol_assessability.py`, called directly:
  - no hand-listed state collection in the changed files or the repository;
  - `_assert_section_dependency_reader` passes;
  - every receipt reader is classified.
- The `CAP_SITES` prefix-slice census, by the inventory test's own helpers: no unreviewed and no
  vanished site.
- An AST scan for locals that shadow a module-level name: none added in `ui_projection.py`.
- The static schema diff and the hash computation above.

## Residuals

- **Addresses no configuration line states.** DHCP or negotiated interface addresses and a
  firewall's failover standby address are not in the index. A neighbour at one of them reads
  "not resolved" when every collected device was captured.
- **A truncated scoped capture.** It can mark some interfaces captured while missing others. The
  projection cannot see that (the same residual as W23).
- **IPv6** is never resolved: the producer parses only IPv4 `ip address` and `ipv4 address`
  lines.
- **An absent `routes` section** still lets an interface-address owner publish, while an absence
  becomes `not_collected`.
- **The status record.** `docs/one-app-contract-gaps-status-2026-10-08.md` is a dated record and
  still lists G17 as partial. Its next reconciliation should mark it closed.

## Verification boundary

Still required before merge:
- every protected exact-head hosted check, including the native-parity group and `api:check`;
- independent refutation;
- the supervisor's push and merge.
