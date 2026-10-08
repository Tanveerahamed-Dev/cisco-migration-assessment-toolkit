# W23 device failure impact and structural links

Started from main `a816bfca`. This record covers gaps G10 and G11. The device page now carries
the stored `failure_impact` row and the `link_centrality` rows that name the device. They are
selected by exact host, built by the fleet topology's own row builders, and never re-simulated.

An empty `failure_impact` selection is `not_collected`, never "no impact".
`compute_failure_impact` writes one row for each `build_network_model` host. An empty
`structural_links` selection is also `not_collected`, because the host-pair model keeps only
links whose two ends were both scanned. A duplicate impact row is `unverified`, and one row is
never picked over the other.

No local test, browser, SPA build, benchmark or frozen smoke was run; the owner's rule is
GitHub-hosted only.

## Native transport schema re-pin

The first hosted run of bootstrap `e0a545f5` reported 99 failures:
- CI job `113260469865`: Tests · py3.13 · ubuntu-latest;
- CI job `113260545113`: Backend e2e tests.

All 99 sit in the native-transport group of `webapp/tests/test_ui_projection_api.py`:
- the pin assertion;
- the prospective-pin parity matrix;
- the W12a/W13 native-parity tests, whose native validator was disabled by the hash mismatch;
- the request-local native smoke;
- the reaudited topology-list check.

Every other test passed, including the new `tests/test_ui_projection_device_impact.py`. The
frontend type-check and build job also passed, including the generated-type `api:check`.

### Reviewed structural delta of the transport schemas

The delta adds no keyword outside the established domain. It uses only `$ref`, `properties`,
`required`, `additionalProperties`, `minItems`, `maxItems`, `oneOf`, `allOf`, `const` and `type`.
The last three come from the existing transport wrappers in `_view_schema` and `_LIST_SCHEMA`:

1. `DevicePage` gains two required properties, `failure_impact` and `structural_links`. They
   are `$ref`s to the existing `TopologyImpactRowList` and `TopologyStructuralLinkRowList`
   definitions, which the topology views already validate.
2. The device limitations array grows from 15 to 17 fixed items (`minItems` = `maxItems`).
   The two added entries re-address the existing limitation IDs `topology_scanned_model` and
   `impact_scanned_scope` into the device document. No new limitation ID or text exists.
3. The list union gains the two device list paths for the new sections, in owner property
   order.

The provider version (`jsonschema-rs` 0.58.5), the private resolver guard, the admitted
instance domain (`_native_instance_allowed`) and the offline Python fallback are unchanged.

**One behavioural consequence:**
- `TopologyStructuralLinkRow.betweenness` is a JSON float, and the admitted native domain
  excludes floats.
- So a device view that carries structural-link rows is validated by the offline Python path,
  exactly as topology views already are.
- Correctness and public errors are unchanged; native acceleration does not apply to those
  device views.
- The opt-in 300 ms projection performance measurement remains the latency evidence.

### Hashes

The hashes are compact `ensure_ascii` JSON plus LF, in owner key order. Values are taken from
the hosted assertion output of the jobs above and were not computed locally. The follow-up pair
below supersedes them:

- view: `ccce3f33ce10533fad39e9bf9b33ee677497b3cbbcc6ad78a3a5feb2d4adc866`
- list: `110640131dd9e789538b4ce43dcc02a75128e8bc25d94906e1829739ab440c11`

The W12b prospective-pin parity test carries the same pair. W24 (#617, the G43 vocabulary block)
moves the same pins. Whichever of the two merges second takes current main, and re-pins on top
of the combined schema with its own reviewed delta.

All required hosted checks on the exact final head remain mandatory, and so does independent
refutation by Codex.

## Follow-up delta after independent refutation

An independent refuter reviewed head `e174471f`. This delta answers its findings P2-1 and P3-2
through P3-8. It is behavioural first; the schema change is one more fixed limitation item.

**Behaviour**
- Both producers compute over every scanned device's evidence. While `collection_completeness`
  lists any blind spot, `/topology/failure_impact`, `/topology/structural_links` and the two
  device selections carry `fleet_lists_exclude_blind_devices`, with a witness ref to each
  blind-spot row. An empty list is then `not_collected`, never "nothing found". This is the
  `_fleet_qualify` precedent already used by the VLAN, endpoint and findings lists. Nodes and
  cables stay unqualified: they are discovery observations, and an uncollected peer stays a row.
- Structural links take the qualifier too. A missing peer can only make a link look like a
  bridge, so `is_bridge: false` holds. But `pairs_cut`, `betweenness` and `rank` can move either
  way when a device behind the link was not collected.
- The device `failure_impact` gap check also requires the running-config (`config=True`).
  `build.py` takes `svi_ip`, the simulation's gateway input, only from the running-config parse.
- A row that opens with the producer's `Blast radius INDETERMINATE` marker withholds its
  severity and counts as `not_collected`, with a witness to `detail`. So does a row whose
  positive `off_scan_gw_vlans` comes with no simulated VLAN. Its style is `not_observed`, never
  `impact_info`. A row that simulated some VLANs and also counts off-scan ones keeps its
  measured values as lower bounds. Each value cites `off_scan_gw_vlans`, following the
  dossier-band precedent. A test drives the real `analyze.compute_failure_impact` to pin the
  marker.
- A one-row-per-device selection with a capture gap now says the row's values may be
  unreliable. A duplicate row keeps the device's gap reason and witnesses. A row the exact-key
  join cannot read makes both new selections `unverified`, with a witness to that row.

**Transport schema delta**
1. The device limitations array grows from 17 to 18 fixed items (`minItems` = `maxItems`). The
   change reaches `DevicePage` and every device view and list variant's `limitations` copy. The
   added entry re-addresses the existing payload limitation `fleet_lists_exclude_blind_devices`.
   It adds no new limitation ID, property or keyword.
2. Limitation `text` and `applies_to` values are instance data, not schema. Two texts changed
   (`fleet_lists_exclude_blind_devices` and `impact_scanned_scope`), and the first gained the two
   topology paths.
3. Each of the 20 device limitation tuples in `openapi.ts` gains one item by hand. The hosted
   `api:check` decides exactness.

**Hashes.** These were computed locally by deterministic serialisation only. The script called
`_native_schema_hash` on `_VIEW_SCHEMA` and `_LIST_SCHEMA`, imported from this worktree. It ran no
test, build or validator. The hosted pin and prospective-parity tests confirm them:

- view: `a2fd2b9994569b2fd3a3df72e3410ae1b74ff41c26833a62239514c677f9de32`
- list: `c47a6ceff24a7392fa9b248ece33b36381f9fd27fc67d3d52ea3d8238a37e0c9`

## Second refutation round

An independent refuter reviewed head `e3f63cca`. This round changes behaviour only. The transport
schema and both native pins are unchanged.

**N1 (P2): a partly simulated row could read as a low verdict.** Take a row that simulated some
VLANs and also counts `off_scan_gw_vlans` above zero. It covers only its VLANs with an in-scan
gateway.
- Its severity is withheld as `not_collected` unless it is `High`, the worst band, which cannot
  be understated. The reason says the severity may understate the blast radius and gives the
  off-scan count. The witness is `off_scan_gw_vlans`.
- The style then follows the withheld-state precedence (`not_observed`). It is never a neutral
  `impact_low` or `impact_medium`.
- A zero count is withheld as `not_collected`, because a lower bound of zero is not a
  measurement of none. Its reason says lower bound, and its witness is `off_scan_gw_vlans`.
- `High` and each positive count stay published as lower bounds, each citing
  `off_scan_gw_vlans`. A published fact carries no reason in the closed schema, so the
  `impact_scanned_scope` text says "lower bound" for them.
- Tests drive the real `analyze.compute_failure_impact` for three cases: a partial Low row (an
  FHRP-covered gateway), a partial Medium row (a backup-covered transit) and the High control.

**N2 (P3): the running-config gap keyed on the wrong capture.**
- `build.py` takes `svi_ip`, the simulation's gateway input, only from the scoped `show
  running-config interface` or `| section ^interface` capture. It marks every interface that
  capture parsed with `run_config_observed: true`.
- The security row comes from the full `show running-config`, which is not that input.
- The hold now applies when no interface of the device carries `run_config_observed: true`.
- An absent marker reads as not captured, so the rule fails closed.
  `html.sparsify_interfaces` drops a false marker, and snapshots that predate the marker
  carry none.

**N3 (P3): the fleet and device surfaces disagreed.**
- The hold lives in the shared row builder `_topology_impact`. The fleet
  `/topology/failure_impact` row and the device row therefore withhold the same severity and
  counts, with the same reason and an `/interfaces/<host>` witness.
- The device selection's separate running-config gap (`config=True`) is removed. That leaves
  one source of truth and no double state.

**Legacy rows.** A row without `off_scan_gw_vlans` predates the producer's assessability marker
(2026-06-26). Whatever its band, its severity and counts are withheld as `not_collected`, with the
row itself as witness.

**Effect on the sample.** In `webapp/sample_data/sample_fleet.snapshot.json`:
- every device carries `run_config_observed`;
- every row carries `off_scan_gw_vlans` = 0, so no row is partial;
- so no fleet row changes.

The device `failure_impact` selections of `core2`, `podacc1` and `podacc2` move from
`not_collected` to `published`. These devices have no security row, but they do have the scoped
interface capture.

**Residuals not closed here**
- Rows written between 2026-06-26 and 2026-07-28 carry `off_scan_gw_vlans`, but they predate the
  blind-trunk INDETERMINATE marker. In that window, a switch whose links all lacked VLAN evidence
  read "No reachability impact", and the row alone cannot show which engine wrote it.
- Snapshots written before 2026-08-10 carry no `run_config_observed`, so every one of their rows
  is held.
- A device whose gateway capture is missing can also skew other devices' rows: they may see its
  VLANs as off-scan or as single-gateway. The hold covers only its own row.
- A row that is not INDETERMINATE but was simulated over evidence-less links carries no marker of
  that.

**Schema and pins.** No limitation ID, property or keyword changed. Only the `impact_scanned_scope`
text changed, and that is instance data. Both hashes were recomputed locally with
`_native_schema_hash` and are unchanged:

- view: `a2fd2b9994569b2fd3a3df72e3410ae1b74ff41c26833a62239514c677f9de32`
- list: `c47a6ceff24a7392fa9b248ece33b36381f9fd27fc67d3d52ea3d8238a37e0c9`

No local test, build or projection ran. The hosted gates and the next refutation decide.

## Third refutation round

An independent refuter reviewed head `5a88283b`. This round changes behaviour only. The transport
schema and both native pins are unchanged. Both fixes live in the shared row builder
(`_topology_impact` in `cisco_toolkit/ui_projection.py`), so the fleet `/topology/failure_impact`
row and the device `failure_impact` row keep one state.

**R3-1 (P2): a held row still published a clean-bill detail.**
- Before this round, the `detail` cell had no pre-check. A row whose measures were held could
  still publish "No reachability impact from removing this switch (within the scan)." A row is
  held when no interface carries `run_config_observed`, when a legacy row has no
  `off_scan_gw_vlans`, when the off-scan count or host cannot be read, or when a positive off-scan
  count comes with nothing simulated.
- Now the detail is withheld with the same state, reason and witness as the measures
  (`_impact_detail_pre`).
- One exception stays published: a detail that opens with the producer's
  `IMPACT_INDETERMINATE_PREFIX` ("Blast radius INDETERMINATE"). That text is the producer's own
  statement that the switch could not be assessed. It is a disclosure, not a clean bill.
- A partial row keeps its per-VLAN detail published. A partial row simulated some VLANs, counts
  `off_scan_gw_vlans` above zero, and has no hold. Its detail lists only what was simulated
  ("VLAN 10: Hard partition ..."), so it claims nothing about the VLANs that were not. The other
  cells already carry the disclosure: a band below `High` and each zero are withheld, `High` and
  each positive count cite `off_scan_gw_vlans`, and the `impact_scanned_scope` text says "lower
  bound".
- Tests:
  - (j) and (k) now require the held detail, with the run-config and legacy reasons and witnesses.
  - (h) requires it for the off-scan-only and unreadable-count holds, and keeps the
    INDETERMINATE detail published.
  - (k) also pins a legacy row whose detail is INDETERMINATE: that detail stays published.
  - (i) still requires the partial row's detail to be published.

**R3-2 (P2): a switch facing an uncollected downstream neighbour got a published clean bill.**

`analyze.compute_failure_impact` simulates only scanned switches. `stranded` counts endpoints on
other scanned switches, and `off_scan_gw_vlans` counts only VLANs whose gateway is off-scan.
Endpoints behind a CDP-seen but never-collected switch therefore count nowhere.
`collection_completeness` lists only inventory devices, so the existing fleet qualifier does not
see that peer either.

The fix is a selection of stored rows, not a re-simulation (`_impact_peers`):
- Select the `cable_map.cables` rows that name the row's host exactly as one end. The join is the
  same exact-text join as `_topology_join`, through the cached `_Ctx.index`.
- Join each far end to `cable_map.nodes` by exact host.
- The row is bounded unless that join finds exactly one node, and the node either:
  - carries `collected: true`; or
  - carries `collected: false` and a kind the producer positively marks as edge gear.

**Which kinds count, from the producer.** `analyze.compute_cable_map` writes
`collected = h in all_interfaces`. A collected node gets `kind: "device"`
(`CABLE_MAP_COLLECTED_KIND`). An uncollected node gets `_node_kind(...)`, which returns one of
`switch`, `router`, `firewall`, `ap`, `phone`, `endpoint` or `unknown`.
- `_node_kind` ranks infrastructure first across every observer (`_KIND_RANK`), and platform
  evidence outranks endpoint type. So a peer is `ap`, `phone` or `endpoint` only when no
  observer's evidence says switch, router or firewall.
- The producer comment says a front end may hide only these positively identified kinds, and that
  `unknown` always stays visible.
- `build_network_model` refuses CDP-speaking phones and APs as uplinks
  (`_is_offscan_uplink_port`).
- What hangs off an AP or a phone depends on the removed switch's own port. The producer already
  excludes that case by its declared scope: the removed switch's own endpoints move with it.

So `_IMPACT_EDGE_KINDS` = {`ap`, `phone`, `endpoint`} bounds nothing. Every other kind is
included, because it can carry endpoints or transit: `switch`, `router`, `firewall`, `unknown`,
a missing or unrecognised kind, or `device` on a node marked uncollected. A node whose
`collected` is neither `true` nor `false` is included too.

**What a bounded row withholds.** The row cannot account for endpoints behind N uncollected
neighbour(s). It withholds these cells as `not_collected`, with that reason and a witness to each
such cable row:
- a band below `High`;
- each zero count;
- a detail that names no simulated VLAN (no readable positive `vlans_impacted`), which is the
  producer's clean bill.

`High` and positive counts stay published as lower bounds and cite each cable, following the
partial-row precedent. A per-VLAN detail stays published, as in R3-1. A row bounded by both the
off-scan count and a neighbour carries both reasons and both witnesses.

**It fails closed.**
- A far end that joins no node, or more than one node, counts as uncollected. The reason says how
  many failed closed.
- A cable row the join cannot read (not an object, or `a`/`b` not text) could name any switch, so
  it bounds every row (`_Ctx.unjoinable`).
- A cable list that cannot be read bounds the row with the list's own state:
  - `analysis_unavailable` for a failed cable-map phase, with its failure record;
  - `unverified` for a malformed list;
  - `not_collected` for an absent list.

**Effect on the sample** (`webapp/sample_data/sample_fleet.snapshot.json`, read with `json.load`):
- It has three uncollected peers:
  - `AP-floor1`, kind `ap`, cabled to `access1` to `access17`;
  - `AP-floor3-01`, kind `ap`, cabled to `core2`;
  - `wan-edge-rtr1.lab`, kind `router`, cabled to `core2` by `/cable_map/cables/35`.
- Only `core2` changes. Its row is `High`, so the band stays published. So do `vlans_impacted` 3,
  `stranded` 42, `hard` 3 and the per-VLAN detail. Each measure now cites
  `/cable_map/cables/35`.
- `core2`'s `backup` and `fhrp` (both 0) become `not_collected`.
- Every access switch faces only an AP, so it is unchanged.
- No sample row is held, so R3-1 changes nothing in the sample.

**Tests.**
- (a) now derives the bound independently from the stored cable map. It pins `core2` as the only
  bounded host, and the router as its only bounding peer.
- Four new (l) tests drive the real `analyze.compute_failure_impact` and
  `analyze.compute_cable_map`:
  - An uncollected downstream switch withholds the clean bill on both surfaces. In the control,
    the same stored row is published once the node reads `collected: true`.
  - An uncollected AP or phone bounds nothing. Six stored-node mutations each bound the row: kind
    `unknown`, no kind, kind `AP`, kind `device`, no `collected`, and `collected` as the string
    `"false"`.
  - A `High` row facing an uncollected router keeps its band, positive counts and detail. It
    withholds only its zeros.
  - Six fail-closed modes: a duplicate node, a missing node, an unreadable cable row, a malformed
    cable list, an absent cable list, and a failed cable-map phase.
- The `impact_scanned_scope` text (instance data, not schema) now states both rules.

**Residuals outside this slice (no code here)**
- **R3-3, producer.** `analyze.compute_failure_impact` counts `blind_links`: inter-switch links
  with no trunk/STP evidence on either end (`cisco_toolkit/analyze.py:1228` to `1232`). It reports
  them only in the INDETERMINATE detail of a switch that simulated nothing (`:1305`), and never
  writes the count into the row. A partially simulated switch can therefore hide evidence-less
  links. Fixing that needs an engine change, plus a regenerated golden snapshot and sample.
- **Other surfaces still render raw `failure_impact` rows without these holds.** Located with
  `git grep`:
  - `webapp/backend/cutover.py:174`: `_worst_blast_radius`, which sets each wave's
    `blast_radius` (`:566`);
  - `webapp/backend/summary.py:116`: `_keystones`, whose fallback sorts raw rows by severity and
    `stranded` (`:131` onward);
  - the AssessHub snapshot table: the `("failure_impact", "Failure impact")` tab in
    `SECTION_LABELS` (`webapp/backend/summary.py:55`), which
    `GET /api/snapshots/{snapshot_id}/section/{name}` serves raw (`webapp/backend/app.py:3251`);
  - in the same route, the dossier recompute (`webapp/backend/app.py:3296`), which also passes
    raw rows to `analyze.compute_device_dossiers`.
- **A truncated scoped capture.** A scoped interface running-config capture can be cut short. It
  then marks some interfaces `run_config_observed` while missing SVIs. The projection cannot
  detect that, because one marked interface lifts the hold.

**Schema and pins.** No limitation ID, property or keyword changed. Only the
`impact_scanned_scope` text changed, and that is instance data. Both hashes were recomputed
locally with `_native_schema_hash` on `_VIEW_SCHEMA` and `_LIST_SCHEMA`. They match the pins
before and after this round:

- view: `a2fd2b9994569b2fd3a3df72e3410ae1b74ff41c26833a62239514c677f9de32`
- list: `c47a6ceff24a7392fa9b248ece33b36381f9fd27fc67d3d52ea3d8238a37e0c9`

No local test, build or projection ran. The hosted gates and the next refutation decide.
