# W38 routing-neighbour peer host (G17) validation

Branch `claude/g17-peer-host`, started from main `a06d1d27`; main `7d547890` (#620) is merged
in, and the review fixes sit on top (see "Review fixes"). This record covers gap G17 of
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
- More than one owning device is ambiguous, by `fib._hosts_owning_ip`'s rule. The `peer_host`
  basis is a fixed owner chain; every observation of the address is a witness ref on the fact,
  so the witnesses name the owners.

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
| An IPv6 address with no owner | `not_collected`: whether a device carries it was never observed | — |
| An IPv6 address with one other owner | `not_collected`: an owner is observed, but IPv6 coverage is incomplete, so a sole owner cannot be claimed | every observation |
| An index input (`interfaces`, `routes`) was not collected | `not_collected`, for a sole owner as for no owner | every observation |
| The index has a coverage gap (below) | `not_collected`, for a sole owner as for no owner; the reason states the gap total | every observation, and the first `_PEER_GAPS_CITED` (8) gaps |
| Exactly one other device carries it, over a complete index | `published`, the device name | every observation |
| No owner, over a complete index | `collected_but_empty`: "not resolved" | — |

A sole owner is never published over an incomplete index: a device the index cannot hold could
be a second owner, and more than one owner is ambiguous. The withheld owner's reason says so
("cannot be named the only owner: a second owner was never ruled out"), and the absence's reason
says an address the index does not hold is not a clean result. Both start with the same
"may be incomplete, because ..." clause, so a consumer can tell a proven owner from one that
cannot be ruled out by state alone.

**What "complete" means.** Interface addresses come only from the scoped interface
running-config capture. `build.py` marks every interface that capture parsed with
`run_config_observed: true`. One predicate, `_run_config_captured`, now serves both the
failure-impact hold and this check, and its behaviour there is unchanged.

The roster is every host key of `devices`, `interfaces`, `routes` and `routing_neighbors`,
completed by the rows of `collection_completeness.devices`
(`analyze.compute_collection_completeness` lists every inventory device that was not fully
collected, including one never reached). One coverage gap is counted for each of:
- a roster device that `collection_completeness` calls not collected, or none of whose
  interfaces carries the marker;
- a `collection_completeness.devices` row that names no roster device by the owner's name rule
  (no case, no surrounding space), whatever its status: a device outside the roster, a row that
  is not an object, or a host that is not text. A row naming a roster device adds no gap: that
  device's own capture is what the index needs, and it is checked directly;
- a devices map that is absent, not a map, or keyed by a non-text name;
- a `collection_completeness` record that cannot complete the roster:
  `ssot.abstention_reason` is neither published nor collected but empty (absent, a failed phase
  such as `failed_phases: ["Collection completeness"]` with the engine's `{}` fallback, or an
  owner fault), or its `devices` is not a list. A failed phase also cites its failure record.

**VRF.** The interface source spans every VRF that a captured interface configures, so a miss
holds in every VRF. VRF selection itself is not modelled:
- an address carried by two devices in any VRFs is unverified;
- a published owner may carry the address in another VRF than the adjacency, where an
  uncollected device could reuse it.

The new device limitation `routing_peer_resolution_scope` says this and the other residuals
below. It is cited on every published and every "not resolved" value. A comparison of the
neighbour row's interface VRF with the owner observation's VRF was considered and not added: the
producer writes `vrf` only for a non-global interface, so an absent field cannot be read as the
global table without inferring state, and BGP rows name no interface at all.

## Effect on the sample

`webapp/sample_data/sample_fleet.snapshot.json` was read with `json.load` and resolved by hand.
All 23 devices carry the capture marker, every `interfaces`, `routes` and `routing_neighbors`
host is a device, `collection_completeness` is readable (summary 23 of 23 complete, `devices: []`),
there are no blind spots, and no address record is malformed. The index is complete, so the
review fixes below change no sample value.

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

Any other branch that moves these pins must re-pin on top of the combined schema. They were
recomputed the same way after integrating main `7d547890` (#620) and again after the review
fixes, and both times they matched. #620 changes no schema. The fixes change only reasons, the
limitation's text and coverage logic: a static comparison of `ui_projection_schema()` with the
pre-fix module found it identical, as are the limitation ids and the vocab block.

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
- Agreement with the published `topology.source_addresses` rows. Both sides read the same index,
  so this is a consumer-drift guard; the sample test above is the independent check.
- The index is built once per context and shared, with `_address_sources` counted under
  `project_devices` and `project_topology`.
- Controlled synthetic cases for each row of the states table. A connected subnet that contains
  the address names no owner, while the engine's own subnet rule would. `_base()` carries a
  readable `collection_completeness` record in the producer's shape.
- Coverage gaps (added by the review fixes):
  - a sole owner over each gap kind is `not_collected` with the owner wording, against a complete
    control that publishes the same owner;
  - the review's counterexample (an owner on `Vlan99` in VRF `MGMT`, the rival device's capture
    unparsed) is withheld, while its complete control publishes;
  - every way the record can fail to complete the roster (absent, a failed phase with the
    engine's `{}` fallback, a failed phase with the record absent, `devices` not a list,
    `devices` absent, a row that is not an object, a non-text status, a non-text host, a partial
    row outside the roster), each expecting `not_collected` for the owner and the absence, never
    `published` or "not resolved", and the failure record where a phase failed;
  - an absent, non-map or non-text-keyed devices map, read through `_address_coverage` directly
    (a device page for such a snapshot is forced to its unknown-host state), plus the real sample
    as a complete control;
  - a partial row naming a captured roster device adds no gap;
  - a 300-device fleet with 298 uncaptured devices: each of 40 neighbour rows states the full gap
    total and cites exactly `_PEER_GAPS_CITED` gaps, so its references stay bounded;
  - an absent `routes` section withholds the sole owner with its observation cited;
  - the IPv6 owned reason no longer says "never observed".
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
- After the review fixes, these were repeated: `py_compile`, the three receipt-vocabulary
  guards, the `CAP_SITES` census, the shadow scan, the schema-identity comparison and the pin
  recomputation. No test was run.

## Review fixes (2026-10-09)

An independent review of `fd26d343` raised two P2 and five P3 items. Each was checked against
the code before it was fixed. After integrating main `7d547890` (#620), the fixes were committed
on `claude/g17-peer-host`.

| Item | Verdict | Change |
|---|---|---|
| P2: `_address_coverage` never read the state of `collection_completeness`, so an absent, failed or malformed record read as "no blind spots", and "not resolved" was stated over an unknown roster | **Real.** The old loop read only `ctx.blind_rows()`, which returns `[]` for each of those inputs. `_base()` had no record at all, yet its test asserted `collected_but_empty`. | The record must be published or collected but empty, and its `devices` must be a list, or one gap is counted (citing the failure record when a phase failed). Every row that names no roster device is a gap, whatever its status or shape. `_base()` gains a readable record, and nine parametrized cases are added. |
| P2: a sole owner was published over an incomplete index, with the gap witnesses in the same role and the same caveat as a proven owner | **Real.** The owner branch returned before any completeness check and only appended the gaps as witnesses. | A sole owner is `not_collected` whenever an input was not collected or the index has a coverage gap, with its own reason. This is `fib._hosts_owning_ip`'s ambiguity rule applied to a second owner that cannot be ruled out. It also closes the earlier residual "an absent `routes` section still lets an interface-address owner publish". `not_collected` rather than `unverified` follows the module's convention: a missing input is not collected, as the W23 failure-impact hold treats a device without a captured running-config. A distinct caveat was not chosen, because it would have changed the schema and the pins for a value no consumer should draw as a peer. The optional VRF comparison was not added (see VRF above). |
| P3: the "not resolved" reason said "so the neighbour is not a collected device" | **Real.** The index sees only configured `ip address` / `ipv4 address` lines and in-scope local and FHRP host routes. | The reason now states what no record in the index states, names the unobserved address kinds, and ends "so this does not prove that the neighbour is not a collected device". The limitation's text matches. |
| P3: an owned IPv6 address said "never observed" while citing the observation | **Real.** | A separate reason, used when an owner was observed: IPv6 coverage is incomplete, so a sole owner cannot be claimed. |
| P3: gap witnesses grew with the fleet on every neighbour row | **Real.** Every published and gap fact carried every gap. | At most `_PEER_GAPS_CITED` (8) gaps are cited, the first in roster order. The reason states the total and, when it truncates, "the witnesses cite the first 8 of them". A 300-device size test pins the bound. Published values no longer carry gaps at all. |
| P3: the validation doc said "Every peer_host basis names both owners", and the board said "Committed locally on main a06d1d27" | **Real.** | Reworded in both places. Main `7d547890` is integrated with a merge commit. Only `docs/NOW.md` conflicted, and the pins are re-verified unchanged. |
| P3: coverage-gap branches had no tests, and one agreement test holds by construction | **Real** for the branches; **accepted** for the agreement test | The gap tests are listed under Tests. The agreement test stays as a consumer-drift guard, and its docstring now says so. |

## Residuals

- **Addresses neither source states.** A DHCP or negotiated interface address whose local route
  was not captured in scope, and a firewall's failover standby address, are not in the index. A
  neighbour at one of them reads "not resolved" over a complete index. The reason and the
  limitation say this is not proof.
- **A truncated scoped capture.** It can mark some interfaces captured while missing others. The
  projection cannot see that (the same residual as W23).
- **IPv6** is never resolved: the producer parses only IPv4 `ip address` and `ipv4 address`
  lines.
- **An inventory count beyond the roster.** The roster is the union of the device-keyed sections
  and the record's rows. A device absent from all of them, which the producer never writes, is
  not compared against `collection_completeness.summary.inventory`. That count belongs to
  `ssot.reconcile`.
- **A routes table missing for one device** is not a gap: interface addresses come from the
  running-config capture. Local host routes only add owners.
- **The status record.** `docs/one-app-contract-gaps-status-2026-10-08.md` is a dated record and
  still lists G17 as partial. Its next reconciliation should mark it closed.

## Verification boundary

Still required before merge:
- every protected exact-head hosted check, including the native-parity group and `api:check`;
- independent refutation;
- the supervisor's push and merge.

## Second refutation round on the W51 train (2026-10-09)

* **P2 (summary not reconciled):** `_address_coverage` now reads the record through the blind-spot record's one coverage verdict, `_cc_coverage` (read through `_Ctx.cc_coverage`, next to F6's `_cc_universe`). A readable record
  whose summary counts a blind spot its list does not carry, cannot be read, or counts an inventory other than the
  roster's is a coverage gap citing that summary or count (probe: `_base()` with `summary.inventory = 5` published
  `r2`; now not_collected). The row rule (a row naming no roster device) stays this reader's own, standing in for
  the unread-rows gap.
* **P3 (failure record past the cap):** `_peer_host` cites the first `_PEER_GAPS_CITED` gaps and, from the rest,
  every failure record; the reason says so. A failed record also doubts every device's own observations (F6), so the
  owner path is withheld before the cap; the cap fix covers the absence path, tested by calling `_peer_host` on a
  fleet whose failed record's gap sits past the cap.
* **Fixtures:** cases that add a device to the record or the devices map now count it in the summary, as the
  producer does (`_counted`); the failed-record cases and the unlisted-summary case are device-scope doubted.
