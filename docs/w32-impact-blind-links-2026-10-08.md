# W32 per-row blind-link count in failure impact (follow-up F1)

Started from main `d0e10888` (#616, W23, merged). This record closes residual **R3-3** of
`docs/w23-device-impact-validation-2026-10-08.md` ("Third refutation round"): the producer counted
evidence-less inter-switch links but never wrote that count into the row.

No local test, build, projection or pipeline ran. The owner's rule is GitHub-hosted only; locally
there was only `py_compile`, Git, reading, and `json.load` of tracked JSON.

## The defect

`analyze.compute_failure_impact` builds `blind_links`: for each switch, the inter-switch links (both
ends scanned) that carry no trunk/STP evidence on either end (`_link_has_vlan_evidence`). Such a link
is absent from every forwarding graph out of ignorance, so a VLAN the switch transits only over it is
never simulated for that switch (`touches` is false, and `off_scan_gw_vlans` cannot count it either).

The count reached exactly one place: the INDETERMINATE detail of a switch that simulated **nothing**.
A switch that simulated even one VLAN wrote a band and counts with no trace of its blind links. Its
row could read `Low` with zero stranded, and nothing in the row disclosed the links it could not reason
about. That is "not observed" becoming "healthy", the defect shape this repository guards against.

## Producer change

`compute_failure_impact` now writes `"blind_links": <int>` on **every** record, zero included.
- It is appended **after** `detail`. Every earlier field keeps its key, value and position. The sort
  key and the `detail` text are unchanged, including both INDETERMINATE branches.
- The value is the existing per-host count. Its definition is not changed: a link with evidence on
  only one end is not counted, and `offscan_links` (one end not scanned) are not model links at all.
- The docstring now lists every record field and says what the three assessability markers mean.

## Projection semantics (no schema change)

All of this lives in the shared row builder `_topology_impact` in `cisco_toolkit/ui_projection.py`,
so the fleet `/topology/failure_impact` row and the device `failure_impact` row stay one state. No
cell, property, limitation ID or keyword was added. `blind_links` is not published as a cell. Each
value it qualifies cites it as a witness (`/failure_impact/<i>/blind_links`).

**A positive count is a bound** (`_impact_blind`), treated exactly like a positive
`off_scan_gw_vlans`:
- a severity below `High` is withheld as `not_collected`, because it may understate;
- each zero count is withheld as `not_collected`, because a lower bound of zero is not a measurement
  of none;
- `High` and every positive count stay published as lower bounds, citing the count;
- the style falls to `not_observed`, never a neutral `impact_low` or `impact_medium`.

Unlike the off-scan bound, it also reaches the detail. A detail that names no simulated VLAN is
withheld as not a clean bill. The current producer never writes that combination (with nothing
simulated and a positive count it writes INDETERMINATE), so this only fails closed on an inconsistent
stored row. A per-VLAN detail stays published as the list of what was simulated.

**Holds (`_impact_hold`)**, mirroring the off-scan pair:
- `blind_links` present but not a count (text, null, negative, a boolean, a fraction or a list)
  withholds every measure and the detail as `unverified`, with a witness to the field;
- a positive count with no VLAN simulated withholds every measure and the detail as
  `not_collected`. This is the INDETERMINATE case read from the count rather than the prose, for a
  row whose detail does not carry the producer's marker.

**Unchanged:**
- The INDETERMINATE prefix hold still wins first, and that detail stays published as the
  producer's own disclosure.
- The legacy `off_scan_gw_vlans` hold, the run-config hold and the duplicate-host doubt keep their
  places and precedence.
- Bounds join in this order: off-scan, blind links, uncollected neighbours.

**Direction, stated precisely.** A row's own blind links can only make that row understate. A blind
link elsewhere can also hide an alternate path, so another switch's removal may read *worse* than it
is. That is a false alarm, not false health. So a published `High` or positive count is a lower bound
against its own row's count, not against other rows'. The `impact_scanned_scope` limitation text says
so; that text is instance data, not schema.

## Rows without the field (every snapshot stored before this change)

**Decision: an absent `blind_links` bounds the row the same way a positive count does** (`not_collected`,
witnessed by the row itself, reason: "this stored row carries no blind_links, so it predates the
producer's per-row count …"). `High` and positive counts stay published as lower bounds; a band below
`High`, every zero and a clean-bill detail are withheld; a per-VLAN detail stays published.

Why:
- Every engine before this change could hide blind links behind a partially simulated row. An absent
  count therefore cannot vouch for a band below `High` or a zero.
- A stored clean bill ("No reachability impact", Info) cannot vouch either:
  - engines written between 2026-06-26 and 2026-07-28 had no blind-link arm at all;
  - the row alone cannot show which engine wrote it (W23's residual).

  So this decision also closes the W23 residual for clean-bill rows.
- It is a **bound, not a full hold**. A measured `High` and a positive count remain true lower bounds
  against the row's own unseen links, so withholding them would discard real measurements.

Rejected alternatives:
- **Read absent as zero.** Absence would become health.
- **Gate on `generated_at`.** A timestamp is not engine identity.
- **Re-derive the count from stored interfaces.** The projection never re-simulates, and
  `test_the_projection_source_never_names_a_topology_producer` pins that.

**Consequence.** Older stored snapshots in AssessHub show these understatable cells withheld, with
that reason, until they are re-analysed offline (`--no-collect --collection-dir`), which writes
current rows. Stored rows are never patched.

## Tests (written, not run)

New tests in `tests/test_ui_projection_device_impact.py`, section (o). They drive the real
`analyze.compute_failure_impact` and `compute_cable_map` over `_blind_fleet`:
- **`g1`:** FHRP-covered and Low, with a link to `x` that carries no evidence on either end.
- **`g2`:** a fully evidenced FHRP peer that is also a sole gateway (High).
- **`acc`:** a fully evidenced clean bill.
- **`x`:** nothing but the blind link.

The tests:
1. `test_o_the_producer_writes_the_blind_link_count_on_every_row`
   - Record fields in their exact order, with `blind_links` last.
   - The count is an `int` on every row: `{g1: 1, g2: 0, acc: 0, x: 1}`.
   - The sort is unchanged.
   - `x`'s INDETERMINATE detail is unchanged.
2. `test_o_a_partly_simulated_switch_with_an_evidence_less_link_withholds_its_band_and_zeros`
   - `g1` withholds Low and its zeros, and publishes the positive counts and its per-VLAN detail,
     citing the count. The device page holds the same row.
   - Controls: `g2` and `acc` publish everything; `g1` with the count set to 0 publishes everything.
   - A positive count beside an off-scan count states and cites both.
3. `test_o_an_unsimulated_switch_keeps_its_indeterminate_hold_and_the_count_alone_holds_too`
   - The INDETERMINATE behaviour is unchanged.
   - The count-only hold applies when the prose is replaced. Control: a count of 0 publishes.
4. `test_o_a_blind_link_count_that_is_not_a_count_is_unverified`: six bad values on a High row.
5. `test_o_a_row_older_than_the_blind_link_count_never_vouches_for_a_clean_bill`
   - The legacy bound on the High, Low and clean-bill rows, and on the device page.
   - The INDETERMINATE hold and the older off-scan legacy hold still win.
   - Control: the clean bill with both markers at 0 publishes.
6. `test_o_every_sample_row_carries_the_count_its_evidence_less_links_imply`
   - **Freshness:** every sample row carries the field.
   - **Independent cross-check:** a stored `link_centrality` pair whose two resolved interface records
     carry none of the four evidence fields puts at least one link into each end's count.

Changed tests, each kept at least as strict:
- **(a)** derives every row's blind-link bound from the stored row (positive or absent), never from a
  host list, beside the existing neighbour bound.
- **(h), (i), (l)** additionally pin each real-producer row's count: x1/x2 1; every evidenced fleet 0.
  The clean bill now also requires a count of 0.
- **(j), (k)** and the unreadable-tail test compared "every measure published" on sample hosts.
  That was an incidental fact about the sample: `core1` and `dist1` may legitimately carry a bound of
  their own after regeneration. Each control now requires exact equality with the projection of the
  unmodified sample, no hold reason on any cell, and `High`, the positive counts and the detail
  published. So the hold or doubt under test still demonstrably leaves the row untouched.
- `tests/test_ui_projection_topology.py`
  - The hand-built fixture row now carries `blind_links: 0`, as a current producer row does; without
    it, the row is correctly bounded.
  - The full-count test pins a count of 0.
- `tests/test_analyze_absence_is_not_health.py` (#13): the counts are `{access1: 1, transit1: 2,
  core1: 1}`. `core1` is a High row that hides its link, which is the F1 shape. Every count is 0 once
  trunk evidence is present.
- `tests/test_sample_fleet.py`: a third sub-field freshness class, `blind_links` on every
  `failure_impact` row.

The golden guards in `tests/test_golden_guard.py` are untouched.

## Regeneration dependency (W31): tests expected to fail until then

This changes stored engine output. `tests/golden/snapshot.json` and
`webapp/sample_data/sample_fleet.snapshot.json` must be regenerated on GitHub-hosted runners through
W31's handoff and imported. They were **not** hand-edited. Until then, these tests are expected to fail:

| Test | Why |
|---|---|
| `tests/test_pipeline_golden.py::test_snapshot_matches_golden` | `failure_impact` rows gain `blind_links`. |
| `tests/test_pipeline_golden.py::test_golden_does_not_depend_on_the_wall_clock_past_every_registry_window` | It runs the same section comparison against the same golden. |
| `tests/test_sample_fleet.py::test_sample_fleet_carries_engine_subfields_the_superset_check_is_blind_to` | Stale-sample guard for the new sub-field. |
| `tests/test_ui_projection_device_impact.py::test_o_every_sample_row_carries_the_count_its_evidence_less_links_imply` | The same freshness guard. |
| `tests/test_ui_projection_device_impact.py::test_n_two_rows_naming_one_host_are_unverified_and_agree_on_both_surfaces` (all three modes) | Before regeneration, `core1` has no count, so its zero cells carry the legacy blind-link reason beside the duplicate doubt. That reason contains "predates", which the unchanged assertion forbids on the non-held row. It passes once `core1` carries its count. |

Expected to keep passing before regeneration, because they derive from the stored row:
- (a), (j), (k) and the unreadable-tail test;
- every real-producer test, including all new (o) producer tests;
- `test_ui_projection_topology`;
- the webapp native smoke for `/failure_impact`, which adds no float.

Sample bytes cascade outside this branch:
- Regenerating the sample changes its digest.
- Atlas Scope's derived files bind that digest: `atlas-scope/src/data/fabric.json`,
  `src/forwarding/acl-bindings.json`, `src/forwarding/rib-evidence.json` and
  `src/panels/producer-emission.json`.
- Those must be recompiled through the Codex-held scope compile handoff, not on this branch.

**Predicted sample effect after regeneration** (read with `json.load`, not computed):
- The stored pair `core1 Gi1/0/40` / `dist1 Gi1/0/3` has no trunk/STP field on either end. Both
  are routed ports with an address on the physical interface. So `core1` and `dist1` should each
  carry `blind_links` 1, and every other row 0.
- `core1` (High) would then withhold `backup` and `fhrp` (0).
- `dist1` (Low, FHRP-covered) would withhold its band and its three zeros, keep `vlans_impacted`
  and `fhrp` (2 each) published as cited lower bounds, and keep its per-VLAN detail.
- No other row changes.

The hosted regeneration decides. Test (o)'s cross-check needs only a count of at least 1 for those two
hosts, not this prediction.

## Consumers to notify (the field is additive; none of these was changed here)

- **Atlas Scope compiler, held by Codex:** `atlas-scope/tools/lib/compile-model.mjs` reads
  `severity`, the counts and `detail` raw into `impact`. It reads neither `off_scan_gw_vlans` nor
  `blind_links`, so a Scope node can show a band the projection withholds.
- **Raw-row renderers.** None of these applies the projection's holds:
  - workbook sheet `excel.write_failure_impact_sheet`; adding a column would change
    `tests/golden/sheet_schema.json`;
  - `deck.py` keystone slide;
  - `runbook.py`, `ops.py`, `archreview.py`, `design.py` and `mop.py`;
  - `mcp_server.failure_impact`, a fixed column pick;
  - `analyze.compute_device_dossiers` ("no modeled reachability impact" prose);
  - `protocol_assurance.cutover_operator_evidence`, which copies whole rows, so the field rides along;
  - AssessHub `webapp/backend/cutover.py`, `summary.py`, the raw section table and the dossier
    recompute (W23's list).
- **Explorer:** `blast_radius_explorer.html` re-simulates in JS. It flags blind adjacency only when
  its verdict is otherwise Info, the same gap one surface over.

## Findings for follow-up (not fixed here)

- **F2, deck false clean bill.** `deck.py` counts INDETERMINATE rows only by `off_scan_gw_vlans`.
  Take a fleet whose switches are INDETERMINATE only because of blind links, with no stranded
  keystones. It gets the green "dependency is well distributed" line. The per-row count makes the fix
  a one-field read.
- **F3, routed links counted as blind.** `_link_has_vlan_evidence` does not read a routed port (an
  address on the physical interface) as positive "carries no VLAN" evidence. Routed point-to-point
  links are therefore counted as blind, including the sample's `core1`/`dist1` link. Refining that
  definition moves existing INDETERMINATE details, so it needs its own slice and golden.
- **F4, links with one end's evidence.** A link with evidence on one end only is never a forwarding
  edge (`_link_carries` needs both ends), yet it is not counted. Same producer-definition slice as F3.
- **F5, one shared assessability helper.** Every raw-row renderer above needs the same three
  markers. An engine-owned helper would close that class instead of a per-surface list.

## Schema and pins

No schema-building code, limitation ID, property or keyword changed. Only the `impact_scanned_scope`
text changed, and that is instance data (`Limitation.text` is a plain string). The native pins
(view `a2fd2b99…`, list `c47a6cef…`) are therefore unchanged by construction. They were not
recomputed locally, because this slice's rule allows no module import beyond `py_compile`. The hosted
pin and prospective-parity tests decide.
