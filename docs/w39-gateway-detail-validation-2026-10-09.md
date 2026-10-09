# W39 VLAN L3 gateway detail (G16) validation

Branch `claude/g16-gateway-detail`, started from main `a06d1d27`. This record covers contract gap G16
(`docs/one-app-contract-gaps-2026-09-30.md`, section 21). A VLAN row's `selections.gateways` is now
a fact list of the stored `l3_forwarding` rows that name its VLAN id. Each gateway row carries
`host`, `svi_ip`, `role`, `tracking` and `risk`. The rows are selected by exact VLAN key and built
from the producer's own values; nothing is re-derived.

No local test, browser, SPA build, OpenAPI export, type check or projection run was made, because
the owner's rule is GitHub-hosted only. Every runtime verdict is pending hosted evidence.

## The contract

**Shape.**
- `VlanSelections.gateways` changes from a nullable index list to `VlanGatewayRowList`, a closed
  fact list of `VlanGatewayRow`.
- A row is `{index, pointer, host, svi_ip, role, tracking, risk}`. `index` and `pointer` address
  `/l3_forwarding/<i>`. The four text cells are `TextFact`; `risk` is a `FlagFact`.
- `selection_sources.gateways` is unchanged and still states the source list's own state.

**Owner.** `excel.write_l3_forwarding_sheet` writes one row per scanned device SVI with an address,
an FHRP group or a connected route. Its row fields map to the cells as follows:

| Cell | Producer field | Published | Withheld |
|---|---|---|---|
| `host` | `switch` | the text | `''` not collected; a non-text unverified |
| `svi_ip` | `svi_ip` | the text | `''` not collected (the row came from FHRP or a route alone) |
| `role` | `role` | the FHRP role as captured | `''` not collected, never "no FHRP" (no group in the brief, or no brief) |
| `tracking` | `tracking` | the device's `show track` summary | see below |
| `risk` | `risk` (its `single-gateway` flag) | `true` / `false` | see below |

**Tracking.** The text is the device's `show track` summary, not bound to the SVI or its FHRP group.
It states the full object count, then the state of at most 6 objects.
- The producer's `[NOT OBSERVED]` marker is `not_collected`, with the reason "never 'no tracking'".
- An empty text is `collected_but_empty` ("captured, no tracked object") only where the snapshot
  proves its producer separates the two cases. Before 2026-07-28 (`b13602f7`) the producer wrote
  `''` both for "captured, none" and for "never captured". The proof is any not-observed tracking or
  risk marker in `l3_forwarding`, or any interface marked `run_config_observed` (written since
  2026-08-10). Without either, `''` is `not_collected` with an ambiguity reason.
- A tracking text beside the row's own "object tracking NOT assessed" risk marker contradicts it
  and is `unverified`, with a witness to the risk field.
- The text must agree with the row's own `tracked-object-down` flag. The producer raises that flag
  exactly when its captured summary reports a Down object (`<N> obj (<D> DOWN)`, read by
  `_TRACK_SUMMARY`, pinned to `excel._track_summary`). An empty text or the not-observed marker
  beside the flag, a summary with no Down head beside it, or a Down head without it, is
  `unverified` with a witness to the risk field.

**Sole-gateway risk.** `risk` reads only the producer's `single-gateway` flag. It never carries
`no-FHRP` or `tracked-object-down`, so `false` is never a health verdict.
- The stored risk text must be the producer's flag list: `ok`, its tracking-not-assessed marker,
  or distinct flags of `tracked-object-down`, `single-gateway` and `no-FHRP` joined by `'; '` in
  the producer's append order (`tracked-object-down` first), with `single-gateway` never beside
  `no-FHRP`. Anything else is `unverified`.
- The flag must agree with the stored rows. `single-gateway` with two or more distinct switches
  naming the VLAN, or no flag with only one switch, is `unverified`, with a witness to each row. A
  gateway row of the VLAN that names no readable switch makes the count unreadable (`unverified`).
- Without the flag, `risk` is published as `false` only where another switch's gateway row of
  the VLAN provably shares this row's segment (`_gateway_segment_hold`): the same readable set of
  networks (the SVI address's network and the primary subnet), and the same VRF where both SVIs'
  VRFs can be read. The producer counts gateways by VLAN id across the scan, so without that proof
  a second row may be VLAN-id reuse at another site or in another VRF, and `false` is `unverified`
  with a witness to each row of the VLAN and its SVI. With the proof, `false` holds whatever the
  coverage, because an unscanned device can only add gateways. A VRF is read from the row's one
  `VlanN` interface: a text, or blank where that interface's running-config was captured (the
  global table); otherwise it cannot be read and is not compared.
- The flag is published as `true` only when the scan covers every gateway the producer's `VlanN`
  rule could count and no stored record contradicts it (below). Otherwise it is withheld in the
  module's precedence (`analysis_unavailable`, then `unverified`, then `not_collected`), with
  every gap's reason and witness.

**Coverage rule** (`_gateway_coverage`). It is fleet-wide and fails closed, because VLAN carriage per
cable is not stored (G14), so a gap cannot be scoped to the VLANs it could reach. A gap is:
- a `collection_completeness` blind spot (partial or not collected), or a row of it with no readable
  status, or the record itself unreadable, absent or failed;
- a `cable_map.nodes` row not marked `collected: true` whose kind is not `ap`, `phone` or `endpoint`
  (the W23 `_IMPACT_EDGE_KINDS`), an unreadable node, a cable row that cannot be read or whose end
  joins no single node, or an unreadable or failed cable map;
- a collected device none of whose interfaces carries `run_config_observed: true` (build.py takes
  `svi_ip` only from that capture), or an unreadable devices or interfaces map;
- a `collection_completeness.summary` that counts more partial or not-collected devices than its
  devices list carries (the producer writes one row per such device), or a summary count that
  cannot be read (`unverified`).

Each gap cites at most 8 witnesses (`_GW_GAP_WITNESS_CAP`); its reason states the full count and
"(8 of N cited)", so the payload grows with the number of gap kinds, not with fleet size.

**Gateways the producer cannot count** (`_GatewayScan.attribution`, per VLAN). The producer counts
only interfaces named `VlanN` (`^Vlan(\d+)$`). Every collected interface address (`svi_ip` and the
configured set `svi_ips`) is read once per projection, and per VLAN:
- an addressed SVI named for the VLAN on a switch with no gateway row (the stored rows undercount)
  is `unverified`;
- any other interface holding an address inside a segment the VLAN's rows name (a routed port,
  subinterface, BDI/BVI/irb unit, or another VLAN's SVI, outside a VRF known to differ) is
  `unverified`. This is scoped by address, so it reaches only the VLAN whose subnet it is in;
- where a row names no readable segment, or the VLAN has no row, any interface not named `VlanN`
  whose subnet leaves a host address no collected interface holds is `not_collected` (the snapshot
  does not store which VLAN it serves). A transit network whose usable addresses are all collected
  interface addresses (the sample's routed /30) and a /32 leave no host and do not count;
- an interface record or address that cannot be read is `unverified` for every VLAN, except on the
  VLAN's own counted SVIs.

**FHRP evidence of another router** (`_GatewayScan.fhrp_gaps`, per sole-flagged row). A role other
than Active or Master (Standby, Listen, Init and every other word) is `unverified`. The device's
HSRP detail (`fhrp_detail[host]`, `build.build_fhrp_detail`) for the row's SVI naming a standby
router no gateway row of the VLAN holds, or a state other than Active or Master, is `unverified`.
An Active or Master row whose detail is absent for the device or names no group on its SVI is
`not_collected` (a standby router outside the scan cannot be ruled out). A detail record or
section that cannot be read is `unverified`. A row with no role and no detail record for its SVI
carries no stored FHRP evidence; that residual is below.

**The list.**
- A failed, absent or unreadable source selects nothing, in its own state (as `selection_sources`
  already said).
- A row the VLAN join cannot read (not an object, or a `vlan` that is not a VLAN id) could name any
  VLAN. It makes every gateway list `unverified` with a witness, keeps the readable rows, and counts
  as a gap for every sole flag. A VLAN row with no readable VLAN id joins nothing (`unverified`).
- An empty selection is `collected_but_empty` only under full coverage; otherwise it is withheld
  with the gaps.
- A published list carries `row_selection_by_exact_key`; under a gap also `vlan_gateway_rows` with
  every gap witness; under a blind spot also `fleet_lists_exclude_blind_devices`.

**The VLAN row's `fhrp` text.** `analyze.compute_vlan_cutover_matrix` writes
`sole gateway on <host> (no FHRP)` for a VLAN with one gateway in the scan. That text is published
only where the gateway row of that switch publishes its sole-gateway risk `true`
(`_vlan_fhrp_pre`, built after the VLAN's gateway rows). A withheld risk lends its state and
witnesses, whatever withheld it (a coverage gap, an unjoinable row, a contradicted flag, an
unreadable risk text, FHRP evidence); a published `false`, or no gateway row naming the switch, is
`unverified`; an unreadable source keeps its own state. So one row never states a sole gateway in
one cell and withholds it in another. Its other texts and its FHRP record are unchanged.

**Limitation.** One new payload limitation, `vlan_gateway_rows`, applies to `/inventory/vlans/rows`
and states all of the above. The `row_selection_by_exact_key` text (instance data) now says that
`selections.gateways` is a fact list.

## Effect on the stored sample and golden

Read statically with `json.load` and the tests' independent rule, not by running the projection.

`webapp/sample_data/sample_fleet.snapshot.json` has 5 VLAN rows and 9 gateway rows. Its one
coverage gap is `/cable_map/nodes/23`, `wan-edge-rtr1.lab` (kind `router`, `collected: false`). It
has no blind spot, no loose cable, and `run_config_observed` on every device. Its two APs are edge
gear.
- VLANs 10, 20, 40 and 41: the list is published and cites `vlan_gateway_rows` and node 23. Each
  row publishes host, SVI address and role (`Active`/`Standby`); tracking is `not_collected` (the
  marker on every row); risk is published `false`.
- VLAN 30: one row (`core1`). Role is `not_collected` (`''`) and tracking is `not_collected`. Risk
  is `not_collected` (single-gateway, coverage unproven) with a witness to node 23. The VLAN row's
  `fhrp` text moves from published to `not_collected` for the same reason.
- The refutation fixes change no stored outcome, read statically with an independent script (not
  the projection): VLANs 10, 20, 40 and 41 each have two rows with an equal `/24` and readable
  global-table VRFs; no collected address lies in any VLAN's subnet outside its own `VlanN` SVIs;
  every address parses; the routed `/30` (core1 `Gi1/0/40`, dist1 `Gi1/0/3`) has both usable
  addresses collected; core1's HSRP detail names Vlan10 and Vlan20 only; and the completeness
  summary counts 0 blind spots over an empty list.

`tests/golden/snapshot.json` has the same shape: 3 VLAN rows, 5 gateway rows, and gap node 4. Neither
file changes; no golden or sample regeneration is needed.

## Native transport schema re-pin

**Reviewed delta.** Over main, the owner schema:
- adds `VlanGatewayRow` and `VlanGatewayRowList` (positions 117 and 135 of 222; every existing
  definition keeps its order);
- changes `VlanSelections.gateways` to a `$ref` of `VlanGatewayRowList`;
- adds `vlan_gateway_rows` to `LimitationId` and to the `limitation_id` unranked vocabulary tokens;
- grows `Trust.limitations` from 29 to 30 fixed items.

The transport schemas change only by those `$defs` and by each non-device view and list branch's
copied `limitations` (5 view and 19 list branches: `minItems` = `maxItems` 29 to 30). Device
branches, the transport `Page_`/`Source_` definitions and every other branch member are unchanged.
The added definitions use only `$ref`, `additionalProperties`, `anyOf`, `const`,
`dependentRequired`, `items`, `maximum`, `minItems`, `minLength`, `minimum`, `oneOf`, `properties`,
`required`, `title`, `type` and `uniqueItems`, all in the established profile. The new instance
values are text, booleans, integers and null, inside the admitted native domain. The provider
version, resolver guard and Python fallback are unchanged.

**Hashes.** Compact `ensure_ascii` JSON plus LF, in owner key order, computed statically with
`ui_projection_api._native_schema_hash` on `_VIEW_SCHEMA` and `_LIST_SCHEMA`. `backend.ui_projection_api`
and `cisco_toolkit.ui_projection` were imported from this worktree, with `__file__` asserted. No
test, validator or projection ran.
- Method check: a `git archive` extract of main `a06d1d27` reproduces main's pins (view `732c68c3…`,
  list `7f256f80…`).
- Now in `_NATIVE_SCHEMA_HASHES` and the W12b prospective pair:
  - view: `9bfad9b410781bc9a3a9fe6a7fc84e4341d97d6c1f2a6b0b4dcaad7146e04e80`
  - list: `b493aa84163f3f76b632e75f625be3a595f03814af727725698b83f58bd2ff6c`

**`openapi.ts`** (hand-edited; hosted `api:check` decides exactness):
- `UiProjection1_LimitationId` and the `limitation_id` vocab tokens gain `"vlan_gateway_rows"` after
  `"vlan_readiness_scope"`.
- openapi-typescript 7.13.0 (`--array-length`) emits a tuple only while `min == max` stays under 30.
  So the 27 copies of the Trust limitations become
  `readonly components["schemas"]["UiProjection1_Limitation"][]`; the 20 18-item device tuples stay.
- `UiProjection1_VlanSelections.gateways` becomes the new list.
- `UiProjection1_VlanGatewayRow` and `UiProjection1_VlanGatewayRowList` are added, alphabetized
  between `ViolationList` and `VlanRow`, in the `VlanRowList` shape.
- A line diff against `claude/trust-inputs` (W28), which crosses 29 to 30 independently, shows the
  27 collapsed lines byte-equal; the only differences are each branch's own additions.

**Atlas Scope.** No transport envelope gains or loses a key, and Scope's contract mode reads no
inventory VLAN row, so no `atlas-scope/` edit or Codex handoff is needed. Scope's contract-mode types
import `openapi.ts`, so its hosted CI runs on this change. The topology envelope's `limitations` type
widens from a 29-item tuple to a readonly array; Scope only checks it with `Array.isArray`, iterates it
and digests it, and no consumer indexes a fixed tuple position.

## Tests (written, not run)

`tests/test_ui_projection_gateways.py`:
- (a) The stored sample and golden, against an independent selection and gap rule: rows, pointers
  and subjects; the published host, address and role; the not-observed tracking; `false` risks; the
  sole risk and the `fhrp` text withheld with the router witness. The covered control removes the
  router: the sole risk is `true` and the `fhrp` text published.
- (b) 19 coverage-gap mutations, each withholding the sole flag in the right state with its witness
  while `false` stays published: blind spots, an absent or unreadable completeness record, seven
  uncollected-node variants, loose and unreadable cables, a missing or textual run-config marker,
  a malformed devices map, and failed cable-map and completeness phases.
- (c) Contradicted flags; 10 unreadable risk texts; the flag combinations that do and do not mean
  sole; an unnamed switch; 5 rows the VLAN join cannot read.
- (d) Tracking: captured-none, both contradictions, a published summary, and the pre-split
  ambiguity with its two proofs.
- (e) Unreadable, absent, null, malformed and failed sources; the empty selection under and without
  coverage; a VLAN row with no readable id.
- (f) The real `excel.write_l3_forwarding_sheet` pins the marker, the clean word, the joiner, each
  flag and the captured-none `''`; the real `analyze.compute_vlan_cutover_matrix` pins the
  sole-gateway `fhrp` text; the producer's own rows over the sample's interfaces project end to end.
- (g) The closed schema and the registered limitation.

Added by the refutation fixes (below): two summary gaps in (b); a parametrized test of a tracking
text against the row's own Down flag (four contradictions, two controls); `fhrp` assertions on the
contradicted-flag and unjoinable-row tests; two order-violating risk texts; an addressed SVI with no
gateway row; four interfaces the `VlanN` rule never counts withholding an empty list; 16 scoped
evidence cases withholding the sole flag (FHRP role, HSRP standby router and state, missing or
unreadable detail, addresses in the subnet, an uncounted SVI, a row with no segment, unreadable
addresses and records), each also withholding the `fhrp` text and leaving other VLANs untouched;
five scoped controls that keep it; the real `build.build_fhrp_detail` deciding an Active sole
gateway both ways; four VLAN-id reuse cases, an unreadable-VRF control and the reviewer's two-site
fleet; the witness cap with 30 uncollected neighbours; and producer pins for the flag order and the
`show track` summary's Down head. The tracking test's Down summary now carries the
`tracked-object-down` flag the producer always writes with it, and the empty-list test now also
clears VLAN 30's SVI address (an addressed SVI with no row is itself a contradiction, tested apart).

Changed: `tests/test_ui_projection_inventory.py` I14 and I20 assert the fact list (same exact-key
indices; withheld with a reason where the source cannot be read, instead of `null`). I0 adds the two
new definitions to its closedness checks. I12's two `excel` cap exemptions are re-reviewed now that
tracking is projected: the full count is in-band, and object descriptions never reach the text.
`webapp/tests/test_ui_projection_api.py` carries the new prospective pins.

## Static checks run locally

- `py_compile` of every changed Python file, and `ruff check` on them.
- The protocol-assessability hand-list scanner over every scanned file, and the
  section-dependency proof on `cisco_toolkit/ui_projection.py`.
- An AST scan for locals shadowing module-level names: no new hit.
- The pin computation, method check, structural schema diff and the `openapi.ts` cross-check above.
- The repository privacy verifier and the client-marker scan, before commit.

## Residuals not closed here

- **Other sole-gateway surfaces keep the in-scan claim without this coverage rule:** the readiness
  check note (`analyze.compute_migration_readiness`, "sole gateway on X (no FHRP)"), the
  cross-layer and punch-list findings (CL-01, CL-03), causality chain A, `archreview`'s single-gateway
  evidence and `design_advisor`'s single-gateway decision. These are other owners.
- **Fleet-wide coverage is conservative.** One uncollected router anywhere withholds every VLAN's
  sole risk. Scoping a gap to the VLANs it can reach needs stored VLAN carriage per cable (G14).
- **Undiscoverable gateways.** A gateway that neither the collection nor CDP/LLDP discovered (for
  example a firewall with discovery disabled) cannot be ruled out by any scan. A published `true` is
  the verdict over the discovered fabric, and the limitation says so.
- **Tracking is projected device-level, though a group-bound owner exists.** The `tracking` cell is
  the device's `show track` summary (`excel._track_summary`). The HSRP detail's per-group track list
  (`fhrp_detail[host][i].track`, `parse.parse_hsrp_detail`'s `Track object N ... decrement`) is
  the SVI-bound record G16 asks for ("object tracking observed or not"). It is not projected here;
  a separate cell would change the closed schema and re-pin. Recorded as a follow-up.
- **An FHRP group neither the brief nor the detail captured leaves no in-snapshot peer evidence.**
  A row with an empty role and no detail record for its SVI is read as having no FHRP evidence; the
  role cell itself stays `not_collected`.
- **VRF comparison only where readable.** A blank VRF is the global table only where the
  interface's running-config was captured; otherwise the two rows are compared on subnet alone.
- **Payload weight.** Each gap cites at most 8 witnesses with its full count in-band, so a list
  grows with gap kinds, not fleet size (pinned with 30 uncollected neighbours). The unchanged
  300 ms sample gate remains the latency evidence.
- **No page renders `selections.gateways` yet.** The AssessHub VLAN tab still shows `fhrp` and
  `gateway_svi_hosts`; rendering it needs the hosted tracked-SPA handoff.
- **W28 overlap.** `claude/trust-inputs` also adds a payload limitation, collapses the same 27
  tuples and moves the same pins. Whichever merges second keeps both limitation IDs in the
  `LimitationId` union and the `limitation_id` tokens, re-pins on the combined schema, and
  regenerates `openapi.ts`.

## Verification boundary

Still required before merge: every protected exact-head hosted check, including the native-parity
group, `api:check` and the frontend type check; independent refutation by Codex; and the supervisor's
merge.

## Refutation fixes (2026-10-09, on `a12e88c0`)

An independent review raised three defects (P1-P2) and four P3 items. Each was checked against
the code before fixing; all were real. No schema change (instance states and the limitation text
only), so no re-pin and no `openapi.ts` change; no golden, sample or `atlas-scope/` change.

| # | Sev | Finding | Verdict and fix |
|---|---|---|---|
| 1 | P1 | `false` published on VLAN-id reuse: the producer counts gateways per VLAN id fleet-wide, so two sites reusing VLAN 30 in different subnets or VRFs each read "another gateway exists". | Real (`write_l3_forwarding_sheet` builds `vlan_gw` by `int(m.group(1))` alone). `false` now needs another switch's row on the same segment (`_gateway_segment_hold`); otherwise `unverified` with every row and SVI cited. |
| 2 | P2 | `true` published beside in-snapshot peer evidence: the producer raises `single-gateway` for `gw_count <= 1` whatever the FHRP state. | Real (`gw_count` ignores `role`; `fhrp_detail` was never read). `_GatewayScan.fhrp_gaps` withholds on a non-Active/Master role, an HSRP standby router or state, a missing detail for an Active/Master row, or unreadable detail. |
| 3 | P2 | Coverage equated "run-config captured" with "every gateway counted", but the producer counts only `VlanN` interfaces. | Real (`^Vlan(\d+)$`). Fixed structurally by address, not by a name list: `_GatewayScan.attribution` (above). The sample's routed /30 is a full transit and does not trip it. The limitation now states the `VlanN` scope. |
| 4 | P3 | Tracking text vs the row's own `tracked-object-down` flag was unchecked. | Fixed: three contradiction cases are `unverified` (above). |
| 5 | P3 | The `fhrp` sole text stayed published when the risk was withheld for reasons other than coverage. | Fixed: the text now follows the named gateway's own risk fact (above). |
| 6 | P3 | The residual claimed no tracked-object/FHRP binding exists. | Corrected: `fhrp_detail[].track` is named as the group-bound owner and recorded as a follow-up; the limitation names it. |
| 7 | P3 | Fail-open leniencies: summary vs list, flag order, unbounded witnesses. | Fixed: the summary check (a), the producer's flag order (b), and the per-gap witness cap with in-band totals (c), pinned by a 30-neighbour case rather than a timing test. |

Static checks rerun after the fixes: `py_compile` and `ruff check` on the changed Python files;
the protocol-assessability hand-list scanner and the section-dependency proof on
`cisco_toolkit/ui_projection.py` (a literal tuple of two completeness summary keys tripped the proof
and was replaced by a derivation from `CC_STATUSES`); the I12 prefix-slice walk (the new owner names
the module cites, such as `build.build_fhrp_detail` and `parse.parse_hsrp_detail`, add no
unreviewed slice); the SSOT citation resolver; an AST scan for locals shadowing module names (no new
hit); the independent static read of the stored sample and golden above; the repository privacy
verifier and the client-marker scan. No test, projection, build or browser run (owner rule).
