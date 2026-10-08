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
