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

**Sole-gateway risk.** `risk` reads only the producer's `single-gateway` flag. It never carries
`no-FHRP` or `tracked-object-down`, so `false` is never a health verdict.
- The stored risk text must be the producer's flag list: `ok`, its tracking-not-assessed marker,
  or distinct flags of `tracked-object-down`, `single-gateway` and `no-FHRP` joined by `'; '`, with
  `single-gateway` never beside `no-FHRP`. Anything else is `unverified`.
- The flag must agree with the stored rows. `single-gateway` with two or more distinct switches
  naming the VLAN, or no flag with only one switch, is `unverified`, with a witness to each row. A
  gateway row of the VLAN that names no readable switch makes the count unreadable (`unverified`).
- Without the flag, `risk` is published as `false` whatever the coverage, because an unscanned
  device can only add gateways.
- The flag is published as `true` only when the scan covers every possible gateway of the VLAN.
  Otherwise it is withheld in the module's precedence (`analysis_unavailable`, then `unverified`,
  then `not_collected`), with every gap's reason and witness.

**Coverage rule** (`_gateway_coverage`). It is fleet-wide and fails closed, because VLAN carriage per
cable is not stored (G14), so a gap cannot be scoped to the VLANs it could reach. A gap is:
- a `collection_completeness` blind spot (partial or not collected), or a row of it with no readable
  status, or the record itself unreadable, absent or failed;
- a `cable_map.nodes` row not marked `collected: true` whose kind is not `ap`, `phone` or `endpoint`
  (the W23 `_IMPACT_EDGE_KINDS`), an unreadable node, a cable row that cannot be read or whose end
  joins no single node, or an unreadable or failed cable map;
- a collected device none of whose interfaces carries `run_config_observed: true` (build.py takes
  `svi_ip` only from that capture), or an unreadable devices or interfaces map.

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
`sole gateway on <host> (no FHRP)` for a VLAN with one gateway in the scan. The same coverage rule
now withholds that text, so one row never states a sole gateway in one cell and withholds it in
another. Its other texts and its FHRP record only grow more certain with coverage, and are unchanged.

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
- **Tracking stays device-level.** The producer does not bind tracked objects to FHRP groups.
- **Payload weight.** Each published gateway list repeats the fleet's gap witnesses, so the
  inventory grows by VLANs times gaps. The unchanged 300 ms sample gate remains the latency evidence.
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
