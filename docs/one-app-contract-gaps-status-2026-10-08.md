> **Dated record (2026-10-08).** This is a status reconciliation of the contract-gap register
> `docs/one-app-contract-gaps-2026-09-30.md` against `main` at `a816bfca`. It is not a work queue.
> Start an item only after giving it a row in `docs/NOW.md`. The register's own text, counts and
> "what the page shows today" lines describe 2026-09-30 and are now partly stale. This file says
> where. Line numbers refer to `cisco_toolkit/ui_projection.py` at `a816bfca` and will drift.
> Re-check the code before relying on them.

# Contract-gap status, 2026-10-08

On `main` at `a816bfca`:

| Status | Count |
|---|---|
| Closed | 8 |
| Partial | 9 |
| Open | 32 |
| Obsolete | 0 |
| **All** | **49** |

The closed count has two caveats:
- G13 is counted once. Its VLAN-wave residual is also closed.
- G18 is partial in name only. The alternative owner, `project_path`, closes most of it.

## P1 items

| ID | Status | Evidence on `main` | What remains |
|---|---|---|---|
| G01 | Closed | `_health_bands` (`ssot.health_band_partition` plus reconcile); `HealthBandRow`; `FleetHealth.bands` | — |
| G06 | Closed | `_readiness` and `_readiness_problem`; `Readiness`, `ReadinessGroupRow` and `ReadinessCheckRow`; `Overview.readiness` | — |
| G08 | Open | `_trust` has census, failures, coverage_matrix, unknown_evidence, ssot and limitations only | The whole item |
| G09 | Closed | `_device_finding_rollup` (engine fold `analyze.compute_device_findings`); `DeviceRow.findings`; `DevicePage.findings_rollup` | Withheld unless running-config capture custody is positive |
| G10 | Partial | Fleet `topology.failure_impact` (`_topology_impact`, `TopologyImpactRow`); caveat `impact_scanned_scope` | The device-page selection. In progress as W23 (`claude/device-impact-spof`) |
| G11 | Partial | Fleet `topology.structural_links` (`_topology_structural`, `TopologyStructuralLinkRow`) | The device-page selection (W23). Centrality is per host pair, not per cable |
| G12 | Closed | `_device_coverage_rollup` (`coverage_matrix.compute_device_coverage`); `DeviceRow.coverage`; `DevicePage.coverage_rollup` | Zero abstentions publish as unverified, never "all covered" |
| G13 | Closed | `_move_group_fact` and `_move_group_problem`; `DeviceRow.move_group`; `DevicePage.move_group`; VLAN `wave` checked by `_vlan_wave_pre`. The engine now writes `group` | The register's "engine defect" text is stale; the limitation now covers legacy rows only |
| G14 | Open | No carriage fact anywhere; `analyze._link_carries` is internal and nothing is stored | Needs a stored engine section first (schema, golden and sample regeneration), then the projection |
| G15 | Partial | VLAN-level election: `stp_root_state`, `stp_root_reason`, `stp_root_claimants` and `stp_root_identities` (`_stp_contract`, `_stp_verdict_pre`) | `selections.stp_roots` is still a bare pointer list, not a per-(device, VLAN) fact list of is_root, root address and root priority |
| G22 | Closed | `_finding_evidence`, `_evidence_list` and `_evidence_problem`; finding-row `evidence_*` cells | The limitation `punch_rows_carry_no_evidence_pointers` now applies to legacy rows only |
| G42 | Closed | `CoverageItem` (`dimension`, `verdict_source`, `is_abstention`) via `_coverage_join` | — |
| G43 | Partial | `LifecycleBand` rank; the topology legend owns link op status, impact severity and bridge tokens | No rank or class block for health band, risk band, VLAN readiness, exposure state, security grade and status, coverage state, unknown-evidence state or punch severity |
| G49 | Closed | Exposure `input_state` (`DOSSIER_INPUT_STATES`, `DOSSIER_EMPTY_IS_CLEAN`); the engine's `DOSSIER_AXIS_INPUTS` | — |

## P2 and P3 items

**Partial:**
- **G45:** topology nodes carry the engine's `collected` flag. The inventory still has no
  three-state collection verdict.
- **G17:** the address index `topology.source_addresses` exists. `NeighborRow` still has no
  `peer_host`.
- **G21:** a per-device severity facet exists via G09. There are no fleet facets.
- **G18:** mostly closed by `project_path`. The opt-in `traffic_assurance_set/1` flows are not
  projected.

**Open:** G02, G03, G04, G05, G07, G16, G19, G20, G23, G24, G25, G26, G27, G28, G29, G30, G31,
G32, G33, G34, G35, G36, G37, G38, G39, G40, G41, G44, G46, G47 and G48.

## Register text that is now misleading

- **G13:** the "engine defect" is fixed. The engine writes the group label.
- **G22:** the evidence-pointer limitation is legacy-only.
- **G49:** the sparse-dictionary absence problem is fixed by the per-exposure `input_state`.
- **G01, G06, G09, G12 and G42:** the register says "the contract drops or publishes none".
  That is stale.
- **G43:** says link op status "has no owner at all". The topology legend now owns it.
- **G10, G11 and G18:** describe neutral overlays and placeholder tabs. The fleet topology
  block and `project_path` exist; only the device joins remain.
- **G45:** says "the map can only use roster membership". Topology nodes now carry `collected`.
- **Numbering collision:** some earlier commits and the `ui_projection` docstring say "G14" and
  "G15". That is an earlier review's numbering, where G15 meant absence rendered as a
  measurement and G14 meant a failed phase read as collected. It does not close this register's
  G14 or G15.

## Suggested next P1 order

Ordered by value against effort:

1. **G10/G11** (W23, in progress).
2. **G43:** an engine-owned `rank` and `class` per closed vocabulary.
   - Pin each rank to its owner in tests.
   - Unknown, Unassessed and Insufficient Data must class as undetermined, never as passing.
3. **G15 residual:** turn `selections.stp_roots` into a fact list read from
   `/stp_roots/<host>/<vid>`.
   - Never re-elect a root from these rows.
   - A malformed `is_root` is unverified, never false.
4. **G08:** `trust.inputs` over a closed registry of inputs.
   - "No row" means "could not assess" only for producers that write a record for every
     collected device.
   - Findings-only sections stay excluded or unverified.
5. **G14:** needs a new stored engine section first. One end with no evidence must read not
   collected, never blocked.
