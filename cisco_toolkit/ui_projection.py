"""ui_projection/1 -- the ONE typed projection from a snapshot to what a screen shows (D9).

"Facts in Python, geometry in the browser." Every verdict, count, rollup, denominator, severity band
and evidence state a UI renders is decided HERE, from the engine's owners, and published in one
schema-tagged payload. The browser only lays out, sorts, filters and draws; it never aggregates, never
re-derives a headline number and never turns an absence into a value.

Slice 1 covers two screens:

* ``overview`` -- the canonical headline facts (:data:`ssot.CANONICAL_FACTS`), the fleet-health
  scoring state, the executive-brief axes (and the registered axes the brief does not carry), the
  top-gating list, the posture statement, and the lifecycle band partition in its canonical order;
* ``trust`` -- the live schema census, the failed-phase record, the published coverage matrix, the
  unknown-evidence summary, the SSOT self-verification, and the projection's own stated limitations;

plus an ``engine`` block naming the snapshot schema and producer versions.

Slice 2 adds the row screens:

* ``inventory`` -- device rows (the ``devices`` map joined with the ``collection_completeness`` blind spots,
  so an unreached device is never dropped), VLAN cutover rows, endpoint rows with their shared-IP and
  dual-homed lists, and the cable-map peers nobody collected; every list in a stable order with a total
  from its owner, ready to be paged;
* ``findings`` -- the engine's punch-list rows, with the severity vocabulary, the remediation the engine
  links and the show command it cites, and nothing it does not publish;
* :func:`project_device` -- one standalone device page per host (identity, physical, blind-spot record,
  health, lifecycle, dossier, coverage, interfaces, links, routes, routing neighbours, security checks,
  native-VLAN mismatches, remediation, NRFU cases, and the punch-list rows and endpoints naming it).

A row cell never goes through a dotted path (a hostname can contain a dot): it takes its section's state,
the owner's device scope, its row join by exact key (two rows naming a key are ``unverified``, never picked
between), then its own not-observed rule and type check. Engine defaults that mean "not observed" (the
DevicePhysical ``""`` and ``0``, the ``[NOT OBSERVED]`` markers, sparse interface fields, empty routing
neighbour lists) are withheld, never published as values. A list the engine caps says so, and its total
is never computed. Nothing is aggregated here: the engine publishes no per-device finding counts, no
severity facets and no evidence pointers behind a punch-list row, so none appears.

Every fact travels in one envelope::

    Fact     = {state, value, subject, refs:[{pointer, role}], basis, reason?, engine_state?,
                engine_state_owner?, caveats?}
    FactList = {state, subject, refs, basis, reason?, engine_state?, engine_state_owner?, caveats?,
                items:[...]}

``state`` is one of :data:`STATES`: the engine's abstention codomain (``ssot.ABSTENTION_STATES``) plus
the two fleet-health domain tokens of ``ssot.fleet_avg_health`` (``not_assessed`` / ``unverified``).
No new token is invented; :data:`DOMAIN_STATE_OWNERS` names who applies each domain token, and the
projection applies ``unverified`` itself by the rules below. ``value`` is ``None`` unless
``state == "published"``; ``reason`` is present exactly when it is not. ``engine_state`` keeps the
raw token of the owner named by ``engine_state_owner`` whenever the projected state differs from it.
``caveats`` names the :data:`LIMITATIONS` that qualify a value, on the value itself. ``subject`` is the
RFC 6901 address of the value (``None`` for a value an owner computes live); every ``refs`` pointer
resolves in the snapshot. ``basis`` names the owner that produced the value; a ``basis`` REF role
names an input section.

How the state of a scalar at dotted path P is decided, first match wins:

1. ``analysis_unavailable`` when ``ssot.abstention_reason`` says so for P or any section P is
   computed from (it folds in the failed-phase record and ``ssot.DERIVED_FACT_BASIS``).
2. ``unverified`` when an owner raised on this snapshot (for example nesting deeper than the
   interpreter's recursion limit): nothing is claimed.
3. The fleet-health posture facts defer to ``ssot.fleet_avg_health``: over a fleet with nothing
   scored a stored ``None`` / ``0`` / ``""`` is ``not_assessed``, never a measurement (G15).
4. ``not_collected`` stays a blind spot (an engine ``null`` says so in its reason).
5. A present value that carries no evidence (``0`` / ``False`` / ``""``) computed from a basis section
   this snapshot did not collect is ``not_collected``: it was computed over nothing.
6. The value must pass its slot's type check (count / score / text / flag / closed enum / fixed
   record); anything else -- NaN, inf, a negative count, a bool count, an integer a browser cannot
   hold exactly (above 2^53-1), an out-of-vocabulary band -- is ``unverified``: withheld, never
   coerced. (An empty text or enum is the producer's "none observed": ``collected_but_empty``.)
7. The posture statement, one sentence over five inputs, is ``not_collected`` when any input was.
8. A present scalar ``0`` / ``False`` the abstention core labels ``collected_but_empty`` is a MEASURED
   zero and is published, unless its owner's own domain state says the input was incomplete (the
   unknown-evidence summary state) or a known engine defect makes it unverifiable (the coverage
   matrix). The section-level deep-empty predicate is not reused for scalars.
9. A value ``ssot.reconcile`` rejects is ``unverified``, whatever rules 3-8 decided -- except a G15
   ``not_assessed`` over zero scored rows, where reconcile says the same thing and is quoted.

A list takes its own state, then rolls up its inputs: a failed input makes it ``analysis_unavailable``,
a contradiction with the producer's rule makes it ``unverified``, and an uncollected input makes it
``not_collected`` ("may be incomplete") -- never ``collected_but_empty``.

The projection is pure and total: no I/O, no clock, no network, never mutates its input, and builds
its output from new containers after a type check per slot, so no raw subtree (and no NaN) can reach
JSON. Rows derived from snapshot KEY order are sorted by key; list order the engine wrote is kept.

The JSON Schema (draft 2020-12) is embedded (:func:`ui_projection_schema`) and generated from the
module constants on every call, so its enums cannot drift from the code; ``tests/test_ui_projection.py``
holds each constant equal to its engine owner. Every typed fact is a closed ``oneOf`` of a published
and a withheld branch, so generated TypeScript narrows ``value`` on ``state``.
"""
from __future__ import annotations

import math
import re
from types import MappingProxyType
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from cisco_toolkit import __version__ as _CODE_SCHEMA_VERSION
from cisco_toolkit import ssot

SCHEMA = "ui_projection/1"
SCHEMA_ID = "urn:atlas:schema:ui-projection:1"

AU = ssot.ANALYSIS_UNAVAILABLE
_PUB = "published"
_CBE = "collected_but_empty"
_NC = "not_collected"
_NA = "not_assessed"
_UV = "unverified"
_FAULT = "\x00owner-fault"          # internal: an owner raised; never emitted (projected as unverified)

#: Projected evidence states: the engine's abstention codomain + the fleet-health domain tokens.
STATES: Tuple[str, ...] = tuple(ssot.ABSTENTION_STATES) + (_NA, _UV)
WITHHELD_STATES: Tuple[str, ...] = tuple(s for s in STATES if s != _PUB)
#: Who applies each domain token (the abstention states are owned by ``ssot.abstention_reason``).
DOMAIN_STATE_OWNERS: Mapping[str, str] = MappingProxyType({
    _NA: "ssot.fleet_avg_health (avg_health; the other posture facts follow it when no device is scored); "
         "analyze.compute_health_scores ('Insufficient Data' band, per device row)",
    _UV: "ssot.fleet_avg_health (an avg_health that is not a finite number, or has no scored-row basis); "
         "cisco_toolkit.ui_projection (slot type checks, "
         "ssot.reconcile violations, contradictions with the producer's rule, owner faults, untrustworthy zeros)",
})
#: ``ssot.fleet_avg_health`` state vocabulary (not exported by its owner; held by tests).
FLEET_HEALTH_STATES: Tuple[str, ...] = ("measured", _NA, _UV, "unpublished")
#: Every raw owner token ``engine_state`` may carry, and the owners it may come from.
ENGINE_STATES: Tuple[str, ...] = STATES + ("measured", "unpublished")
ENGINE_STATE_OWNERS: Tuple[str, ...] = ("ssot.abstention_reason", "ssot.fleet_avg_health")
REF_ROLES: Tuple[str, ...] = ("subject", "basis", "failure_record", "witness", "denominator")
#: The largest integer a browser's JSON parser keeps exact (Number.MAX_SAFE_INTEGER).
JS_MAX_SAFE_INT = 2 ** 53 - 1

# Local copies of engine vocabularies; tests/test_ui_projection.py holds each equal to its owner.
SEVERITIES: Tuple[str, ...] = ("Critical", "High", "Medium", "Low", "Info")     # analyze._APP_SEV_RANK
HEALTH_BANDS: Tuple[str, ...] = ("Critical", "Poor", "Fair", "Good", "Excellent")   # ssot health-band order
COVERAGE_STATES: Tuple[str, ...] = ("covered", "not_collected", "partial", "unverified", "unparsed",
                                    "not_observed")                             # unknown_evidence._COVERAGE_STATES
UNKNOWN_EVIDENCE_STATES: Tuple[str, ...] = ("observed_no_unknowns", "observed_with_unresolved", "incomplete",
                                            "incomplete_with_unresolved", "unavailable")
#: The unknown-evidence summary states its owner reaches only with every source observed completely.
UE_COMPLETE_STATES: Tuple[str, ...] = ("observed_no_unknowns", "observed_with_unresolved")
UE_SOURCE_STATES: Tuple[str, ...] = ("observed", "observed_empty", "partial", "not_collected",
                                     "malformed")                               # unknown_evidence._SOURCE_STATES
SNAPSHOT_SCHEMA = "collect_parse_snapshot/1"                                    # html.snapshot_state
#: Lifecycle summary field -> band label (ssot lifecycle-band table), and its inverse.
LIFECYCLE_BAND_FACTS: Mapping[str, str] = MappingProxyType({
    "n_past_ldos": "Past-LDoS", "n_past_eos": "Past-EoS", "n_near": "Near-LDoS", "n_active": "Active",
    "n_unknown": "Unknown"})
LIFECYCLE_BAND_FACTS_BY_BAND: Mapping[str, str] = MappingProxyType(
    {band: name for name, band in LIFECYCLE_BAND_FACTS.items()})
#: The canonical lifecycle band order (analyze._LIFECYCLE_BAND_RANK), most severe first.
LIFECYCLE_BAND_ORDER: Tuple[str, ...] = ("Past-LDoS", "Near-LDoS", "Past-EoS", "Active", "Unknown")
NOT_ASSESSED_REASONS: Tuple[str, ...] = ("no_health_rows", "all_insufficient_data", "no_scored_rows")
PHASE_CLASSIFICATIONS: Tuple[str, ...] = ("sections", "intermediate", "non_section", "unknown")
CENSUS_KINDS: Tuple[str, ...] = ("absent", "list", "dict", "scalar")

#: Axis label -> the ``compute_executive_brief`` inputs that axis is computed from. The producer
#: publishes no per-axis basis, so this table is owned HERE and held against the producer's source by
#: an AST test (every literal ``ax("...")`` label, every basis a parameter and a phase section).
AXIS_BASIS: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    "Fleet health": ("health_scores",),
    "Migration punch-list": ("punchlist",),
    "Application domains": ("application_intelligence",),
    "Cutover sequence": ("application_intelligence", "migration_readiness"),
    "Hardware lifecycle (EoL)": ("lifecycle_risk",),
    "Segmentation": ("segmentation",),
    "Multicast / timing": ("multicast_intelligence",),
    "Remediation": ("remediation_plan",),
    "Operational logs": ("syslog_intelligence",),
    "QoS posture": ("qos_audit",),
    "Software risk": ("software_risk",),
    "Platform capacity": ("platform_health",),
    "Asset risk register": ("device_dossiers",),
})
#: The axes the producer emits whatever its inputs (held by a test calling it with no input at all).
ALWAYS_EMITTED_AXES: Tuple[str, ...] = ("Fleet health", "Migration punch-list")
#: The inputs the posture statement's flags read (analyze.compute_executive_brief).
POSTURE_STATEMENT_BASIS: Tuple[str, ...] = ("health_scores", "lifecycle_risk", "segmentation",
                                            "multicast_intelligence", "migration_readiness")
#: Every brief input: an unregistered axis label fails CLOSED to all of them.
BRIEF_INPUTS: Tuple[str, ...] = tuple(sorted(set().union(*AXIS_BASIS.values(), POSTURE_STATEMENT_BASIS)))
#: Every scalar path this projection cross-checks against ``ssot.reconcile`` (its check names).
RECONCILED_PATHS: Tuple[str, ...] = tuple(path for path, _c in ssot.CANONICAL_FACTS.values()) + (
    "lifecycle_risk.summary.n_devices",)

_POSTURE_FACTS = ("avg_health", "n_critical", "n_poor", "worst_band")
_AXIS_GATING = ("Critical", "High")          # the producer's top_gating rule
_OWNER_FAULTS = (RecursionError, TypeError, ValueError, AttributeError, KeyError, IndexError, OverflowError)

# Slice 2 (inventory, device page, findings): local copies of engine vocabularies and tables.
# tests/test_ui_projection_inventory.py holds each one equal to its owner.
PUNCH_RANK: Mapping[str, int] = MappingProxyType(
    {"Critical": 4, "High": 3, "Medium": 2, "Low": 1})                            # analyze._PUNCH_RANK
DOSSIER_BANDS: Tuple[str, ...] = ("Severe", "Elevated", "Guarded", "Low", "Unassessed")   # analyze._DOSSIER_BANDS
EXPOSURE_STATES: Tuple[str, ...] = ("risk", "watch", "ok", "na")    # analyze.compute_device_dossiers ax() states
VLAN_READINESS: Tuple[str, ...] = ("NOT READY", "CAUTION", "READY")     # analyze._VLAN_CUTOVER_READY_RANK
ENDPOINT_CONFIDENCES: Tuple[str, ...] = ("Inferred-high", "Inferred-medium", "Unknown")    # analyze._EP_CONF
#: The statuses analyze.compute_collection_completeness lists (it lists only blind spots, never 'complete').
CC_STATUSES: Tuple[str, ...] = ("not collected", "partial")
SEC_STATUSES: Tuple[str, ...] = ("pass", "fail", "na")                          # parse.parse_security
SEC_SEVERITIES: Tuple[str, ...] = ("high", "medium", "low", "info")             # parse._SEC_CHECKS + "info"
SEC_GRADES: Tuple[str, ...] = ("weak", "partial", "hardened")                   # parse.parse_security
OP_STATUSES: Tuple[str, ...] = ("up", "down", "unknown")                        # analyze.compute_cable_map
NOT_OBSERVED_SENTINEL = "[NOT OBSERVED]"                                        # analyze.VLAN_CUTOVER_NOT_OBSERVED
NRFU_NOT_OBSERVED = "[NOT OBSERVED — record baseline at execution]"        # nrfu_export.NOT_OBSERVED
PUNCH_BASIS_UNPUBLISHED = ("severity basis NOT published by this snapshot — check the finding's own "
                           "detail for what it rests on")                        # analyze.PUNCH_BASIS_UNPUBLISHED
PUNCH_CONFIDENCE_UNPUBLISHED = "evidence confidence NOT published by this snapshot"
HEALTH_BAND_NOT_SCORED = "Insufficient Data"                                    # the ssot not-scored band
#: model.DevicePhysical ints that default to 0 with no "not observed" state (active_ports has one: None).
DEVICE_PHYSICAL_ZERO_DEFAULTS: Tuple[str, ...] = ("num_power_supplies", "num_modules", "total_ports")
#: model.DevicePhysical text fields (default ""), in field order, minus the hostname key.
DEVICE_PHYSICAL_TEXT: Tuple[str, ...] = (
    "platform", "model", "serial_number", "chassis_serial", "sw_version", "uptime", "system_mac", "ps_status",
    "power_capacity_w", "power_drawn_w", "power_remaining_w", "fan_status", "temperature_status",
    "reported_hostname")
IDENTITY_FIELDS: Tuple[str, ...] = ("model", "platform", "sw_version", "serial_number", "chassis_serial", "uptime",
                                    "system_mac", "reported_hostname")
PHYSICAL_TEXT_FIELDS: Tuple[str, ...] = ("ps_status", "power_capacity_w", "power_drawn_w", "power_remaining_w",
                                         "fan_status", "temperature_status")
#: The model.InterfaceData columns a device page shows, in display order.
IF_COLUMNS: Tuple[str, ...] = (
    "status", "switchport_mode", "vlan", "speed", "duplex", "description", "cdp_neighbor", "neighbor_port",
    "trunk_allowed_vlans", "trunk_native_vlan", "stp_fwd_vlans", "stp_blk_vlans", "end_host_ip", "end_host_mac",
    "port_channel", "svi_ip", "vrf")
#: Lists and texts the engine cuts with no total published (owner slice bounds). tests/test_ui_projection_inventory.py
#: walks every producer this module names and holds each prefix slice it reaches to this table or a reviewed exemption.
ENGINE_LIST_CAPS: Mapping[str, int] = MappingProxyType({
    "health_scores[].deductions": 8,                      # analyze.compute_health_scores
    "endpoint_dependencies.dual_homed[].ports": 8,        # analyze.compute_endpoint_dependencies
    "remediation_plan[].why": 300,                        # analyze.compute_remediation_plan
    "vlan_cutover[].app_domain": 3,                       # analyze.compute_vlan_cutover_matrix (domains joined " + ")
    "punchlist[].detail": 400,                            # analyze.compute_migration_punchlist (_clip)
})
#: The separator compute_vlan_cutover_matrix joins the (at most 3) application domains with.
APP_DOMAIN_JOINER = " + "
#: What analyze.compute_migration_punchlist's _clip appends to a text it cut.
PUNCH_DETAIL_CLIP_MARKER = " …"
#: analyze._ESSENTIAL_LABELS: the essential command groups collection_completeness names as missing.
ESSENTIAL_LABELS: Tuple[str, ...] = ("interface status", "switchport", "version/inventory", "CDP/LLDP neighbors")
#: Device-page selection -> the essential captures its rows are derived from (all of them for the punch-list, which
#: rolls up every axis). A partial device missing one of them gets a list that may be incomplete.
SELECTION_NEEDS: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    "links": ("CDP/LLDP neighbors",),                                     # analyze.compute_cable_map
    "native_vlan_mismatches": ("CDP/LLDP neighbors", "switchport"),        # excel.compute_trunk_native_mismatches
    "endpoints": ("interface status", "switchport"),                       # analyze.compute_endpoint_identity
    "findings": ESSENTIAL_LABELS,                                          # analyze.compute_migration_punchlist
})
#: Every section an analysis phase writes (ssot.PHASE_SECTIONS): its value can be computed from a failed phase's
#: fallback two hops away, which ssot.failed_sections does not mark.
ANALYSIS_SECTIONS: FrozenSet[str] = frozenset(s for secs in ssot.PHASE_SECTIONS.values() for s in secs)
#: The dossier bands a missing ('na') axis can understate: every band below the top one (Unassessed is no band).
DOSSIER_UNDERSTATABLE: Tuple[str, ...] = ("Elevated", "Guarded", "Low")
#: VLAN cutover field -> the ``compute_vlan_cutover_matrix`` inputs it is computed from. The producer publishes
#: no per-field basis, so this table is owned HERE and held against the producer's parameters by tests.
VLAN_FIELD_BASIS: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    "vlan": ("interfaces",), "name": ("interfaces",), "stp_root": ("stp_roots",),
    "stp_root_default_election": ("stp_roots",), "fhrp": ("interfaces", "fhrp_detail"),
    "gateway_svi_hosts": ("interfaces",), "endpoint_count": ("endpoint_identity",),
    "endpoint_mix": ("endpoint_identity",), "app_domain": ("application_intelligence",),
    "criticality": ("application_intelligence",), "dependencies": ("multicast_intelligence", "interfaces"),
    "wave": ("move_groups", "wave_sequencing"), "scenario": ("move_groups", "wave_sequencing"),
    "readiness": ("move_groups", "migration_readiness"), "cutover_window": (), "rollback_owner": (),
})
#: The ``compute_migration_punchlist`` inputs that are snapshot sections (its rows roll up over them).
PUNCHLIST_INPUTS: Tuple[str, ...] = (
    "cross_layer", "security", "config_hygiene", "physical_health", "l3_forwarding", "protocol_health",
    "health_scores", "move_groups", "syslog_intelligence", "qos_audit", "software_risk", "platform_health",
    "device_dossiers", "protocol_assessability", "vtp_safety_baseline", "ipv6_routing_adjacency_baseline")
#: The key four consumers read from a move-group row, which ``compute_move_groups`` never writes.
MOVE_GROUP_LABEL = "group"


def _limitation(lid: str, owner: str, text: str, applies_to: Sequence[str]) -> Mapping[str, Any]:
    return MappingProxyType({"id": lid, "owner": owner, "text": text, "applies_to": tuple(applies_to)})


#: What this projection cannot claim, stated once, addressed to the payload paths it qualifies, and
#: named again in ``caveats`` on every value it qualifies.
LIMITATIONS: Tuple[Mapping[str, Any], ...] = (
    _limitation(
        "census_present_keys_only", "ssot.compute_schema_census",
        "The census covers only the keys present in this snapshot. n_not_collected counts present keys whose "
        "value is null; a section absent from the snapshot is not counted (the engine has no static "
        "expected-section registry yet), so the count is a lower bound and a zero is withheld rather than "
        "published as evidence that every expected section was collected. A non-string key (impossible in "
        "JSON) has no RFC 6901 address and no row.",
        ["/trust/census/summary/n_not_collected", "/trust/census/rows"]),
    _limitation(
        "failure_record_written_only_on_failure", "COLLECT_PARSE_V3_23_0.main",
        "assessment_integrity.failed_phases is written only when a phase failed; its absence is not a "
        "statement that every phase passed.",
        ["/trust/failures/record"]),
    _limitation(
        "one_hop_failure_attribution", "ssot.failed_sections",
        "A failed phase marks only the sections one hop away (ssot.PHASE_SECTIONS, ssot.DERIVED_FACT_BASIS). "
        "A section computed from a failed section's fallback is not marked: device_dossiers is not marked "
        "when failure_impact fails. Every brief value, and every row value computed by an analysis phase, published "
        "while a failure is recorded carries this caveat.",
        ["/overview/axes", "/overview/absent_axes", "/overview/top_gating", "/overview/posture_statement",
         "/inventory/devices", "/inventory/vlans", "/inventory/endpoints", "/inventory/uncollected_peers",
         "/findings/rows", "/findings/total"]),
    _limitation(
        "axis_basis_owned_by_projection", "cisco_toolkit.ui_projection.AXIS_BASIS",
        "analyze.compute_executive_brief publishes no per-axis basis. The axis-to-input table is owned by "
        "this projection and held against the producer's source by tests; an unregistered axis label fails "
        "closed to every brief input. The producer omits an axis whose input carries nothing to report; "
        "absent_axes names every registered axis the brief does not carry.",
        ["/overview/axes", "/overview/absent_axes"]),
    _limitation(
        "reconcile_checks_only_with_raw_basis", "ssot.reconcile",
        "A reconcile check runs only when its raw basis is present. n_checked counts the checks that "
        "actually ran, verified requires at least one, and with none run the violation count is withheld.",
        ["/trust/ssot/verified", "/trust/ssot/n_checked", "/trust/ssot/n_violations", "/trust/ssot/violations"]),
    _limitation(
        "measured_zero_mapping", "cisco_toolkit.ui_projection",
        "The abstention core labels a present scalar 0 or false collected_but_empty. This projection "
        "publishes it (and a fixed-shape record made only of such values) as a measured value only when no "
        "basis section is uncollected, ssot.reconcile does not reject it, and its owner's domain state does "
        "not call the input incomplete; engine_state keeps the owner's token. An empty text or mapping "
        "stays collected_but_empty.",
        ["/overview/facts", "/overview/lifecycle", "/trust/unknown_evidence", "/trust/ssot/engine_stamp",
         "/inventory/devices/total"]),
    _limitation(
        "abstention_addresses_dict_paths_only", "ssot.abstention_reason",
        "The abstention core cannot address an array element. A list item takes its list's state, then its "
        "basis sections' failure or blind-spot state, then its own type check. It reads dotted paths, so it cannot "
        "address a path through a hostname that contains a dot either: a row cell takes its section's state and "
        "the device scope of ssot.abstention_reason, then its own row join and type check.",
        ["/overview/axes", "/overview/top_gating", "/trust/failures/record", "/trust/unknown_evidence/sources",
         "/inventory/devices", "/inventory/vlans", "/inventory/endpoints", "/findings/rows"]),
    _limitation(
        "coverage_matrix_shown_as_published", "coverage_matrix.compute_coverage_matrix",
        "The coverage matrix is shown exactly as the engine published it and is never recomputed. The "
        "engine emits 'covered' where a coverage source (capture_integrity, parse_yield) is silent, so a "
        "covered row is not proof that those sources ran, and a zero count from it is withheld as "
        "unverified.",
        ["/trust/coverage_matrix"]),
    _limitation(
        "projection_owned_verdicts", "cisco_toolkit.ui_projection",
        "These verdicts are this projection's, not an engine owner's: census matches_live (rows compared by "
        "key), stamp_matches_live, snapshot_schema_supported, the top_gating check against the producer's "
        "rule (every Critical/High axis headline, in axis order) and its axis_index join, the always-emitted "
        "axis check, and the unverified state for a failed type check, an integer above 2^53-1, a reconcile "
        "violation or an owner fault. On the row screens: the device total's row-count check, the punch-list "
        "priority and rank checks against the producer's rule, a cap's reached flag, the incomplete state of a list "
        "whose input a blind spot, a missing essential capture or a missing security row withheld, the empty "
        "VLAN-dependency and default-election checks against the gateway SVI and root-bridge records, and the "
        "completeness claim of the uncollected-peer list.",
        ["/trust/census/embedded/matches_live", "/trust/ssot/stamp_matches_live",
         "/engine/snapshot_schema_supported", "/overview/top_gating", "/overview/absent_axes",
         "/inventory/devices/total", "/inventory/vlans", "/inventory/endpoints", "/inventory/uncollected_peers",
         "/findings/rows"]),
    _limitation(
        "device_physical_defaults_not_observed", "model.DevicePhysical",
        "The device record defaults its text fields to '' and num_power_supplies, num_modules and total_ports to 0, "
        "with no 'not observed' state (only active_ports has one: null). A default is withheld as not_collected, "
        "never shown as a measured value; an active_ports of 0 is a measured zero. total_ports counts the parsed "
        "physical interfaces, not the chassis.",
        ["/inventory/devices"]),
    _limitation(
        "health_scored_without_security", "analyze.compute_health_scores",
        "A device with no captured running-config (no security row) gets no security deduction at all, so its "
        "health score and band are computed without that input. Every such published score or band carries this "
        "caveat.",
        ["/inventory/devices"]),
    _limitation(
        "health_scored_over_partial_collection",
        "analyze.compute_health_scores, analyze.compute_collection_completeness",
        "A device collection_completeness lists as partial keeps its health band while enough essential captures "
        "returned (its data quality at or above the scorer's threshold), so its score and band are computed without "
        "the missing inputs, for example the CDP/LLDP neighbours behind the cross-layer deductions. Every such "
        "published score or band carries this caveat, with a witness ref to the blind-spot row's missing list.",
        ["/inventory/devices"]),
    _limitation(
        "dossier_band_over_unassessed_axes", "analyze.compute_device_dossiers",
        "The risk register scores only the axes it could assess: an axis marked 'na' adds nothing to the exposure "
        "score. A band below Severe computed while the row's own n_na is above zero may understate the risk, so it "
        "carries this caveat, with a witness ref to that n_na. The count is the engine's; nothing is recomputed.",
        ["/inventory/devices"]),
    _limitation(
        "engine_list_capped",
        "analyze.compute_health_scores, analyze.compute_endpoint_dependencies, analyze.compute_remediation_plan, "
        "analyze.compute_vlan_cutover_matrix, analyze.compute_migration_punchlist",
        "The engine cuts some lists and texts and publishes no total: health deductions after 8, dual-homed ports "
        "after 8, remediation 'why' text after 300 characters, a VLAN's application domains after 3, and a "
        "punch-list detail near 400 characters (the engine marks that cut with ' …'). A list at its cap means "
        "'at least this many'; the projection never computes the missing total.",
        ["/inventory/vlans", "/inventory/endpoints/dual_homed", "/findings/rows"]),
    _limitation(
        "move_group_label_absent", "analyze.compute_move_groups",
        "compute_move_groups writes no 'group' label on its rows, yet the punch-list, remediation, dossier and "
        "endpoint-dependency consumers read one, so their wave, move_groups and split_across_groups values are "
        "computed over no labels. They are withheld as not_collected while no move group carries a label. The VLAN "
        "cutover matrix is not affected: it labels groups by position.",
        ["/findings/rows", "/inventory/endpoints/dual_homed"]),
    _limitation(
        "vlan_cutover_universe", "analyze.compute_vlan_cutover_matrix",
        "The VLAN rows are the cutover matrix's universe (access ports, SVIs and STP roots), not the headline VLAN "
        "inventory (analyze.vlan_inventory, executive_brief.scale.n_vlans). They are two owners and are not "
        "reconciled. endpoint_count is a per-port sum of learned MACs, not a count of distinct endpoints.",
        ["/inventory/vlans"]),
    _limitation(
        "vlan_field_basis_owned_by_projection", "cisco_toolkit.ui_projection.VLAN_FIELD_BASIS",
        "analyze.compute_vlan_cutover_matrix publishes no per-field basis. The field-to-input table is owned by this "
        "projection and held against the producer's parameters by tests.",
        ["/inventory/vlans"]),
    _limitation(
        "punch_rows_carry_no_evidence_pointers", "analyze.compute_migration_punchlist",
        "A punch-list row carries no pointer to the findings it folds, and names a show command only for "
        "single-command categories. The engine publishes no totals by severity, category or device (only prose in "
        "the brief's axis headline), so none is computed here.",
        ["/findings/rows", "/findings/total"]),
    _limitation(
        "row_selection_by_exact_key", "cisco_toolkit.ui_projection",
        "Rows are joined to a device, VLAN or endpoint by exact key equality, with the owner's own key rule; a "
        "collection_completeness blind-spot row is joined by the rule of its owner's device scope (the name without "
        "case or surrounding space, ssot.abstention_reason). Two rows naming the same key are unverified, never "
        "picked between. The inventory is the union of the devices map and the collection_completeness blind spots. "
        "A selection is null when its source list could not be read (selection_sources says why), and [] when it "
        "was read and names nothing.",
        ["/inventory/devices", "/inventory/endpoints", "/inventory/vlans"]),
    _limitation(
        "fleet_lists_exclude_blind_devices", "analyze.compute_collection_completeness",
        "collection_completeness lists devices the collection reached only partly or not at all. A fleet list derived "
        "from device evidence holds only what was collected: an uncollected capture adds no row. While any blind spot "
        "is listed, a published list carries this caveat, with a witness ref to each blind-spot row, and an empty one "
        "is not_collected, never 'nothing found'.",
        ["/inventory/vlans", "/inventory/endpoints", "/findings/rows", "/findings/total"]),
    _limitation(
        "findings_without_running_config", "analyze.compute_migration_punchlist",
        "A device in the devices map with no security row (no captured running-config) contributes no "
        "configuration-derived punch-list row (security, configuration hygiene, QoS). While any device lacks one, "
        "published findings carry this caveat, with a witness ref to each such device record, and an empty list is "
        "not_collected.",
        ["/findings/rows", "/findings/total"]),
)
#: What a device document cannot claim; addressed inside a ``DeviceDocument``.
DEVICE_LIMITATIONS: Tuple[Mapping[str, Any], ...] = (
    _limitation(
        "routes_in_scope_only", "build.scope_routes",
        "The embedded routes are the in-scope subset of the routing table, not the whole table. A device with no "
        "route row may have out-of-scope routes, or a routing table that was not parsed.",
        ["/device/routes"]),
    _limitation(
        "interface_default_not_observed", "model.InterfaceData, html.sparsify_interfaces",
        "Interface fields default to '' and the snapshot drops them, so an unobserved field and an observed empty "
        "one look the same. Both are withheld as not_collected; run_config_observed is shown only when true.",
        ["/device/interfaces"]),
    _limitation(
        "routing_neighbors_empty_is_ambiguous", "build.build_routing_neighbors",
        "An empty neighbour list means the protocol is not running, or its command was not collected or not "
        "parsed. The engine does not tell these apart, so an empty list is withheld as not_collected.",
        ["/device/routing_neighbors"]),
)
#: The payload limitations a device page can cite, re-addressed into a ``DeviceDocument`` (so the document defines
#: every caveat it carries): limitation id -> its applies_to inside the document.
DEVICE_CITED_LIMITATIONS: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    "one_hop_failure_attribution": ("/device/collection", "/device/health", "/device/lifecycle", "/device/dossier",
                                    "/device/coverage", "/device/links", "/device/remediation", "/device/nrfu_cases",
                                    "/device/findings", "/device/endpoints"),
    "coverage_matrix_shown_as_published": ("/device/coverage",),
    "projection_owned_verdicts": ("/device/health/deductions_cap", "/device/remediation/items", "/device/links",
                                  "/device/native_vlan_mismatches", "/device/findings", "/device/endpoints"),
    "device_physical_defaults_not_observed": ("/device/physical",),
    "health_scored_without_security": ("/device/health",),
    "health_scored_over_partial_collection": ("/device/health",),
    "dossier_band_over_unassessed_axes": ("/device/dossier/risk_band",),
    "engine_list_capped": ("/device/health/deductions", "/device/remediation/items"),
    "move_group_label_absent": ("/device/remediation/items",),
    "row_selection_by_exact_key": ("/device/links", "/device/native_vlan_mismatches", "/device/findings",
                                   "/device/endpoints"),
})
_LIMITATION_IDS = tuple(lim["id"] for lim in LIMITATIONS)
_ALL_LIMITATION_IDS = _LIMITATION_IDS + tuple(lim["id"] for lim in DEVICE_LIMITATIONS)
_DEVICE_DOC_LIMITATIONS: Tuple[Mapping[str, Any], ...] = DEVICE_LIMITATIONS + tuple(
    _limitation(lim["id"], lim["owner"], lim["text"], DEVICE_CITED_LIMITATIONS[lim["id"]])
    for lim in LIMITATIONS if lim["id"] in DEVICE_CITED_LIMITATIONS)

_R_CBE = "collected but empty: the engine looked and found nothing of this kind (not a blind spot)"
_R_NC = "not collected: a blind spot, not a clean result"
_R_NULL = ("not published: the engine wrote null here (it abstained), which is neither a measurement nor "
           "a clean result")
_R_AU = ("analysis unavailable: the phase that computes this failed this run, so an empty or absent value "
         "is not evidence of absence (see assessment_integrity.failed_phases)")
_RECORD_ABSENT_REASON = ("no failed-phase record: assessment_integrity.failed_phases is written only when a "
                         "phase failed, so its absence is not a statement that every phase passed")
_SLOT_RULE = {
    "count": "a non-negative integer no larger than 2^53-1, the largest integer a browser keeps exact",
    "score": "a finite number from 0 to 100",
    "text": "a string", "flag": "a boolean", "enum": "a value of its closed vocabulary",
    "axis": "a {severity, headline, detail} record with a known severity",
    "by_state": "a mapping of coverage states to counts",
    "stamp": "a {verified, n_facts, n_checked, n_violations} record",
    "source": "a {section, state, records_examined, detail_complete} record",
    "list": "a list",
    "text_list": "a list of strings",
    "fhrp": "an FHRP record {proto, group, vip, members} or the engine's text",
    "exposure": "an {axis, state, label} record with a known state",
    "compound": "a {code, title, severity, basis} record with a known severity",
    "security_check": "an {id, title, severity, status, detail, cis_ref, remediation} record with a known severity "
                      "and status",
    "security_summary": "a {fail, pass, na, grade} record with a known grade",
    "trunk_native": "an {a_host, a_port, a_native, b_host, b_port, b_native} record of strings",
    "cable_ends": "an {a, a_port, b, b_port, is_pc} record",
    "coverage_cell": "a coverage state of its closed vocabulary",
    "shared_ip": "an {ip, switches, macs} record",
}

# Slice 2 reasons (a reason that is not collected_but_empty never says "not a blind spot").
_R_DEFAULT_TEXT = ("not collected: the engine's default empty text. The device record (model.DevicePhysical) has no "
                   "'not observed' state, so an empty field is not an observed value")
_R_DEFAULT_ZERO = ("not collected: the engine's default 0. The device record (model.DevicePhysical) has no "
                   "'not observed' state for this count, so a zero is not a measurement")
_R_NONE = "not collected: the engine wrote null here because it did not observe this value"
_R_SENTINEL = "not collected: the engine's own not-observed marker, so there is no value to show"
_R_SPARSE = ("not collected: the interface record carries no value for this field. The snapshot drops empty "
             "interface fields (html.sparsify_interfaces), so an unobserved field and an observed empty one look "
             "the same")
_R_HUMAN = ("not collected: left blank on purpose. A human owns this field (the person running the change fills in "
            "the cutover window and the rollback owner)")
_R_NO_ROW = "not collected: {section} carries no row for this device"
_R_DEVICE_NC = ("not collected: collection_completeness lists this device as not collected, so every fact about it "
                "is a blind spot (ssot.abstention_reason, device scope)")
_R_AMBIG = "unverified: {n} rows in {section} name this key, so no single row can be chosen"
_R_NOT_SCORED = ("not assessed: the engine banded this device 'Insufficient Data' (a collection gap or an interface "
                 "set it could not parse), so its score is not a measurement (analyze.compute_health_scores)")
_R_MG = ("not collected: the engine's move groups carry no 'group' label (analyze.compute_move_groups), so this value "
         "was computed over no labels")
_R_NO_SOURCE_CMD = ("not collected: a composite category. The engine cites no single show command for it "
                    "(analyze.compute_migration_punchlist)")
_R_UNKNOWN_HOST = ("not collected: no roster in this snapshot names this device (devices, collection_completeness, "
                   "cable_map)")
_R_BAD_HOST = "unverified: the device key is not a string, so it names no snapshot row"
_R_NOT_OBJECT = "unverified: the engine row is not an object, so none of its fields can be read"
_R_CAP_TOTAL = ("not collected: the engine cuts this list at {limit} and publishes no total, so the full count is "
                "not known")
_R_OWNER_EMPTY = ("unverified: the abstention core calls this list empty (it carries no evidence), yet it holds rows; "
                  "they cannot be read as findings")
_R_DEVICE_BLIND = ("collection_completeness lists this device as not collected (ssot.abstention_reason, device "
                   "scope)")
_R_NO_IFACE = "this device has no interface parse result"
_R_NO_CONFIG = ("security carries no row for this device (no captured running-config), so its configuration-derived "
                "rows could not be generated")
_R_ROLE_DEFAULT = ("not collected: the engine infers the role from the device's parsed interfaces (a gateway SVI makes "
                   "it 'distribution', else 'access'); this device has none, so the role is the engine's default, not "
                   "an observation")
_R_FLEET_BLIND = ("not collected: collection_completeness lists {n} device(s) as partial or not collected, so an empty "
                  "list is not a clean result; their uncollected evidence could add rows")
_R_FLEET_NO_CONFIG = ("not collected: {n} device(s) in the devices map have no security row (no captured "
                      "running-config), so their configuration-derived rows could not be generated; an empty list is "
                      "not a clean result")


def _is_text(value: Any) -> bool:
    """A string a UTF-8 encoder can write. A lone surrogate (JSON admits the escape) is not text: it would make the
    serializer raise, so a value or key carrying one is treated as not a string."""
    if not isinstance(value, str):
        return False
    if value.isascii():
        return True
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _norm(name: str) -> str:
    """The owners' device-name match key (ssot._device_not_collected): no case, no surrounding space."""
    return name.strip().lower()


def _safe_text(value: str) -> str:
    """Owner prose that may quote a snapshot value: a lone surrogate is escaped, never passed through."""
    return value if _is_text(value) else value.encode("utf-8", "backslashreplace").decode("utf-8")


# ---------------------------------------------------------------------------------------------------
# RFC 6901 pointers
# ---------------------------------------------------------------------------------------------------
def json_pointer(*tokens: Any) -> str:
    """RFC 6901: ``~`` -> ``~0`` first, then ``/`` -> ``~1``; list indices are decimal."""
    return "".join("/" + str(tok).replace("~", "~0").replace("/", "~1") for tok in tokens)


_MISSING = object()


def _get(doc: Any, tokens: Sequence[Any]) -> Any:
    """Follow str tokens through dicts and int tokens through lists; ``_MISSING`` when it does not resolve."""
    cur = doc
    for tok in tokens:
        if isinstance(cur, dict) and isinstance(tok, str):
            if tok not in cur:
                return _MISSING
            cur = cur[tok]
        elif isinstance(cur, list) and isinstance(tok, int) and not isinstance(tok, bool):
            if not 0 <= tok < len(cur):
                return _MISSING
            cur = cur[tok]
        else:
            return _MISSING
    return cur


def _tokens(path: str) -> Tuple[str, ...]:
    return tuple(path.split("."))


# ---------------------------------------------------------------------------------------------------
# per-call context: the owners' answers, computed once, every owner call guarded
# ---------------------------------------------------------------------------------------------------
def _fault_text(owner: str, exc: BaseException) -> str:
    return (f"unverified: the engine owner {owner} raised {type(exc).__name__} on this snapshot (for example "
            f"nesting deeper than the interpreter's recursion limit, or a value of an impossible type), so "
            f"nothing is claimed")


_UNSET = object()


class _Ctx:
    """The owners' answers for one snapshot. ``failed_sections`` is read eagerly (every fact consults it); the
    fleet-health, reconcile and summary owners run on first use, so a screen that never reads them never pays."""

    def __init__(self, snap: Any) -> None:
        self.s: Dict[str, Any] = snap if isinstance(snap, dict) else {}
        self.faults: Dict[str, str] = {}
        direct, unattributed = self._call("ssot.failed_sections", ssot.failed_sections, (frozenset(), True))
        self.direct = frozenset(k for k in direct if _is_text(k))
        self.unattributed = bool(unattributed)
        self._fh: Any = _UNSET
        self._violations: Any = _UNSET
        self._summary: Any = _UNSET
        self._abst: Dict[str, str] = {}
        self._abst_dev: Dict[Tuple[str, str], str] = {}
        self._indexes: Dict[Any, Dict[str, List[int]]] = {}
        self._fe: Dict[Tuple[FrozenSet[str], bool], List[Tuple[str, Sequence[Any]]]] = {}
        self._census: Optional[Tuple[Optional[Dict[str, Any]], Optional[str]]] = None
        self._census_counts: Optional[Dict[str, Any]] = None
        self._mg: Optional[bool] = None
        self._cc_witness: Dict[str, List[Tuple[str, Sequence[Any]]]] = {}
        self._blind_rows: Optional[List[int]] = None
        self._no_config: Optional[List[str]] = None
        self._stp_roots: Optional[Dict[int, Tuple[str, str, Dict[str, Any]]]] = None

    def _call(self, owner: str, fn: Callable[[Any], Any], fallback: Any) -> Any:
        try:
            return fn(self.s)
        except _OWNER_FAULTS as exc:
            self.faults[owner] = _fault_text(owner, exc)
            return fallback

    @property
    def fh(self) -> Dict[str, Any]:
        if self._fh is _UNSET:
            self._fh = self._call("ssot.fleet_avg_health", ssot.fleet_avg_health,
                                  {"state": "unpublished", "value": None, "n_scored": None, "n_rows": None})
        return self._fh

    @property
    def violations(self) -> Optional[List[str]]:
        if self._violations is _UNSET:
            raw = self._call("ssot.reconcile", ssot.reconcile, None)
            self._violations = None if raw is None else [_safe_text(str(v)) for v in raw]
        return self._violations

    @property
    def summary(self) -> Optional[Dict[str, Any]]:
        if self._summary is _UNSET:
            self._summary = self._call("ssot.summary", ssot.summary, None)
        return self._summary

    @property
    def any_failure(self) -> bool:
        return bool(self.direct) or self.unattributed

    def abst(self, subject: str) -> str:
        if subject not in self._abst:
            try:
                token = ssot.abstention_reason(self.s, subject)
            except _OWNER_FAULTS as exc:
                token = _FAULT
                self.faults[f"abstention:{subject}"] = _fault_text("ssot.abstention_reason", exc)
            self._abst[subject] = token
        return self._abst[subject]

    def fault(self, subjects: Iterable[str]) -> str:
        for subject in subjects:
            if self.abst(subject) == _FAULT:
                return self.faults[f"abstention:{subject}"]
        return _fault_text("ssot.abstention_reason", RecursionError())

    def violations_for(self, path: str) -> List[str]:
        return [v for v in (self.violations or ()) if v.startswith(path + "=")]

    def refs(self, entries: Iterable[Tuple[str, Sequence[Any]]]) -> List[Dict[str, str]]:
        """Resolving refs only, de-duplicated, in the order given."""
        out: List[Dict[str, str]] = []
        seen = set()
        for role, toks in entries:
            if _get(self.s, toks) is _MISSING:
                continue
            key = (json_pointer(*toks), role)
            if key not in seen:
                seen.add(key)
                out.append({"pointer": key[0], "role": role})
        return out

    def classify(self, label: Any) -> str:
        if not isinstance(label, str):
            return "unknown"                  # the owner's answer for every non-text JSON value
        try:
            return ssot.phase_classification(label)
        except _OWNER_FAULTS:
            return "unknown"

    def failure_entries(self, sections: Iterable[str], unavailable: bool) -> List[Tuple[str, Sequence[Any]]]:
        """``failure_record`` refs for the failures that cover `sections`; when the fact is unavailable
        but no attributed failure covers it, the unattributed failures are what explain it (cached)."""
        key = (frozenset(sections), bool(unavailable))
        if key not in self._fe:
            self._fe[key] = self._failure_entries(key[0], key[1])
        return list(self._fe[key])

    def abst_dev(self, section: str, host: str) -> str:
        """``ssot.abstention_reason`` scoped to one device (its not-collected check runs first)."""
        key = (section, host)
        if key not in self._abst_dev:
            try:
                token = ssot.abstention_reason(self.s, section, device=host)
            except _OWNER_FAULTS as exc:
                token = _FAULT
                self.faults[f"abstention:{section}"] = _fault_text("ssot.abstention_reason", exc)
            self._abst_dev[key] = token
        return self._abst_dev[key]

    def device_blind(self, section: str, host: Any) -> bool:
        """The owner's device scope says ``not_collected`` where its section-level answer does not: the device
        is a collection blind spot (``collection_completeness`` lists it as not collected)."""
        return (_is_text(host) and bool(host) and self.abst_dev(section, host) == _NC
                and self.abst(section) != _NC)

    def cc_row(self, host: Any) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        """The blind-spot row the owner's device scope reads for `host` (ssot._device_not_collected: the name
        without case or surrounding space, first match wins), or ``(None, None)``."""
        if not _is_text(host):
            return None, None
        idx = self.index(("collection_completeness", "devices"), ("host",), norm=True).get(_norm(host), [])
        rows = _get(self.s, ("collection_completeness", "devices"))
        return (idx[0], rows[idx[0]]) if idx else (None, None)

    def cc_witness(self, host: str) -> List[Tuple[str, Sequence[Any]]]:
        """The blind-spot row that makes `host` not collected, by the owner's matching rule."""
        if host not in self._cc_witness:
            i, _row = self.cc_row(host)
            self._cc_witness[host] = [] if i is None else [("witness", ("collection_completeness", "devices", i))]
        return list(self._cc_witness[host])

    def index(self, toks: Tuple[Any, ...], fields: Tuple[str, ...], multi: bool = False,
              norm: bool = False) -> Dict[str, List[int]]:
        """Key -> every row index naming it, over the list at `toks` (one pass, cached). A key is a text field
        value (or, with `multi`, each text in a list field); with `norm` it is compared without case or surrounding
        space. Duplicates stay visible."""
        key = (toks, fields, multi, norm)
        if key not in self._indexes:
            out: Dict[str, List[int]] = {}
            rows = _get(self.s, toks)
            for i, row in enumerate(rows if isinstance(rows, list) else ()):
                if not isinstance(row, dict):
                    continue
                names: List[str] = []
                for field in fields:
                    val = row.get(field)
                    if multi and isinstance(val, list):
                        names.extend(x for x in val if _is_text(x))
                    elif _is_text(val):
                        names.append(val)
                for name in dict.fromkeys(_norm(n) if norm else n for n in names):
                    out.setdefault(name, []).append(i)
            self._indexes[key] = out
        return self._indexes[key]

    def blind_rows(self) -> List[int]:
        """Every collection_completeness row listing a device as partial or not collected (the owner's statuses)."""
        if self._blind_rows is None:
            rows = _get(self.s, ("collection_completeness", "devices"))
            self._blind_rows = [i for i, row in enumerate(rows if isinstance(rows, list) else ())
                                if isinstance(row, dict) and _is_text(row.get("status"))
                                and _norm(row["status"]) in CC_STATUSES]
        return list(self._blind_rows)

    def no_config_hosts(self) -> List[str]:
        """The devices-map hosts the security map carries no row for (no captured running-config)."""
        if self._no_config is None:
            devices, sec = self.s.get("devices"), self.s.get("security")
            self._no_config = (sorted(h for h in devices if _is_text(h) and h not in sec)
                               if isinstance(devices, dict) and isinstance(sec, dict) else [])
        return list(self._no_config)

    def stp_root_record(self, vid: int) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        """``(host, key, record)`` of the STP root compute_vlan_cutover_matrix reads for VLAN `vid`: the first sorted
        host whose non-MST record, keyed by that VLAN id, claims root (its own rule, record order kept)."""
        if self._stp_roots is None:
            out: Dict[int, Tuple[str, str, Dict[str, Any]]] = {}
            roots = self.s.get("stp_roots")
            for host in sorted(k for k in roots if _is_text(k)) if isinstance(roots, dict) else ():
                recs = roots[host]
                for key, rec in (recs.items() if isinstance(recs, dict) else ()):
                    v = _vid(key, strip=False) if _is_text(key) else None
                    if (v is not None and isinstance(rec, dict) and not rec.get("is_mst") and rec.get("is_root")
                            and v not in out):
                        out[v] = (host, key, rec)
            self._stp_roots = out
        return self._stp_roots.get(vid)

    @property
    def mg_labelled(self) -> bool:
        """True when some move group carries a non-empty text label (the key its consumers read)."""
        if self._mg is None:
            rows = self.s.get("move_groups")
            self._mg = isinstance(rows, list) and any(
                isinstance(g, dict) and isinstance(g.get(MOVE_GROUP_LABEL), str) and g[MOVE_GROUP_LABEL].strip()
                for g in rows)
        return self._mg

    def census(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """``ssot.compute_schema_census`` (computed once): ``(census, fault text)``."""
        if self._census is None:
            try:
                self._census = (ssot.compute_schema_census(self.s), None)
            except _OWNER_FAULTS as exc:
                self._census = (None, _fault_text("ssot.compute_schema_census", exc))
        return self._census

    def census_count(self, section: str) -> Any:
        if self._census_counts is None:
            live, _fault = self.census()
            self._census_counts = {row.get("key"): row.get("count") for row in (live or {}).get("sections", ())
                                   if isinstance(row.get("key"), str)}
        return self._census_counts.get(section)

    def if_nc(self, host: Any) -> bool:
        """The device has no interface parse result: its interfaces row is absent or empty (the engine writes an
        unreached inventory host as ``{}``)."""
        ifaces = self.s.get("interfaces")
        row = ifaces.get(host) if isinstance(ifaces, dict) and _is_text(host) else None
        return not (isinstance(row, dict) and row)

    def _failure_entries(self, sections: Iterable[str], unavailable: bool) -> List[Tuple[str, Sequence[Any]]]:
        secs = set(sections)
        entries: List[Tuple[str, Sequence[Any]]] = []
        unattributed: List[Tuple[str, Sequence[Any]]] = []
        integ = self.s.get("assessment_integrity")
        if isinstance(integ, dict):
            raw = integ.get("failed_phases")
            if isinstance(raw, list):
                for i, label in enumerate(raw):
                    kind = self.classify(label)
                    toks = ("assessment_integrity", "failed_phases", i)
                    if kind == "sections":
                        if secs & set(ssot.PHASE_SECTIONS.get(label, ())):
                            entries.append(("failure_record", toks))
                    elif kind != "non_section":
                        unattributed.append(("failure_record", toks))
            elif raw:
                unattributed.append(("failure_record", ("assessment_integrity", "failed_phases")))
            for sec in sorted(secs):
                val = integ.get(sec)
                if isinstance(val, str) and val.strip().lower() in ssot.INTEGRITY_FAILURE_TOKENS:
                    entries.append(("failure_record", ("assessment_integrity", sec)))
        for sec in sorted(secs):
            val = self.s.get(sec)
            if isinstance(val, dict) and val.get("_unavailable"):
                entries.append(("failure_record", (sec, "_unavailable")))
        if unavailable and not entries:
            entries.extend(unattributed)
        return entries

    def unavailable_reason(self, sections: Iterable[str]) -> str:
        failed = sorted(set(sections) & self.direct)
        if failed:
            return f"{_R_AU}; failed sections: {', '.join(failed)}"
        if self.unattributed:
            return f"{_R_AU}; a failure could not be attributed to sections, so this value may be its fallback"
        return _R_AU

    def violation_witness(self, violations: Sequence[str]) -> List[Tuple[str, Sequence[Any]]]:
        stored = _get(self.s, ("assessment_integrity", "violations"))
        if not isinstance(stored, list):
            return []
        return [("witness", ("assessment_integrity", "violations", i))
                for i, text in enumerate(stored) if isinstance(text, str) and text in violations]


# ---------------------------------------------------------------------------------------------------
# slot type checks: (ok, typed value built from NEW containers)
# ---------------------------------------------------------------------------------------------------
def _count(raw: Any) -> Tuple[bool, Any]:
    if isinstance(raw, bool):
        return False, None
    if isinstance(raw, int):
        return (0 <= raw <= JS_MAX_SAFE_INT), (int(raw) if 0 <= raw <= JS_MAX_SAFE_INT else None)
    if isinstance(raw, float) and math.isfinite(raw) and raw.is_integer() and 0 <= raw <= JS_MAX_SAFE_INT:
        return True, int(raw)
    return False, None


def _score(raw: Any) -> Tuple[bool, Any]:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return False, None
    if isinstance(raw, int):
        return (0 <= raw <= 100), (int(raw) if 0 <= raw <= 100 else None)
    ok = math.isfinite(raw) and 0.0 <= raw <= 100.0
    return ok, (float(raw) if ok else None)


def _text_list(raw: Any) -> Tuple[bool, Any]:
    if isinstance(raw, list) and all(_is_text(x) for x in raw):
        return True, list(raw)
    return False, None


_FHRP_TEXT = ("proto", "group", "vip")
_FHRP_MEMBER_TEXT = ("host", "proto", "group", "vip", "role", "vmac")


def _fhrp(raw: Any) -> Tuple[bool, Any]:
    """analyze.compute_vlan_cutover_matrix's FHRP record, rebuilt field by field (analyze.py members dict). The
    producer writes '' for a field no gateway evidenced (a joined group of no members, a member with no election
    detail); that is not an observed value, so it travels as null."""
    if not isinstance(raw, dict) or not all(_is_text(raw.get(k)) for k in _FHRP_TEXT):
        return False, None
    members = raw.get("members")
    if not isinstance(members, list):
        return False, None
    out: List[Dict[str, Any]] = []
    for member in members:
        if not isinstance(member, dict) or not all(_is_text(member.get(k)) for k in _FHRP_MEMBER_TEXT):
            return False, None
        prio, preempt = member.get("priority"), member.get("preempt")
        if prio is not None:
            ok, prio = _count(prio)
            if not ok:
                return False, None
        if preempt is not None and not isinstance(preempt, bool):
            return False, None
        row = {k: member[k] or None for k in _FHRP_MEMBER_TEXT}
        row.update(priority=prio, preempt=preempt)
        out.append({k: row[k] for k in ("host", "proto", "group", "vip", "role", "priority", "preempt", "vmac")})
    return True, {**{k: raw[k] or None for k in _FHRP_TEXT}, "members": out}


#: Fixed-shape records: slot -> ((field, slot, vocabulary), ...), in output order.
_RECORD_SLOTS: Mapping[str, Tuple[Tuple[str, str, Tuple[str, ...]], ...]] = MappingProxyType({
    "exposure": (("axis", "text", ()), ("state", "enum", EXPOSURE_STATES), ("label", "text", ())),
    "compound": (("code", "text", ()), ("title", "text", ()), ("severity", "enum", SEVERITIES),
                 ("basis", "text", ())),
    "security_check": (("id", "text", ()), ("title", "text", ()), ("severity", "enum", SEC_SEVERITIES),
                       ("status", "enum", SEC_STATUSES), ("detail", "text", ()), ("cis_ref", "text", ()),
                       ("remediation", "text", ())),
    "security_summary": (("fail", "count", ()), ("pass", "count", ()), ("na", "count", ()),
                         ("grade", "enum", SEC_GRADES)),
    "trunk_native": tuple((k, "text", ()) for k in ("a_host", "a_port", "a_native", "b_host", "b_port", "b_native")),
    "cable_ends": (("a", "text", ()), ("a_port", "text", ()), ("b", "text", ()), ("b_port", "text", ()),
                   ("is_pc", "flag", ())),
    "shared_ip": (("ip", "text", ()), ("switches", "text_list", ()), ("macs", "text_list", ())),
})


def _record(raw: Dict[str, Any], slot: str) -> Tuple[bool, Any]:
    out: Dict[str, Any] = {}
    for key, kind, vocab in _RECORD_SLOTS[slot]:
        ok, val = _typed(raw.get(key), kind, vocab)
        if not ok:
            return False, None
        out[key] = val
    return True, out


def _typed(raw: Any, slot: str, vocab: Sequence[str] = ()) -> Tuple[bool, Any]:
    if slot == "count":
        return _count(raw)
    if slot == "score":
        return _score(raw)
    if slot == "text":
        ok = _is_text(raw)
        return ok, (raw if ok else None)
    if slot == "flag":
        return isinstance(raw, bool), (raw if isinstance(raw, bool) else None)
    if slot == "enum":
        ok = isinstance(raw, str) and raw in vocab
        return ok, (raw if ok else None)
    if slot == "text_list":
        return _text_list(raw)
    if slot == "fhrp":
        return (True, raw) if _is_text(raw) else _fhrp(raw)
    if slot == "coverage_cell":
        ok = isinstance(raw, str) and raw in COVERAGE_STATES
        return ok, (raw if ok else None)
    if not isinstance(raw, dict):
        return False, None
    if slot in _RECORD_SLOTS:
        return _record(raw, slot)
    if slot == "axis":
        sev, head, det = raw.get("severity"), raw.get("headline"), raw.get("detail")
        if isinstance(sev, str) and sev in SEVERITIES and _is_text(head) and _is_text(det):
            return True, {"severity": sev, "headline": head, "detail": det}
        return False, None
    if slot == "by_state":
        out: Dict[str, int] = {}
        for key, val in raw.items():
            ok, num = _count(val)
            if not (isinstance(key, str) and key in COVERAGE_STATES and ok):
                return False, None
            out[key] = num
        return True, {k: out[k] for k in COVERAGE_STATES if k in out}
    if slot == "stamp":
        verified = raw.get("verified")
        nums = {k: _count(raw.get(k)) for k in ("n_facts", "n_checked", "n_violations")}
        if isinstance(verified, bool) and all(ok for ok, _v in nums.values()):
            return True, {"verified": verified, **{k: v for k, (_ok, v) in nums.items()}}
        return False, None
    if slot == "source":
        sec, state, det = raw.get("section"), raw.get("state"), raw.get("detail_complete")
        ok_n, n = _count(raw.get("records_examined"))
        if (_is_text(sec) and isinstance(state, str) and state in UE_SOURCE_STATES and ok_n
                and isinstance(det, bool)):
            return True, {"section": sec, "state": state, "records_examined": n, "detail_complete": det}
        return False, None
    return False, None


def _measured_zero(value: Any) -> bool:
    """A present 0 / False (or a fixed-shape record made only of them) is a measurement, not absence."""
    if isinstance(value, dict):
        return bool(value) and all(_measured_zero(v) for v in value.values())
    return value is False or (isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0)


def _carries_nothing(raw: Any) -> bool:
    return raw is None or raw == "" or (_count(raw)[0] and _count(raw)[1] == 0)


_MEASURED_ZERO_SLOTS = frozenset({"count", "score", "flag", "stamp", "source"})


def _unverified_reason(slot: str) -> str:
    return (f"unverified: the value failed this projection's '{slot}' type check ({_SLOT_RULE[slot]}); it is "
            f"withheld, never coerced")


def _not_assessed_reason(ctx: _Ctx) -> str:
    posture = _get(ctx.s, ("executive_brief", "posture"))
    token = posture.get("not_assessed") if isinstance(posture, dict) else None
    tail = f"; producer reason: {token}" if isinstance(token, str) and token in NOT_ASSESSED_REASONS else ""
    n_scored = ctx.fh.get("n_scored")
    if n_scored == 0:
        head = "not assessed: no device was health-scored, so a stored value is not a measurement"
    elif isinstance(n_scored, int):
        head = (f"not assessed: the engine withheld the fleet average although {n_scored} health row(s) are "
                f"scored")
    else:
        head = "not assessed: the engine published no fleet average and no scored health rows can be counted"
    return f"{head} (ssot.fleet_avg_health){tail}"


def _fleet_unverified_reason(owner_reason: Any) -> str:
    """Why ``ssot.fleet_avg_health`` withholds a published average, in its own reason's words: a finite number
    with no scored health rows behind it is NOT "not a finite number" (``ssot.FLEET_AVG_UNVERIFIED_REASONS``)."""
    if owner_reason == "no_scored_basis":
        return ("unverified: ssot.fleet_avg_health finds no scored health rows behind the published average "
                "(reason no_scored_basis): the snapshot carries no health_scores list, so the number is not a "
                "measurement")
    if owner_reason == "not_a_number":
        return ("unverified: ssot.fleet_avg_health reports a published average that is not a finite number "
                "(reason not_a_number)")
    return "unverified: ssot.fleet_avg_health withholds the published average as not a measurement"


def _envelope(state: str, value: Any, subject: Optional[str], refs: List[Dict[str, str]], basis: str,
              reason: str, owner_token: Optional[str] = None, token_owner: str = "ssot.abstention_reason",
              caveats: Sequence[str] = ()) -> Dict[str, Any]:
    fact: Dict[str, Any] = {"state": state, "value": value if state == _PUB else None, "subject": subject,
                            "refs": refs, "basis": basis}
    if state != _PUB:
        fact["reason"] = reason
    if owner_token is not None and owner_token != _FAULT and owner_token != state:
        fact["engine_state"] = owner_token
        fact["engine_state_owner"] = token_owner
    cav = [c for c in _ALL_LIMITATION_IDS if c in set(caveats)]
    if cav:
        fact["caveats"] = cav
    return fact


def _state_reason(ctx: _Ctx, state: str, slot: str, sections: Sequence[str]) -> str:
    if state == AU:
        return ctx.unavailable_reason(sections)
    if state == _NA:
        return _not_assessed_reason(ctx)
    if state == _UV:
        return _unverified_reason(slot)
    if state == _CBE:
        return _R_CBE
    return _R_NC


# ---------------------------------------------------------------------------------------------------
# scalar facts
# ---------------------------------------------------------------------------------------------------
#: A gate on a typed value: ``None`` to let it through, else ``(state, reason, extra ref entries)``.
_Gate = Callable[["_Ctx", Any, bool], Optional[Tuple[str, str, List[Tuple[str, Sequence[Any]]]]]]


def _scalar(ctx: _Ctx, path: str, slot: str, basis: str, *, vocab: Sequence[str] = (),
            extra_basis: Sequence[str] = (), posture_name: Optional[str] = None, nc_basis_any: bool = False,
            gate: Optional[_Gate] = None, witness: Sequence[Tuple[str, Sequence[Any]]] = (),
            caveats: Sequence[str] = (), published_caveats: Sequence[str] = ()) -> Dict[str, Any]:
    toks = _tokens(path)
    raw = _get(ctx.s, toks)
    present = raw is not _MISSING
    raw = None if raw is _MISSING else raw
    t = ctx.abst(path)
    owner_token: Optional[str] = t
    token_owner = "ssot.abstention_reason"
    own = tuple(ssot.fact_basis(path))
    sections = own + tuple(s for s in extra_basis if s not in own)
    derived = sections[1:]
    state: Optional[str] = None
    value: Any = None
    reason: Optional[str] = None
    extra_refs: List[Tuple[str, Sequence[Any]]] = []
    cav = list(caveats)
    faulted = False

    if t == AU or any(ctx.abst(s) == AU for s in derived):
        state = AU
    elif t == _FAULT or any(ctx.abst(s) == _FAULT for s in derived):
        state, reason, faulted = _UV, ctx.fault((path,) + derived), True
    elif posture_name == "avg_health" and ctx.fh["state"] != "unpublished":
        owner_token, token_owner = ctx.fh["state"], "ssot.fleet_avg_health"
        if owner_token == _NA:
            state = _NA
        elif owner_token == _UV:
            state = _UV
            reason = _fleet_unverified_reason(ctx.fh.get("reason"))
    elif (posture_name in _POSTURE_FACTS and (ctx.fh["state"] == _NA or ctx.fh.get("n_scored") == 0)
          and _carries_nothing(raw)):
        state = _NA
    if state is None:
        if t == _NC:
            state, reason = _NC, (_R_NULL if present else _R_NC)
        else:
            ok, typed = _typed(raw, slot, vocab)
            empty = t == _CBE                      # the core: present, carries no evidence (0 / "" / False)
            zero = slot in _MEASURED_ZERO_SLOTS and ok and _measured_zero(typed)
            nc_basis = [s for s in derived if ctx.abst(s) == _NC]
            gated = gate(ctx, typed, zero) if (gate is not None and ok) else None
            if nc_basis and empty:
                state = _NC                        # nothing, computed over nothing: before any type verdict
                reason = (f"not collected: this value is computed from {', '.join(nc_basis)}, which this snapshot "
                          f"does not carry, so it is not a measurement")
            elif empty and raw == "" and slot in ("text", "enum"):
                state = _CBE                       # the producer's empty text ("no band observed")
            elif not ok:
                state = _UV
            elif nc_basis and nc_basis_any:
                state = _NC
                reason = (f"not collected: this value is computed from {', '.join(nc_basis)}, which this snapshot "
                          f"does not carry, so it is not a measurement")
            elif gated is not None:
                state, reason, extra_refs = gated
            elif empty and not zero:
                state = _CBE
            else:
                state, value = _PUB, typed
                if empty:
                    cav.append("measured_zero_mapping")
    hits = ctx.violations_for(path)
    if hits and state != AU and not faulted:
        if state == _NA and ctx.fh.get("n_scored") == 0:
            # G15: the owner already withholds it as not assessed; reconcile states the same thing
            reason = ((reason or _not_assessed_reason(ctx))
                      + "; ssot.reconcile agrees the stored value is not a measurement: " + "; ".join(hits))
        else:
            state, value = _UV, None
            reason = "unverified: ssot.reconcile rejects this value: " + "; ".join(hits)
        extra_refs = extra_refs + ctx.violation_witness(hits)
    if state == _PUB:
        cav.extend(published_caveats)
    refs = ctx.refs([("subject", toks)]
                    + [("basis", (s,)) for s in derived]
                    + ctx.failure_entries(sections, state == AU)
                    + list(witness) + extra_refs)
    return _envelope(state, value, json_pointer(*toks), refs, basis,
                     reason or _state_reason(ctx, state, slot, sections), owner_token, token_owner, cav)


def _live_count(ctx: _Ctx, value: Any, basis: str, *, fault: Optional[str] = None,
                withhold: Optional[Tuple[str, str]] = None, caveats: Sequence[str] = ()) -> Dict[str, Any]:
    """A count an owner computes live (no snapshot address)."""
    if fault:
        return _envelope(_UV, None, None, [], basis, fault)
    if withhold:
        return _envelope(withhold[0], None, None, [], basis, withhold[1])
    ok, typed = _count(value)
    if not ok:
        return _envelope(_UV, None, None, [], basis, _unverified_reason("count"))
    return _envelope(_PUB, typed, None, [], basis, "", caveats=caveats)


# ---------------------------------------------------------------------------------------------------
# lists
# ---------------------------------------------------------------------------------------------------
def _list_base(ctx: _Ctx, path: str) -> Tuple[str, Optional[str], Any, Optional[str]]:
    """``(base state, owner token, raw, reason)`` for a list at a dotted path (before any rollup)."""
    raw = _get(ctx.s, _tokens(path))
    present = raw is not _MISSING
    raw = None if raw is _MISSING else raw
    t = ctx.abst(path)
    if t == AU:
        return AU, t, raw, None
    if t == _FAULT:
        return _UV, None, raw, ctx.fault((path,))
    if t == _NC:
        return _NC, t, raw, (_R_NULL if present else _R_NC)
    if not isinstance(raw, list):
        return _UV, t, raw, _unverified_reason("list")
    return t, t, raw, None


def _factlist(ctx: _Ctx, path: Optional[str], basis: str, items: List[Any], base: str, owner: Optional[str],
              *, rollup: Sequence[str] = (), reason: Optional[str] = None, contradiction: Optional[str] = None,
              caveats: Sequence[str] = ()) -> Dict[str, Any]:
    toks = _tokens(path) if path else ()
    own = tuple(ssot.fact_basis(path)) if path else ()
    sections = own + tuple(s for s in rollup if s not in own)
    rollup_failed = sorted(s for s in rollup if ctx.abst(s) == AU)
    rollup_fault = [s for s in rollup if ctx.abst(s) == _FAULT]
    rollup_nc = sorted(s for s in rollup if ctx.abst(s) == _NC)
    if base == AU or rollup_failed:
        state = AU
        reason = ctx.unavailable_reason(sections)
        if rollup_failed:
            reason += ("; the list may be incomplete: a failed input can drop or empty an entry "
                       f"({', '.join(rollup_failed)})")
    elif base == _UV:
        state = _UV
    elif contradiction:
        state, reason = _UV, contradiction
    elif rollup_fault:
        state, reason = _UV, ctx.fault(rollup_fault)
    elif rollup_nc and base in (_PUB, _CBE):
        state = _NC
        reason = ("not collected: the list may be incomplete, because inputs it is computed from were not "
                  f"collected ({', '.join(rollup_nc)}); an absent entry is not a clean result")
    else:
        state = base
    if state == _CBE and not reason:
        reason = _R_CBE
    refs = ctx.refs(([("subject", toks)] if toks else []) + [("basis", (s,)) for s in sections[1:]]
                    + ctx.failure_entries(sections, state == AU))
    out: Dict[str, Any] = {"state": state, "subject": json_pointer(*toks) if toks else None, "refs": refs,
                           "basis": basis}
    if state != _PUB:
        out["reason"] = reason or _state_reason(ctx, state, "list", sections)
    if owner is not None and owner != _FAULT and owner != state:
        out["engine_state"] = owner
        out["engine_state_owner"] = "ssot.abstention_reason"
    cav = [c for c in _LIMITATION_IDS if c in set(caveats)]
    if cav:
        out["caveats"] = cav
    out["items"] = items
    return out


def _item_basis_state(ctx: _Ctx, basis: Sequence[str]) -> Tuple[Optional[str], Optional[str]]:
    states = [ctx.abst(s) for s in basis]
    if AU in states:
        return AU, None
    if _FAULT in states:
        return _UV, ctx.fault(basis)
    if _NC in states:
        missing = [s for s, st in zip(basis, states) if st == _NC]
        return _NC, f"not collected: its input was not collected ({', '.join(missing)})"
    return None, None


def _brief_caveats(ctx: _Ctx, *extra: str) -> Tuple[str, ...]:
    return extra + (("one_hop_failure_attribution",) if ctx.any_failure else ())


# ---------------------------------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------------------------------
def _lineage_witness(ctx: _Ctx, name: str) -> List[Tuple[str, Sequence[Any]]]:
    rows = _get(ctx.s, ("fact_lineage", "facts"))
    if isinstance(rows, list):
        for i, row in enumerate(rows):
            if isinstance(row, dict) and row.get("name") == name:
                return [("witness", ("fact_lineage", "facts", i))]
    return []


def _overview_facts(ctx: _Ctx) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, (path, concept) in ssot.CANONICAL_FACTS.items():
        witness = _lineage_witness(ctx, name)
        if name in LIFECYCLE_BAND_FACTS:
            witness = witness + [("denominator", ("lifecycle_risk", "summary", "n_devices"))]
        if name == "worst_band":
            fact = _scalar(ctx, path, "enum", f"ssot.canonical_facts:{path}", vocab=HEALTH_BANDS,
                           posture_name=name, witness=witness)
        elif name == "avg_health":
            fact = _scalar(ctx, path, "score", f"ssot.fleet_avg_health:{path}", posture_name=name, witness=witness)
        else:
            fact = _scalar(ctx, path, "count", f"ssot.canonical_facts:{path}",
                           posture_name=name if name in _POSTURE_FACTS else None, witness=witness)
        out[name] = {"path": path, "concept": concept, "fact": fact}
    return out


def _fleet_health(ctx: _Ctx, avg: Dict[str, Any]) -> Dict[str, Any]:
    fh = ctx.fh
    hs_t = ctx.abst("health_scores")
    health = ctx.s.get("health_scores")
    block: Dict[str, Any] = {"state": avg["state"]}
    if avg["state"] != _PUB:
        block["reason"] = avg["reason"]
    block["engine_state"] = fh["state"]
    token = None
    if avg["state"] == _NA:
        posture = _get(ctx.s, ("executive_brief", "posture"))
        raw = posture.get("not_assessed") if isinstance(posture, dict) else None
        token = raw if isinstance(raw, str) and raw in NOT_ASSESSED_REASONS else None
    block["not_assessed_reason"] = token
    for key in ("n_scored", "n_rows"):
        entries: List[Tuple[str, Sequence[Any]]] = [("basis", ("health_scores",))]
        if key == "n_scored":
            entries.append(("witness", ("executive_brief", "posture", "n_scored")))
        reason = ""
        value = None
        if hs_t == AU:
            state = AU
        elif hs_t == _FAULT:
            state, reason = _UV, ctx.fault(("health_scores",))
        elif health is not None and not isinstance(health, list):
            state, reason = _UV, "unverified: health_scores is not a list, so no row can be counted"
        elif not isinstance(health, list):
            state = _NC
        else:
            ok, value = _count(fh.get(key))
            state = _PUB if ok else _UV
        refs = ctx.refs(entries + ctx.failure_entries(("health_scores",), state == AU))
        block[key] = _envelope(state, value, None, refs, f"ssot.fleet_avg_health:{key}",
                               reason or _state_reason(ctx, state, "count", ("health_scores",)))
    return block


def _axes(ctx: _Ctx) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Any, str]:
    path = "executive_brief.axes"
    base, owner, raw, breason = _list_base(ctx, path)
    items: List[Dict[str, Any]] = []
    cav = _brief_caveats(ctx, "axis_basis_owned_by_projection")
    for i, row in enumerate(raw if isinstance(raw, list) else ()):
        label = row.get("axis") if isinstance(row, dict) and _is_text(row.get("axis")) else None
        basis = AXIS_BASIS.get(label, BRIEF_INPUTS) if label is not None else BRIEF_INPUTS
        toks = ("executive_brief", "axes", i)
        value = None
        reason = None
        basis_state, basis_reason = _item_basis_state(ctx, basis)
        if base == AU or basis_state == AU:
            state = AU                                # a failed input always wins
        elif base != _PUB:
            state, reason = base, breason
        elif basis_state is not None:
            state, reason = basis_state, basis_reason
        else:
            ok, value = _typed(row, "axis")
            state = _PUB if ok else _UV
        refs = ctx.refs([("subject", toks)] + [("basis", (s,)) for s in basis]
                        + ctx.failure_entries(("executive_brief",) + tuple(basis), state == AU))
        fact = _envelope(state, value, json_pointer(*toks), refs, "analyze.compute_executive_brief",
                         reason or _state_reason(ctx, state, "axis", basis),
                         caveats=cav if state == _PUB else ())
        items.append({"index": i, "axis": label, "basis_sections": list(basis), "fact": fact})
    present = {it["axis"] for it in items}
    contradiction = None
    missing_always = [lab for lab in ALWAYS_EMITTED_AXES if lab not in present]
    if base in (_PUB, _CBE) and missing_always:
        contradiction = ("unverified: the producer always emits the axes "
                         f"{', '.join(ALWAYS_EMITTED_AXES)}, and this brief lacks {', '.join(missing_always)}")
    listing = _factlist(ctx, path, "analyze.compute_executive_brief", items, base, owner, rollup=BRIEF_INPUTS,
                        reason=breason, contradiction=contradiction,
                        caveats=cav if base in (_PUB, _CBE) else ())
    return listing, items, raw, base


def _absent_axes(ctx: _Ctx, items: List[Dict[str, Any]], base: str) -> List[Dict[str, Any]]:
    present = {it["axis"] for it in items}
    out = []
    for label, basis in AXIS_BASIS.items():
        if label in present:
            continue
        basis_state, basis_reason = _item_basis_state(ctx, basis)
        reason: Optional[str] = None
        if base == AU or basis_state == AU:
            state = AU
        elif base == _UV:
            state, reason = _UV, "unverified: the brief's axis list is malformed or could not be evaluated"
        elif base == _NC:
            state, reason = _NC, "not collected: the snapshot carries no executive-brief axis list"
        elif basis_state is not None:
            state, reason = basis_state, basis_reason
        elif label in ALWAYS_EMITTED_AXES:
            state, reason = _UV, "unverified: the producer always emits this axis, and the brief lacks it"
        else:
            state, reason = _CBE, ("collected but empty: the producer did not emit this axis; it omits an axis "
                                   "whose input carries nothing to report (not a blind spot)")
        refs = ctx.refs([("basis", (s,)) for s in basis]
                        + ctx.failure_entries(("executive_brief",) + tuple(basis), state == AU))
        fact = _envelope(state, None, None, refs, "analyze.compute_executive_brief",
                         reason or _state_reason(ctx, state, "axis", basis))
        out.append({"axis": label, "basis_sections": list(basis), "fact": fact})
    return out


def _top_gating(ctx: _Ctx, axis_items: List[Dict[str, Any]], axes_raw: Any, axes_base: str) -> Dict[str, Any]:
    path = "executive_brief.top_gating"
    base, owner, raw, breason = _list_base(ctx, path)
    gating: List[Tuple[int, Any]] = []
    if isinstance(axes_raw, list):
        gating = [(k, row.get("headline")) for k, row in enumerate(axes_raw)
                  if isinstance(row, dict) and row.get("severity") in _AXIS_GATING]
    contradiction = None
    if axes_base == _PUB and base in (_PUB, _CBE) and isinstance(raw, list):
        texts = all(isinstance(x, str) for x in raw) and all(isinstance(h, str) for _k, h in gating)
        if not texts or list(raw) != [h for _k, h in gating]:
            contradiction = ("unverified: top_gating disagrees with the producer's rule over the published axes "
                             f"(every Critical/High axis headline, in axis order): {len(gating)} expected, "
                             f"{len(raw)} published")
    items: List[Dict[str, Any]] = []
    cav = _brief_caveats(ctx, "projection_owned_verdicts")
    for i, text in enumerate(raw if isinstance(raw, list) else ()):
        toks = ("executive_brief", "top_gating", i)
        j: Optional[int] = None
        if isinstance(text, str):
            if i < len(gating) and gating[i][1] == text:
                j = gating[i][0]
            else:
                j = next((k for k, head in gating if isinstance(head, str) and head == text), None)
        entries: List[Tuple[str, Sequence[Any]]] = [("subject", toks)]
        basis: Tuple[str, ...] = ()
        value = None
        reason: Optional[str] = None
        if base != _PUB:
            state, reason = base, breason
        elif j is None or j >= len(axis_items):
            state = _UV
            reason = "unverified: no Critical/High axis carries this headline (the producer's top_gating rule)"
        else:
            axis_item = axis_items[j]
            basis = tuple(axis_item["basis_sections"])
            entries.append(("witness", ("executive_brief", "axes", j)))
            state = axis_item["fact"]["state"]
            reason = axis_item["fact"].get("reason")
            if state == _PUB:
                ok, value = _typed(text, "text")
                state = _PUB if ok else _UV
                reason = None
        refs = ctx.refs(entries + [("basis", (s,)) for s in basis]
                        + ctx.failure_entries(("executive_brief",) + basis, state == AU))
        fact = _envelope(state, value, json_pointer(*toks), refs, "analyze.compute_executive_brief",
                         reason or _state_reason(ctx, state, "text", basis), caveats=cav if state == _PUB else ())
        items.append({"index": i, "axis_index": j, "fact": fact})
    return _factlist(ctx, path, "analyze.compute_executive_brief", items, base, owner, rollup=BRIEF_INPUTS,
                     reason=breason, contradiction=contradiction, caveats=cav if base in (_PUB, _CBE) else ())


def _overview(ctx: _Ctx) -> Dict[str, Any]:
    facts = _overview_facts(ctx)
    axes, axis_items, axes_raw, axes_base = _axes(ctx)
    lc_owner = "analyze.compute_lifecycle_risk"
    return {
        "facts": facts,
        "fleet_health": _fleet_health(ctx, facts["avg_health"]["fact"]),
        "axes": axes,
        "absent_axes": _absent_axes(ctx, axis_items, axes_base),
        "posture_statement": _scalar(ctx, "executive_brief.posture_statement", "text",
                                     "analyze.compute_executive_brief", extra_basis=POSTURE_STATEMENT_BASIS,
                                     nc_basis_any=True, published_caveats=_brief_caveats(ctx)),
        "top_gating": _top_gating(ctx, axis_items, axes_raw, axes_base),
        "lifecycle": {
            "bands": [{"band": band, "fact_name": LIFECYCLE_BAND_FACTS_BY_BAND[band], "rank": rank}
                      for rank, band in enumerate(LIFECYCLE_BAND_ORDER)],
            "of": _scalar(ctx, "lifecycle_risk.summary.n_devices", "count",
                          f"{lc_owner}:lifecycle_risk.summary.n_devices"),
            "asof": _scalar(ctx, "lifecycle_risk.summary.asof", "text", f"{lc_owner}:lifecycle_risk.summary.asof"),
        },
    }


def project_overview(snap: Any) -> Dict[str, Any]:
    """The Overview screen: canonical facts, fleet-health scoring state, brief axes, lifecycle bands."""
    return _overview(_Ctx(snap))


# ---------------------------------------------------------------------------------------------------
# trust
# ---------------------------------------------------------------------------------------------------
_CENSUS_SUMMARY_KEYS = ("n_published", "n_collected_but_empty", "n_not_collected", "n_analysis_unavailable",
                        "n_sections")


def _census_rows_by_key(sections: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(sections, list):
        return None
    out: Dict[str, Any] = {}
    for row in sections:
        if not isinstance(row, dict) or not isinstance(row.get("key"), str) or row["key"] in out:
            return None
        out[row["key"]] = row
    return out


def _state_token(ctx: _Ctx, token: str) -> str:
    return _UV if token == _FAULT else token


def _census(ctx: _Ctx) -> Dict[str, Any]:
    basis = "ssot.compute_schema_census"
    live, fault = ctx.census()
    embedded_state = _state_token(ctx, ctx.abst("schema_census"))
    if live is None:
        summary = {k: _live_count(ctx, None, f"{basis}:summary.{k}", fault=fault) for k in _CENSUS_SUMMARY_KEYS}
        rows = _factlist(ctx, None, basis, [], _UV, None, reason=fault)
        return {"basis": basis, "summary": summary, "rows": rows,
                "embedded": {"state": embedded_state, "matches_live": None}}
    items = []
    for row in live["sections"]:
        key = row.get("key")
        if not _is_text(key):
            continue                                  # a non-JSON key has no RFC 6901 address
        count = row.get("count")
        items.append({"key": key, "state": row["state"],
                      "count": count if isinstance(count, int) and not isinstance(count, bool) else None,
                      "kind": row["kind"], "note": row["note"], "pointer": json_pointer(key)})
    items.sort(key=lambda r: r["key"])
    live_sum = live["summary"]
    n_sections = live_sum.get("n_sections", 0)
    empty = ("not collected: the snapshot carries no top-level section, so nothing was counted"
             if not n_sections else None)
    summary = {}
    for key in _CENSUS_SUMMARY_KEYS:
        value = live_sum.get(key, 0)              # the owner omits n_analysis_unavailable when it is 0
        withhold = (_NC, empty) if empty else None
        cav: Tuple[str, ...] = ()
        if key == "n_not_collected" and not empty:
            cav = ("census_present_keys_only",)
            if value == 0:
                withhold = (_NC, "not collected: 0 present keys are null, but a section absent from this "
                                 "snapshot is not counted (no expected-section registry), so zero is not "
                                 "evidence that every expected section was collected")
        summary[key] = _live_count(ctx, value, f"{basis}:summary.{key}", withhold=withhold, caveats=cav)
    rows = _factlist(ctx, None, basis, items, _PUB if items else _NC, None,
                     reason=None if items else "not collected: the snapshot carries no top-level section",
                     caveats=("census_present_keys_only",))
    embedded = ctx.s.get("schema_census")
    matches: Optional[bool] = None
    if embedded is not None:
        emb_rows = _census_rows_by_key(embedded.get("sections")) if isinstance(embedded, dict) else None
        matches = (isinstance(embedded, dict) and emb_rows is not None
                   and embedded.get("schema") == live["schema"] and embedded.get("summary") == live_sum
                   and emb_rows == _census_rows_by_key(live["sections"]))
    return {"basis": basis, "summary": summary, "rows": rows,
            "embedded": {"state": embedded_state, "matches_live": matches}}


def _failures(ctx: _Ctx) -> Dict[str, Any]:
    path = "assessment_integrity.failed_phases"
    base, owner, raw, breason = _list_base(ctx, path)
    items = []
    for i, label in enumerate(raw if isinstance(raw, list) else ()):
        kind = ctx.classify(label)
        items.append({"index": i, "label": label if _is_text(label) else None, "classification": kind,
                      "sections": list(ssot.PHASE_SECTIONS.get(label, ())) if kind == "sections" else [],
                      "pointer": json_pointer("assessment_integrity", "failed_phases", i)})
    record = _factlist(ctx, path, "ssot.failed_sections", items, base, owner,
                       reason=_RECORD_ABSENT_REASON if base == _NC else breason)
    direct = []
    for sec in sorted(ctx.direct):
        direct.append({"section": sec,
                       "refs": ctx.refs([("subject", (sec,))] + ctx.failure_entries((sec,), False))})
    return {"basis": "ssot.failed_sections", "record": record, "direct_sections": direct,
            "unattributed": ctx.unattributed}


def _coverage_zero_gate(ctx: _Ctx, _typed_value: Any, zero: bool):
    if not zero:
        return None
    return (_UV, "unverified: the coverage matrix labels a row covered even where its coverage sources are "
                 "silent, so a zero count from it is not verified (see coverage_matrix_shown_as_published)", [])


def _coverage_matrix(ctx: _Ctx) -> Dict[str, Any]:
    owner = "coverage_matrix.compute_coverage_matrix"
    cav = ("coverage_matrix_shown_as_published",)
    out: Dict[str, Any] = {}
    for key in ("n_devices", "n_axes", "n_rows", "n_covered", "n_abstained"):
        path = f"coverage_matrix.summary.{key}"
        out[key] = _scalar(ctx, path, "count", f"{owner}:{path}", gate=_coverage_zero_gate, published_caveats=cav)
    out["by_state"] = _scalar(ctx, "coverage_matrix.summary.by_state", "by_state",
                              f"{owner}:coverage_matrix.summary.by_state", published_caveats=cav)
    out["note"] = _scalar(ctx, "coverage_matrix.summary.note", "text", f"{owner}:coverage_matrix.summary.note")
    return out


def _ue_count_gate(ctx: _Ctx, _typed_value: Any, zero: bool):
    state = _get(ctx.s, ("unknown_evidence", "summary", "state"))
    witness = [("witness", ("unknown_evidence", "summary", "state"))]
    if state == "unavailable":
        return (AU, "analysis unavailable: the owner's summary state is 'unavailable' (the unknown-evidence "
                    "aggregate could not be computed), so this count is not evidence", witness)
    if not zero:
        return None
    if isinstance(state, str) and state in UE_COMPLETE_STATES:
        return None
    if isinstance(state, str) and state in UNKNOWN_EVIDENCE_STATES:
        return (_NC, f"not collected: the owner's summary state is '{state}' (a source was not observed "
                     "completely), so a zero is not proof that nothing is unknown", witness)
    return (_UV, "unverified: the owner's summary state is missing or outside its vocabulary, so a zero "
                 "cannot be verified", witness)


def _unknown_evidence(ctx: _Ctx) -> Dict[str, Any]:
    owner = "unknown_evidence.compute_unknown_evidence"
    out: Dict[str, Any] = {}
    for key, slot, vocab, gate in (("state", "enum", UNKNOWN_EVIDENCE_STATES, None),
                                   ("n_events", "count", (), _ue_count_gate),
                                   ("n_unresolved", "count", (), _ue_count_gate),
                                   ("source_coverage_complete", "flag", (), None),
                                   ("claim_scope", "text", (), None), ("note", "text", (), None)):
        path = f"unknown_evidence.summary.{key}"
        out[key] = _scalar(ctx, path, slot, f"{owner}:{path}", vocab=vocab, gate=gate)
    path = "unknown_evidence.sources"
    base, token, raw, breason = _list_base(ctx, path)
    items = []
    for i, row in enumerate(raw if isinstance(raw, list) else ()):
        toks = ("unknown_evidence", "sources", i)
        value = None
        reason = None
        if base != _PUB:
            state, reason = base, breason
        else:
            ok, value = _typed(row, "source")
            state = _PUB if ok else _UV
        refs = ctx.refs([("subject", toks)] + ctx.failure_entries(("unknown_evidence",), state == AU))
        items.append({"index": i, "fact": _envelope(state, value, json_pointer(*toks), refs, f"{owner}:{path}",
                                                    reason or _state_reason(ctx, state, "source", ()))})
    out["sources"] = _factlist(ctx, path, f"{owner}:{path}", items, base, token, reason=breason)
    return out


def _ssot_block(ctx: _Ctx) -> Dict[str, Any]:
    live = ctx.summary
    violations = ctx.violations                       # both owners run before their faults are read
    fault = ctx.faults.get("ssot.summary") or ctx.faults.get("ssot.reconcile")
    if live is None or violations is None:
        fault = fault or _fault_text("ssot.summary", TypeError())
    block: Dict[str, Any] = {"basis": "ssot.summary"}
    rc = ("reconcile_checks_only_with_raw_basis",)
    if fault:
        block["verified"] = _envelope(_UV, None, None, [], "ssot.summary:verified", fault)
        for key in ("n_facts", "n_checked", "n_violations"):
            block[key] = _live_count(ctx, None, f"ssot.summary:{key}", fault=fault)
        block["violations"] = _factlist(ctx, None, "ssot.reconcile", [], _UV, None, reason=fault)
        live_stamp = None
    else:
        ok_v = isinstance(live.get("verified"), bool)
        block["verified"] = (_envelope(_PUB, live["verified"], None, [], "ssot.summary:verified", "", caveats=rc)
                             if ok_v else _envelope(_UV, None, None, [], "ssot.summary:verified",
                                                    _unverified_reason("flag")))
        n_checked = live.get("n_checked")
        block["n_facts"] = _live_count(ctx, live.get("n_facts"), "ssot.summary:n_facts")
        block["n_checked"] = _live_count(ctx, n_checked, "ssot.summary:n_checked", caveats=rc)
        none_ran = ("not collected: no reconcile check ran (none of their raw bases is present), so a zero "
                    "violation count would verify nothing")
        block["n_violations"] = _live_count(ctx, live.get("n_violations"), "ssot.summary:n_violations",
                                            withhold=(_NC, none_ran) if n_checked == 0 else None, caveats=rc)
        texts = list(violations or ())
        if n_checked == 0:
            vbase, vreason = _NC, none_ran
        elif texts:
            vbase, vreason = _PUB, None
        else:
            vbase, vreason = _CBE, "collected but empty: every check that ran reconciled (not a blind spot)"
        block["violations"] = _factlist(ctx, None, "ssot.reconcile", texts, vbase, None, reason=vreason, caveats=rc)
        live_stamp = {k: live.get(k) for k in ("verified", "n_facts", "n_checked", "n_violations")}
    stamp = _scalar(ctx, "executive_brief.ssot", "stamp", "ssot.summary (stamped by COLLECT_PARSE_V3_23_0.main)")
    block["engine_stamp"] = stamp
    block["stamp_matches_live"] = ((stamp["value"] == live_stamp)
                                   if stamp["state"] == _PUB and live_stamp is not None else None)
    return block


def _limitations_payload() -> List[Dict[str, Any]]:
    return [{"id": lim["id"], "owner": lim["owner"], "text": lim["text"], "applies_to": list(lim["applies_to"])}
            for lim in LIMITATIONS]


def _trust(ctx: _Ctx) -> Dict[str, Any]:
    return {
        "census": _census(ctx),
        "failures": _failures(ctx),
        "coverage_matrix": _coverage_matrix(ctx),
        "unknown_evidence": _unknown_evidence(ctx),
        "ssot": _ssot_block(ctx),
        "limitations": _limitations_payload(),
    }


def project_trust(snap: Any) -> Dict[str, Any]:
    """The Trust screen: census, failure record, coverage matrix, unknown evidence, SSOT verification."""
    return _trust(_Ctx(snap))


# ---------------------------------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------------------------------
def _engine(ctx: _Ctx) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, owner in (("schema", "html.snapshot_state"), ("script_version", "html.snapshot_state"),
                       ("generated_at", "html.snapshot_state"), ("collected_at", "COLLECT_PARSE_V3_23_0.main")):
        out["snapshot_schema" if key == "schema" else key] = _scalar(ctx, key, "text", f"{owner}:{key}")
    stamp = out["snapshot_schema"]
    out["snapshot_schema_supported"] = (stamp["value"] == SNAPSHOT_SCHEMA) if stamp["state"] == _PUB else None
    out["code_schema_version"] = str(_CODE_SCHEMA_VERSION)
    return out


def project_engine(snap: Any) -> Dict[str, Any]:
    """Which snapshot schema and producer versions this payload was projected from."""
    return _engine(_Ctx(snap))


# ---------------------------------------------------------------------------------------------------
# slice 2: row joins, cells and lists
#
# A hostname can contain a dot, and the abstention core reads dotted paths, so no path through a host or
# a port ever reaches ssot.abstention_reason: a section's state comes from its fixed path, the device's
# blind-spot state from the owner's device scope, and a row from an exact-key join over tokens.
# ---------------------------------------------------------------------------------------------------
_KIND = {dict: "an object", list: "a list"}


class _Row:
    """One engine row joined for its cells: where it is, or why none of its fields can be read."""
    __slots__ = ("state", "reason", "toks", "raw", "sections", "extra", "basis_refs", "bare")

    def __init__(self, state: Optional[str], reason: Optional[str], toks: Optional[Tuple[Any, ...]], raw: Any,
                 sections: Sequence[str], extra: Sequence[Tuple[str, Sequence[Any]]] = (), basis_refs: bool = True,
                 bare: bool = False) -> None:
        self.state = state
        self.reason = reason
        self.toks = None if toks is None else tuple(toks)
        self.raw = raw
        self.sections = tuple(sections)
        self.extra = list(extra)
        self.basis_refs = basis_refs
        self.bare = bare


def _secs_fail(ctx: _Ctx, sections: Sequence[str]) -> Optional[Tuple[str, str]]:
    """``analysis_unavailable`` when any section failed; ``unverified`` when an owner raised on one."""
    if any(ctx.abst(s) == AU for s in sections):
        return AU, ctx.unavailable_reason(sections)
    faulted = [s for s in sections if ctx.abst(s) == _FAULT]
    if faulted:
        return _UV, ctx.fault(faulted)
    return None


def _resolve(ctx: _Ctx, path_toks: Tuple[str, ...], sections: Sequence[str], *, key: Any = _MISSING,
             key_field: Optional[str] = None, want: Any = dict, host: Any = None,
             absent: Optional[Tuple[str, str]] = None, forced: Optional[Tuple[str, str]] = None,
             norm: bool = False) -> _Row:
    """Join one row. `path_toks` is a FIXED container path (never a host). With `key` alone the container is a
    map keyed by it; with `key_field` it is a list whose rows name the key in that field (with `norm`, compared
    without case or surrounding space); with neither the container itself is the row. First match wins: forced
    (an unknown device) -> the device's blind spot (owner order) -> a failed or faulted section -> an uncollected
    section -> a wrong container -> the join (absent / ambiguous) -> a row of the wrong type."""
    keyed = key is not _MISSING and key_field is None
    cand: Optional[Tuple[Any, ...]] = (path_toks + (key,)) if keyed else (path_toks if key is _MISSING else None)
    if forced is not None:
        return _Row(forced[0], forced[1], None, None, sections, basis_refs=False, bare=True)
    if host is not None and ctx.device_blind(sections[0], host):
        return _Row(_NC, _R_DEVICE_NC, cand, None, sections, ctx.cc_witness(host), basis_refs=False)
    path = ".".join(path_toks)
    hit = _secs_fail(ctx, (path,) + tuple(sections))
    if hit:
        return _Row(hit[0], hit[1], cand, None, sections)
    container = _get(ctx.s, path_toks)
    if ctx.abst(path) == _NC:
        return _Row(_NC, _R_NULL if container is None else _R_NC, cand, None, sections)
    if key is _MISSING:
        if not isinstance(container, want):
            return _Row(_UV, f"unverified: {path} is not {_KIND[want]}", cand, None, sections)
        return _Row(None, None, path_toks, container, sections)
    need = dict if keyed else list
    if not isinstance(container, need):
        return _Row(_UV, f"unverified: {path} is not {_KIND[need]}, so no row can be read", cand, None, sections)
    miss = absent or (_NC, _R_NO_ROW.format(section=path))
    if keyed:
        if not _is_text(key) or key not in container:
            return _Row(miss[0], miss[1], cand, None, sections)
        toks, raw = path_toks + (key,), container[key]
    else:
        idx = (ctx.index(path_toks, (key_field,), norm=norm).get(_norm(key) if norm else key, [])
               if _is_text(key) else [])
        if not idx:
            return _Row(miss[0], miss[1], None, None, sections)
        if len(idx) > 1:
            return _Row(_UV, _R_AMBIG.format(n=len(idx), section=path), None, None, sections,
                        [("witness", path_toks + (i,)) for i in idx])
        toks, raw = path_toks + (idx[0],), container[idx[0]]
    if want is not None and not isinstance(raw, want):
        why = _R_NOT_OBJECT if want is dict else "unverified: the engine value is not a list, so no row can be read"
        return _Row(_UV, why, toks, raw, sections)
    return _Row(None, None, toks, raw, sections)


def _list_row(toks: Tuple[Any, ...], raw: Any, sections: Sequence[str]) -> _Row:
    return _Row(None, None, toks, raw, sections) if isinstance(raw, dict) else _Row(
        _UV, _R_NOT_OBJECT, toks, raw, sections)


def _void(value: Any) -> bool:
    return _carries_nothing(value) or value == []


#: A pre-check on a raw field: ``None`` to go on, else the withheld ``(state, reason)`` (a not-observed marker), or
#: ``(state, reason, extra ref entries)`` when a record elsewhere in the snapshot witnesses why.
_Pre = Callable[[Any, _Row], Optional[Tuple[Any, ...]]]


def _one_hop(ctx: _Ctx, state: str, sections: Iterable[str]) -> Tuple[str, ...]:
    """The one-hop caveat on a value an analysis phase computed, published while a failure is recorded."""
    if state in (_PUB, _CBE) and ctx.any_failure and any(s in ANALYSIS_SECTIONS for s in sections):
        return ("one_hop_failure_attribution",)
    return ()
#: A gate on a typed field value: ``None`` to publish, else ``(state, reason, extra ref entries)``.
_CellGate = Callable[[_Ctx, Any, _Row], Optional[Tuple[str, str, List[Tuple[str, Sequence[Any]]]]]]


def _cell(ctx: _Ctx, row: _Row, field: Optional[str], slot: str, basis: str, *, vocab: Sequence[str] = (),
          sections: Optional[Sequence[str]] = None, pre: Optional[_Pre] = None, gate: Optional[_CellGate] = None,
          empty: Optional[Tuple[str, str]] = None, missing: Optional[str] = None, caveats: Sequence[str] = (),
          published_caveats: Sequence[str] = (),
          witness: Sequence[Tuple[str, Sequence[Any]]] = ()) -> Dict[str, Any]:
    """One row cell (`field` None: the whole row as one record). First match wins: the row's own state ->
    a failed or faulted section -> a missing key -> the field's not-observed rule -> the type check -> the
    gate -> nothing computed over an uncollected input -> an empty text or list -> published."""
    secs = tuple(sections) if sections else row.sections
    toks = None if row.toks is None else row.toks + (() if field is None else (field,))
    extra = list(row.extra)
    value: Any = None
    state: str
    reason: Optional[str] = None
    if row.state is not None:
        state, reason = row.state, row.reason
    else:
        hit = _secs_fail(ctx, secs)
        if hit:
            state, reason = hit
        elif field is not None and (not isinstance(row.raw, dict) or field not in row.raw):
            state, reason = _NC, missing or f"not collected: the engine row carries no {field}"
        else:
            raw = row.raw if field is None else row.raw[field]
            early = pre(raw, row) if pre is not None else None
            if early is not None:
                state, reason = early[0], early[1]
                extra += list(early[2]) if len(early) > 2 else []
            else:
                ok, typed = _typed(raw, slot, vocab)
                gated = gate(ctx, typed, row) if (gate is not None and ok) else None
                nc_basis = [s for s in secs[1:] if ctx.abst(s) == _NC]
                if not ok:
                    state = _UV
                elif gated is not None:
                    state, reason, more = gated
                    extra += more
                elif nc_basis and _void(typed):
                    state = _NC
                    reason = (f"not collected: this value is computed from {', '.join(nc_basis)}, which this "
                              f"snapshot does not carry, so it is not a measurement")
                elif typed == "" or typed == []:
                    state, reason = empty or (_CBE, _R_CBE)
                else:
                    state, value = _PUB, typed
    if row.bare:
        refs: List[Dict[str, str]] = []
    else:
        entries: List[Tuple[str, Sequence[Any]]] = [("subject", toks)] if toks is not None else []
        if row.basis_refs:
            entries += [("basis", (s,)) for s in secs[1:]]
        refs = ctx.refs(entries + ctx.failure_entries(secs, state == AU) + extra + list(witness))
    cav = list(caveats) + (list(published_caveats) + list(_one_hop(ctx, state, secs)) if state == _PUB else [])
    return _envelope(state, value, None if toks is None else json_pointer(*toks), refs, basis,
                     reason or _state_reason(ctx, state, slot, secs), caveats=cav)


def _rolled(ctx: _Ctx, state: str, reason: Optional[str], sections: Sequence[str], rollup: Sequence[str],
            incomplete: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """A list's state after its inputs roll up (the slice-1 ``_factlist`` order)."""
    all_secs = tuple(sections) + tuple(s for s in rollup if s not in sections)
    failed = sorted(s for s in rollup if ctx.abst(s) == AU)
    faulted = [s for s in rollup if ctx.abst(s) == _FAULT]
    uncollected = sorted(s for s in rollup if ctx.abst(s) == _NC)
    if state == AU or failed:
        head = reason if (state == AU and reason) else ctx.unavailable_reason(all_secs)
        tail = ("; the list may be incomplete: a failed input can drop or empty an entry "
                f"({', '.join(failed)})") if failed else ""
        return AU, head + tail
    if state == _UV:
        return state, reason
    if faulted:
        return _UV, ctx.fault(faulted)
    if uncollected and state in (_PUB, _CBE):
        return _NC, ("not collected: the list may be incomplete, because inputs it is computed from were not "
                     f"collected ({', '.join(uncollected)}); an absent entry is not a clean result")
    if incomplete and state in (_PUB, _CBE):
        return _NC, incomplete
    return state, reason


#: A qualification of a fleet list: ``(caveat id, reason when the list is empty, witness ref entries)``. A published
#: list carries the caveat and its witnesses; an empty one is not_collected for that reason, never a clean absence.
_Qualify = Tuple[str, str, List[Tuple[str, Sequence[Any]]]]


def _listing(ctx: _Ctx, state: str, reason: Optional[str], toks: Optional[Tuple[Any, ...]], basis: str,
             items: List[Any], *, sections: Sequence[str] = (), rollup: Sequence[str] = (),
             extra: Sequence[Tuple[str, Sequence[Any]]] = (), caveats: Sequence[str] = (),
             incomplete: Optional[str] = None, bare: bool = False,
             qualify: Sequence[_Qualify] = ()) -> Dict[str, Any]:
    all_secs = tuple(sections) + tuple(s for s in rollup if s not in sections)
    if not bare:
        state, reason = _rolled(ctx, state, reason, sections, rollup, incomplete)
    if state == _PUB and not items:
        state, reason = _CBE, reason or _R_CBE                  # a published list is never empty
    witness: List[Tuple[str, Sequence[Any]]] = []
    cav = list(caveats)
    if qualify and state in (_PUB, _CBE):
        for cid, _why, wit in qualify:
            cav.append(cid)
            witness += wit
        if state == _CBE:
            state, reason = _NC, "; ".join(why for _c, why, _w in qualify)
    if state != _PUB and not reason:
        reason = _R_CBE if state == _CBE else _state_reason(ctx, state, "list", all_secs)
    entries: List[Tuple[str, Sequence[Any]]] = []
    if not bare:
        entries = (([("subject", toks)] if toks is not None else []) + [("basis", (s,)) for s in rollup]
                   + ctx.failure_entries(all_secs, state == AU) + list(extra) + witness)
    out: Dict[str, Any] = {"state": state, "subject": None if toks is None else json_pointer(*toks),
                           "refs": ctx.refs(entries), "basis": basis}
    if state != _PUB:
        out["reason"] = reason
    cav += _one_hop(ctx, state, all_secs)
    # a withheld list still qualifies the rows it carries (an incomplete list shows what it has)
    kept = [c for c in _ALL_LIMITATION_IDS if c in set(cav)] if (state in (_PUB, _CBE) or items) else []
    if kept:
        out["caveats"] = kept
    out["items"] = items
    return out


def _list_state(ctx: _Ctx, path_toks: Tuple[str, ...], sections: Sequence[str],
                want: Any = list) -> Tuple[str, Optional[str], Any]:
    """``(state, reason, container)`` of a whole engine container at a FIXED path, before selection/rollup.
    The container is returned whenever it can be read (also under a failed phase, whose rows then read
    as unavailable)."""
    path = ".".join(path_toks)
    raw = _get(ctx.s, path_toks)
    hit = _secs_fail(ctx, (path,) + tuple(sections))
    if hit:
        return hit[0], hit[1], (raw if isinstance(raw, want) else None)
    if ctx.abst(path) == _NC:
        return _NC, (_R_NULL if raw is None else _R_NC), None
    if not isinstance(raw, want):
        return _UV, f"unverified: {path} is not {_KIND[want]}, so no row can be read", None
    if want is list and raw and ctx.abst(path) == _CBE:
        return _UV, _R_OWNER_EMPTY, raw
    return (_PUB if raw else _CBE), None, raw


def _sub_list(ctx: _Ctx, row: _Row, field: str, *, pre_state: Optional[Tuple[str, str]] = None,
              empty: Optional[Tuple[str, str]] = None,
              missing: Optional[str] = None) -> Tuple[str, Optional[str], Optional[Tuple[Any, ...]], Any]:
    """``(state, reason, toks, list)`` of a list held in one field of a joined row."""
    toks = None if row.toks is None else row.toks + (field,)
    if row.state is not None:
        return row.state, row.reason, toks, None
    raw = row.raw.get(field, _MISSING) if isinstance(row.raw, dict) else _MISSING
    hit = _secs_fail(ctx, row.sections)
    if hit:
        return hit[0], hit[1], toks, (raw if isinstance(raw, list) else None)
    if raw is _MISSING:
        return _NC, missing or f"not collected: the engine row carries no {field}", toks, None
    if not isinstance(raw, list):
        return _UV, f"unverified: the engine's {field} is not a list, so none of it can be read", toks, None
    if pre_state is not None:
        return pre_state[0], pre_state[1], toks, raw
    if not raw:
        state, reason = empty or (_CBE, _R_CBE)
        return state, reason, toks, raw
    return _PUB, None, toks, raw


def _items(ctx: _Ctx, list_toks: Optional[Tuple[Any, ...]], raw_list: Any, slot: str, basis: str,
           sections: Sequence[str], *, hold: Optional[Tuple[str, str]] = None,
           published_caveats: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """``{index, pointer, fact}`` per element; each element is type-checked as one `slot` value. `hold`
    withholds every element with its list's own state (a list that is not assessed)."""
    out: List[Dict[str, Any]] = []
    if list_toks is None or not isinstance(raw_list, list):
        return out
    for j, raw in enumerate(raw_list):
        toks = list_toks + (j,)
        row = _Row(hold[0] if hold else None, hold[1] if hold else None, toks, raw, sections)
        out.append({"index": j, "pointer": json_pointer(*toks),
                    "fact": _cell(ctx, row, None, slot, basis, published_caveats=published_caveats)})
    return out


def _device_gap(ctx: _Ctx, host: Any, section: str, needs: Sequence[str],
                config: bool = False) -> Optional[Tuple[str, List[Tuple[str, Sequence[Any]]]]]:
    """Why rows naming `host` may be missing from a list derived from `needs` (essential captures), first match
    wins: the owner's device scope calls it not collected -> its blind-spot row names a needed capture as
    missing -> it has no interface parse -> (with `config`) it has no security row. ``None``: nothing withheld."""
    if not _is_text(host):
        return None
    if ctx.device_blind(section, host):
        return _R_DEVICE_BLIND, ctx.cc_witness(host)
    i, row = ctx.cc_row(host)
    if i is not None and isinstance(row, dict) and _is_text(row.get("status")) and _norm(row["status"]) == "partial":
        missing = row.get("missing")
        if isinstance(missing, list):
            hit = [m for m in missing if _is_text(m) and m in needs]
            if hit:
                return (f"collection_completeness lists {', '.join(hit)} as missing for this device",
                        [("witness", ("collection_completeness", "devices", i, "missing"))])
        else:
            return ("collection_completeness lists this device as partial and names no readable missing list",
                    [("witness", ("collection_completeness", "devices", i))])
    if ctx.if_nc(host):
        return _R_NO_IFACE, []
    if config and _cfg_missing(ctx, host):
        return _R_NO_CONFIG, []
    return None


def _cfg_missing(ctx: _Ctx, host: str) -> bool:
    """`host` has no security row while the security map itself is readable (else the list rollup already says so)."""
    sec = ctx.s.get("security")
    return isinstance(sec, dict) and host not in sec


def _sel_state(ctx: _Ctx, base: str, reason: Optional[str], selected: Sequence[Any],
               gap: Optional[Tuple[str, List[Tuple[str, Sequence[Any]]]]],
               cbe: str) -> Tuple[str, Optional[str], List[Tuple[str, Sequence[Any]]]]:
    """The state of the rows of one list that name a device: the owner's rows, or an honest absence. A device gap
    makes the selection not_collected: with rows it may be incomplete, without rows it is no clean result."""
    if base not in (_PUB, _CBE):
        return base, reason, []
    if gap is not None:
        why, wit = gap
        if selected:
            return _NC, (f"not collected: the list may be incomplete: {why}; the rows shown are the ones other "
                         "evidence names"), wit
        return _NC, (f"not collected: {why}, so no row naming it could be derived; an absent row is not a clean "
                     "result"), wit
    if selected:
        return _PUB, None, []
    return _CBE, f"collected but empty: {cbe} (not a blind spot)", []


def _cap(limit: int, raw: Any, owner: str, readable: bool) -> Dict[str, Any]:
    """An engine cap: the limit, whether the list reaches it (``None`` when the list could not be read), and a total
    that no owner publishes."""
    return {"limit": limit, "reached": (isinstance(raw, list) and len(raw) >= limit) if readable else None,
            "total": _envelope(_NC, None, None, [], f"{owner} (capped; no total published)",
                               _R_CAP_TOTAL.format(limit=limit))}


def _total(ctx: _Ctx, section: str, listing: Dict[str, Any], *, sections: Sequence[str],
           witness: Sequence[Tuple[str, Sequence[Any]]] = (), caveats: Sequence[str] = (),
           qualify: Sequence[_Qualify] = ()) -> Dict[str, Any]:
    """A row list's total: the census count of its section, following the list's own final state (a live count,
    like the census summary: a zero over an empty list is published without a zero-mapping caveat)."""
    basis = f"ssot.compute_schema_census:{section}.count"
    state, reason, value = listing["state"], listing.get("reason"), None
    if state in (_PUB, _CBE):
        _live, fault = ctx.census()
        ok, typed = _count(ctx.census_count(section))
        if fault:
            state, reason = _UV, fault
        elif ok:
            state, value, reason = _PUB, typed, None
        else:
            state, reason = _UV, _unverified_reason("count")
    cav = list(caveats)
    wit = list(witness)
    if state == _PUB:
        for cid, _why, w in qualify:
            cav.append(cid)
            wit += w
        cav += _one_hop(ctx, state, sections)
    refs = ctx.refs([("witness", (section,))] + wit + ctx.failure_entries(sections, state == AU))
    return _envelope(state, value, None, refs, basis, reason or _state_reason(ctx, state, "count", sections),
                     caveats=cav if state == _PUB else ())


def _fleet_qualify(ctx: _Ctx, config: bool = False) -> List[_Qualify]:
    """The fleet-list qualifications (see :data:`_Qualify`): blind devices, and, for the punch-list, devices whose
    running-config was not captured."""
    out: List[_Qualify] = []
    blind = ctx.blind_rows()
    if blind:
        out.append(("fleet_lists_exclude_blind_devices", _R_FLEET_BLIND.format(n=len(blind)),
                    [("witness", ("collection_completeness", "devices", i)) for i in blind]))
    if config:
        lacking = ctx.no_config_hosts()
        if lacking:
            out.append(("findings_without_running_config", _R_FLEET_NO_CONFIG.format(n=len(lacking)),
                        [("witness", ("devices", h)) for h in lacking]))
    return out


def _vid(value: Any, strip: bool = True) -> Optional[int]:
    """The owners' VLAN-id key rule: a decimal text (or a non-negative int) -> int; anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        text = value.strip() if strip else value
        if text.isdigit():
            try:
                return int(text)
            except ValueError:                  # a Unicode digit int() rejects, or an over-long literal
                return None
    return None


def _vid_index(ctx: _Ctx, toks: Tuple[str, ...]) -> Dict[int, List[int]]:
    out: Dict[int, List[int]] = {}
    rows = _get(ctx.s, toks)
    for i, row in enumerate(rows if isinstance(rows, list) else ()):
        vid = _vid(row.get("vlan")) if isinstance(row, dict) else None
        if vid is not None:
            out.setdefault(vid, []).append(i)
    return out


# pre-checks (the engine's own "not observed" defaults and markers)
def _default_text(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
    return (_NC, _R_DEFAULT_TEXT) if raw == "" else None


def _default_zero(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
    return (_NC, _R_DEFAULT_ZERO) if _count(raw) == (True, 0) else None


def _null_value(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
    return (_NC, _R_NONE) if raw is None else None


def _marker(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
    return (_NC, _R_SENTINEL) if raw == NOT_OBSERVED_SENTINEL else None


def _sparse(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
    return (_NC, _R_SPARSE) if raw == "" else None


def _blank(reason: str, empty: Any = "") -> _Pre:
    """An empty text (or, with ``empty=[]``, an empty list) that means "not observed" for this field."""
    def pre(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
        return (_NC, reason) if type(raw) is type(empty) and raw == empty else None
    return pre


def _not_scored(_raw: Any, row: _Row) -> Optional[Tuple[str, str]]:
    band = row.raw.get("band") if isinstance(row.raw, dict) else None
    return (_NA, _R_NOT_SCORED) if isinstance(band, str) and band == HEALTH_BAND_NOT_SCORED else None


def _mg_pre(ctx: _Ctx) -> _Pre:
    def pre(_raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
        return None if ctx.mg_labelled else (_NC, _R_MG)
    return pre


# ---------------------------------------------------------------------------------------------------
# inventory: devices
# ---------------------------------------------------------------------------------------------------
_ABSENT_DEVICE = (_NC, "not collected: the collection never reached this device, so it has no device record "
                       "(model.DevicePhysical); coverage_matrix reads the same absence as a blind spot")
_ABSENT_HEALTH = (_NC, "not collected: health_scores carries no row for this device (the engine scores only "
                       "devices whose interfaces it parsed)")
_ABSENT_LIFECYCLE = (_NC, "not collected: lifecycle_risk carries no row for this device")
_ABSENT_DOSSIER = (_NC, "not collected: device_dossiers carries no row for this device")
_ABSENT_CC = (_CBE, "collected but empty: collection_completeness lists only partial or not-collected devices, "
                    "and it does not list this one (not a blind spot)")
#: A host outside the devices map that collection_completeness does not list either: only neighbours saw it.
_ABSENT_CC_PEER = (_NC, "not collected: this device is in neither the devices map nor collection_completeness; "
                        "only its neighbours reported it")
_B_HEALTH = "analyze.compute_health_scores:health_scores[]."
_B_LIFECYCLE = "analyze.compute_lifecycle_risk:lifecycle_risk.per_device[]."
_B_DOSSIER = "analyze.compute_device_dossiers:device_dossiers.per_device[]."
_B_CC = "analyze.compute_collection_completeness:collection_completeness.devices[]."


def _dev_basis(field: str) -> str:
    return "html.snapshot_state:devices{}." + field


def _joins(ctx: _Ctx, host: Any, forced: Optional[Tuple[str, str]] = None) -> Dict[str, _Row]:
    """The rows one device joins: its record, health, lifecycle, dossier and blind-spot rows. The blind-spot
    row itself is evidence of non-collection, so the device scope does not withhold it; it is joined by the rule
    of its owner's device scope (no case, no surrounding space). Its absence means "not a blind spot" only for a
    device the devices map carries."""
    devices = ctx.s.get("devices")
    in_devices = _is_text(host) and isinstance(devices, dict) and host in devices
    return {
        "devices": _resolve(ctx, ("devices",), ("devices",), key=host, host=host, absent=_ABSENT_DEVICE,
                            forced=forced),
        "health": _resolve(ctx, ("health_scores",), ("health_scores",), key=host, key_field="switch", host=host,
                           absent=_ABSENT_HEALTH, forced=forced),
        "lifecycle": _resolve(ctx, ("lifecycle_risk", "per_device"), ("lifecycle_risk",), key=host,
                              key_field="host", host=host, absent=_ABSENT_LIFECYCLE, forced=forced),
        "dossier": _resolve(ctx, ("device_dossiers", "per_device"), ("device_dossiers",), key=host,
                            key_field="host", host=host, absent=_ABSENT_DOSSIER, forced=forced),
        "collection": _resolve(ctx, ("collection_completeness", "devices"), ("collection_completeness",),
                               key=host, key_field="host", norm=True,
                               absent=_ABSENT_CC if in_devices else _ABSENT_CC_PEER, forced=forced),
    }


def _row_pointer(row: _Row) -> Optional[str]:
    return json_pointer(*row.toks) if row.state is None and row.toks is not None else None


def _health_caveat(ctx: _Ctx, host: Any,
                   dossier: _Row) -> Tuple[Tuple[str, ...], List[Tuple[str, Sequence[Any]]]]:
    """A score computed with no security row, or over a partial collection, carries a caveat: the first witnessed by
    the dossier's own 'na' security axis, the second by the blind-spot row's missing list."""
    cav: List[str] = []
    witness: List[Tuple[str, Sequence[Any]]] = []
    if not _is_text(host):
        return (), []
    if _cfg_missing(ctx, host):
        cav.append("health_scored_without_security")
        exps = dossier.raw.get("exposures") if dossier.state is None and isinstance(dossier.raw, dict) else None
        for j, exp in enumerate(exps if isinstance(exps, list) else ()):
            if isinstance(exp, dict) and exp.get("axis") == "Security posture" and exp.get("state") == "na":
                witness.append(("witness", dossier.toks + ("exposures", j)))
                break
    i, row = ctx.cc_row(host)
    if i is not None and isinstance(row, dict) and _is_text(row.get("status")) and _norm(row["status"]) == "partial":
        cav.append("health_scored_over_partial_collection")
        witness.append(("witness", ("collection_completeness", "devices", i, "missing")))
    return tuple(cav), witness


def _role_pre(ctx: _Ctx, host: Any) -> _Pre:
    def pre(_raw: Any, _row: _Row) -> Optional[Tuple[Any, ...]]:
        return (_NC, _R_ROLE_DEFAULT) if ctx.if_nc(host) else None
    return pre


def _health_cells(ctx: _Ctx, host: Any, j: Dict[str, _Row]) -> Dict[str, Dict[str, Any]]:
    cav, wit = _health_caveat(ctx, host, j["dossier"])
    health = j["health"]
    return {
        "score": _cell(ctx, health, "score", "score", _B_HEALTH + "score", pre=_not_scored, published_caveats=cav,
                       witness=wit),
        "band": _cell(ctx, health, "band", "enum", _B_HEALTH + "band", vocab=HEALTH_BANDS, pre=_not_scored,
                      published_caveats=cav, witness=wit),
        "role": _cell(ctx, health, "role", "text", _B_HEALTH + "role", pre=_role_pre(ctx, host)),
    }


def _risk_band(ctx: _Ctx, dossier: _Row) -> Dict[str, Any]:
    """The dossier band, caveated when it sits below the top band while the row's own n_na counts unassessed axes."""
    cav: Tuple[str, ...] = ()
    wit: List[Tuple[str, Sequence[Any]]] = []
    if dossier.state is None and isinstance(dossier.raw, dict):
        ok, n_na = _count(dossier.raw.get("n_na"))
        if ok and n_na > 0 and dossier.raw.get("risk_band") in DOSSIER_UNDERSTATABLE:
            cav, wit = ("dossier_band_over_unassessed_axes",), [("witness", dossier.toks + ("n_na",))]
    return _cell(ctx, dossier, "risk_band", "enum", _B_DOSSIER + "risk_band", vocab=DOSSIER_BANDS,
                 published_caveats=cav, witness=wit)


def _device_row(ctx: _Ctx, host: str, dev_keys: Iterable[str], cc_norm: Mapping[str, List[int]]) -> Dict[str, Any]:
    j = _joins(ctx, host)
    in_devices = host in dev_keys
    blind = cc_norm.get(_norm(host), [])
    pointer = (json_pointer("devices", host) if in_devices
               else json_pointer("collection_completeness", "devices", blind[0]) if len(blind) == 1 else None)
    health = _health_cells(ctx, host, j)
    row: Dict[str, Any] = {
        "host": host, "pointer": pointer,
        "rosters": {"devices": in_devices, "collection_completeness": bool(blind)},
        "rows": {name: _row_pointer(j[name]) for name in ("health", "lifecycle", "dossier", "collection")},
        "collection_status": _cell(ctx, j["collection"], "status", "enum", _B_CC + "status", vocab=CC_STATUSES),
    }
    for field in ("model", "platform", "sw_version", "serial_number"):
        row[field] = _cell(ctx, j["devices"], field, "text", _dev_basis(field), pre=_default_text)
    row.update(role=health["role"], health_score=health["score"], health_band=health["band"],
               lifecycle_band=_cell(ctx, j["lifecycle"], "band", "enum", _B_LIFECYCLE + "band",
                                    vocab=LIFECYCLE_BAND_ORDER),
               risk_band=_risk_band(ctx, j["dossier"]))
    return row


def _device_rows(ctx: _Ctx) -> Dict[str, Any]:
    devices = ctx.s.get("devices")
    dev_keys = frozenset(k for k in devices if _is_text(k)) if isinstance(devices, dict) else frozenset()
    cc_norm = ctx.index(("collection_completeness", "devices"), ("host",), norm=True)
    dev_norm = {_norm(k) for k in dev_keys}
    cc_rows = _get(ctx.s, ("collection_completeness", "devices"))
    # a blind spot the devices map names (without case or surrounding space) is that device's row, not a new one;
    # the rest are named by their first row's own spelling
    blind_only = {cc_rows[idx[0]]["host"] for name, idx in cc_norm.items() if name not in dev_norm}
    hosts = sorted(dev_keys | blind_only)
    items = [_device_row(ctx, host, dev_keys, cc_norm) for host in hosts]
    base, reason, _raw = _list_state(ctx, ("devices",), ("devices",), want=dict)
    if base in (_PUB, _CBE):
        base = _PUB if items else _CBE
    rows = _listing(ctx, base, reason, ("devices",),
                    "html.snapshot_state:devices + analyze.compute_collection_completeness:"
                    "collection_completeness.devices", items, sections=("devices",),
                    rollup=("collection_completeness",),
                    caveats=("row_selection_by_exact_key", "device_physical_defaults_not_observed"))
    n_rows = len(items)

    def _matches_rows(_ctx: _Ctx, typed: Any, _zero: bool):
        if typed == n_rows:
            return None
        return (_UV, f"unverified: the inventory rows (the devices map and the collection_completeness blind spots) "
                     f"number {n_rows}; the owner's inventory count says {typed}", [])

    total = _scalar(ctx, "collection_completeness.summary.inventory", "count",
                    "analyze.compute_collection_completeness:collection_completeness.summary.inventory",
                    gate=_matches_rows, witness=[("witness", ("executive_brief", "scale", "n_devices")),
                                                 ("witness", ("coverage_matrix", "summary", "n_devices"))],
                    published_caveats=_brief_caveats(ctx))
    return {"total": total, "rows": rows}


# ---------------------------------------------------------------------------------------------------
# inventory: VLANs
# ---------------------------------------------------------------------------------------------------
_B_VLAN = "analyze.compute_vlan_cutover_matrix:vlan_cutover[]."
_R_NO_GROUP = "not collected: none of this VLAN's switches is in a sequenced move group"


def _vlan_endpoint_zero(raw: Any, row: _Row) -> Optional[Tuple[str, str]]:
    if _count(raw) == (True, 0) and isinstance(row.raw, dict) and row.raw.get("endpoint_mix") == NOT_OBSERVED_SENTINEL:
        return (_NC, "not collected: no endpoint was observed on this VLAN (its endpoint_mix is the engine's "
                     "not-observed marker), so the 0 is not a measurement")
    return None


def _vlan_election_pre(ctx: _Ctx) -> _Pre:
    """The default-election flag is ``False`` over nothing when no root was observed, or when the root the owner
    reads carries no parsed priority (compute_vlan_cutover_matrix tests ``isinstance(prio, int)``)."""
    def pre(_raw: Any, row: _Row) -> Optional[Tuple[Any, ...]]:
        rec = row.raw if isinstance(row.raw, dict) else {}
        if rec.get("stp_root") == NOT_OBSERVED_SENTINEL:
            return (_NC, "not collected: no STP root was observed for this VLAN, so the default-election flag is a "
                         "false over nothing")
        ok, vid = _count(rec.get("vlan"))
        root = ctx.stp_root_record(vid) if ok else None
        if root is None:
            return None
        host, key, record = root
        prio = record.get("root_priority")
        if isinstance(prio, int) and not isinstance(prio, bool):
            return None
        toks = ("stp_roots", host, key) + (("root_priority",) if "root_priority" in record else ())
        return (_NC, "not collected: the root bridge's root_priority for this VLAN was not parsed (it is not a "
                     "number), so the default-election flag is a false over nothing", [("witness", toks)])
    return pre


_SVI = re.compile(r"^Vlan0*(\d+)$", re.IGNORECASE)                  # compute_vlan_cutover_matrix's SVI rule


def _vlan_deps_pre(ctx: _Ctx) -> _Pre:
    """An empty dependency list is a clean result only when the DHCP relay could be read on every gateway SVI: the
    producer reads ``dhcp_helpers`` from the gateway SVI's running-config, so no gateway, or a gateway SVI whose
    running-config was not observed, leaves the relay unread."""
    def pre(raw: Any, row: _Row) -> Optional[Tuple[Any, ...]]:
        if not (isinstance(raw, list) and not raw):
            return None
        rec = row.raw if isinstance(row.raw, dict) else {}
        ok, vid = _count(rec.get("vlan"))
        hosts = rec.get("gateway_svi_hosts")
        if not ok or not isinstance(hosts, list) or not hosts:
            return (_NC, "not collected: no gateway SVI was observed for this VLAN, so its DHCP relay could not be "
                         "read; an empty list is not a clean result")
        ifaces = ctx.s.get("interfaces")
        unread: List[Tuple[str, Sequence[Any]]] = []
        for host in hosts:
            ports = ifaces.get(host) if isinstance(ifaces, dict) and _is_text(host) else None
            svis = [p for p in (ports if isinstance(ports, dict) else ())
                    if _is_text(p) and _SVI.match(p) and _vid(_SVI.match(p).group(1)) == vid]
            if not svis:
                unread.append(("witness", ("interfaces", host)) if _is_text(host) else ("witness", ("interfaces",)))
            for port in svis:
                svi = ports[port]
                if not (isinstance(svi, dict) and svi.get("run_config_observed") is True):
                    unread.append(("witness", ("interfaces", host, port)))
        if unread:
            return (_NC, "not collected: the running-config of a gateway SVI for this VLAN was not observed, so its "
                         "DHCP relay could not be read; an empty list is not a clean result", unread)
        return None
    return pre


def _vlan_scenario_pre(raw: Any, row: _Row) -> Optional[Tuple[Any, ...]]:
    if raw != "":
        return None
    wave = row.raw.get("wave") if isinstance(row.raw, dict) else None
    if _is_text(wave) and wave:
        return (_NC, "not collected: the wave sequencing names none of this VLAN's switches as hard cutover, "
                     "make-before-break or homing unknown")
    return _NC, _R_NO_GROUP


#: VLAN field -> (slot, vocabulary, pre-check, empty rule, published caveats). A pre-check that reads other records
#: is built per call (:func:`_vlan_rows`).
_VLAN_CELLS: Mapping[str, Tuple[str, Tuple[str, ...], Optional[_Pre], Optional[Tuple[str, str]], Tuple[str, ...]]] = \
    MappingProxyType({
        "vlan": ("count", (), None, None, ()),
        "name": ("text", (), _blank("not collected: no VLAN name was evidenced"), None, ()),
        "stp_root": ("text", (), _marker, None, ()),
        "stp_root_default_election": ("flag", (), None, None, ()),
        "fhrp": ("fhrp", (), _marker, None, ()),
        "gateway_svi_hosts": ("text_list", (), _blank("not collected: no gateway SVI was observed for this VLAN "
                                                      "(its fhrp abstains with the engine's marker)", []), None, ()),
        "endpoint_count": ("count", (), _vlan_endpoint_zero, None, ("vlan_cutover_universe",)),
        "endpoint_mix": ("text", (), _marker, None, ()),
        "app_domain": ("text", (), None, (_CBE, "collected but empty: no application domain maps this VLAN "
                                                "(not a blind spot)"), ()),
        "criticality": ("text", (), None, (_CBE, "collected but empty: no application domain maps this VLAN "
                                                 "(not a blind spot)"), ()),
        "dependencies": ("text_list", (), None, (_CBE, "collected but empty: the engine flagged no multicast, "
                                                       "querier or DHCP-relay dependency for this VLAN, and every "
                                                       "gateway SVI's running-config was read (not a blind spot)"),
                         ()),
        "wave": ("text", (), _blank(_R_NO_GROUP), None, ()),
        "scenario": ("text", (), _vlan_scenario_pre, None, ()),
        "readiness": ("enum", VLAN_READINESS, _blank("not collected: no readiness verdict covers this VLAN's move "
                                                     "groups"), None, ()),
        "cutover_window": ("text", (), _blank(_R_HUMAN), None, ()),
        "rollback_owner": ("text", (), _blank(_R_HUMAN), None, ()),
    })


def _stp_root_index(ctx: _Ctx) -> Dict[int, List[str]]:
    """VLAN id -> ``/stp_roots/<host>/<vid>`` for every non-MST record whose key is a VLAN id (the owner's rule)."""
    out: Dict[int, List[str]] = {}
    roots = ctx.s.get("stp_roots")
    for host in sorted(k for k in roots if _is_text(k)) if isinstance(roots, dict) else ():
        recs = roots[host]
        for key in (sorted(k for k in recs if _is_text(k)) if isinstance(recs, dict) else ()):
            vid = _vid(key, strip=False)
            if vid is not None and isinstance(recs[key], dict) and not recs[key].get("is_mst"):
                out.setdefault(vid, []).append(json_pointer("stp_roots", host, key))
    return {vid: sorted(ptrs) for vid, ptrs in out.items()}


def _source(ctx: _Ctx, toks: Tuple[str, ...], sections: Sequence[str], basis: str,
            want: Any = list) -> Tuple[Dict[str, Any], bool]:
    """The evidence state of a list a selection reads, and whether its rows can be selected at all."""
    state, reason, _raw = _list_state(ctx, toks, sections, want)
    all_secs = (".".join(toks),) + tuple(sections)
    out: Dict[str, Any] = {"state": state, "subject": json_pointer(*toks),
                           "refs": ctx.refs([("subject", toks)] + ctx.failure_entries(all_secs, state == AU)),
                           "basis": basis}
    if state != _PUB:
        out["reason"] = reason or (_R_CBE if state == _CBE else _state_reason(ctx, state, "list", all_secs))
    return out, state in (_PUB, _CBE)


def _vlan_rows(ctx: _Ctx) -> Dict[str, Any]:
    toks = ("vlan_cutover",)
    base, reason, raw = _list_state(ctx, toks, toks)
    src_roots, ok_roots = _source(ctx, ("stp_roots",), ("stp_roots",), "build.build_stp_roots:stp_roots{}{}", want=dict)
    src_gw, ok_gw = _source(ctx, ("l3_forwarding",), ("l3_forwarding",),
                            "excel.write_l3_forwarding_sheet:l3_forwarding[]")
    src_ep, ok_ep = _source(ctx, ("endpoint_identity",), ("endpoint_identity",),
                            "analyze.compute_endpoint_identity:endpoint_identity[]")
    roots, gateways, endpoints = _stp_root_index(ctx), _vid_index(ctx, ("l3_forwarding",)), _vid_index(
        ctx, ("endpoint_identity",))
    pres = {"stp_root_default_election": _vlan_election_pre(ctx), "dependencies": _vlan_deps_pre(ctx)}
    capped = ENGINE_LIST_CAPS["vlan_cutover[].app_domain"]
    items: List[Dict[str, Any]] = []
    for i, rec in enumerate(raw if isinstance(raw, list) else ()):
        row = _list_row(toks + (i,), rec, toks)
        item: Dict[str, Any] = {"index": i, "pointer": json_pointer(*toks, i)}
        for field, (slot, vocab, pre, empty, pub_cav) in _VLAN_CELLS.items():
            if field == "app_domain":
                dom = rec.get("app_domain") if isinstance(rec, dict) else None
                if _is_text(dom) and dom and len(dom.split(APP_DOMAIN_JOINER)) >= capped:
                    pub_cav = pub_cav + ("engine_list_capped",)
            item[field] = _cell(ctx, row, field, slot, _B_VLAN + field, vocab=vocab,
                                sections=toks + VLAN_FIELD_BASIS[field], pre=pres.get(field, pre), empty=empty,
                                published_caveats=pub_cav)
        ok, vid = _count(rec.get("vlan")) if isinstance(rec, dict) else (False, None)
        item["selections"] = {"stp_roots": (list(roots.get(vid, ())) if ok else []) if ok_roots else None,
                              "gateways": (list(gateways.get(vid, ())) if ok else []) if ok_gw else None,
                              "endpoints": (list(endpoints.get(vid, ())) if ok else []) if ok_ep else None}
        items.append(item)
    qualify = _fleet_qualify(ctx)
    listing = _listing(ctx, base, reason, toks, "analyze.compute_vlan_cutover_matrix:vlan_cutover", items,
                       sections=toks, caveats=("vlan_cutover_universe", "vlan_field_basis_owned_by_projection",
                                               "row_selection_by_exact_key"), qualify=qualify)
    total = _total(ctx, "vlan_cutover", listing, sections=toks,
                   witness=[("witness", ("executive_brief", "scale", "n_vlans"))], caveats=("vlan_cutover_universe",),
                   qualify=qualify)
    return {"total": total, "rows": listing,
            "selection_sources": {"stp_roots": src_roots, "gateways": src_gw, "endpoints": src_ep}}


# ---------------------------------------------------------------------------------------------------
# inventory: endpoints
# ---------------------------------------------------------------------------------------------------
_B_EP = "analyze.compute_endpoint_identity:endpoint_identity[]."
_B_DEPS = "analyze.compute_endpoint_dependencies:endpoint_dependencies."
_EP_BLANK = {
    "host": "not collected: the engine row names no switch", "port": "not collected: the engine row names no port",
    "mac": "not collected: the engine row names no MAC", "vlan": "not collected: the engine row names no VLAN",
    "ip": "not collected: no ARP entry resolved this endpoint's MAC to an IP address",
    "vendor": "not collected: the offline OUI registry returned no vendor for this MAC",
}


def _endpoint_row(ctx: _Ctx, i: int, rec: Any, vlan_rows: Optional[Mapping[int, List[int]]],
                  shared: Optional[Mapping[str, List[int]]], dual: Optional[Mapping[str, List[int]]],
                  ifaces_ok: bool) -> Dict[str, Any]:
    """One endpoint row. A selection whose source list could not be read is null (a ``None`` index)."""
    toks = ("endpoint_identity", i)
    row = _list_row(toks, rec, ("endpoint_identity",))
    item: Dict[str, Any] = {"index": i, "pointer": json_pointer(*toks)}
    for field in ("host", "port", "mac", "vlan", "ip"):
        item[field] = _cell(ctx, row, field, "text", _B_EP + field, pre=_blank(_EP_BLANK[field]))
    item["mac_count"] = _cell(ctx, row, "mac_count", "count", _B_EP + "mac_count")
    item["vendor"] = _cell(ctx, row, "vendor", "text", _B_EP + "vendor", pre=_blank(_EP_BLANK["vendor"]))
    item["endpoint_class"] = _cell(ctx, row, "endpoint_class", "text", _B_EP + "endpoint_class")
    item["confidence"] = _cell(ctx, row, "confidence", "enum", _B_EP + "confidence", vocab=ENDPOINT_CONFIDENCES)
    item["evidence"] = _cell(ctx, row, "evidence", "text", _B_EP + "evidence")
    rec = rec if isinstance(rec, dict) else {}
    host, port, ip, mac = rec.get("host"), rec.get("port"), rec.get("ip"), rec.get("mac")
    iface = (json_pointer("interfaces", host, port) if ifaces_ok and _is_text(host) and _is_text(port)
             and _get(ctx.s, ("interfaces", host, port)) is not _MISSING else None)
    vid = _vid(rec.get("vlan")) if _is_text(rec.get("vlan")) or isinstance(rec.get("vlan"), int) else None
    matches = (vlan_rows.get(vid, []) if vid is not None else []) if vlan_rows is not None else []
    ip_key = ip.strip() if _is_text(ip) else ""
    item["selections"] = {
        "interface": iface, "vlan_row": matches[0] if len(matches) == 1 else None,
        "shared_ip": None if shared is None else (list(shared.get(ip_key, ())) if ip_key else []),
        "dual_homed": None if dual is None else (list(dual.get(mac.lower(), ())) if _is_text(mac) else [])}
    return item


def _dual_homed_row(ctx: _Ctx, k: int, rec: Any) -> Dict[str, Any]:
    toks = ("endpoint_dependencies", "dual_homed", k)
    row = _list_row(toks, rec, ("endpoint_dependencies",))
    basis = _B_DEPS + "dual_homed[]."
    mg_secs = ("endpoint_dependencies", "move_groups")
    ports = rec.get("ports") if isinstance(rec, dict) else None
    cap = ENGINE_LIST_CAPS["endpoint_dependencies.dual_homed[].ports"]
    ports_fact = _cell(ctx, row, "ports", "text_list", basis + "ports",
                       published_caveats=("engine_list_capped",) if isinstance(ports, list) and len(ports) >= cap
                       else ())
    return {
        "index": k, "pointer": json_pointer(*toks),
        "mac": _cell(ctx, row, "mac", "text", basis + "mac"),
        "endpoint_class": _cell(ctx, row, "endpoint_class", "text", basis + "endpoint_class"),
        "ip": _cell(ctx, row, "ip", "text", basis + "ip", pre=_blank(_EP_BLANK["ip"])),
        "vendor": _cell(ctx, row, "vendor", "text", basis + "vendor", pre=_blank(_EP_BLANK["vendor"])),
        "switches": _cell(ctx, row, "switches", "text_list", basis + "switches"),
        "ports": ports_fact,
        "ports_cap": _cap(cap, ports, "analyze.compute_endpoint_dependencies", ports_fact["state"] in (_PUB, _CBE)),
        "move_groups": _cell(ctx, row, "move_groups", "text_list", basis + "move_groups", sections=mg_secs,
                             pre=_mg_pre(ctx)),
        "split_across_groups": _cell(ctx, row, "split_across_groups", "flag", basis + "split_across_groups",
                                     sections=mg_secs, pre=_mg_pre(ctx)),
    }


def _endpoint_rows(ctx: _Ctx) -> Dict[str, Any]:
    toks = ("endpoint_identity",)
    base, reason, raw = _list_state(ctx, toks, toks)
    deps = ("endpoint_dependencies",)
    stoks, dtoks = ("endpoint_dependencies", "shared_ip"), ("endpoint_dependencies", "dual_homed")
    src_if, ok_if = _source(ctx, ("interfaces",), ("interfaces",), "html.snapshot_state:interfaces{}{}", want=dict)
    src_vl, ok_vl = _source(ctx, ("vlan_cutover",), ("vlan_cutover",),
                            "analyze.compute_vlan_cutover_matrix:vlan_cutover[]")
    src_sh, ok_sh = _source(ctx, stoks, deps, _B_DEPS + "shared_ip[]")
    src_dh, ok_dh = _source(ctx, dtoks, deps, _B_DEPS + "dual_homed[]")
    vlan_rows: Dict[int, List[int]] = {}
    vrows = ctx.s.get("vlan_cutover")
    for k, rec in enumerate(vrows if isinstance(vrows, list) else ()):
        ok, vid = _count(rec.get("vlan")) if isinstance(rec, dict) else (False, None)
        if ok:
            vlan_rows.setdefault(vid, []).append(k)
    shared = ctx.index(stoks, ("ip",)) if ok_sh else None
    dual = ctx.index(dtoks, ("mac",)) if ok_dh else None
    items = [_endpoint_row(ctx, i, rec, vlan_rows if ok_vl else None, shared, dual, ok_if)
             for i, rec in enumerate(raw if isinstance(raw, list) else ())]
    qualify = _fleet_qualify(ctx)
    listing = _listing(ctx, base, reason, toks, "analyze.compute_endpoint_identity:endpoint_identity", items,
                       sections=toks, caveats=("row_selection_by_exact_key",), qualify=qualify)
    total = _total(ctx, "endpoint_identity", listing, sections=toks,
                   witness=[("witness", ("executive_brief", "scale", "n_endpoints"))], qualify=qualify)
    sbase, sreason, sraw = _list_state(ctx, stoks, deps)
    shared_list = _listing(ctx, sbase, sreason, stoks, _B_DEPS + "shared_ip",
                           _items(ctx, stoks, sraw, "shared_ip", _B_DEPS + "shared_ip[]", deps), sections=deps,
                           rollup=toks, qualify=qualify)
    dbase, dreason, draw = _list_state(ctx, dtoks, deps)
    dual_items = [_dual_homed_row(ctx, k, rec) for k, rec in enumerate(draw if isinstance(draw, list) else ())]
    dual_list = _listing(ctx, dbase, dreason, dtoks, _B_DEPS + "dual_homed", dual_items, sections=deps, rollup=toks,
                         caveats=("engine_list_capped",) + (() if ctx.mg_labelled else ("move_group_label_absent",)),
                         qualify=qualify)
    return {"total": total, "rows": listing, "shared_ip": shared_list, "dual_homed": dual_list,
            "selection_sources": {"interfaces": src_if, "vlan_rows": src_vl, "shared_ip": src_sh,
                                  "dual_homed": src_dh}}


def _uncollected_peers(ctx: _Ctx) -> Dict[str, Any]:
    toks = ("cable_map", "nodes")
    base, reason, raw = _list_state(ctx, toks, ("cable_map",))
    basis = "analyze.compute_cable_map:cable_map.nodes[]."
    items = []
    unreadable = []
    for i, node in enumerate(raw if isinstance(raw, list) else ()):
        if not (isinstance(node, dict) and isinstance(node.get("collected"), bool)):
            unreadable.append(i)
        elif node["collected"] is False:
            row = _Row(None, None, toks + (i,), node, ("cable_map",))
            items.append({"index": i, "pointer": json_pointer(*toks, i),
                          "host": _cell(ctx, row, "host", "text", basis + "host"),
                          "kind": _cell(ctx, row, "kind", "text", basis + "kind")})
    extra: List[Tuple[str, Sequence[Any]]] = []
    if base in (_PUB, _CBE):
        if unreadable:
            base = _UV
            reason = (f"unverified: {len(unreadable)} cable-map node(s) carry no boolean 'collected' flag, so the "
                      "list of uncollected peers cannot be complete")
            extra = [("witness", toks + (i,)) for i in unreadable]
        else:
            base, reason = (_PUB, None) if items else (
                _CBE, "collected but empty: every cable-map node was collected (not a blind spot)")
    return _listing(ctx, base, reason, toks, "analyze.compute_cable_map:cable_map.nodes (collected is false)", items,
                    sections=("cable_map",), extra=extra)


def _inventory(ctx: _Ctx) -> Dict[str, Any]:
    return {"devices": _device_rows(ctx), "vlans": _vlan_rows(ctx), "endpoints": _endpoint_rows(ctx),
            "uncollected_peers": _uncollected_peers(ctx)}


def project_inventory(snap: Any) -> Dict[str, Any]:
    """The Inventory screens: device rows, VLAN rows, endpoint rows (with their dependency lists) and the
    cable-map peers nobody collected. Every row list is in a stable order with a total from its owner."""
    return _inventory(_Ctx(snap))


# ---------------------------------------------------------------------------------------------------
# findings (the migration punch-list)
# ---------------------------------------------------------------------------------------------------
_B_PUNCH = "analyze.compute_migration_punchlist:punchlist[]."


def _priority_gate(_ctx: _Ctx, typed: Any, row: _Row):
    if row.toks is not None and typed == row.toks[-1] + 1:
        return None
    return (_UV, "unverified: the producer numbers the punch-list 1..n in its own order; this row's priority is not "
                 "its position", [])


def _rank_gate(_ctx: _Ctx, typed: Any, row: _Row):
    sev = row.raw.get("severity") if isinstance(row.raw, dict) else None
    if isinstance(sev, str) and sev in SEVERITIES and typed == PUNCH_RANK.get(sev, 0):
        return None
    return (_UV, "unverified: the producer derives rank from severity (Critical 4, High 3, Medium 2, Low 1, else 0); "
                 "this row's rank does not match its severity", [])


def _unpublished_marker(marker: str, what: str) -> _Pre:
    def pre(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
        return (_NC, f"not collected: the engine's own marker that this row publishes no {what}") if raw == marker \
            else None
    return pre


_BASIS_PRE = _unpublished_marker(PUNCH_BASIS_UNPUBLISHED, "severity basis")
_CONF_PRE = _unpublished_marker(PUNCH_CONFIDENCE_UNPUBLISHED, "evidence confidence")
_R_FOLDED_ONLY = "not collected: the engine publishes {what} only for the multicast / media risks it folds"


def _finding_row(ctx: _Ctx, i: int, rec: Any, cav: Tuple[str, ...]) -> Dict[str, Any]:
    toks = ("punchlist", i)
    row = _list_row(toks, rec, ("punchlist",))
    item: Dict[str, Any] = {
        "index": i, "pointer": json_pointer(*toks),
        "priority": _cell(ctx, row, "priority", "count", _B_PUNCH + "priority", gate=_priority_gate,
                          published_caveats=cav),
        "rank": _cell(ctx, row, "rank", "count", _B_PUNCH + "rank", gate=_rank_gate, published_caveats=cav),
        "severity": _cell(ctx, row, "severity", "enum", _B_PUNCH + "severity", vocab=SEVERITIES, published_caveats=cav),
    }
    for field in ("category", "title"):
        item[field] = _cell(ctx, row, field, "text", _B_PUNCH + field, published_caveats=cav)
    detail = rec.get("detail") if isinstance(rec, dict) else None
    clipped = ("engine_list_capped",) if _is_text(detail) and PUNCH_DETAIL_CLIP_MARKER in detail else ()
    item["detail"] = _cell(ctx, row, "detail", "text", _B_PUNCH + "detail", published_caveats=cav + clipped)
    item["devices"] = _cell(ctx, row, "devices", "text_list", _B_PUNCH + "devices", published_caveats=cav,
                            empty=(_CBE, "collected but empty: a fleet-level row that names no device (not a blind "
                                         "spot)"))
    item["wave"] = _cell(ctx, row, "wave", "text", _B_PUNCH + "wave", sections=("punchlist", "move_groups"),
                         pre=_mg_pre(ctx), published_caveats=cav,
                         empty=(_CBE, "collected but empty: none of this row's devices is in a labelled move group "
                                      "(not a blind spot)"))
    item["remediation"] = _cell(ctx, row, "remediation", "text", _B_PUNCH + "remediation", published_caveats=cav,
                                empty=(_CBE, "collected but empty: the engine linked no remediation to this row (not "
                                             "a blind spot)"))
    item["severity_basis"] = _cell(ctx, row, "severity_basis", "text", _B_PUNCH + "severity_basis", pre=_BASIS_PRE,
                                   missing=_R_FOLDED_ONLY.format(what="a severity basis"), published_caveats=cav)
    item["evidence_confidence"] = _cell(ctx, row, "evidence_confidence", "text", _B_PUNCH + "evidence_confidence",
                                        pre=_CONF_PRE, missing=_R_FOLDED_ONLY.format(what="an evidence confidence"),
                                        published_caveats=cav)
    item["source_command"] = _cell(ctx, row, "source_command", "text", _B_PUNCH + "source_command",
                                   missing=_R_NO_SOURCE_CMD, published_caveats=cav)
    return item


def _findings(ctx: _Ctx) -> Dict[str, Any]:
    toks = ("punchlist",)
    base, reason, raw = _list_state(ctx, toks, toks)
    cav = _brief_caveats(ctx)
    items = [_finding_row(ctx, i, rec, cav) for i, rec in enumerate(raw if isinstance(raw, list) else ())]
    mg = () if ctx.mg_labelled else ("move_group_label_absent",)
    qualify = _fleet_qualify(ctx, config=True)
    listing = _listing(ctx, base, reason, toks, "analyze.compute_migration_punchlist:punchlist", items, sections=toks,
                       rollup=PUNCHLIST_INPUTS, caveats=("punch_rows_carry_no_evidence_pointers",) + mg + cav,
                       qualify=qualify)
    total = _total(ctx, "punchlist", listing, sections=toks + PUNCHLIST_INPUTS,
                   caveats=("punch_rows_carry_no_evidence_pointers",), qualify=qualify)
    axes = _get(ctx.s, ("executive_brief", "axes"))
    heads = [k for k, ax in enumerate(axes) if isinstance(ax, dict) and ax.get("axis") == "Migration punch-list"] \
        if isinstance(axes, list) else []
    return {"total": total, "headline_axis_index": heads[0] if len(heads) == 1 else None, "rows": listing}


def project_findings(snap: Any) -> Dict[str, Any]:
    """The Findings screen: the engine's punch-list rows, with the remediation it links and nothing more."""
    return _findings(_Ctx(snap))


# ---------------------------------------------------------------------------------------------------
# the device page (a standalone document per device)
# ---------------------------------------------------------------------------------------------------
_B_IF = "html.snapshot_state:interfaces{}{}."
_B_SEC = "parse.parse_security:security{}."
_B_RP = "analyze.compute_remediation_plan:remediation_plan.by_device{}[]."
_B_NRFU = "nrfu_export.compute_nrfu_commands:nrfu_commands.waves[].devices[].cases[]."


def _nrfu_marker(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
    return (_NC, _R_SENTINEL) if raw == NRFU_NOT_OBSERVED else None


def _roc_false(raw: Any, _row: _Row) -> Optional[Tuple[str, str]]:
    return (_NC, "not collected: the record does not say the running-config was observed for this port") \
        if raw is False else None


def _interfaces_block(ctx: _Ctx, host: Any, forced: Optional[Tuple[str, str]]) -> Dict[str, Any]:
    ifr = _resolve(ctx, ("interfaces",), ("interfaces",), key=host, host=host, forced=forced,
                   absent=(_NC, "not collected: interfaces carries no parse result for this device"))
    rows: List[Dict[str, Any]] = []
    if ifr.state is None:
        for port in sorted(k for k in ifr.raw if _is_text(k)):
            toks = ifr.toks + (port,)
            prow = _list_row(toks, ifr.raw[port], ("interfaces",))
            rows.append({"port": port, "pointer": json_pointer(*toks),
                         "cells": {c: _cell(ctx, prow, c, "text", _B_IF + c, pre=_sparse, missing=_R_SPARSE)
                                   for c in IF_COLUMNS},
                         "run_config_observed": _cell(ctx, prow, "run_config_observed", "flag",
                                                      _B_IF + "run_config_observed", pre=_roc_false,
                                                      missing="not collected: the record does not say the "
                                                              "running-config was observed for this port")})
    state, reason = (ifr.state, ifr.reason) if ifr.state else (
        (_PUB, None) if rows else (_NC, "not collected: the interface parse returned no port for this device (an "
                                        "unparseable capture reads the same)"))
    return {"columns": list(IF_COLUMNS),
            "rows": _listing(ctx, state, reason, ifr.toks, "html.snapshot_state:interfaces{}", rows,
                             sections=("interfaces",), extra=ifr.extra, caveats=("interface_default_not_observed",),
                             bare=ifr.bare)}


def _selection_rows(ctx: _Ctx, host: Any, forced: Optional[Tuple[str, str]], block: str, toks: Tuple[str, ...],
                    fields: Tuple[str, ...], basis: str, cbe: str, build: Callable[[int, Any], Dict[str, Any]], *,
                    multi: bool = False, base_state: Optional[Tuple[str, Optional[str], Any]] = None,
                    sections: Optional[Tuple[str, ...]] = None, config: bool = False) -> Dict[str, Any]:
    """The rows of one engine list that name this device (selection only; never a count). The device's own gaps
    (:func:`_device_gap` over the captures :data:`SELECTION_NEEDS` names for `block`) make it not_collected."""
    secs = sections or (toks[0],)
    if forced is not None:
        return _listing(ctx, forced[0], forced[1], None, basis, [], bare=True)
    base, reason, raw = base_state or _list_state(ctx, toks, (toks[0],))
    sel = ctx.index(toks, fields, multi).get(host, []) if isinstance(raw, list) and _is_text(host) else []
    items = [build(i, raw[i]) for i in sel]
    gap = _device_gap(ctx, host, toks[0], SELECTION_NEEDS[block], config=config)
    state, reason, wit = _sel_state(ctx, base, reason, sel, gap, cbe)
    return _listing(ctx, state, reason, toks, basis, items, sections=secs, extra=wit,
                    caveats=("row_selection_by_exact_key",))


def _cable_row(ctx: _Ctx, i: int, rec: Any) -> Dict[str, Any]:
    toks = ("cable_map", "cables", i)
    row = _list_row(toks, rec, ("cable_map",))
    basis = "analyze.compute_cable_map:cable_map.cables[]."
    return {"index": i, "pointer": json_pointer(*toks),
            "ends": _cell(ctx, row, None, "cable_ends", basis + "{a, a_port, b, b_port, is_pc}"),
            "speed": _cell(ctx, row, "speed", "text", basis + "speed",
                           pre=_blank("not collected: no link speed was observed for this cable")),
            "confirmation": _cell(ctx, row, "confirmation", "text", basis + "confirmation"),
            "op_status": _cell(ctx, row, "op_status", "enum", basis + "op_status", vocab=OP_STATUSES)}


def _routes_block(ctx: _Ctx, host: Any, forced: Optional[Tuple[str, str]]) -> Dict[str, Any]:
    rr = _resolve(ctx, ("routes",), ("routes",), key=host, host=host, want=list, forced=forced,
                  absent=(_NC, "not collected: routes carries no in-scope route for this device, or its routing "
                               "table was not parsed"))
    basis = "build.scope_routes:routes{}[]."
    items: List[Dict[str, Any]] = []
    for i, rec in enumerate(rr.raw if rr.state is None else ()):
        toks = rr.toks + (i,)
        row = _list_row(toks, rec, ("routes",))
        none = (_CBE, "collected but empty: the route line states none (not a blind spot)")
        items.append({"index": i, "pointer": json_pointer(*toks),
                      "prefix": _cell(ctx, row, "prefix", "text", basis + "prefix"),
                      "source": _cell(ctx, row, "source", "text", basis + "source"),
                      "next_hop": _cell(ctx, row, "next_hop", "text", basis + "next_hop", empty=none),
                      "out_intf": _cell(ctx, row, "out_intf", "text", basis + "out_intf", empty=none),
                      "admin_distance": _cell(ctx, row, "admin_distance", "count", basis + "admin_distance",
                                              pre=_null_value, missing="not collected: the route line carries no "
                                                                       "administrative distance")})
    state, reason = (rr.state, rr.reason) if rr.state else (
        (_PUB, None) if items else (_CBE, "collected but empty: no in-scope route for this device (not a blind spot)"))
    return _listing(ctx, state, reason, rr.toks, "build.scope_routes:routes{}", items, sections=("routes",),
                    extra=rr.extra, caveats=("routes_in_scope_only",), bare=rr.bare)


def _neighbors_block(ctx: _Ctx, host: Any, forced: Optional[Tuple[str, str]]) -> Dict[str, Any]:
    rn = _resolve(ctx, ("routing_neighbors",), ("routing_neighbors",), key=host, host=host, forced=forced,
                  absent=(_NC, "not collected: routing_neighbors carries no row for this device"))
    group_basis = "build.build_routing_neighbors:routing_neighbors{}{}"
    basis = group_basis + "[]."
    groups: List[Dict[str, Any]] = []
    for proto in (sorted(k for k in rn.raw if _is_text(k)) if rn.state is None else ()):
        gtoks = rn.toks + (proto,)
        lst = rn.raw[proto]
        rows: List[Dict[str, Any]] = []
        if not isinstance(lst, list):
            state, reason = _UV, "unverified: the neighbour list is not a list"
        elif not lst:
            state, reason = _NC, ("not collected: an empty neighbour list means the protocol is not running, or its "
                                  "command was not collected or not parsed; the engine does not tell them apart")
        else:
            state, reason = _PUB, None
            for i, rec in enumerate(lst):
                toks = gtoks + (i,)
                row = _list_row(toks, rec, ("routing_neighbors",))
                cells = {f: _cell(ctx, row, f, "text", basis + f,
                                  missing=f"not collected: the {proto} neighbour parser does not emit {f}")
                         for f in ("neighbor", "state", "address", "interface", "as")}
                rows.append({"index": i, "pointer": json_pointer(*toks), **cells})
        groups.append({"protocol": proto, "pointer": json_pointer(*gtoks),
                       "neighbors": _listing(ctx, state, reason, gtoks, group_basis, rows,
                                             sections=("routing_neighbors",),
                                             caveats=("routing_neighbors_empty_is_ambiguous",))})
    state, reason = (rn.state, rn.reason) if rn.state else (
        (_PUB, None) if groups else (_NC, "not collected: the engine recorded no routing protocol for this device"))
    return _listing(ctx, state, reason, rn.toks, "build.build_routing_neighbors:routing_neighbors{}", groups,
                    sections=("routing_neighbors",), extra=rn.extra, bare=rn.bare,
                    caveats=("routing_neighbors_empty_is_ambiguous",))


def _security_block(ctx: _Ctx, host: Any, forced: Optional[Tuple[str, str]]) -> Dict[str, Any]:
    sr = _resolve(ctx, ("security",), ("security",), key=host, host=host, forced=forced,
                  absent=(_NC, "not collected: security carries no row for this device (no captured running-config)"))
    state, reason, toks, raw = _sub_list(ctx, sr, "findings", empty=(_CBE, "collected but empty: the check list is "
                                                                           "empty (not a blind spot)"))
    checks = _listing(ctx, state, reason, toks, _B_SEC + "findings", _items(ctx, toks, raw, "security_check",
                                                                               _B_SEC + "findings[]", ("security",)),
                      sections=("security",), extra=sr.extra, bare=sr.bare)
    return {"summary": _cell(ctx, sr, "summary", "security_summary", _B_SEC + "summary"), "checks": checks}


def _remediation_block(ctx: _Ctx, host: Any, forced: Optional[Tuple[str, str]]) -> Dict[str, Any]:
    plan = _resolve(ctx, ("remediation_plan",), ("remediation_plan",), forced=forced)
    rb = _resolve(ctx, ("remediation_plan", "by_device"), ("remediation_plan",), key=host, host=host, want=list,
                  forced=forced, absent=(_CBE, "collected but empty: the engine generated no remediation item for "
                                               "this device (not a blind spot)"))
    cap = ENGINE_LIST_CAPS["remediation_plan[].why"]
    mg_secs = ("remediation_plan", "move_groups")
    items: List[Dict[str, Any]] = []
    for i, rec in enumerate(rb.raw if rb.state is None else ()):
        toks = rb.toks + (i,)
        row = _list_row(toks, rec, ("remediation_plan",))
        why = rec.get("why") if isinstance(rec, dict) else None
        item: Dict[str, Any] = {"index": i, "pointer": json_pointer(*toks),
                                "severity": _cell(ctx, row, "severity", "enum", _B_RP + "severity", vocab=SEVERITIES)}
        for field in ("category", "title"):
            item[field] = _cell(ctx, row, field, "text", _B_RP + field)
        item["why"] = _cell(ctx, row, "why", "text", _B_RP + "why",
                            published_caveats=("engine_list_capped",) if isinstance(why, str) and len(why) >= cap
                            else ())
        item["commands"] = _cell(ctx, row, "commands", "text_list", _B_RP + "commands")
        for field in ("verify", "caution", "source"):
            item[field] = _cell(ctx, row, field, "text", _B_RP + field)
        item["wave"] = _cell(ctx, row, "wave", "text", _B_RP + "wave", sections=mg_secs, pre=_mg_pre(ctx),
                             empty=(_CBE, "collected but empty: this device is in no labelled move group (not a "
                                          "blind spot)"))
        items.append(item)
    sec = ctx.s.get("security")
    incomplete = None if (isinstance(sec, dict) and isinstance(host, str) and host in sec) else (
        "not collected: the list may be incomplete: security carries no row for this device (no captured "
        "running-config), so the configuration-derived items could not be generated")
    state, reason = (rb.state, rb.reason) if rb.state else (_PUB if items else _CBE, None)
    return {"banner": _cell(ctx, plan, "banner", "text", "analyze.compute_remediation_plan:remediation_plan.banner"),
            "items": _listing(ctx, state, reason, rb.toks, "analyze.compute_remediation_plan:remediation_plan."
                                                            "by_device{}", items, sections=("remediation_plan",),
                              extra=rb.extra, incomplete=incomplete, bare=rb.bare,
                              caveats=(("move_group_label_absent",) if not ctx.mg_labelled else ()))}


def _nrfu_block(ctx: _Ctx, host: Any, forced: Optional[Tuple[str, str]]) -> Dict[str, Any]:
    toks = ("nrfu_commands", "waves")
    basis = "nrfu_export.compute_nrfu_commands:nrfu_commands.waves[].devices[].cases"
    if forced is not None:
        return _listing(ctx, forced[0], forced[1], None, basis, [], bare=True)
    if ctx.device_blind("nrfu_commands", host):
        return _listing(ctx, _NC, _R_DEVICE_NC, toks, basis, [], sections=("nrfu_commands",),
                        extra=ctx.cc_witness(host))
    base, reason, raw = _list_state(ctx, toks, ("nrfu_commands",))
    items: List[Dict[str, Any]] = []
    malformed = False
    for w, wave in enumerate(raw if isinstance(raw, list) else ()):
        devs = wave.get("devices") if isinstance(wave, dict) else None
        if not isinstance(devs, list):
            malformed = True
            continue
        for d, dev in enumerate(devs):
            if not isinstance(dev, dict) or dev.get("host") != host:
                continue
            cases = dev.get("cases")
            if not isinstance(cases, list):
                malformed = True
                continue
            for k, case in enumerate(cases):
                ctoks = toks + (w, "devices", d, "cases", k)
                row = _list_row(ctoks, case, ("nrfu_commands",))
                item: Dict[str, Any] = {"wave_index": w, "device_index": d, "case_index": k,
                                        "pointer": json_pointer(*ctoks)}
                for field in ("id", "scope", "command", "source_key"):
                    item[field] = _cell(ctx, row, field, "text", _B_NRFU + field)
                item["phase"] = _cell(ctx, row, "phase", "count", _B_NRFU + "phase")
                item["expected"] = _cell(ctx, row, "expected", "text", _B_NRFU + "expected", pre=_nrfu_marker)
                item["evidence_state"] = _cell(ctx, row, "evidence_state", "text", _B_NRFU + "evidence_state",
                                               missing="not collected: this case publishes no evidence state")
                items.append(item)
    if base in (_PUB, _CBE):
        if malformed:
            base, reason = _UV, "unverified: an NRFU wave or device entry is malformed, so its cases cannot be read"
        else:
            base, reason = (_PUB, None) if items else (_NC, "not collected: the NRFU pack generated no case for this "
                                                            "device")
    return _listing(ctx, base, reason, toks, basis, items, sections=("nrfu_commands",))


def _device_limitations_payload() -> List[Dict[str, Any]]:
    """The device document's own limitations, then every payload limitation a device page can cite, re-addressed."""
    return [{"id": lim["id"], "owner": lim["owner"], "text": lim["text"], "applies_to": list(lim["applies_to"])}
            for lim in _DEVICE_DOC_LIMITATIONS]


def _device_page(ctx: _Ctx, host: Any) -> Dict[str, Any]:
    if _is_text(host):
        devices = ctx.s.get("devices")
        rosters = {"devices": isinstance(devices, dict) and host in devices,
                   "collection_completeness": ctx.cc_row(host)[0] is not None,
                   "cable_map": host in ctx.index(("cable_map", "nodes"), ("host",))}
        forced = None if any(rosters.values()) else (_NC, _R_UNKNOWN_HOST)
    else:
        rosters = {"devices": False, "collection_completeness": False, "cable_map": False}
        forced = (_UV, _R_BAD_HOST)
    j = _joins(ctx, host, forced)
    dev = j["devices"]
    phys_cav = ("device_physical_defaults_not_observed",)
    physical: Dict[str, Any] = {f: _cell(ctx, dev, f, "count", _dev_basis(f), pre=_default_zero,
                                         published_caveats=phys_cav) for f in DEVICE_PHYSICAL_ZERO_DEFAULTS}
    physical["active_ports"] = _cell(ctx, dev, "active_ports", "count", _dev_basis("active_ports"), pre=_null_value,
                                     published_caveats=phys_cav)
    physical.update({f: _cell(ctx, dev, f, "text", _dev_basis(f), pre=_default_text, published_caveats=phys_cav)
                     for f in PHYSICAL_TEXT_FIELDS})
    cc = j["collection"]
    health = _health_cells(ctx, host, j)
    hrow = j["health"]
    ded_cap = ENGINE_LIST_CAPS["health_scores[].deductions"]
    dstate, dreason, dtoks, draw = _sub_list(
        ctx, hrow, "deductions", pre_state=_not_scored(None, hrow),
        empty=(_CBE, "collected but empty: the device was scored with no deduction (not a blind spot)"))
    ded_readable = dstate in (_PUB, _CBE)
    ded_capped = ded_readable and isinstance(draw, list) and len(draw) >= ded_cap
    deductions = _listing(ctx, dstate, dreason, dtoks, _B_HEALTH + "deductions",
                          _items(ctx, dtoks, draw, "text", _B_HEALTH + "deductions[]", ("health_scores",),
                                 hold=(dstate, dreason) if dstate == _NA else None),
                          sections=("health_scores",), extra=hrow.extra, bare=hrow.bare,
                          caveats=("engine_list_capped",) if ded_capped else ())
    lc = j["lifecycle"]
    dated = _blank("not collected: the engine publishes no date here (it withholds the EoS / LDoS dates when no "
                   "retained bulletin matches the model)")
    dd = j["dossier"]
    xs, xr, xt, xraw = _sub_list(ctx, dd, "exposures", empty=(_CBE, "collected but empty: the dossier lists no "
                                                                    "exposure axis (not a blind spot)"))
    cs, cr, ct, craw = _sub_list(ctx, dd, "compound", empty=(_CBE, "collected but empty: no compound risk pattern "
                                                                   "coincides on this device (not a blind spot)"))
    cov = _resolve(ctx, ("coverage_matrix", "by_device"), ("coverage_matrix",), key=host, host=host, forced=forced,
                   absent=(_NC, "not collected: coverage_matrix carries no row for this device"))
    cov_items: List[Dict[str, Any]] = []
    for axis in (sorted(k for k in cov.raw if _is_text(k)) if cov.state is None else ()):
        crow = _Row(None, None, cov.toks + (axis,), cov.raw[axis], ("coverage_matrix",))
        fact = _cell(ctx, crow, None, "coverage_cell", "coverage_matrix.compute_coverage_matrix:by_device{}{}",
                     published_caveats=("coverage_matrix_shown_as_published",))
        if fact["state"] == _PUB:
            fact["value"] = {"axis": axis, "state": fact["value"]}
        cov_items.append({"axis": axis, "pointer": json_pointer(*crow.toks), "fact": fact})
    cov_state, cov_reason = (cov.state, cov.reason) if cov.state else (_PUB if cov_items else _CBE, None)
    punch_base, punch_reason, _praw = _list_state(ctx, ("punchlist",), ("punchlist",))
    punch_state = _rolled(ctx, punch_base, punch_reason, ("punchlist",), PUNCHLIST_INPUTS)
    return {
        "host": host if _is_text(host) else None,
        "rosters": rosters,
        "identity": {f: _cell(ctx, dev, f, "text", _dev_basis(f), pre=_default_text) for f in IDENTITY_FIELDS},
        "physical": physical,
        "collection": {"status": _cell(ctx, cc, "status", "enum", _B_CC + "status", vocab=CC_STATUSES),
                       "data_quality": _cell(ctx, cc, "data_quality", "score", _B_CC + "data_quality"),
                       "missing": _cell(ctx, cc, "missing", "text_list", _B_CC + "missing")},
        "health": {**health, "deductions": deductions,
                   "deductions_cap": _cap(ded_cap, draw, "analyze.compute_health_scores", ded_readable)},
        "lifecycle": {
            "band": _cell(ctx, lc, "band", "enum", _B_LIFECYCLE + "band", vocab=LIFECYCLE_BAND_ORDER),
            "status": _cell(ctx, lc, "status", "text", _B_LIFECYCLE + "status"),
            "eos": _cell(ctx, lc, "eos", "text", _B_LIFECYCLE + "eos", pre=dated),
            "ldos": _cell(ctx, lc, "ldos", "text", _B_LIFECYCLE + "ldos", pre=dated),
            "source": _cell(ctx, lc, "source", "text", _B_LIFECYCLE + "source",
                            pre=_blank("not collected: no retained lifecycle source matched this model")),
            "conf": _cell(ctx, lc, "conf", "text", _B_LIFECYCLE + "conf",
                          pre=_blank("not collected: no lifecycle confidence was published for this model")),
            "citation_status": _cell(ctx, lc, "citation_status", "text", _B_LIFECYCLE + "citation_status"),
        },
        "dossier": {
            "risk_band": _risk_band(ctx, dd),
            "exposures": _listing(ctx, xs, xr, xt, _B_DOSSIER + "exposures",
                                  _items(ctx, xt, xraw, "exposure", _B_DOSSIER + "exposures[]", ("device_dossiers",)),
                                  sections=("device_dossiers",), extra=dd.extra, bare=dd.bare),
            "compound": _listing(ctx, cs, cr, ct, _B_DOSSIER + "compound",
                                 _items(ctx, ct, craw, "compound", _B_DOSSIER + "compound[]", ("device_dossiers",)),
                                 sections=("device_dossiers",), extra=dd.extra, bare=dd.bare),
        },
        "coverage": _listing(ctx, cov_state, cov_reason, cov.toks, "coverage_matrix.compute_coverage_matrix:by_device{}",
                             cov_items, sections=("coverage_matrix",), extra=cov.extra,
                             caveats=("coverage_matrix_shown_as_published",), bare=cov.bare),
        "interfaces": _interfaces_block(ctx, host, forced),
        "links": _selection_rows(ctx, host, forced, "links", ("cable_map", "cables"), ("a", "b"),
                                 "analyze.compute_cable_map:cable_map.cables", "no cable in the cable map names this "
                                 "device", lambda i, rec: _cable_row(ctx, i, rec), sections=("cable_map",)),
        "routes": _routes_block(ctx, host, forced),
        "routing_neighbors": _neighbors_block(ctx, host, forced),
        "security": _security_block(ctx, host, forced),
        "native_vlan_mismatches": _selection_rows(
            ctx, host, forced, "native_vlan_mismatches", ("trunk_native",), ("a_host", "b_host"),
            "excel.compute_trunk_native_mismatches:trunk_native",
            "no native-VLAN mismatch names this device",
            lambda i, rec: {"index": i, "pointer": json_pointer("trunk_native", i),
                            "fact": _cell(ctx, _list_row(("trunk_native", i), rec, ("trunk_native",)), None,
                                          "trunk_native", "excel.compute_trunk_native_mismatches:trunk_native[]")}),
        "remediation": _remediation_block(ctx, host, forced),
        "nrfu_cases": _nrfu_block(ctx, host, forced),
        "findings": _selection_rows(
            ctx, host, forced, "findings", ("punchlist",), ("devices",),
            "analyze.compute_migration_punchlist:punchlist",
            "no punch-list row names this device",
            lambda i, _rec: {"index": i, "pointer": json_pointer("punchlist", i)}, multi=True,
            base_state=(punch_state[0], punch_state[1], _praw), sections=("punchlist",) + PUNCHLIST_INPUTS,
            config=True),
        "endpoints": _selection_rows(
            ctx, host, forced, "endpoints", ("endpoint_identity",), ("host",),
            "analyze.compute_endpoint_identity:endpoint_identity",
            "no endpoint was identified on this device",
            lambda i, _rec: {"index": i, "pointer": json_pointer("endpoint_identity", i)}),
        "limitations": _device_limitations_payload(),
    }


def project_device(snap: Any, host: Any) -> Dict[str, Any]:
    """One device page, as a standalone ``DeviceDocument``: identity, physical, blind-spot record, health,
    lifecycle, dossier, coverage, interfaces, links, routes, routing neighbours, security checks, native-VLAN
    mismatches, remediation, NRFU cases, and the punch-list rows and endpoints that name it. A host no roster
    names claims nothing; a host that is not a string names no row."""
    ctx = _Ctx(snap)
    return {"schema": SCHEMA, "engine": _engine(ctx), "device": _device_page(ctx, host)}


def project_devices(snap: Any, hosts: Any) -> List[Dict[str, Any]]:
    """One ``DeviceDocument`` per host in `hosts` (a list or tuple; anything else names none), in order, over ONE
    shared context: each document equals :func:`project_device` for its host and owns every container in it."""
    ctx = _Ctx(snap)
    return [{"schema": SCHEMA, "engine": _engine(ctx), "device": _device_page(ctx, host)}
            for host in (hosts if isinstance(hosts, (list, tuple)) else ())]


def project(snap: Any) -> Dict[str, Any]:
    """The whole ``ui_projection/1`` payload for one snapshot (device pages are separate documents:
    :func:`project_device`). Pure and total."""
    ctx = _Ctx(snap)
    return {"schema": SCHEMA, "engine": _engine(ctx), "overview": _overview(ctx), "trust": _trust(ctx),
            "inventory": _inventory(ctx), "findings": _findings(ctx)}


# ---------------------------------------------------------------------------------------------------
# JSON Schema (draft 2020-12), generated fresh from the module constants on every call
# ---------------------------------------------------------------------------------------------------
def _ref(name: str) -> Dict[str, Any]:
    return {"$ref": f"#/$defs/{name}"}


def _null() -> Dict[str, Any]:
    return {"type": "null"}


def _nullable(schema: Dict[str, Any]) -> Dict[str, Any]:
    return {"anyOf": [schema, _null()]}


def _nonneg_int() -> Dict[str, Any]:
    return {"type": "integer", "minimum": 0, "maximum": JS_MAX_SAFE_INT}


def _str() -> Dict[str, Any]:
    return {"type": "string"}


def _closed(title: str, required: Sequence[str], properties: Dict[str, Any]) -> Dict[str, Any]:
    missing = [k for k in required if k not in properties]
    if missing:
        raise ValueError(f"schema {title}: required but undeclared {missing}")
    return {"title": title, "type": "object", "additionalProperties": False, "required": list(required),
            "properties": properties}


def _envelope_props() -> Dict[str, Any]:
    return {"subject": _nullable(_ref("Pointer")), "refs": {"type": "array", "items": _ref("Ref")},
            "basis": {"type": "string", "minLength": 1}, "engine_state": _ref("EngineState"),
            "engine_state_owner": _ref("EngineStateOwner"),
            "caveats": {"type": "array", "minItems": 1, "uniqueItems": True, "items": _ref("LimitationId")}}


def _paired(branch: Dict[str, Any]) -> Dict[str, Any]:
    """``engine_state`` never travels without the owner that produced it (and vice versa)."""
    branch["dependentRequired"] = {"engine_state": ["engine_state_owner"], "engine_state_owner": ["engine_state"]}
    return branch


def _fact_def(title: str, value: Dict[str, Any]) -> Dict[str, Any]:
    required = ["state", "value", "subject", "refs", "basis"]
    published = _paired(_closed(f"{title}Published", required,
                                {"state": {"const": _PUB}, "value": value, **_envelope_props()}))
    withheld = _paired(_closed(f"{title}Withheld", required + ["reason"],
                               {"state": _ref("WithheldState"), "value": _null(),
                                "reason": {"type": "string", "minLength": 1}, **_envelope_props()}))
    return {"title": title, "oneOf": [published, withheld]}


def _withheld_fact_def(title: str) -> Dict[str, Any]:
    branch = _fact_def(title, _null())["oneOf"][1]
    branch["title"] = title
    return branch


def _list_def(title: str, item: Dict[str, Any]) -> Dict[str, Any]:
    required = ["state", "subject", "refs", "basis", "items"]
    published = _paired(_closed(f"{title}Published", required,
                                {"state": {"const": _PUB}, "items": {"type": "array", "minItems": 1, "items": item},
                                 **_envelope_props()}))
    withheld = _paired(_closed(f"{title}Withheld", required + ["reason"],
                               {"state": _ref("WithheldState"), "items": {"type": "array", "items": item},
                                "reason": {"type": "string", "minLength": 1}, **_envelope_props()}))
    return {"title": title, "oneOf": [published, withheld]}


def _copy_schema(node: Any) -> Any:
    """A structural copy: every path gets its own node, so the schema never aliases one node twice."""
    if isinstance(node, dict):
        return {k: _copy_schema(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_copy_schema(v) for v in node]
    return node


def _canon_def(title: str, fact: str) -> Dict[str, Any]:
    return _closed(title, ("path", "concept", "fact"), {"path": _str(), "concept": _str(), "fact": _ref(fact)})


def _enum(values: Sequence[str]) -> Dict[str, Any]:
    return {"type": "string", "enum": list(values)}


def _bool() -> Dict[str, Any]:
    return {"type": "boolean"}


def _item_def(title: str, fact: str) -> Dict[str, Any]:
    return _closed(title, ("index", "pointer", "fact"),
                   {"index": _nonneg_int(), "pointer": _ref("Pointer"), "fact": _ref(fact)})


def _row_def(title: str, head: Mapping[str, Any], cells: Sequence[Tuple[str, str]],
             tail: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    props: Dict[str, Any] = dict(head)
    props.update({name: _ref(fact) for name, fact in cells})
    props.update(tail or {})
    return _closed(title, tuple(props), props)


def _indexed() -> Dict[str, Any]:
    return {"index": _nonneg_int(), "pointer": _ref("Pointer")}


_TEXT = "TextFact"
_DEVICE_ROW_CELLS = (("collection_status", "CollectionStatusFact"), ("model", _TEXT), ("platform", _TEXT),
                     ("sw_version", _TEXT), ("serial_number", _TEXT), ("role", _TEXT), ("health_score", "ScoreFact"),
                     ("health_band", "BandFact"), ("lifecycle_band", "LifecycleBandFact"),
                     ("risk_band", "RiskBandFact"))
_VLAN_ROW_FACTS = {"vlan": "CountFact", "stp_root_default_election": "FlagFact", "fhrp": "FhrpFact",
                   "gateway_svi_hosts": "TextListFact", "endpoint_count": "CountFact",
                   "dependencies": "TextListFact", "readiness": "ReadinessFact"}
_ENDPOINT_ROW_CELLS = (("host", _TEXT), ("port", _TEXT), ("mac", _TEXT), ("vlan", _TEXT), ("ip", _TEXT),
                       ("mac_count", "CountFact"), ("vendor", _TEXT), ("endpoint_class", _TEXT),
                       ("confidence", "EndpointConfidenceFact"), ("evidence", _TEXT))
_FINDING_ROW_CELLS = (("priority", "CountFact"), ("rank", "CountFact"), ("severity", "SeverityFact"),
                      ("category", _TEXT), ("title", _TEXT), ("detail", _TEXT), ("devices", "TextListFact"),
                      ("wave", _TEXT), ("remediation", _TEXT), ("severity_basis", _TEXT),
                      ("evidence_confidence", _TEXT), ("source_command", _TEXT))


def _slice2_defs(defs: Dict[str, Any]) -> None:
    """Inventory, Findings and the device page: typed facts, rows, lists and sections."""
    for name, vocab in (("LifecycleBandFact", LIFECYCLE_BAND_ORDER), ("RiskBandFact", DOSSIER_BANDS),
                        ("SeverityFact", SEVERITIES), ("ReadinessFact", VLAN_READINESS),
                        ("EndpointConfidenceFact", ENDPOINT_CONFIDENCES), ("CollectionStatusFact", CC_STATUSES),
                        ("OpStatusFact", OP_STATUSES)):
        defs[name] = _fact_def(name, _enum(vocab))
    defs["TextListFact"] = _fact_def("TextListFact", {"type": "array", "items": _str()})
    defs["FhrpMember"] = _closed("FhrpMember", ("host", "proto", "group", "vip", "role", "priority", "preempt", "vmac"),
                                 {**{k: _nullable(_str()) for k in _FHRP_MEMBER_TEXT},
                                  "priority": _nullable(_nonneg_int()), "preempt": _nullable(_bool())})
    defs["FhrpValue"] = _closed("FhrpValue", _FHRP_TEXT + ("members",),
                                {**{k: _nullable(_str()) for k in _FHRP_TEXT},
                                 "members": {"type": "array", "items": _ref("FhrpMember")}})
    defs["FhrpFact"] = _fact_def("FhrpFact", {"anyOf": [_ref("FhrpValue"), _str()]})
    record_titles = {"exposure": "Exposure", "compound": "Compound", "security_check": "SecurityCheck",
                     "security_summary": "SecuritySummary", "trunk_native": "TrunkNative", "cable_ends": "CableEnds",
                     "shared_ip": "SharedIp"}
    kinds = {"text": _str, "count": _nonneg_int, "flag": _bool, "text_list": lambda: {"type": "array", "items": _str()}}
    for slot, title in record_titles.items():
        props = {key: (_enum(vocab) if kind == "enum" else kinds[kind]()) for key, kind, vocab in _RECORD_SLOTS[slot]}
        defs[f"{title}Value"] = _closed(f"{title}Value", tuple(props), props)
        defs[f"{title}Fact"] = _fact_def(f"{title}Fact", _ref(f"{title}Value"))
    defs["CoverageCellValue"] = _closed("CoverageCellValue", ("axis", "state"),
                                        {"axis": _str(), "state": _enum(COVERAGE_STATES)})
    defs["CoverageCellFact"] = _fact_def("CoverageCellFact", _ref("CoverageCellValue"))
    defs["Cap"] = _closed("Cap", ("limit", "reached", "total"),
                          {"limit": {"type": "integer", "minimum": 1, "maximum": JS_MAX_SAFE_INT},
                           "reached": _nullable(_bool()), "total": _ref("WithheldFact")})
    source_required = ["state", "subject", "refs", "basis"]
    defs["SelectionSource"] = {"title": "SelectionSource", "oneOf": [
        _paired(_closed("SelectionSourcePublished", source_required, {"state": {"const": _PUB}, **_envelope_props()})),
        _paired(_closed("SelectionSourceWithheld", source_required + ["reason"],
                        {"state": _ref("WithheldState"), "reason": {"type": "string", "minLength": 1},
                         **_envelope_props()}))]}
    defs["IndexList"] = {"title": "IndexList", "type": "array", "items": _nonneg_int()}
    defs["RowRef"] = _closed("RowRef", ("index", "pointer"), _indexed())
    for title, fact in (("TextItem", _TEXT), ("ExposureItem", "ExposureFact"), ("CompoundItem", "CompoundFact"),
                        ("SecurityCheckItem", "SecurityCheckFact"), ("TrunkNativeItem", "TrunkNativeFact"),
                        ("SharedIpItem", "SharedIpFact")):
        defs[title] = _item_def(title, fact)
    defs["CoverageItem"] = _closed("CoverageItem", ("axis", "pointer", "fact"),
                                   {"axis": _str(), "pointer": _ref("Pointer"), "fact": _ref("CoverageCellFact")})
    defs["DeviceRosters"] = _closed("DeviceRosters", ("devices", "collection_completeness"),
                                    {"devices": _bool(), "collection_completeness": _bool()})
    defs["DeviceRowRefs"] = _closed("DeviceRowRefs", ("health", "lifecycle", "dossier", "collection"),
                                    {k: _nullable(_ref("Pointer")) for k in ("health", "lifecycle", "dossier",
                                                                             "collection")})
    defs["DeviceRow"] = _row_def("DeviceRow", {"host": _str(), "pointer": _nullable(_ref("Pointer")),
                                               "rosters": _ref("DeviceRosters"), "rows": _ref("DeviceRowRefs")},
                                 _DEVICE_ROW_CELLS)
    defs["VlanSelections"] = _closed("VlanSelections", ("stp_roots", "gateways", "endpoints"),
                                     {"stp_roots": _nullable({"type": "array", "items": _ref("Pointer")}),
                                      "gateways": _nullable(_ref("IndexList")),
                                      "endpoints": _nullable(_ref("IndexList"))})
    defs["VlanRow"] = _row_def("VlanRow", _indexed(),
                               [(f, _VLAN_ROW_FACTS.get(f, _TEXT)) for f in VLAN_FIELD_BASIS],
                               {"selections": _ref("VlanSelections")})
    defs["EndpointSelections"] = _closed("EndpointSelections", ("interface", "vlan_row", "shared_ip", "dual_homed"),
                                         {"interface": _nullable(_ref("Pointer")), "vlan_row": _nullable(_nonneg_int()),
                                          "shared_ip": _nullable(_ref("IndexList")),
                                          "dual_homed": _nullable(_ref("IndexList"))})
    defs["EndpointRow"] = _row_def("EndpointRow", _indexed(), _ENDPOINT_ROW_CELLS,
                                   {"selections": _ref("EndpointSelections")})
    defs["DualHomedRow"] = _row_def("DualHomedRow", _indexed(),
                                    (("mac", _TEXT), ("endpoint_class", _TEXT), ("ip", _TEXT), ("vendor", _TEXT),
                                     ("switches", "TextListFact"), ("ports", "TextListFact"), ("ports_cap", "Cap"),
                                     ("move_groups", "TextListFact"), ("split_across_groups", "FlagFact")))
    defs["PeerRow"] = _row_def("PeerRow", _indexed(), (("host", _TEXT), ("kind", _TEXT)))
    defs["FindingRow"] = _row_def("FindingRow", _indexed(), _FINDING_ROW_CELLS)
    defs["InterfaceCells"] = _closed("InterfaceCells", IF_COLUMNS, {c: _ref(_TEXT) for c in IF_COLUMNS})
    defs["InterfaceRow"] = _closed("InterfaceRow", ("port", "pointer", "cells", "run_config_observed"),
                                   {"port": _str(), "pointer": _ref("Pointer"), "cells": _ref("InterfaceCells"),
                                    "run_config_observed": _ref("FlagFact")})
    defs["CableRow"] = _row_def("CableRow", _indexed(), (("ends", "CableEndsFact"), ("speed", _TEXT),
                                                         ("confirmation", _TEXT), ("op_status", "OpStatusFact")))
    defs["RouteRow"] = _row_def("RouteRow", _indexed(), (("prefix", _TEXT), ("source", _TEXT), ("next_hop", _TEXT),
                                                         ("out_intf", _TEXT), ("admin_distance", "CountFact")))
    defs["NeighborRow"] = _row_def("NeighborRow", _indexed(), tuple((f, _TEXT) for f in ("neighbor", "state",
                                                                                          "address", "interface",
                                                                                          "as")))
    defs["NeighborGroup"] = _closed("NeighborGroup", ("protocol", "pointer", "neighbors"),
                                    {"protocol": _str(), "pointer": _ref("Pointer"),
                                     "neighbors": _ref("NeighborRowList")})
    defs["RemediationRow"] = _row_def("RemediationRow", _indexed(),
                                      (("severity", "SeverityFact"), ("category", _TEXT), ("title", _TEXT),
                                       ("why", _TEXT), ("commands", "TextListFact"), ("verify", _TEXT),
                                       ("caution", _TEXT), ("source", _TEXT), ("wave", _TEXT)))
    defs["NrfuCaseRow"] = _row_def("NrfuCaseRow", {"wave_index": _nonneg_int(), "device_index": _nonneg_int(),
                                                   "case_index": _nonneg_int(), "pointer": _ref("Pointer")},
                                   (("id", _TEXT), ("scope", _TEXT), ("command", _TEXT), ("source_key", _TEXT),
                                    ("phase", "CountFact"), ("expected", _TEXT), ("evidence_state", _TEXT)))
    for title, item in (("DeviceRowList", "DeviceRow"), ("VlanRowList", "VlanRow"), ("EndpointRowList", "EndpointRow"),
                        ("SharedIpList", "SharedIpItem"), ("DualHomedList", "DualHomedRow"), ("PeerList", "PeerRow"),
                        ("FindingRowList", "FindingRow"), ("TextItemList", "TextItem"),
                        ("ExposureList", "ExposureItem"), ("CompoundList", "CompoundItem"),
                        ("CoverageList", "CoverageItem"), ("InterfaceRowList", "InterfaceRow"),
                        ("CableRowList", "CableRow"), ("RouteRowList", "RouteRow"),
                        ("NeighborRowList", "NeighborRow"), ("NeighborGroupList", "NeighborGroup"),
                        ("SecurityCheckList", "SecurityCheckItem"), ("TrunkNativeList", "TrunkNativeItem"),
                        ("RemediationRowList", "RemediationRow"), ("NrfuCaseList", "NrfuCaseRow"),
                        ("RowRefList", "RowRef")):
        defs[title] = _list_def(title, _ref(item))
    defs["InventoryDevices"] = _closed("InventoryDevices", ("total", "rows"),
                                       {"total": _ref("CountFact"), "rows": _ref("DeviceRowList")})
    vlan_sources = ("stp_roots", "gateways", "endpoints")
    defs["InventoryVlans"] = _closed("InventoryVlans", ("total", "rows", "selection_sources"),
                                     {"total": _ref("CountFact"), "rows": _ref("VlanRowList"),
                                      "selection_sources": _closed("VlanSelectionSources", vlan_sources,
                                                                   {k: _ref("SelectionSource") for k in vlan_sources})})
    ep_sources = ("interfaces", "vlan_rows", "shared_ip", "dual_homed")
    defs["InventoryEndpoints"] = _closed("InventoryEndpoints",
                                         ("total", "rows", "shared_ip", "dual_homed", "selection_sources"),
                                         {"total": _ref("CountFact"), "rows": _ref("EndpointRowList"),
                                          "shared_ip": _ref("SharedIpList"), "dual_homed": _ref("DualHomedList"),
                                          "selection_sources": _closed("EndpointSelectionSources", ep_sources,
                                                                       {k: _ref("SelectionSource")
                                                                        for k in ep_sources})})
    defs["Inventory"] = _closed("Inventory", ("devices", "vlans", "endpoints", "uncollected_peers"),
                                {"devices": _ref("InventoryDevices"), "vlans": _ref("InventoryVlans"),
                                 "endpoints": _ref("InventoryEndpoints"), "uncollected_peers": _ref("PeerList")})
    defs["Findings"] = _closed("Findings", ("total", "headline_axis_index", "rows"),
                               {"total": _ref("CountFact"), "headline_axis_index": _nullable(_nonneg_int()),
                                "rows": _ref("FindingRowList")})
    identity = _closed("DeviceIdentity", IDENTITY_FIELDS, {f: _ref(_TEXT) for f in IDENTITY_FIELDS})
    physical_props = {**{f: _ref("CountFact") for f in DEVICE_PHYSICAL_ZERO_DEFAULTS + ("active_ports",)},
                      **{f: _ref(_TEXT) for f in PHYSICAL_TEXT_FIELDS}}
    n_lims = len(_DEVICE_DOC_LIMITATIONS)
    defs["DevicePage"] = _closed("DevicePage", (
        "host", "rosters", "identity", "physical", "collection", "health", "lifecycle", "dossier", "coverage",
        "interfaces", "links", "routes", "routing_neighbors", "security", "native_vlan_mismatches", "remediation",
        "nrfu_cases", "findings", "endpoints", "limitations"), {
        "host": _nullable(_str()),
        "rosters": _closed("DevicePageRosters", ("devices", "collection_completeness", "cable_map"),
                           {"devices": _bool(), "collection_completeness": _bool(), "cable_map": _bool()}),
        "identity": identity,
        "physical": _closed("DevicePhysical", tuple(physical_props), physical_props),
        "collection": _closed("DeviceCollection", ("status", "data_quality", "missing"),
                              {"status": _ref("CollectionStatusFact"), "data_quality": _ref("ScoreFact"),
                               "missing": _ref("TextListFact")}),
        "health": _closed("DeviceHealth", ("score", "band", "role", "deductions", "deductions_cap"),
                          {"score": _ref("ScoreFact"), "band": _ref("BandFact"), "role": _ref(_TEXT),
                           "deductions": _ref("TextItemList"), "deductions_cap": _ref("Cap")}),
        "lifecycle": _closed("DeviceLifecycle", ("band", "status", "eos", "ldos", "source", "conf", "citation_status"),
                             {"band": _ref("LifecycleBandFact"),
                              **{f: _ref(_TEXT) for f in ("status", "eos", "ldos", "source", "conf",
                                                          "citation_status")}}),
        "dossier": _closed("DeviceDossier", ("risk_band", "exposures", "compound"),
                           {"risk_band": _ref("RiskBandFact"), "exposures": _ref("ExposureList"),
                            "compound": _ref("CompoundList")}),
        "coverage": _ref("CoverageList"),
        "interfaces": _closed("DeviceInterfaces", ("columns", "rows"),
                              {"columns": {"type": "array", "minItems": len(IF_COLUMNS), "maxItems": len(IF_COLUMNS),
                                           "items": _enum(IF_COLUMNS)},
                               "rows": _ref("InterfaceRowList")}),
        "links": _ref("CableRowList"), "routes": _ref("RouteRowList"), "routing_neighbors": _ref("NeighborGroupList"),
        "security": _closed("DeviceSecurity", ("summary", "checks"),
                            {"summary": _ref("SecuritySummaryFact"), "checks": _ref("SecurityCheckList")}),
        "native_vlan_mismatches": _ref("TrunkNativeList"),
        "remediation": _closed("DeviceRemediation", ("banner", "items"),
                               {"banner": _ref(_TEXT), "items": _ref("RemediationRowList")}),
        "nrfu_cases": _ref("NrfuCaseList"), "findings": _ref("RowRefList"), "endpoints": _ref("RowRefList"),
        "limitations": {"type": "array", "minItems": n_lims, "maxItems": n_lims, "items": _ref("Limitation")},
    })
    defs["DeviceDocument"] = _closed("DeviceDocument", ("schema", "engine", "device"),
                                     {"schema": {"type": "string", "const": SCHEMA}, "engine": _ref("Engine"),
                                      "device": _ref("DevicePage")})


def _build_schema() -> Dict[str, Any]:
    defs: Dict[str, Any] = {
        "State": {"title": "State", "type": "string", "enum": list(STATES)},
        "WithheldState": {"title": "WithheldState", "type": "string", "enum": list(WITHHELD_STATES)},
        "AbstentionState": {"title": "AbstentionState", "type": "string", "enum": list(ssot.ABSTENTION_STATES)},
        "EngineState": {"title": "EngineState", "type": "string", "enum": list(ENGINE_STATES)},
        "EngineStateOwner": {"title": "EngineStateOwner", "type": "string", "enum": list(ENGINE_STATE_OWNERS)},
        "LimitationId": {"title": "LimitationId", "type": "string", "enum": list(_ALL_LIMITATION_IDS)},
        "Pointer": {"title": "Pointer", "type": "string", "pattern": "^(/([^~/]|~[01])*)*$"},
        "Ref": _closed("Ref", ("pointer", "role"), {"pointer": _ref("Pointer"),
                                                     "role": {"type": "string", "enum": list(REF_ROLES)}}),
        "CountFact": _fact_def("CountFact", _nonneg_int()),
        "ScoreFact": _fact_def("ScoreFact", {"type": "number", "minimum": 0, "maximum": 100}),
        "TextFact": _fact_def("TextFact", _str()),
        "FlagFact": _fact_def("FlagFact", {"type": "boolean"}),
        "BandFact": _fact_def("BandFact", {"type": "string", "enum": list(HEALTH_BANDS)}),
        "UnknownEvidenceStateFact": _fact_def("UnknownEvidenceStateFact",
                                              {"type": "string", "enum": list(UNKNOWN_EVIDENCE_STATES)}),
        "AxisValue": _closed("AxisValue", ("severity", "headline", "detail"),
                             {"severity": {"type": "string", "enum": list(SEVERITIES)}, "headline": _str(),
                              "detail": _str()}),
        "AxisFact": _fact_def("AxisFact", _ref("AxisValue")),
        "ByStateValue": _closed("ByStateValue", (), {k: _nonneg_int() for k in COVERAGE_STATES}),
        "ByStateFact": _fact_def("ByStateFact", _ref("ByStateValue")),
        "StampValue": _closed("StampValue", ("verified", "n_facts", "n_checked", "n_violations"),
                              {"verified": {"type": "boolean"}, "n_facts": _nonneg_int(),
                               "n_checked": _nonneg_int(), "n_violations": _nonneg_int()}),
        "StampFact": _fact_def("StampFact", _ref("StampValue")),
        "SourceValue": _closed("SourceValue", ("section", "state", "records_examined", "detail_complete"),
                               {"section": _str(), "state": {"type": "string", "enum": list(UE_SOURCE_STATES)},
                                "records_examined": _nonneg_int(), "detail_complete": {"type": "boolean"}}),
        "SourceFact": _fact_def("SourceFact", _ref("SourceValue")),
        "WithheldFact": _withheld_fact_def("WithheldFact"),
        "CanonCount": _canon_def("CanonCount", "CountFact"),
        "CanonScore": _canon_def("CanonScore", "ScoreFact"),
        "CanonBand": _canon_def("CanonBand", "BandFact"),
        "AxisItem": _closed("AxisItem", ("index", "axis", "basis_sections", "fact"),
                            {"index": _nonneg_int(), "axis": _nullable(_str()),
                             "basis_sections": {"type": "array", "items": _str()}, "fact": _ref("AxisFact")}),
        "AbsentAxis": _closed("AbsentAxis", ("axis", "basis_sections", "fact"),
                              {"axis": {"type": "string", "enum": list(AXIS_BASIS)},
                               "basis_sections": {"type": "array", "items": _str()}, "fact": _ref("WithheldFact")}),
        "TopGatingItem": _closed("TopGatingItem", ("index", "axis_index", "fact"),
                                 {"index": _nonneg_int(), "axis_index": _nullable(_nonneg_int()),
                                  "fact": _ref("TextFact")}),
        "SourceItem": _closed("SourceItem", ("index", "fact"), {"index": _nonneg_int(), "fact": _ref("SourceFact")}),
        "CensusRow": _closed("CensusRow", ("key", "state", "count", "kind", "note", "pointer"),
                             {"key": _str(), "state": _ref("AbstentionState"), "count": _nullable(_nonneg_int()),
                              "kind": {"type": "string", "enum": list(CENSUS_KINDS)}, "note": _str(),
                              "pointer": _ref("Pointer")}),
        "FailureRecordItem": _closed("FailureRecordItem", ("index", "label", "classification", "sections", "pointer"),
                                     {"index": _nonneg_int(), "label": _nullable(_str()),
                                      "classification": {"type": "string", "enum": list(PHASE_CLASSIFICATIONS)},
                                      "sections": {"type": "array", "items": _str()}, "pointer": _ref("Pointer")}),
        "DirectSection": _closed("DirectSection", ("section", "refs"),
                                 {"section": _str(), "refs": {"type": "array", "items": _ref("Ref")}}),
        "Limitation": _closed("Limitation", ("id", "owner", "text", "applies_to"),
                              {"id": _ref("LimitationId"), "owner": _str(), "text": _str(),
                               "applies_to": {"type": "array", "minItems": 1, "items": _ref("Pointer")}}),
        "LifecycleBand": _closed("LifecycleBand", ("band", "fact_name", "rank"),
                                 {"band": {"type": "string", "enum": list(LIFECYCLE_BAND_ORDER)},
                                  "fact_name": {"type": "string", "enum": [
                                      LIFECYCLE_BAND_FACTS_BY_BAND[b] for b in LIFECYCLE_BAND_ORDER]},
                                  "rank": {"type": "integer", "minimum": 0,
                                           "maximum": len(LIFECYCLE_BAND_ORDER) - 1}}),
    }
    defs["AxisList"] = _list_def("AxisList", _ref("AxisItem"))
    defs["TopGatingList"] = _list_def("TopGatingList", _ref("TopGatingItem"))
    defs["SourceList"] = _list_def("SourceList", _ref("SourceItem"))
    defs["CensusRowList"] = _list_def("CensusRowList", _ref("CensusRow"))
    defs["FailureRecordList"] = _list_def("FailureRecordList", _ref("FailureRecordItem"))
    defs["ViolationList"] = _list_def("ViolationList", _str())
    defs["Engine"] = _closed(
        "Engine", ("snapshot_schema", "script_version", "generated_at", "collected_at", "snapshot_schema_supported",
                   "code_schema_version"),
        {"snapshot_schema": _ref("TextFact"), "script_version": _ref("TextFact"), "generated_at": _ref("TextFact"),
         "collected_at": _ref("TextFact"), "snapshot_schema_supported": _nullable({"type": "boolean"}),
         "code_schema_version": _str()})
    defs["OverviewFacts"] = _closed(
        "OverviewFacts", tuple(ssot.CANONICAL_FACTS),
        {name: _ref("CanonBand" if name == "worst_band" else "CanonScore" if name == "avg_health" else "CanonCount")
         for name in ssot.CANONICAL_FACTS})
    fh_common = {"engine_state": {"type": "string", "enum": list(FLEET_HEALTH_STATES)},
                 "n_scored": _ref("CountFact"), "n_rows": _ref("CountFact")}
    fh_required = ["state", "engine_state", "not_assessed_reason", "n_scored", "n_rows"]
    defs["FleetHealth"] = {"title": "FleetHealth", "oneOf": [
        _closed("FleetHealthPublished", fh_required,
                {"state": {"const": _PUB}, "not_assessed_reason": _null(), **fh_common}),
        _closed("FleetHealthWithheld", fh_required + ["reason"],
                {"state": _ref("WithheldState"), "reason": {"type": "string", "minLength": 1},
                 "not_assessed_reason": _nullable({"type": "string", "enum": list(NOT_ASSESSED_REASONS)}),
                 **fh_common})]}
    n_bands = len(LIFECYCLE_BAND_ORDER)
    defs["Lifecycle"] = _closed("Lifecycle", ("bands", "of", "asof"),
                                {"bands": {"type": "array", "minItems": n_bands, "maxItems": n_bands,
                                           "items": _ref("LifecycleBand")},
                                 "of": _ref("CountFact"), "asof": _ref("TextFact")})
    defs["Overview"] = _closed(
        "Overview", ("facts", "fleet_health", "axes", "absent_axes", "posture_statement", "top_gating", "lifecycle"),
        {"facts": _ref("OverviewFacts"), "fleet_health": _ref("FleetHealth"), "axes": _ref("AxisList"),
         "absent_axes": {"type": "array", "items": _ref("AbsentAxis")}, "posture_statement": _ref("TextFact"),
         "top_gating": _ref("TopGatingList"), "lifecycle": _ref("Lifecycle")})
    defs["CensusSummary"] = _closed("CensusSummary", _CENSUS_SUMMARY_KEYS,
                                    {k: _ref("CountFact") for k in _CENSUS_SUMMARY_KEYS})
    defs["Census"] = _closed(
        "Census", ("basis", "summary", "rows", "embedded"),
        {"basis": {"type": "string", "const": "ssot.compute_schema_census"}, "summary": _ref("CensusSummary"),
         "rows": _ref("CensusRowList"),
         "embedded": _closed("CensusEmbedded", ("state", "matches_live"),
                             {"state": _ref("State"), "matches_live": _nullable({"type": "boolean"})})})
    defs["Failures"] = _closed(
        "Failures", ("basis", "record", "direct_sections", "unattributed"),
        {"basis": {"type": "string", "const": "ssot.failed_sections"}, "record": _ref("FailureRecordList"),
         "direct_sections": {"type": "array", "items": _ref("DirectSection")}, "unattributed": {"type": "boolean"}})
    defs["CoverageMatrix"] = _closed(
        "CoverageMatrix", ("n_devices", "n_axes", "n_rows", "n_covered", "n_abstained", "by_state", "note"),
        {"n_devices": _ref("CountFact"), "n_axes": _ref("CountFact"), "n_rows": _ref("CountFact"),
         "n_covered": _ref("CountFact"), "n_abstained": _ref("CountFact"), "by_state": _ref("ByStateFact"),
         "note": _ref("TextFact")})
    defs["UnknownEvidence"] = _closed(
        "UnknownEvidence", ("state", "n_events", "n_unresolved", "source_coverage_complete", "claim_scope", "note",
                            "sources"),
        {"state": _ref("UnknownEvidenceStateFact"), "n_events": _ref("CountFact"), "n_unresolved": _ref("CountFact"),
         "source_coverage_complete": _ref("FlagFact"), "claim_scope": _ref("TextFact"), "note": _ref("TextFact"),
         "sources": _ref("SourceList")})
    defs["Ssot"] = _closed(
        "Ssot", ("basis", "verified", "n_facts", "n_checked", "n_violations", "violations", "engine_stamp",
                 "stamp_matches_live"),
        {"basis": {"type": "string", "const": "ssot.summary"}, "verified": _ref("FlagFact"),
         "n_facts": _ref("CountFact"), "n_checked": _ref("CountFact"), "n_violations": _ref("CountFact"),
         "violations": _ref("ViolationList"), "engine_stamp": _ref("StampFact"),
         "stamp_matches_live": _nullable({"type": "boolean"})})
    n_lims = len(LIMITATIONS)
    defs["Trust"] = _closed(
        "Trust", ("census", "failures", "coverage_matrix", "unknown_evidence", "ssot", "limitations"),
        {"census": _ref("Census"), "failures": _ref("Failures"), "coverage_matrix": _ref("CoverageMatrix"),
         "unknown_evidence": _ref("UnknownEvidence"), "ssot": _ref("Ssot"),
         "limitations": {"type": "array", "minItems": n_lims, "maxItems": n_lims, "items": _ref("Limitation")}})
    _slice2_defs(defs)
    root = _closed("UiProjection", ("schema", "engine", "overview", "trust", "inventory", "findings"),
                   {"schema": {"type": "string", "const": SCHEMA}, "engine": _ref("Engine"),
                    "overview": _ref("Overview"), "trust": _ref("Trust"), "inventory": _ref("Inventory"),
                    "findings": _ref("Findings")})
    root["title"] = SCHEMA
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SCHEMA_ID, **root, "$defs": defs}


def ui_projection_schema() -> Dict[str, Any]:
    """The ``ui_projection/1`` JSON Schema (draft 2020-12), built fresh on every call (no shared nodes)."""
    return _copy_schema(_build_schema())


__all__ = [
    "ALWAYS_EMITTED_AXES", "ANALYSIS_SECTIONS", "APP_DOMAIN_JOINER", "AXIS_BASIS", "BRIEF_INPUTS", "CC_STATUSES",
    "CENSUS_KINDS", "COVERAGE_STATES", "DEVICE_CITED_LIMITATIONS", "DEVICE_LIMITATIONS", "DEVICE_PHYSICAL_TEXT",
    "DEVICE_PHYSICAL_ZERO_DEFAULTS", "DOMAIN_STATE_OWNERS", "DOSSIER_BANDS", "DOSSIER_UNDERSTATABLE",
    "ENDPOINT_CONFIDENCES", "ENGINE_LIST_CAPS", "ENGINE_STATES", "ENGINE_STATE_OWNERS", "ESSENTIAL_LABELS",
    "EXPOSURE_STATES", "FLEET_HEALTH_STATES", "HEALTH_BANDS", "HEALTH_BAND_NOT_SCORED", "IDENTITY_FIELDS",
    "IF_COLUMNS", "JS_MAX_SAFE_INT", "LIFECYCLE_BAND_FACTS", "LIFECYCLE_BAND_FACTS_BY_BAND", "LIFECYCLE_BAND_ORDER",
    "LIMITATIONS", "MOVE_GROUP_LABEL", "NOT_ASSESSED_REASONS", "NOT_OBSERVED_SENTINEL", "NRFU_NOT_OBSERVED",
    "OP_STATUSES", "PHASE_CLASSIFICATIONS", "PHYSICAL_TEXT_FIELDS", "POSTURE_STATEMENT_BASIS", "PUNCHLIST_INPUTS",
    "PUNCH_BASIS_UNPUBLISHED", "PUNCH_CONFIDENCE_UNPUBLISHED", "PUNCH_DETAIL_CLIP_MARKER", "PUNCH_RANK",
    "RECONCILED_PATHS", "REF_ROLES", "SCHEMA", "SCHEMA_ID", "SEC_GRADES", "SEC_SEVERITIES", "SEC_STATUSES",
    "SELECTION_NEEDS", "SEVERITIES", "SNAPSHOT_SCHEMA", "STATES", "UE_COMPLETE_STATES", "UE_SOURCE_STATES",
    "UNKNOWN_EVIDENCE_STATES", "VLAN_FIELD_BASIS", "VLAN_READINESS", "WITHHELD_STATES", "json_pointer", "project",
    "project_device", "project_devices", "project_engine", "project_findings", "project_inventory",
    "project_overview", "project_trust", "ui_projection_schema",
]
